# Benchmark results

[Documentation](../README.md) · [Run the benchmarks](README.md) · [Profiler analysis](../profiler/results.md)

Unless labelled otherwise, these are Linux/AArch64 VM development results. CPU
is user plus system time; RSS is peak resident memory. Native Linux confirmation
for Memcached and MySQL is reported below. A dash means the metric was not
retained and must not be inferred as unchanged.

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

## Native Linux Memcached 1.6.29

This comparison used the supplied 30-second `memtier_benchmark` workload from
`focs-lab/tsan-experiments` at commit
`ffb2d5a8cac32c27d5eb0dcb667428435aca0320`. Each variant had one warmup and
seven interleaved measured runs. CPU is user plus system time; RSS is peak
resident memory.

| Variant | Runs | Throughput | Wall time | Total CPU | Peak RSS |
| --- | ---: | ---: | ---: | ---: | ---: |
| Stock | 7 | 67,837.63 ops/s | 33.27 s | 110.09 s | 56,768 KiB |
| Parallel note | 7 | 60,542.90 ops/s (-10.75%) | 33.26 s (-0.03%) | 106.36 s (-3.39%) | 56,828 KiB (+0.11%) |
| Shadow resident | 7 | 67,897.24 ops/s (+0.09%) | 33.27 s (+0.00%) | 109.95 s (-0.13%) | 56,828 KiB (+0.11%) |

Shadow resident is indistinguishable from stock. Parallel note reduces server
CPU slightly but also reduces delivered throughput by 10.75%, so it is not a
performance improvement. Profiler and hardware-counter runs are separate from
these timing measurements. Raw logs and per-run measurements are retained on
the native benchmark host and are not committed.

## Native Linux MySQL 8.0.39

This native x86-64 run used MySQL 8.0.39 and the supplied sysbench
`oltp_read_write` workload from `focs-lab/tsan-experiments` commit
`ffb2d5a8cac32c27d5eb0dcb667428435aca0320`: three workers and 180 seconds per
run. One warmup preceded seven balanced, interleaved measured repetitions.
Values are medians; dispersion is median absolute deviation (MAD), and
percentages are relative to stock.

| Variant | Runs | TPS | QPS | Wall time | Total CPU | Peak server RSS |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Stock | 7 | 13.65 (MAD 0.22) | 273.12 (MAD 4.33) | 180.20 s (MAD 0.01) | 336.74 s (MAD 0.43) | 3,046,412 KiB (MAD 248) |
| Parallel note | 7 | 10.43 (-23.59%; MAD 0.04) | 208.51 (-23.66%; MAD 0.96) | 180.28 s (+0.04%; MAD 0.04) | 341.10 s (+1.29%; MAD 0.36) | 3,060,656 KiB (+0.47%; MAD 1,060) |
| Shadow resident | 7 | 13.30 (-2.56%; MAD 0.10) | 265.91 (-2.64%; MAD 2.02) | 180.17 s (-0.02%; MAD 0.03) | 337.73 s (+0.29%; MAD 0.70) | 3,050,652 KiB (+0.14%; MAD 560) |

Total CPU, user time, and system time include both the sysbench client and
MySQL server. The retained operating-system counters were:

| Variant | User time | System time | Minor faults | Major faults | Voluntary switches | Involuntary switches | Exit status |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Stock | 325.06 s (MAD 0.73) | 11.94 s (MAD 0.09) | 570,725 (MAD 2,901) | 0 (MAD 0) | 653,788 (MAD 2,792) | 354,028 (MAD 2,145) | 0 |
| Parallel note | 330.89 s (+1.79%; MAD 0.40) | 10.43 s (-12.65%; MAD 0.03) | 478,855 (-16.10%; MAD 3,592) | 0 (MAD 0; max 1) | 621,108 (-5.00%; MAD 2,403) | 347,135 (-1.95%; MAD 2,454) | 0 |
| Shadow resident | 325.83 s (+0.24%; MAD 0.53) | 11.90 s (-0.34%; MAD 0.10) | 562,354 (-1.47%; MAD 1,827) | 0 (MAD 0; max 1) | 669,114 (+2.34%; MAD 2,655) | 360,022 (+1.69%; MAD 3,613) | 0 |

The parallel-note variant reduced throughput by about 24% despite similar wall
time, while shadow resident remained within 3% of stock throughput with nearly
unchanged CPU and RSS. All measured client and server processes exited
successfully. Ownership-profiler and stock `perf stat` executions completed
separately after headline timing and are not included in these rows.

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
