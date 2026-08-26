# TSan One-Word Filter

This project investigates whether ThreadSanitizer (TSan) can avoid ordinary
shadow-memory updates while a memory cell is representable by one exact shadow
word. A parallel note region stores that word. When an access cannot be merged
exactly, the note is handed to normal TSan shadow memory and the cell remains on
the standard path.

The current implementation is sound: it does not discard history at the
transition to normal TSan tracking. Its practical result is mixed. A narrow
private-write microbenchmark is substantially faster, but the tested
real-world and proxy workloads are slower and use more resident memory.

## Repository layout

- `llvm-project/` — LLVM fork pinned to the implementation commit.
- `TSan_v3_Source_Reference.md` — source-level guide to TSan v3.
- `report/` — design, soundness, implementation, and evaluation notes.
- `mvp/` — build instructions and compact benchmark sources.
- `results/summary.md` — headline performance and memory measurements.
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

Start with [the MVP guide](mvp/README.md) for the design and build commands,
then read [the results summary](results/summary.md) for the current limits.
