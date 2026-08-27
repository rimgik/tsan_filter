# Shadow-resident exact-hit filter — 2026-08-27

This experiment moves the fast check into TSan's existing four-word shadow
cell. It allocates no note mapping and does not implement ownership or merging.

The one-slot version is commit `7c8ce9a14d78` on
`feat/shadow-resident-filter`. The staged four-slot version is commit
`c883c4524e3a` on `feat/shadow-resident-staged`. Both are based on pristine
LLVM commit `73e729f7b2f0` and are disabled unless
`-mllvm -tsan-shadow-resident-filter` is used.

## Staged check

For eligible accesses, the pass constructs the same 32-bit word as TSan and
performs this check:

```text
load and compare slot 0
    hit  -> continue
    miss -> load and compare slots 1, 2, and 3
               hit  -> continue
               miss -> call ordinary TSan
```

All slot loads are relaxed 32-bit atomic loads. Writes require an exact word
match. Reads use the same read-bit adjustment and read-only marker handling as
stock `ContainsSameAccess`. A hit therefore takes the same early-return case
that the runtime would take. A miss does not modify shadow memory before the
ordinary callback runs.

This is not a private/shared classifier. It keeps all normal TSan history and
does not inline `CheckRaces`, which also handles clocks, trace state, reports,
and shadow replacement.

The optimization is limited to aligned, ordinary 1-, 2-, 4-, and 8-byte
accesses in eligible leaf functions. Unaligned, 16-byte, volatile, compound,
atomic, range, and non-leaf cases retain stock instrumentation.

## Generated code

On AArch64 the common slot-0 path contains one shadow `ldr`, one comparison,
and one conditional branch after constructing the current word. Only the miss
edge contains the three remaining `ldr` instructions. LLVM combines their
comparisons into a `cmp`/`ccmp` chain. The fast-state pointer and shadow
mapping constants are loaded once per eligible function; the current fast-state
word is still reloaded for every access.

There is no merge operation in this path.

## Correctness

- Linux and Darwin LLVM instrumentation checks passed.
- Focused private-loop and cross-thread race tests passed.
- On macOS, both flag-off and flag-on builds reported the upstream simple data
  race.
- Static and shared TSan runtime linking passed on Linux.
- Full Linux `check-tsan`: 356 passed, 102 unsupported, 2 expected failures,
  and no unexpected failures.

## Linux/AArch64 results

The Linux environment was an Ubuntu 24.04 AArch64 Lima VM with four virtual
CPUs, 8 GiB RAM, and 4 KiB pages. Runs were warmed, rotated, and CPU-pinned
where applicable. All samples, including outliers, were retained.

The private benchmark repeatedly writes one aligned heap cell. The handoff
benchmark first writes the cell on the main thread, then creates a worker that
writes it in a loop. Thread creation orders the two accesses, so there is no
race. TSan normally places the worker's access in slot 1; this deliberately
tests the slot-0 miss path.

| Comparison | Runs | First mean | Second mean | Relative result |
| --- | ---: | ---: | ---: | ---: |
| Private: stock vs slot 0 | 30 paired | 0.5488 s | 0.1613 s | slot 0 70.61% faster, ±0.34 pp |
| Private: slot 0 vs staged | 30 paired | 0.1683 s | 0.1718 s | staged 2.29% slower, ±2.38 pp |
| Handoff: stock vs slot 0 | 20 rotated | 0.5835 s | 0.6783 s | slot 0 16.23% slower, 95% CI [15.20%, 17.26%] |
| Handoff: stock vs staged | 20 rotated | 0.5835 s | 0.2810 s | staged 52.15% faster, 95% CI [49.66%, 54.51%] |
| SQLite: stock vs staged | 15 rotated | 5.609 s | 5.599 s | staged 0.14% faster, 95% CI [-1.38%, 1.65%] |
| Redis: stock vs staged | 15 rotated | 92,377 req/s | 91,843 req/s | staged 0.65% slower, 95% CI [-3.90%, 2.71%] |

The slot-0-only filter is excellent while the current word remains in slot 0,
but it is worse than stock when the repeated hit is in another slot: every
iteration performs the inline miss and then calls TSan, which scans the shadow
again. The staged check removes that pathology. Its 58.83% reduction relative
to slot 0 on the handoff benchmark is the clearest evidence for probing the
remaining slots.

SQLite and Redis do not establish either a speedup or a regression. Their
confidence intervals include zero, so their small mean differences are treated
as measurement noise.

Linux peak RSS was also effectively unchanged:

| Workload | Stock | Slot 0 | Staged |
| --- | ---: | ---: | ---: |
| SQLite | 112,908 KiB | 112,688 KiB | 112,704 KiB |
| Redis | about 41,804 KiB | about 41,828 KiB | about 41,916 KiB |

## macOS/AArch64 results

The macOS comparison used one custom compiler and runtime with the pass flag
off and on. This isolates the instrumentation change, but the flag-off build
should be called a control rather than a separately built pristine stock LLVM.
Each timing result contains 30 paired runs of 300 million writes.

| Workload | Flag off | Staged | Relative result |
| --- | ---: | ---: | ---: |
| Private cell | 0.9785 s | 0.1659 s | staged 83.05% faster, 95% CI [82.93%, 83.17%] |
| Ordered handoff | 0.9921 s | 0.2539 s | staged 74.45% faster, 95% CI [74.13%, 74.76%] |

Five peak-RSS repetitions used `/usr/bin/time -l`. Private means were
30,310,400 bytes with the flag off and 30,323,507 bytes with it on. Handoff
means were 30,543,053 bytes for both variants. These differences are page-level
variation, not evidence of added memory use.

## Conclusion

The repeated exact-hit case can be made much cheaper than a TSan callback
without losing shadow history or allocating another mapping. Checking only
slot 0 is too brittle. The staged four-slot check preserves its shortest hot
path and handles a repeated access stored in any shadow slot.

The synthetic result is strong, but the application result is currently
neutral. Native Linux with PMU access is the next environment needed to
measure cycles, instructions, branch misses, and cache events before attempting
further instruction-level tuning.
