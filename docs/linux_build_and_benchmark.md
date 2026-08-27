# Building and testing the TSan filters on Linux

This workflow builds LLVM/Clang and compiler-rt, compiles the same benchmark
with pristine TSan and either filter, and measures time and peak RSS.
The commands work on native Linux and inside the local Lima VM.

## 1. Prepare Linux

Ubuntu packages:

```sh
sudo apt-get update
sudo apt-get install build-essential clang cmake ninja-build python3 ccache git
```

The current checkout accepts Ubuntu 24.04's CMake 3.28 with a warning. LLVM 24
is moving to a 3.31 minimum, so upgrade CMake if a later revision rejects it.

Use a source path without spaces. LLVM's lit substitutions do not reliably
quote a test source path containing spaces. In the Lima VM the macOS project is
already visible through virtiofs, so no source copy is required. Create a
no-space bind mount and keep build output on the VM's ext4 disk:

```sh
mkdir -p "$HOME/src/llvm-project" "$HOME/build"
sudo mount --bind "/Users/rimgik/Project/TSan FYP/llvm-project" \
  "$HOME/src/llvm-project"
findmnt -T "$HOME/src/llvm-project"
```

Edits made on macOS are immediately visible in Linux. Only generated object
files and binaries live in `$HOME/build`; they are not copied back to macOS.
A symlink is not sufficient: lit can resolve it to the original path and then
split `TSan FYP` into separate command arguments. Repeat the bind mount after a
VM restart if it is not configured persistently.

## 2. Build the candidate compiler

From the outer `tsan_filter` repository:

```sh
./tool/linux_tsan.sh configure \
  "$HOME/src/llvm-project" \
  "$HOME/build/tsan-filter"

./tool/linux_tsan.sh build "$HOME/build/tsan-filter"
```

The first build is large. Later edits normally need only the second command.
The script selects the native LLVM target, enables TSan tests, uses a Release
build with assertions disabled, and enables ccache when installed.

## 3. Keep a true stock comparator

Use a separate clean source tree at the candidate's parent commit and a
separate build directory. Do not call a candidate binary “stock” merely
because `one_word_filter=0`: candidate compiler instrumentation can still
change its code and invalidate the comparison.

```sh
./tool/linux_tsan.sh configure \
  "$HOME/src/llvm-stock" \
  "$HOME/build/tsan-stock"

./tool/linux_tsan.sh build "$HOME/build/tsan-stock"
```

Record both source revisions before measuring:

```sh
git -C "$HOME/src/llvm-project" rev-parse HEAD
git -C "$HOME/src/llvm-stock" rev-parse HEAD
```

## 4. Compile benchmark code

Stock TSan:

```sh
./tool/linux_tsan.sh compile-stock \
  "$HOME/build/tsan-stock" \
  mvp/benchmarks/bench_private_write.cpp \
  "$HOME/build/bench-private-stock"
```

Filter candidate:

```sh
./tool/linux_tsan.sh compile-filter \
  "$HOME/build/tsan-filter" \
  mvp/benchmarks/bench_private_write.cpp \
  "$HOME/build/bench-private-filter"
```

Shadow-resident candidate:

```sh
./tool/linux_tsan.sh compile-shadow-resident \
  "$HOME/build/tsan-shadow-resident" \
  mvp/benchmarks/bench_private_write.cpp \
  "$HOME/build/bench-private-shadow-resident"
```

The equivalent manual commands are:

```sh
"$HOME/build/tsan-stock/bin/clang++" \
  -O1 -gline-tables-only -fsanitize=thread \
  mvp/benchmarks/bench_private_write.cpp \
  -o "$HOME/build/bench-private-stock"

"$HOME/build/tsan-filter/bin/clang++" \
  -O1 -gline-tables-only -fsanitize=thread \
  -mllvm -tsan-one-word-filter \
  mvp/benchmarks/bench_private_write.cpp \
  -o "$HOME/build/bench-private-filter"

"$HOME/build/tsan-shadow-resident/bin/clang++" \
  -O1 -gline-tables-only -fsanitize=thread \
  -mllvm -tsan-shadow-resident-filter \
  mvp/benchmarks/bench_private_write.cpp \
  -o "$HOME/build/bench-private-shadow-resident"
```

The compile-time flag changes the instrumentation pass. The runtime flag turns
on the extra mapping and allocator tagging:

