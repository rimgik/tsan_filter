# Benchmark results

[Documentation](../README.md) · [Run the benchmarks](README.md) · [Profiler analysis](../profiler/results.md)

These are Linux/AArch64 VM development results. CPU is user plus system time;
RSS is peak resident memory. Native Linux confirmation remains pending. A dash
means the metric was not retained and must not be inferred as unchanged.

## Parallel-note filter

| Workload | Stock | Parallel note | CPU/throughput change | Stock RSS | Note RSS | RSS change |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Private loop, 300M writes | 0.5427 s | 0.3944 s | 27% faster | — | — | — |
| Redis | 91,351 req/s | 63,123 req/s | 31% lower throughput | 41,688 KiB | 59,480 KiB | +42.7% |
| SQLite speedtest1 | 5.76 s | 9.92 s | 72% slower | 112,908 KiB | 124,520 KiB | +10.3% |
| NPB BT-W | 22.44 s | 79.24 s | 253.1% slower | 41,080 KiB | 54,520 KiB | +32.7% |
| NPB IS-B | 37.32 s | 59.80 s | 60.2% slower | 844,024 KiB | 856,824 KiB | +1.5% |
| NPB CG-A | 24.45 s | 37.67 s | 54.1% slower | 111,992 KiB | 125,176 KiB | +11.8% |

The private loop is a deliberately favourable case. Every application-sized
workload paid more for the second mapping and merge logic than it recovered by
avoiding runtime calls.

## Shadow-resident filter

| Workload | Stock CPU | Shadow CPU | CPU change | Stock RSS | Shadow RSS | RSS change |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Private loop, 300M writes | 0.5488 s | 0.1718 s | 68.7% faster | — | — | — |
| Redis | 92,377 req/s | 91,843 req/s | 0.65% lower throughput | ~41,804 KiB | ~41,916 KiB | +0.3% |
| SQLite speedtest1 | 5.609 s | 5.599 s | 0.2% faster | 112,908 KiB | 112,704 KiB | -0.2% |
| NPB BT-W | 22.44 s | 15.75 s | 29.8% faster | 41,080 KiB | 41,124 KiB | +0.1% |
| NPB IS-B | 37.32 s | 37.39 s | 0.2% slower | 844,024 KiB | 844,068 KiB | +0.0% |
| NPB CG-A | 24.45 s | 24.32 s | 0.5% faster | 111,992 KiB | 111,908 KiB | -0.1% |

Redis, SQLite, IS-B, and CG-A were statistically indistinguishable from stock
in the retained runs. BT-W is the main application-sized positive result.
The [profiler analysis](../profiler/results.md) explains why.
