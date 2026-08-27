# TSan Fast-Filter Experiments

This project investigates whether ThreadSanitizer (TSan) can recognize repeated
accesses before entering its runtime callback. The first implementation stores
an exactly mergeable word in a parallel note region. The second reads slot 0 of
the existing TSan shadow cell and inlines a subset of TSan's
`ContainsSameAccess` check.

Both retain ordinary TSan history. The separate-note design wins on a narrow
private-write loop but loses substantially on Redis and SQLite. The
shadow-resident design is about 71% faster on that favorable loop and was
approximately neutral on the tested Redis and SQLite runs, without adding a
memory mapping.

## Repository layout

- `llvm-project/` — LLVM fork pinned to the implementation commit.
- `TSan_v3_Source_Reference.md` — source-level guide to TSan v3.
- `report/` — design, soundness, implementation, and evaluation notes.
- `mvp/` — build instructions and compact benchmark sources.
- `results/summary.md` — headline performance and memory measurements.
- `results/linux_vm_2026-08-27.md` — Linux/AArch64 validation results.
- `results/shadow_resident_2026-08-27.md` — existing-shadow experiment.
- `results/experiment_log.md` — retained and rejected optimization trials.
- `docs/linux_build_and_benchmark.md` — reproducible Linux build workflow.
- `tool/linux_tsan.sh` — build, compile, check, run, and measure commands.
- `docs/` — project brief and proposal.
- `article/README.md` — related papers and links.

## Implementation

The implementation is available on
[`feat/one-word-note`](https://github.com/rimgik/llvm-project/tree/feat/one-word-note)
and tagged
[`one-word-note-v1`](https://github.com/rimgik/llvm-project/tree/one-word-note-v1).
The pinned commit is
[`7bbf797`](https://github.com/rimgik/llvm-project/commit/7bbf797546779f077778e90237a7f1a36a04bc4b).

The feature is disabled by default. Enable compiler instrumentation with
`-mllvm -tsan-one-word-filter` and enable the runtime with
`TSAN_OPTIONS=one_word_filter=1`.

The newer shadow-resident experiment is commit `7c8ce9a14d78` on
`feat/shadow-resident-filter`. Enable it with
`-mllvm -tsan-shadow-resident-filter`; it has no runtime option.

Start with [the MVP guide](mvp/README.md) for the design and build commands,
or use [the Linux workflow](docs/linux_build_and_benchmark.md) for a current
end-to-end build. Read [the results summary](results/summary.md) and the
[Linux VM evaluation](results/linux_vm_2026-08-27.md) for the current limits.
The [shadow-resident results](results/shadow_resident_2026-08-27.md) compare
the next design with pristine TSan.
