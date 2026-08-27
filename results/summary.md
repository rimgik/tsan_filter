# Evaluation Summary

The side-note v1 is an exact, sound one-word filter. It is disabled by default in
both the compiler and runtime. Measurements compare separately built stock and
filtered TSan binaries, with diagnostic counters disabled.

## Side-note v1 results

| Workload | Stock | Filter | Change |
| --- | ---: | ---: | ---: |
| Private hot-cell writes, 300M operations | 2.00 s | 0.68 s | 2.9× faster |
| 128 MiB private allocation | 0.46 s | 0.49 s | 6.5% slower |
| SQLite speedtest1, thread-safe | 4.12 s | 4.39 s | 6.6% slower |
| SQLite speedtest1, thread safety disabled | 3.36 s | 3.62 s | 7.7% slower |
| LZ4 `decompress_safe` | 69.3 MB/s | 62.5 MB/s | 9.8% lower throughput |
| BabelStream serial Triad | 4684 MB/s | 2898 MB/s | 38.1% lower throughput |
| LULESH serial, `-s 30 -i 50` | 5.58 s | 6.74 s | 20.8% slower |

The hot-cell test is deliberately favourable: one aligned eight-byte heap
cell is repeatedly written by its owning thread in a leaf function. It shows
that an inlined note hit can be cheaper than a TSan callback. It is not
representative of an entire application.

## Memory

For a 128 MiB live application allocation made from 4096 32-KiB blocks:

| Build | Peak resident memory |
| --- | ---: |
| Plain, without TSan | 129.8 MiB |
| Stock TSan | 478.8 MiB |
| Filtered TSan | 543.1 MiB |

The filter added 64.3 MiB, or 13.4% over stock TSan. This matches the note
density: four metadata bytes per eight application bytes. The additional
mapping reserves about 1.5 TiB of virtual address space on the tested platform,
although untouched pages do not contribute the same amount of resident memory.

Peak resident memory also increased in the application benchmarks: SQLite from
about 121.7 MiB to 132.7 MiB, LZ4 from 74.5 MiB to 81.4 MiB, BabelStream from
334.9 MiB to 383.3 MiB, and LULESH from 125.3 MiB to 137.9 MiB.

## Interpretation

The exact filter wins only when many accesses repeatedly hit a one-word note
and the compiler can inline the check. Real workloads still pay the mapping,
lookup, and branch costs, while many cells eventually require normal TSan
tracking. Therefore v1 is useful as a concrete lower-bound experiment and a
sound implementation baseline, but it is not currently a general performance
improvement over stock TSan.

## Shadow-resident follow-up

A later prototype inlines exact comparisons against TSan's existing shadow
cell. It keeps stock history and adds no mapping, allocator metadata, or
private/shared state.

The first version checked only slot 0. Thirty paired Linux runs made the
private hot-cell loop 70.61% faster than stock, but an ordered thread-handoff
case was 16.23% slower because its repeated exact word lived in slot 1.

The staged version checks slot 0 first and probes slots 1–3 only after a miss:

| Linux workload | Stock | Slot 0 | Staged |
| --- | ---: | ---: | ---: |
| Ordered handoff | 0.584 s | 0.678 s | 0.281 s |
| SQLite speedtest1 | 5.609 s | 5.713 s | 5.599 s |
| Redis mean throughput | 92,377 req/s | 90,668 req/s | 91,843 req/s |

The staged handoff result is 52.15% faster than stock. SQLite and Redis
confidence intervals include zero, so they establish neither a general
speedup nor a regression. Peak RSS is unchanged within measurement variation,
as expected from reusing normal shadow memory.

Thirty paired macOS flag-off/flag-on runs also found large synthetic gains:
83.05% on the private loop and 74.45% on ordered handoff. Native Linux PMU
measurements are still needed for instruction, branch, and cache attribution.
See `shadow_resident_2026-08-27.md` for the design, confidence intervals,
correctness checks, and exact revisions.
