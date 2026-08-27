# Experiment log

Measurements below were made in the Ubuntu 24.04 AArch64 Lima VM unless noted
otherwise. Candidate-to-candidate comparisons isolate one implementation
change; stock numbers are kept in `linux_vm_2026-08-27.md`.

## Linux note-range selection — kept

The first Linux port checked low, fixed-heap, and high application ranges. On
AArch64 the fixed-heap range is empty, while normal allocations use high
application memory. Replacing the three-way probe with low memory plus one
platform-selected secondary range changed the private-loop median from
0.5905 s to 0.3944 s.

## Prefetch ordinary shadow on note-path entry — rejected

The experiment issued `__builtin_prefetch(MemToShadow(addr), 0, 3)` after the
shadow address calculation and before processing the one-word note. The
generated AArch64 callback contained `prfm pldl1keep`, and focused private,
revocation, and race tests passed.

Five or seven warmed, interleaved repetitions compared the same candidate
before and after adding the prefetch:

| Workload | Without prefetch | With prefetch | Difference |
| --- | ---: | ---: | ---: |
| Private loop, median time | 0.396888 s | 0.398167 s | 0.3% slower |
| Redis, median throughput | 63,163 req/s | 63,564 req/s | 0.6% faster |
| SQLite, median time | 9.58 s | 9.52 s | 0.6% faster |

Redis peak RSS was 59,448 KiB for both variants. SQLite peak RSS was
124,520 KiB without the prefetch and 124,508 KiB with it. These differences
are smaller than normal run-to-run variation, so the prefetch was removed.
It cannot help an inline exact-note hit because that path never enters the
runtime. It is also wasted when the runtime successfully merges into the note
and does not inspect ordinary shadow.

## Cache-line interpretation

A TSan shadow cell is four 32-bit words, or 16 bytes, and fits inside one
64-byte cache line. A cache miss fetches the whole line, so changing an aligned
load from 16 bytes to 4 bytes does not remove that line-fill latency. The two
operations are still not free or equivalent: instruction count, vector
comparison work, dependencies, bandwidth, and line residency remain relevant.

The separate note is a second address stream. A note miss followed by fallback
can fetch both a note line and an ordinary-shadow line. This motivates the next
experiment: recognize repeated exact accesses directly in the existing shadow
cell, without a second mapping.

## Existing shadow, slot 0 plus three empty slots — superseded

The first shadow-resident prototype loaded all four 32-bit words in the normal
TSan shadow cell. It skipped the runtime callback only when slot 0 exactly
matched the current access and slots 1–3 were empty. Relaxed atomic loads became
four ordinary AArch64 `ldr` instructions in the same 16-byte cell.

Seven warmed, CPU-pinned private-loop runs had medians of 0.551 seconds for
stock TSan and 0.243 seconds for this check, about a 56% reduction. SQLite was
5.81 seconds versus 5.86 seconds stock. Redis was 90,827 versus 89,824 requests
per second stock. The application differences are too small for a performance
claim, but unlike the separate-note filter there was no large regression.

The three empty-slot loads are not required. Stock `ContainsSameAccess` returns
as soon as any slot exactly matches the current access, regardless of the other
slots. Requiring emptiness only makes the inline subset more conservative.

## Existing shadow, exact slot-0 hit — superseded

The refined check performs one relaxed 32-bit load from normal shadow slot 0.
An exact write match, or stock's read-adjusted exact match, skips the callback;
every mismatch uses unmodified TSan. It allocates no extra memory and does not
implement a separate private/shared state machine.

Thirty paired private-loop runs measured 0.5488 seconds stock and 0.1613
seconds candidate on average, a 70.61% reduction with an approximate 95%
interval of ±0.34 percentage points.

The weakness appears when the repeated current word is not in slot 0. In the
ordered handoff benchmark, the main thread initializes the cell and a worker
created afterward writes it repeatedly. TSan places the worker's word in slot
1. Across 20 rotated runs, stock averaged 0.5835 seconds and the slot-0 filter
averaged 0.6783 seconds. The filter was 16.23% slower, with a 95% interval of
[15.20%, 17.26%], because every iteration performed the inline miss and then
called TSan to find the exact hit in slot 1.

## Existing shadow, staged four-slot hit — kept

The staged version keeps the slot-0 load and branch as the common path. Only a
slot-0 miss loads slots 1–3. A hit in any slot skips the callback; an all-slot
miss falls back unchanged. The implementation performs exact comparisons only:
there is no merge, shadow write, ownership state, or second mapping.

On AArch64, the rest block compiles to three 32-bit loads followed by a compact
`cmp`/`ccmp` chain. The common slot-0 hit does not execute those loads.

Repeated Linux measurements:

| Workload | Stock | Slot 0 | Staged | Interpretation |
| --- | ---: | ---: | ---: | --- |
| Ordered handoff, 20 runs | 0.5835 s | 0.6783 s | 0.2810 s | staged 52.15% faster than stock |
| SQLite, 15 runs | 5.609 s | 5.713 s | 5.599 s | all differences include zero |
| Redis, 15 runs | 92,377 req/s | 90,668 req/s | 91,843 req/s | all differences include zero |

The staged handoff result is 58.83% lower than slot 0, with a 95% interval of
[56.95%, 60.62%]. On the private slot-0 case, 30 paired runs put staged 2.29%
behind the one-slot version, but the interval was ±2.38 percentage points, so
no difference was established.

Peak RSS remained effectively unchanged. SQLite measured 112,908 KiB stock,
112,688 KiB slot 0, and 112,704 KiB staged. Redis was approximately 41,804,
41,828, and 41,916 KiB respectively.

The same pass was also tested on macOS using one compiler with the feature flag
off and on. Thirty paired runs found the staged version 83.05% faster on the
private loop and 74.45% faster on the ordered handoff loop. Five-run peak RSS
means differed by only 13 KiB on the private test and were identical on the
handoff test.

Linux and Darwin instrumentation tests, focused race tests, and the full Linux
TSan suite passed. See `shadow_resident_2026-08-27.md` for confidence
intervals, protocol details, and exact revisions.

## Hardware counters in the local VM — unavailable

`perf` is installed and software timing events work, but the Apple
Virtualization Framework guest exposes no PMU events. Even after temporarily
allowing perf access, cycles, instructions, branches, and cache events report
`not supported`. Final IPC and cache-miss measurements therefore require
native Linux or a VM/hypervisor with PMU passthrough.
