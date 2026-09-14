# `tsan-experiments` application suite

[Benchmarks](README.md) · [Results](results.md)

## Scope

The evaluation pins
[`focs-lab/tsan-experiments`](https://github.com/focs-lab/tsan-experiments)
at `ffb2d5a8cac32c27d5eb0dcb667428435aca0320` and compares separately built
stock TSan, parallel note, and shadow resident.

| Family | Workload |
| --- | --- |
| Memcached 1.6.29 | Supplied 30-second `memtier_benchmark` workload |
| Redis 7.0.15 | Supplied `redis-benchmark` operation set |
| SQLite 3.50.2 | Default multithreaded `threadtest3` |
| FFmpeg 4.3.9 | H.264, H.265, MJPEG, and stream copy |
| MySQL 8.0.39 | `sysbench oltp_read_write`, 3 threads, 180 seconds |

Chromium is excluded. ClickHouse receives only a preflight because the pinned
checkout does not contain the source tree, dataset, configuration, or shared
helper required by its scripts.

## Protocol

Each completed comparison has one warmup followed by seven measured runs in a
balanced, interleaved order. A run is accepted only when the application exits
cleanly, emits its expected result, produces no unexpected TSan report, and its
server is shut down. Timing runs record workload throughput, wall time, total
CPU time, and server peak RSS together.

The workload profiler is run separately with ordinary TSan race tracking still
enabled. Its CPU and RSS are diagnostic overhead and are not candidate
performance results.

## Preflight

```sh
./tool/tsan_experiments.py preflight \
  --suite "$HOME/src/tsan-experiments" \
  --stock "$HOME/build/stock/bin/clang" \
  --parallel-note "$HOME/build/parallel-note/bin/clang" \
  --shadow-resident "$HOME/build/shadow-resident/bin/clang" \
  --expected-commit ffb2d5a8cac32c27d5eb0dcb667428435aca0320 \
  --output "$HOME/results/tsan-experiments/provenance.json"
```

Raw builds and measurements remain outside Git. Only the pinned manifest,
wrapper, commands, and reviewed aggregate tables belong in this repository.

Current reviewed FFmpeg measurements are in the
[benchmark results](results.md#ffmpeg-439).

The small build wrapper currently covers Redis, Memcached, and SQLite:

```sh
./tool/build_tsan_experiment.sh redis stock \
  "$HOME/build/stock/bin/clang" "$HOME/src/tsan-experiments" "$HOME/build/apps"
```

Replace `stock` and the compiler path with `parallel-note` or
`shadow-resident` for the candidate builds. Each output directory contains a
`build-manifest.txt` recording the exact compiler and flags.
