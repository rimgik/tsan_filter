# Shadow-resident filter — Linux/AArch64, 2026-08-27

This experiment inlines an exact-hit check against slot 0 of TSan's existing
shadow cell. It is commit `7c8ce9a14d78` on
`feat/shadow-resident-filter`, based on pristine LLVM commit `73e729f7b2f0`.
The feature is disabled by default and enabled with
`-mllvm -tsan-shadow-resident-filter`.

## What it does

For aligned, non-atomic 1, 2, 4, or 8-byte accesses in eligible leaf functions,
the pass computes `MemToShadow(addr)` and compares shadow slot 0 with the word
TSan would construct for the current access. A match skips the runtime callback.
A mismatch calls ordinary TSan without changing or discarding any shadow word.

This is a subset of stock `ContainsSameAccess`. It is not proof that the object
is thread-private, and it does not need ownership, revocation, allocator tags,
or a second mapping. Reads use the same read-bit adjustment as stock TSan.

The generated AArch64 hot path contains one plain `ldr` for the relaxed shadow
load, one comparison, and a conditional branch. Mapping constants and a pointer
to the current thread's fast state are loaded once per eligible function.

## Correctness

- LLVM instrumentation test: passed.
- Focused private-loop and cross-thread race test: passed.
- Static and shared TSan runtime linking: passed.
- Full `check-tsan`: 356 passed, 102 unsupported, 2 expected failures, and no
  unexpected failures.

The implementation deliberately falls back for unaligned, 16-byte, volatile,
compound, atomic, memintrinsic, and non-leaf cases.

## Results

The environment was an Ubuntu 24.04 AArch64 Lima VM with four virtual CPUs,
8 GiB RAM, and 4 KiB pages. Stock and candidate were separate Release builds
from the same base revision. Application results use five warmed, interleaved
runs; the private loop uses seven CPU-pinned runs.

The private loop was built at `-O1` and wrote one aligned heap cell 300 million
times. SQLite 3.54 speedtest1 used
`--size 25 --testset main --memdb :memory:`. Redis 8.8 used 100,000 requests
each for SET, GET, and INCR with 20 clients after a 20,000-request warmup. The
server used two I/O threads on CPUs 0–1 and the uninstrumented client used CPUs
2–3.

| Workload | Stock TSan | Shadow-resident | Result |
| --- | ---: | ---: | ---: |
| One cell, 300M writes | 0.584 s | 0.170 s | 70.8% faster |
| SQLite speedtest1, size 25 | 5.78 s | 5.77 s | 0.2% faster |
| Redis SET/GET/INCR mean | 89,072 req/s | 90,135 req/s | 1.2% faster |

Peak RSS was effectively unchanged: 21,716 versus 21,632 KiB for an earlier
private-loop measurement, 112,908 versus 112,684 KiB for SQLite, and 41,688
versus 41,784 KiB for Redis.

The private-loop improvement is real but deliberately favorable: one runtime
call initializes the shadow, then repeated exact hits stay inline. The SQLite
and Redis differences are within VM noise, so the current evidence supports
“no observed regression,” not a general speedup claim.

## Counter limitation

The Lima VM does not expose cycles, instructions, IPC, or cache events through
`perf`; those events report `not supported`. Use native Linux or PMU passthrough
before attributing the result to cache misses or instruction count.
