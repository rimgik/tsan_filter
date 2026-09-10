# Current benchmark results

[Benchmark index](README.md)

These are Linux/AArch64 VM development results. CPU is user plus system time;
RSS is peak resident memory. Native Linux confirmation remains pending.

## NPB OpenMP

| Workload | Variant | CPU | Peak RSS |
| --- | --- | ---: | ---: |
| BT-W | Stock | 22.44 s | 41,080 KiB |
| BT-W | Parallel note | 79.24 s (+253.1%) | 54,520 KiB (+32.7%) |
| BT-W | Shadow-resident | 15.75 s (-29.8%) | 41,124 KiB (+0.1%) |
| IS-B | Stock | 37.32 s | 844,024 KiB |
| IS-B | Parallel note | 59.80 s (+60.2%) | 856,824 KiB (+1.5%) |
| IS-B | Shadow-resident | 37.39 s (+0.2%) | 844,068 KiB (+0.0%) |
| CG-A | Stock | 24.45 s | 111,992 KiB |
| CG-A | Parallel note | 37.67 s (+54.1%) | 125,176 KiB (+11.8%) |
| CG-A | Shadow-resident | 24.32 s (-0.5%) | 111,908 KiB (-0.1%) |

IS-B and CG-A leave shadow-resident statistically indistinguishable from
stock. Their note regressions are much larger than the measured VM noise.

## Why BT performs well

The profiler measured the slot-0 rate directly:

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

BT issued 8.42 billion instrumented callbacks. Its numerical loops repeatedly
produce an access word already in slot 0, so the inline comparison avoids most
runtime calls. IS often needs later slots; CG usually misses and then pays for
normal TSan as well.

This is not mainly an ownership result. Although 83.04% of BT cell touches
occurred during a private phase, exact-note opportunities not already handled
by stock `ContainsSameAccess` were only 0.02%.

## Page density

Over 92% of reached shadow pages were dense for BT-W, IS-W, and CG-W. IS-B was
99.99% dense. Increasing allocation size therefore did not make ordinary
shadow pages avoidable. This explains why shadow-resident keeps stock-like RSS
and why the separate note adds memory instead of replacing ordinary shadow.
