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

The private loop is a deliberately favourable case. Every application-sized
workload paid more for the second mapping and merge logic than it recovered by
avoiding runtime calls.

## Shadow-resident filter

| Workload | Stock CPU | Shadow CPU | CPU change | Stock RSS | Shadow RSS | RSS change |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Private loop, 300M writes | 0.5488 s | 0.1718 s | 68.7% faster | — | — | — |
| Redis | 92,377 req/s | 91,843 req/s | 0.65% lower throughput | ~41,804 KiB | ~41,916 KiB | +0.3% |
| SQLite speedtest1 | 5.609 s | 5.599 s | 0.2% faster | 112,908 KiB | 112,704 KiB | -0.2% |

Redis, SQLite, IS-B, and CG-A were statistically indistinguishable from stock
in the retained runs. BT-W is the main application-sized positive result.
The [profiler analysis](../profiler/results.md) explains why.

## NPB OpenMP

Each completed comparison used one warmup followed by seven balanced measured
runs with four OpenMP workers. All measured runs passed NPB verification. NPB
time is elapsed benchmark time; total CPU is user plus system time. Class S was
used only for build and correctness smoke tests, so it has no performance row.

| Workload | Variant | Measured runs | Median NPB time | Total CPU | Peak RSS |
| --- | --- | ---: | ---: | ---: | ---: |
| BT-W | Stock | 7 | 5.540 s | 22.440 s | 41,080 KiB |
| BT-W | Parallel note | 7 | 19.640 s (+254.5%) | 79.240 s (+253.1%) | 54,520 KiB (+32.7%) |
| BT-W | Shadow-resident | 7 | 3.880 s (-30.0%) | 15.750 s (-29.8%) | 41,124 KiB (+0.1%) |
| BT-A | Stock | 7 | 117.010 s | 471.110 s | 166,776 KiB |
| BT-A | Parallel note | 0 (timeout) | — | — | — |
| BT-A | Shadow-resident | 7 | 79.140 s (-32.4%) | 319.620 s (-32.2%) | 166,820 KiB (+0.03%) |
| IS-W | Stock | 7 | 0.220 s | 1.160 s | 58,360 KiB |
| IS-W | Parallel note | 7 | 0.360 s (+63.6%) | 1.840 s (+58.6%) | 71,160 KiB (+21.9%) |
| IS-W | Shadow-resident | 7 | 0.210 s (-4.5%) | 1.130 s (-2.6%) | 58,276 KiB (-0.1%) |
| IS-B | Stock | 7 | 7.240 s | 37.320 s | 844,024 KiB |
| IS-B | Parallel note | 7 | 11.620 s (+60.5%) | 59.800 s (+60.2%) | 856,824 KiB (+1.5%) |
| IS-B | Shadow-resident | 7 | 7.250 s (+0.1%) | 37.390 s (+0.2%) | 844,068 KiB (+0.0%) |
| CG-W | Stock | 7 | 1.540 s | 6.770 s | 56,440 KiB |
| CG-W | Parallel note | 7 | 2.320 s (+50.6%) | 10.420 s (+53.9%) | 69,496 KiB (+23.1%) |
| CG-W | Shadow-resident | 7 | 1.560 s (+1.3%) | 6.840 s (+1.0%) | 56,356 KiB (-0.1%) |
| CG-A | Stock | 7 | 5.490 s | 24.450 s | 111,992 KiB |
| CG-A | Parallel note | 7 | 8.030 s (+46.3%) | 37.670 s (+54.1%) | 125,176 KiB (+11.8%) |
| CG-A | Shadow-resident | 7 | 5.440 s (-0.9%) | 24.320 s (-0.5%) | 111,908 KiB (-0.1%) |

BT-A parallel note has no measured repetitions because its preliminary run
exceeded the 120-second per-process limit. The paired BT-A shadow-resident NPB
time improved by 33.04%, with an approximate 95% confidence interval from
28.05% to 37.69%.

The BT-W and BT-A improvements are materially larger than VM noise and agree
with the profiler. The smaller shadow-resident differences for IS and CG are
statistically indistinguishable from stock. Parallel note is consistently
slower and uses more memory in every completed NPB comparison.

## FFmpeg 4.3.9

These runs used the pinned `WatchingEyeTexture.mkv`, four worker threads, one
warmup, and seven balanced measured repetitions. Times and RSS are medians;
the value in parentheses is relative to stock.

| Codec | Variant | Runs | Wall time | Total CPU | Peak RSS |
| --- | --- | ---: | ---: | ---: | ---: |
| H.264 | Stock | 7 | 63.15 s | 238.45 s | 448,948 KiB |
| H.264 | Parallel note | 7 | 79.07 s (+25.2%) | 306.64 s (+28.6%) | 663,744 KiB (+47.8%) |
| H.264 | Shadow resident | 7 | 63.00 s (-0.2%) | 239.09 s (+0.3%) | 453,424 KiB (+1.0%) |
| H.265 | Stock | 7 | 320.56 s | 1,249.93 s | 1,045,908 KiB |
| H.265 | Parallel note | 7 | 375.97 s (+17.3%) | 1,468.78 s (+17.5%) | 1,306,524 KiB (+24.9%) |
| H.265 | Shadow resident | 7 | 323.53 s (+0.9%) | 1,250.06 s (+0.0%) | 1,048,164 KiB (+0.2%) |
| MJPEG | Stock | 7 | 113.07 s | 448.47 s | 312,136 KiB |
| MJPEG | Parallel note | 7 | 188.67 s (+66.9%) | 741.51 s (+65.3%) | 433,112 KiB (+38.8%) |
| MJPEG | Shadow resident | 7 | 111.66 s (-1.2%) | 442.65 s (-1.3%) | 316,488 KiB (+1.4%) |
| Copy | Stock | 7 | 1.276 s | 1.27 s | 86,708 KiB |
| Copy | Parallel note | 7 | 2.236 s (+75.3%) | 2.23 s (+75.6%) | 99,468 KiB (+14.7%) |
| Copy | Shadow resident | 7 | 1.212 s (-5.1%) | 1.20 s (-5.5%) | 90,992 KiB (+4.9%) |

Shadow resident is effectively at stock performance for the three encoding
workloads. Copy is too short for its small absolute difference to support a
general speed claim. Parallel note is slower and uses more resident memory in
all four modes. H.265 had visible VM drift (stock wall-time standard deviation
27.19 s), so these remain development results pending native Linux repetition.
