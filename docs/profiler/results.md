# Profiler results and analysis

[Documentation](../README.md) · [Profiler guide](README.md) · [Metric definitions](metrics.md)

The profiler uses ordinary TSan instrumentation and always continues through
normal race tracking after recording diagnostics. Its CPU time and memory are
profiler overhead, not candidate performance results.

## Optimization opportunities

Percentages are dynamic accesses except private cells and the three page
columns. CSA means stock TSan's `ContainsSameAccess` fast path.

| Workload | Private cells | Private accesses | Private beyond CSA | Exact note | Note beyond CSA | Any shadow-slot hit | Avoidable pages | Mixed pages | Fallback pages |
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

The slot-0 rate comes directly from raw counters:

```text
shadow_exact_slot0_hits / shadow_exact_eligible
= 7,121,605,909 / 7,894,960,407
= 90.20%
```

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

| Workload | Sparse pages | Dense pages | Peak RSS | Shadow RSS | Profiler RSS |
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
