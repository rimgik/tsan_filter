# Profiler results and analysis

[Documentation](../README.md) · [Profiler guide](README.md) · [Metric definitions](metrics.md)

The profiler uses ordinary TSan instrumentation and always continues through
normal race tracking after recording diagnostics. Its CPU time and memory are
profiler overhead, not candidate performance results.

## Application workloads

Redis 8.8 and SQLite were rerun on the Linux/AArch64 VM with the current
profiler. Redis used 100,000 SET, GET, and INCR requests, 20 clients, and two
I/O threads. SQLite speedtest1 used `--size 10`.

| Workload | Private cells | Private-phase accesses | Private accesses beyond CSA | Exact-note absorbed accesses | Exact-note accesses beyond CSA | Exact-shadow hits among eligible accesses | Potentially avoidable shadow pages | Mixed-path shadow pages | Fallback-only shadow pages |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Redis | 35.78% | 53.75% | 13.68% | 2.55% | 0.65% | 66.67% | 34.34% | 56.42% | 9.24% |
| SQLite | 100.00% | 100.00% | 36.79% | 6.01% | 1.44% | 71.59% | 0.25% | 78.84% | 20.92% |

| Workload | Sparse shadow pages | Dense shadow pages | Peak total RSS | Peak shadow RSS | Peak profiler RSS |
| --- | ---: | ---: | ---: | ---: | ---: |
| Redis | 39.25% | 39.97% | 44,608 KiB | 6,796 KiB | 2,868 KiB |
| SQLite | 0.95% | 86.29% | 122,248 KiB | 45,624 KiB | 20,088 KiB |

Redis has real ownership transitions: 6,103,761 of 9,503,767 observed cell
lifetimes became shared. Its one-word opportunity beyond stock CSA is only
0.65%, while one third of reached pages remain potentially avoidable.

SQLite has no ownership transitions, but private ownership alone is not enough.
It recorded 23,265,081 ineligible note accesses, 338,211 merge failures, and
523,840,974 accesses after permanent fallback. Only 27 of 10,976 reached pages
were potentially avoidable. Exact-shadow candidates hit slot 0 23.33% of the
time, later slots 48.26%, and missed 28.41%.

## Controlled and microbenchmark workloads

These Linux/AArch64 diagnostic runs predate the NPB evaluation. “Exact note”
is the percentage of accesses absorbed by the simulated one-word note. “Exact
shadow hit” uses only runtime-visible eligible accesses as its denominator.

| Workload | Private cells | Exact-note absorbed accesses | Exact-shadow hits among eligible accesses | Potentially avoidable shadow pages | Mixed-path shadow pages | Fallback-only shadow pages | Sparse shadow pages | Dense shadow pages |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Controlled 60-page test | 99.78% | 98.91% | 5.89% | 50.00% | 33.33% | 16.67% | 58.33% | 25.00% |
| Private loop, 30M writes | 100.00% | 100.00% | 100.00% | 33.33% | 33.33% | 33.33% | 66.67% | 0.00% |
| 256 MiB contiguous private allocation | 100.00% | 100.00% | 0.01% | 100.00% | 0.00% | 0.00% | 0.00% | 100.00% |

The private loop produced 30,000,002 slot-0 hits and one miss among 30,000,003
eligible accesses. It is the ideal shadow-resident case.

The large allocation produced 234,881,024 exact merges and 4,194,304 coverage
hits. All but one of 131,074 observed pages were potentially avoidable. This
explains the earlier parallel-note memory win: a contiguous private workload
can avoid almost all ordinary-shadow residency even though note operations
still add CPU cost.

## Optimization opportunities

Percentages are dynamic accesses except private cells and the three page
columns. CSA means stock TSan's `ContainsSameAccess` fast path.

| Workload | Private cells | Private-phase accesses | Private accesses beyond CSA | Exact-note absorbed accesses | Exact-note accesses beyond CSA | Exact-shadow hits among eligible accesses | Potentially avoidable shadow pages | Mixed-path shadow pages | Fallback-only shadow pages |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| BT-W | 19.73% | 83.04% | 0.48% | 5.22% | 0.02% | 96.06% | 1.24% | 36.95% | 61.81% |
| IS-W | 3.92% | 36.46% | 4.75% | 7.85% | 0.37% | 64.35% | 0.02% | 25.82% | 74.15% |
| CG-W | 39.15% | 25.53% | 14.98% | 10.55% | 0.17% | 37.63% | 15.83% | 80.69% | 3.48% |
| IS-B | 4.02% | 36.20% | 4.68% | 7.87% | 0.37% | 64.39% | <0.01% | 25.30% | 74.70% |
| CG-A | 36.31% | 31.09% | 13.95% | 17.17% | 0.15% | 43.41% | 12.53% | 85.41% | 2.05% |

High private-access percentages do not imply that the parallel note can skip
those accesses. Complete history must also remain exactly representable in one
word. The “note beyond CSA” column is therefore the useful incremental
opportunity, and it stays below 0.4% here.

## Why BT favours shadow-resident filtering

The slot-0 rate comes from one profiler-enabled BT-W execution. The runtime
increments `shadow_exact_eligible` whenever an access is eligible for the
exact-shadow simulation. It additionally increments
`shadow_exact_slot0_hits` when the access word already matches shadow slot 0.
The raw JSON fields were stored locally at
`$HOME/build/npb-cpp/profiles/bt-W.json`:

```text
shadow_exact_slot0_hits / shadow_exact_eligible
= 7,121,605,909 / 7,894,960,407
= 90.20%
```

The profiler observed 7.12 billion slot-0 matches among 7.89 billion eligible
cell touches. These are dynamic access counts from the diagnostic run; they are
unrelated to the seven timing repetitions in the performance table.

| Workload | Slot-0 hit | Any-slot hit | Miss |
| --- | ---: | ---: | ---: |
| BT-W | 90.20% | 96.06% | 3.94% |
| IS-W | 21.41% | 64.35% | 35.65% |
| CG-W | 13.56% | 37.63% | 62.37% |

BT-W issued 8.42 billion instrumented callbacks. Its repetitive numerical
loops usually find an identical word in slot 0, so the inline shadow-resident
check avoids most runtime calls. IS often requires a later slot; CG usually
misses and then pays for both the inline checks and normal TSan.

This is not primarily an ownership win. BT-W has 83.04% private-phase
accesses, but exact-note opportunity beyond stock CSA is only 0.02%.

## Shadow-page density and memory

| Workload | Sparse shadow pages | Dense shadow pages | Peak total RSS | Peak shadow RSS | Peak profiler RSS |
| --- | ---: | ---: | ---: | ---: | ---: |
| BT-W | 0.31% | 92.49% | 44,348 KiB | 6,504 KiB | 3,212 KiB |
| IS-W | 0.24% | 99.67% | 67,604 KiB | 18,236 KiB | 9,192 KiB |
| CG-W | 0.31% | 99.49% | 64,972 KiB | 17,032 KiB | 8,432 KiB |
| IS-B | <0.01% | 99.99% | 1,119,776 KiB | 542,020 KiB | 275,680 KiB |
| CG-A | 0.08% | 99.86% | 139,456 KiB | 53,876 KiB | 27,332 KiB |

Almost every reached shadow page is dense. A page cannot be omitted merely
because some cells on it are private: one fallback cell materializes the page.
This explains why shadow-resident filtering keeps approximately stock memory,
while a parallel note normally adds resident pages instead of replacing stock
shadow pages. The separate-note large-allocation microbenchmark is favourable
only when much of its reserved metadata remains untouched.
