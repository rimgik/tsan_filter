# Running the benchmarks

[Documentation](../README.md) · [Results](results.md) · [Profiler analysis](../profiler/results.md)

## Contents

| Workload | Purpose |
| --- | --- |
| [Private loop](#private-loop) | Best-case repeated access to one cell. |
| [Large allocation](#large-allocation) | Exposes virtual versus resident metadata cost. |
| [Ordered handoff](#ordered-handoff) | Exercises a useful word outside shadow slot 0. |
| [Controlled profiler tests](#controlled-profiler-tests) | Checks known ownership and page-density ratios. |
| [Redis](#redis) | Concurrent server workload. |
| [SQLite speedtest1](#sqlite-speedtest1) | Single-process application workload. |
| [NPB OpenMP](npb-openmp.md) | Parallel BT, IS, and CG kernels. |
| [`tsan-experiments` applications](tsan-experiments.md) | Memcached, Redis, SQLite, FFmpeg, and MySQL. |

## Common setup

Build each LLVM branch separately by following the [Linux build guide](../build-linux.md):

```sh
STOCK_BUILD="$HOME/build/tsan-stock"
NOTE_BUILD="$HOME/build/tsan-note"
SHADOW_BUILD="$HOME/build/tsan-shadow"
PROFILER_BUILD="$HOME/build/tsan-profiler"
OUT="$HOME/build/tsan-bench"
mkdir -p "$OUT"
```

Use the build matching each compiler option. A pristine stock build is required;
disabling a runtime flag in a feature build is not a stock comparison.

## Private loop

```sh
./tool/linux_tsan.sh compile-stock "$STOCK_BUILD" mvp/benchmarks/bench_private_write.cpp "$OUT/private-stock" -pthread
./tool/linux_tsan.sh compile-filter "$NOTE_BUILD" mvp/benchmarks/bench_private_write.cpp "$OUT/private-note" -pthread
./tool/linux_tsan.sh compile-shadow-resident "$SHADOW_BUILD" mvp/benchmarks/bench_private_write.cpp "$OUT/private-shadow" -pthread

./tool/linux_tsan.sh measure-stock "$OUT/private-stock" 300000000
./tool/linux_tsan.sh measure-filter "$OUT/private-note" 300000000
./tool/linux_tsan.sh measure-shadow-resident "$OUT/private-shadow" 300000000
```

## Large allocation

This test allocates four 64 MiB buffers and writes every byte.

```sh
./tool/linux_tsan.sh compile-stock "$STOCK_BUILD" mvp/benchmarks/bench_bigalloc.c "$OUT/bigalloc-stock" -pthread
./tool/linux_tsan.sh compile-filter "$NOTE_BUILD" mvp/benchmarks/bench_bigalloc.c "$OUT/bigalloc-note" -pthread
./tool/linux_tsan.sh measure-stock "$OUT/bigalloc-stock"
./tool/linux_tsan.sh measure-filter "$OUT/bigalloc-note"
```

## Ordered handoff

```sh
./tool/linux_tsan.sh compile-stock "$STOCK_BUILD" mvp/benchmarks/bench_handoff_write.cpp "$OUT/handoff-stock" -pthread
./tool/linux_tsan.sh compile-shadow-resident "$SHADOW_BUILD" mvp/benchmarks/bench_handoff_write.cpp "$OUT/handoff-shadow" -pthread
./tool/linux_tsan.sh measure-stock "$OUT/handoff-stock" 300000000
./tool/linux_tsan.sh measure-shadow-resident "$OUT/handoff-shadow" 300000000
```

## Controlled profiler tests

These sources call TSan access hooks directly, so compiler memory
instrumentation is disabled to avoid double counting.

```sh
"$PROFILER_BUILD/bin/clang++" -O1 -gline-tables-only -fsanitize=thread -mllvm -tsan-instrument-memory-accesses=0 -pthread mvp/benchmarks/bench_profile_private_ratio.cpp -o "$OUT/profile-ratio"
"$PROFILER_BUILD/bin/clang++" -O1 -gline-tables-only -fsanitize=thread -mllvm -tsan-instrument-memory-accesses=0 -pthread mvp/benchmarks/bench_profile_density.cpp -o "$OUT/profile-density"

./tool/workload_profile.py ownership --wait-for-range --output "$OUT/ratio.json" --smaps-csv "$OUT/ratio-smaps.csv" -- "$OUT/profile-ratio"
./tool/workload_profile.py ownership --wait-for-range --output "$OUT/density.json" --smaps-csv "$OUT/density-smaps.csv" -- "$OUT/profile-density"
```

The first test expects 60% private cells. The second expects 58.33% sparse
pages, 25% dense pages, 50% potentially avoidable pages, 33.33% mixed pages,
and 16.67% fallback-only pages.

## Redis

Build Redis separately with each compiler, TSan enabled, and the system
allocator. Start one server per variant, then run the same pinned
`redis-benchmark` command. Record server peak RSS and client throughput; client
CPU time is not server CPU time.

```sh
make distclean
make -j4 CC="$BUILD/bin/clang" MALLOC=libc CFLAGS="-O1 -gline-tables-only -fsanitize=thread $FEATURE_CFLAGS" LDFLAGS="-fsanitize=thread"
./src/redis-server --port 6380 --save '' --appendonly no --io-threads 2
./src/redis-benchmark -p 6380 -t set,get,incr -n 100000 -c 20
```

For parallel note, set `FEATURE_CFLAGS=-mllvm -tsan-one-word-filter` and run the
server with `TSAN_OPTIONS=one_word_filter=1`. For shadow resident, use
`FEATURE_CFLAGS=-mllvm -tsan-shadow-resident-filter` and no runtime flag.

## SQLite speedtest1

Compile the same SQLite checkout and `test/speedtest1.c` with each compiler.
The timing comparison uses `--size 25`; profiler runs use `--size 10`.

```sh
"$BUILD/bin/clang" -O1 -gline-tables-only -fsanitize=thread $FEATURE_CFLAGS sqlite3.c test/speedtest1.c -ldl -lpthread -lm -o "$OUT/speedtest1"
./tool/linux_tsan.sh measure-stock "$OUT/speedtest1" --size 25
```

Use the matching feature run or measure command for each candidate binary.

## Measurement policy

- Run correctness tests first and perform a stock-versus-stock calibration.
- Use one warmup and at least seven interleaved measured runs.
- Report total CPU time and peak RSS together, with median and dispersion.
- Keep thread count, affinity, input, and environment identical.
- Run the profiler and hardware counters separately from timing.
- Treat VM measurements as development evidence; use native Linux for final PMU results.

```sh
./tool/repeat_benchmark.py \
  --variant stock="$OUT/app-stock" --variant candidate="$OUT/app-candidate" \
  --runs 7 --warmups 1 --timeout 120 --cpu 0-3 --csv "$OUT/timing.csv"
```
