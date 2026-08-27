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