```sh
./tool/linux_tsan.sh run-stock "$HOME/build/bench-private-stock" 300000000
./tool/linux_tsan.sh run-filter "$HOME/build/bench-private-filter" 300000000
./tool/linux_tsan.sh run-shadow-resident \
  "$HOME/build/bench-private-shadow-resident" 300000000
```

The shadow-resident candidate needs no runtime option and allocates no extra
mapping.

Recompile the benchmark after every compiler-rt rebuild because the static
TSan runtime is linked into the executable.

## 5. Correctness before timing

Run the upstream TSan suite:

```sh
./tool/linux_tsan.sh check "$HOME/build/tsan-filter"
```

The relevant upstream coverage is split across:

- `compiler-rt/test/tsan/`: end-to-end lit tests for reports, races,
  interceptors, atomics, synchronization, and platform behavior;
- `compiler-rt/lib/tsan/tests/unit/`: unit tests for shadow words, vector
  clocks, synchronization, allocation, traces, and flags;
- `compiler-rt/lib/tsan/tests/rtl/`: runtime tests and `tsan_bench.cpp`;
- `compiler-rt/test/tsan/bench_threads.cpp`: a thread create/join benchmark.

TSan does include microbenchmarks, but the `DISABLED_BENCH.*` tests are manual
and are not a general performance suite. After building tests, one can be run
with:

```sh
"$HOME/build/tsan-filter/runtimes/runtimes-bins/compiler-rt/lib/tsan/tests/rtl/TsanRtlTest-$(uname -m)-Test" \
  --gtest_also_run_disabled_tests \
  --gtest_filter=DISABLED_BENCH.Mop8Write
```

On AArch64 the binary is named `TsanRtlTest-aarch64-Test`. Locate it with
`find "$HOME/build/tsan-filter" -name 'TsanRtlTest-*-Test'` if necessary.
Use external applications such as Redis and SQLite for representative
performance measurements.

## 6. Measure fairly

The script reports wall, user and system time, peak RSS, page faults, and
context switches:

```sh
./tool/linux_tsan.sh measure-stock "$HOME/build/bench-private-stock" 300000000
./tool/linux_tsan.sh measure-filter "$HOME/build/bench-private-filter" 300000000
./tool/linux_tsan.sh measure-shadow-resident \
  "$HOME/build/bench-private-shadow-resident" 300000000
```

Use one warmup followed by at least seven interleaved repetitions. Run a
stock-versus-stock A/A calibration first. For servers, measure client
throughput and pin the server and client to disjoint CPUs where possible.
Diagnostic counters must be disabled during headline timing runs.

`perf stat` is appropriate on native Linux:

```sh
./tool/linux_tsan.sh perf-stat \
  "$HOME/build/bench-private-stock" 300000000
```

Override `PERF_EVENTS` or `PERF_REPETITIONS` when needed. Keep counter runs
separate from headline timing runs.

The local Apple-virtualized Lima VM does not expose those PMU events, so it is
useful for Linux builds, correctness, timing, RSS, `/proc`, and page-fault
checks, but not final IPC or cache-miss evidence.

## 7. Why Linux and macOS can differ

The stock Linux compiler does not infer that the heap object in the private
write benchmark is thread-private. Its loop still calls `__tsan_write8` on
every iteration.

The important Linux difference found during this evaluation was in our port,
not stock LLVM. AArch64 Linux places normal allocations in the high
application range because its fixed heap range is empty. The first port added
low, heap, and high note ranges, making every inline probe perform three range
checks and a three-way index calculation. Selecting only low memory plus one
platform-dependent allocation range restored a two-range probe and changed the
300-million-write result from slower than stock to faster than stock.

Page size is not the explanation for that hot-cell result. Allocation tagging
and the benchmark's initial store occur before the timer, so the single app,
note, and shadow pages are already resident. Linux's 4 KiB pages can affect
fault count and TLB pressure for large working sets, but not a loop repeatedly
touching the same cache line. Verify rather than assume with:

```sh
getconf PAGESIZE
./tool/linux_tsan.sh measure-filter "$HOME/build/bench-private-filter" 300000000
```

Finally, virtual-machine scheduling can dominate short server runs. Discard a
series when the same binary varies widely; do not select the most favorable
sample.
