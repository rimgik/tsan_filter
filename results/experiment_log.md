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

## Existing shadow, exact slot-0 hit — kept

The refined check performs one relaxed 32-bit load from normal shadow slot 0.
An exact write match, or stock's read-adjusted exact match, skips the callback;
every mismatch uses unmodified TSan. It allocates no extra memory and does not
implement a separate private/shared state machine.

In one interleaved seven-run private-loop series, median time was 0.584 seconds
for stock, 0.256 seconds for the four-load form, and 0.170 seconds for the
one-load form. The one-load check was about 71% faster than stock in this
deliberately favorable case.

Five-run application medians were approximately neutral:

| Workload | Stock | Exact slot 0 | Difference |
| --- | ---: | ---: | ---: |
| SQLite speedtest1 | 5.78 s | 5.77 s | 0.2% faster |
| Redis mean throughput | 89,072 req/s | 90,135 req/s | 1.2% faster |

SQLite median peak RSS was 112,908 KiB stock and 112,684 KiB candidate. Redis
was 41,688 KiB and 41,784 KiB respectively. These small differences are within
VM variability. Focused pass and transition tests, static and shared runtime
linking, and the full TSan suite passed with no unexpected failures.

## Hardware counters in the local VM — unavailable

`perf` is installed and software timing events work, but the Apple
Virtualization Framework guest exposes no PMU events. Even after temporarily
allowing perf access, cycles, instructions, branches, and cache events report
`not supported`. Final IPC and cache-miss measurements therefore require
native Linux or a VM/hypervisor with PMU passthrough.
