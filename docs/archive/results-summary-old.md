# Evaluation Summary

The current v1 is an exact, sound one-word filter. It is disabled by default in
both the compiler and runtime. Measurements compare separately built stock and
filtered TSan binaries, with diagnostic counters disabled.

## Headline results

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
