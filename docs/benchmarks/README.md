# Benchmarks

[Documentation index](../README.md) · [Current results](current-results.md)

## Workload groups

| Group | Purpose |
| --- | --- |
| Private loop | Best-case repeated access to one aligned cell. |
| Large allocation | Separates virtual reservation from resident-page cost. |
| Handoff | Moves a repeated exact word into a later shadow slot. |
| Controlled profiler tests | Produce known ownership ratios and page-density buckets. |
| Redis and SQLite | Application/proxy workloads. |
| NPB OpenMP | BT, IS, and CG parallel scientific workloads. |

See [NPB OpenMP](npb-openmp.md) for setup and classes.

## Timing policy

- Compare separately built stock and candidate compilers.
- Run an identical stock-versus-stock calibration first.
- Use one warmup and at least seven balanced repetitions.
- Pin workers and keep OpenMP settings fixed.
- Report benchmark time, total CPU time, and peak RSS together.
- Report medians and dispersion; retain all samples.
- Run ownership profiling and hardware counters separately from timing.
- Treat Linux VM timing as development evidence; use native Linux for final
  cycles, instructions, IPC, and cache counters.

The balanced runner enforces a per-process limit and records CSV output:

```sh
./tool/repeat_benchmark.py \
  --variant stock="$HOME/build/app-stock" \
  --variant candidate="$HOME/build/app-candidate" \
  --runs 7 --warmups 1 --timeout 120 --cpu 0-3 \
  --csv "$HOME/build/timing.csv"
```

Next: [current results](current-results.md).
