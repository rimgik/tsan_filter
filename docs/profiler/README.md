# Workload profiler

[Documentation index](../README.md) · [Metric definitions](metrics.md)

The profiler measures which optimizations a workload could use. It does not
filter accesses: after recording its counters, it always continues through
normal TSan race tracking.

```text
instrumented access
        |
        v
 record owner, note simulation, slot and page counters
        |
        v
 normal TSan MemoryAccess and race detection
```

## Branch and runtime options

- Branch: `feat/workload-profiler`
- Compiler instrumentation: normal `-fsanitize=thread`
- Runtime: `TSAN_OPTIONS=ownership_profile=1`
- Output: `ownership_profile_path=FILE`

Allocation ownership is enabled by default. Set
`ownership_profile_allocations=0` to assign ownership on first access instead.

The runtime implementation is in `tsan_ownership_profile.cpp` and
`tsan_ownership_profile.h`. Hooks in `tsan_rtl_access.cpp`, `tsan_mman.cpp`,
and thread lifecycle code feed it accesses, allocations, and stable owner IDs.

## Run

Build using the [Linux guide](../build-linux.md), compile normally, then:

```sh
./tool/workload_profile.py ownership \
  --output "$HOME/build/profile.json" \
  --smaps-csv "$HOME/build/profile-smaps.csv" \
  -- "$HOME/build/example-tsan"
```

Profiler elapsed time and profiler RSS are diagnostic overhead. Never compare
them with stock as candidate performance. Use the normal timing runner with
profiling disabled for CPU and RSS comparisons.

For hardware counters, also with ownership profiling disabled:

```sh
./tool/workload_profile.py perf \
  --runs 7 --cpu 2 --output "$HOME/build/perf.csv" \
  -- "$HOME/build/example-tsan"
```

Next: [metric definitions](metrics.md) and
[benchmark methodology](../benchmarks/README.md).
