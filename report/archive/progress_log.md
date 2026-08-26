# Progress Log

Consolidated from the weekly reports and supervisor updates during the 2026-08-24 cleanup, in chronological order. Each section is the original doc verbatim, unedited.

---

## supervisor_update_2026-07-05.md

# Update: Soundness of the Ownership Filter, and the Corrected Design

This note reports three results since the v0.2 proposal: (1) v0.2 as written is unsound and the holes are structural, not patchable details; (2) a minimality argument showing what any sound replacement is forced to look like; (3) a literature check (July 2026) confirming the corrected design still occupies an open niche. The correctness bar throughout is *parity*: no false positive TSan would not report, no race missed that stock TSan v3 catches.

## 1. Why v0.2 is unsound

v0.2 summarises a region's entire single-owner phase as one `(sid, last-write-epoch)` tag and checks happens-before once at the exclusive-to-shared transition. Every failure below comes from the same root: the tag is a *summary*, and each thing the summary drops is something stock TSan kept in shadow.

**False positives (masks).** The tag has no byte mask. Owner writes byte 0; a second thread writes byte 1, unordered. Stock sees disjoint masks and stays silent; the boundary check sees an unordered write-write pair and reports. This alone disqualifies the design — precision is TSan's hardest guarantee.

**Missed races (later reads).** Owner does `W(byte0, e5)` then `R(byte3, e7)`. The tag keeps the write epoch. A foreign write to byte 3, ordered after e5 but concurrent with e7, passes the boundary check; stock has the read word in shadow and reports.

**Missed races (reader sets).** In the read-shared state several threads' reads are elided. The first write must be checked against every unordered reader; stock holds up to four reader words; one tag cannot represent a set. The read-shared fast path — the main advantage of the 2-bit design — is precisely the state a scalar tag cannot summarise.

**Unreportable races.** TSan prints a race only if `RestoreStack` finds a trace event matching the old shadow word; otherwise the report is silently dropped. Elided accesses were never traced, so even a correctly *detected* boundary race is suppressed.

**Racy transition.** The owner updates the tag with plain stores while a foreign thread CASes the state; an in-flight owner access can be elided at the very moment the region becomes shared — the racing access itself goes unrecorded. OCTET and FIB pay round-trip / safe-point coordination exactly here; a bare CAS does not close the window.

## 2. What a sound design is forced to look like

Ask the question mathematically: over a single-owner phase, what is the minimal state that decides, for any future foreign access `(mask, type, clock)`, exactly what stock would decide? Same-thread accesses subsume each other only per byte: a later access covers an earlier one iff its mask is a superset and it is not a read replacing a write (any thread unordered with the old access is unordered with the covering one, which conflicts with at least as much). What survives is, per byte, the latest write epoch plus the latest read epoch where later — worst case about 28 bytes, *larger than the 16-byte shadow cell elision was meant to avoid*. Parity with stock is no cheaper in the worst case: stock's four non-dominated words can each be the sole witness of a race for some future access, so any parity-preserving state must reproduce all four.

Conclusion: **no summary beats storing on all inputs.** Compression can only be probabilistic, and its shape is forced: keep *one verbatim shadow word* while it covers the phase's live history, and the moment a new access fails the cover rule ($m_{\mathrm{new}} \supseteq m_{\mathrm{old}}$ and (old is read or new is write); masks of equal-epoch same-type accesses may be losslessly unioned), flush the old word into real shadow before replacing it. At the transition the last word is flushed too, so shadow then equals stock's and ordinary TSan takes over — no boundary check, no synthetic reports, no summary to get wrong. The verbatim representation also satisfies the trace requirement, since each cached word was traced when created.

The cover rule is stock's own domination rule; that is not the contribution. The contribution is purely where it runs: a 4-byte meta cell covers 8 bytes of application memory (one cache line per 128 B) against the 16-byte shadow cell (one line per 32 B) — 4× the density — and shadow pages for data that never becomes shared are never faulted in at all. TSan's residual overhead is dominated by shadow cache traffic (the v2→v3 redesign halved shadow word size for exactly this reason), so the bet targets the right cost. It remains a bet: stock's hit path is also a single 16-byte SIMD load, so the win exists only where the shadow line would miss cache while the denser meta line stays resident. This is measurable before any real engineering (Section 4).

A second, independent mechanism falls out for free. After handover the meta cell would sit idle; instead it becomes a **victim slot**: words evicted from TSan's 4-word cell are flushed into it and consulted on the slow path only. This is sound by construction — it only ever *adds* history stock discards — so every outcome is "equal to stock or strictly better." It directly targets TSan's one documented incompleteness (bounded shadow with pseudo-random eviction), at zero hot-path cost.

## 3. Literature position (checked July 2026)

Paznikov et al. (*Compiling Away the Overhead of Race Detection*, Dec 2025) is being upstreamed into TSan: five static analyses deleting provably race-free instrumentation, 1.34× geomean. It removes the statically provable subset; our filter targets the dynamically-private remainder (escaped pointers, heap aliasing, input-dependent sharing) — complementary, but all our measurements must baseline on a Paznikov-enabled TSan or the headroom is overstated. The sampling line (POPL 2023; PLDI 2025 timestamping) gets speed by abandoning detection parity, which is our differentiator. TMon (CCPE 2026) reaches TSan-v3-level detection via Intel PT but is postmortem and hardware-bound; notably it also attacks shadow-overwrite misses, independent evidence for the victim-slot idea. Tech-ASan (2025) validates the cheap-pre-check-before-shadow pattern for ASan. No published system is a dynamic, online, parity-preserving filter inside TSan v3's fixed shadow; the victim-slot mechanism appears unclaimed.

## 4. Plan

Milestone 1 is a counting-only build (never skips, never changes behaviour) that decides everything cheaply: (a) the fraction of single-owner-phase accesses whose live history stays at one word — the single number the write-back design lives or dies by; (b) the exclusive / read-shared / write-shared access breakdown for C/C++, which no published study reports and is a contribution regardless of outcome; (c) overlap between would-be cache hits and stock's `ContainsSameAccess` hits; (d) cache-miss profile over a working-set sweep, on a Paznikov-enabled baseline. If (a) and (d) support the bet, implement the write-back cell and victim slot behind TSan's test suite as a regression gate (reports must match stock exactly; the victim slot may only add true reports). If they do not, the victim slot and the measurement study stand alone as the deliverable.

---

## supervisor_update_2026-07-16.md

# Update: Measurement Build and First Results

## 1. What was built

A measurement-only version of TSan ("counting build"): stock TSan v3 plus a flag-gated hook that classifies every aligned memory access and prints a histogram at exit. Detection behaviour is untouched. The goal is to measure, before building anything, the upper bound of what a sound ownership filter can save: how many accesses are private, and of those, how many are not already absorbed by TSan's existing fast path. Source changes in Appendix D.

```
                          instrumented access
                                  |
                                  v
                 +--------------------------------+
                 |     stock TSan v3, UNCHANGED   |
                 |  fast path -> race check ->    |
                 |  store/evict -> (report)       |
                 +--------------------------------+
                                  |
                                  | (counting hook, flag-gated)
                                  v
                 +--------------------------------+
                 |  classify this access:         |
                 |   cell state?  fast-path hit?  |
                 |   filter would absorb it?      |
                 +--------------------------------+
                                  |
                                  v
                        counters, printed at exit
```

Per access the hook asks three questions:

```
Q1: what did the cell contain at this moment?      (exclusive rows, sum to 100%)

      no history ------------------------- first-touch
      only my own words ------------------ private
      other threads' words, reads only --- read-shared
      other threads' words, write there -- write-shared
      access is atomic ------------------- atomics

Q2: would stock's existing fast path (ContainsSameAccess,
    exact repeated access) absorb it anyway?             -> "csa" column

Q3: only if Q2 = no: would the proposed ownership filter
    absorb it (cover = superset mask at newer epoch,
    merge = same-epoch mask union)?                      -> filter's marginal market
```

## 2. Benchmarks

| workload | purpose | source |
|---|---|---|
| bench_private | best case for "cover": per-thread accumulator in a lock loop | Appendix A |
| bench_init | best case for "merge": build buffers byte-wise, publish once | Appendix B |
| bench_shared | worst case: 8 threads hammer one shared struct | Appendix C |
| Redis | real server workload | below |

Redis setup: redis-stable built with the instrumented clang (`make CC="clang -fsanitize=thread" OPTIMIZATION=-O1 MALLOC=libc`, jemalloc disabled so TSan intercepts allocation), run as `redis-server --port 7777 --io-threads 4`, loaded with `redis-benchmark -n 50000 -c 20 -t set,get,incr,lpush,lpop,sadd` (about 390M instrumented accesses), stopped gracefully so the histogram prints.

## 3. Results

Redis, 391M accesses:

| bucket | % of total | of which csa | filter beyond csa | rest |
|---|---|---|---|---|
| private | 26% | 70% | 14% cover + 8% merge | 6% |
| read-shared | 29% | 66% | impossible (proven) | 33% |
| write-shared | 38% | 61% | not applicable | 38% |
| first-touch | 2% | | | |
| atomics | 3% | | | |

```
share of ALL accesses (Redis):

private      |##########################               | 26%
read-shared  |#############################            | 29%
write-shared |######################################   | 38%
first-touch  |##                                       |  2%
atomics      |###                                      |  3%

inside the private 26%:

already free (csa)   |####################################      | 70%
filter marginal      |###########                               | 22%
neither              |###                                       |  6%
```

Microbenchmarks matched predictions:

| bench | dominant bucket | key number |
|---|---|---|
| bench_init | private 93% | merge absorbs 46% of private beyond csa |
| bench_shared | write-shared 66% | csa ~0%: cell content turns over constantly |
| bench_private | artifact, see finding 2 | private undercounted ~120x |

## 4. Findings

### Finding 1: the filter's runtime headroom on server code is small

```
all accesses (100%)
   |
   |-- 54%+  provably cannot race right now (private + read-shared)
   |            |
   |            |-- ~2/3 already absorbed by stock's fast path
   |            |
   |            '-- filter's marginal work market: 26% x 22% = ~6% of accesses
   |                               = roughly 3% end-to-end, before overheads
   |
   '-- what remains:
        (a) cache/memory: ALL private traffic (fast-path hits included) stops
            touching 16-byte shadow lines; private regions never materialise
            shadow pages at all (metadata 2x -> 0.5x for that data)
        (b) init-heavy code: merge alone absorbs 40%+ (bench_init)
```

### Finding 2: TSan's slot recycling breaks naive ownership; the design must handle it

TSan identifies threads in shadow by a borrowed slot id (256 slots, 14-bit per-slot epoch). A thread doing sync operations exhausts its slot every ~16K syncs and re-attaches under a new id:

```
thread T, 2M lock/unlock iterations:

  slot 0            slot 7            slot 3
  epochs 1..16384   epochs 1..16384   epochs ...        (~120 re-attaches)
  |---------------|-----------------|----------------
                  ^                 ^
                  old words in shadow still say "slot 0":
                  T no longer recognises ITS OWN history
                  -> naive filter hands private data over, forever
```

Measured effect: 8M genuinely private accumulator accesses classified write-shared; only the first ~16K-per-thread window (131K accesses, matching 4 x 16384 x 2 exactly) counted as private. The measured private fraction is therefore a lower bound, and the write-shared row's high csa rate suggests part of it is this artifact. The fix, now part of the design: each thread keeps the slot/epoch intervals it held; ownership is validated against the interval. Sound because slot epochs are monotonic within a generation.

### Remark: where the known eviction incompleteness concentrates

TSan's bounded shadow is a known, accepted source of missed races. The benchmark only locates it: bench_shared's fast-path rate of ~0% means contended cells recycle their content constantly, so the misses sit in the write-shared bucket (38% of accesses on Redis). A cheap extension could park the evicted word in the filter's side cell and check it on the slow path; listed as an option, not a finding.

Raw outputs and patches: `mvp/` and `benchmark_result/` in the repo.

---

## Appendix A: bench_private.c

```c
#include <pthread.h>
#include <stdio.h>
#include <stdlib.h>

#define THREADS 4
#define ITERS 2000000

pthread_mutex_t m = PTHREAD_MUTEX_INITIALIZER;
long shared_tickets = 0;

void *worker(void *arg) {
    // Heap-allocated so it is actually instrumented: a stack local would be
    // register-allocated at -O1 and skipped by clang's TSan escape analysis.
    long *sum = malloc(64);             // own cache line, thread-private
    *sum = 0;
    for (long i = 0; i < ITERS; i++) {
        pthread_mutex_lock(&m);         // epoch++ at unlock
        long t = shared_tickets++;      // tiny shared touch
        pthread_mutex_unlock(&m);
        *sum += t;                      // same cell, same mask, new epoch
    }
    long r = *sum;
    free(sum);
    return (void *)r;
}

int main(void) {
    pthread_t th[THREADS];
    for (int i = 0; i < THREADS; i++) pthread_create(&th[i], 0, worker, 0);
    void *r;
    long total = 0;
    for (int i = 0; i < THREADS; i++) { pthread_join(th[i], &r); total += (long)r; }
    printf("total=%ld\n", total);
    return 0;
}
```

## Appendix B: bench_init.c

```c
#include <pthread.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#define BUFS 2000
#define BUFSZ 4096

char *bufs[BUFS];
pthread_mutex_t m = PTHREAD_MUTEX_INITIALIZER;
pthread_cond_t cv = PTHREAD_COND_INITIALIZER;
int ready = 0;

void *reader(void *arg) {
    pthread_mutex_lock(&m);
    while (ready < BUFS) pthread_cond_wait(&cv, &m);
    pthread_mutex_unlock(&m);
    long sum = 0;
    for (int i = 0; i < BUFS; i++)
        for (int j = 0; j < BUFSZ; j += 512) sum += bufs[i][j];
    printf("reader sum=%ld\n", sum);
    return 0;
}

int main(void) {
    pthread_t th;
    pthread_create(&th, 0, reader, 0);
    for (int i = 0; i < BUFS; i++) {
        bufs[i] = malloc(BUFSZ);
        for (int j = 0; j < BUFSZ; j++)     // byte writes: masks grow, merge
            bufs[i][j] = (char)(i + j);
    }
    pthread_mutex_lock(&m);
    ready = BUFS;                            // publish
    pthread_cond_broadcast(&cv);
    pthread_mutex_unlock(&m);
    pthread_join(th, 0);
    return 0;
}
```

## Appendix C: bench_shared.c

```c
#include <pthread.h>
#include <stdio.h>

#define THREADS 8
#define ITERS 500000

pthread_mutex_t m = PTHREAD_MUTEX_INITIALIZER;
struct { long a, b, c, d; } S;

void *worker(void *arg) {
    for (long i = 0; i < ITERS; i++) {
        pthread_mutex_lock(&m);
        S.a++; S.b += 2; S.c ^= i; S.d = S.a + S.b;
        pthread_mutex_unlock(&m);
    }
    return 0;
}

int main(void) {
    pthread_t th[THREADS];
    for (int i = 0; i < THREADS; i++) pthread_create(&th[i], 0, worker, 0);
    for (int i = 0; i < THREADS; i++) pthread_join(th[i], 0);
    printf("S.a=%ld\n", S.a);
    return 0;
}
```

## Appendix D: TSan source changes (branch `ownership-counting`, 3 files)

New runtime flag (`tsan_flags.inc`):

```c
TSAN_FLAG(bool, ownership_counting, false,
          "Measurement only: collect ownership/cover/merge statistics for "
          "memory accesses and print them at exit. Does not change race "
          "detection behavior.")
```

Classifier and counters (`tsan_rtl_access.cpp`):

```c
struct OwnershipCounters {
  atomic_uint64_t atomics;
  atomic_uint64_t empty;
  atomic_uint64_t priv, priv_csa, priv_cover_ncsa, priv_merge_ncsa;
  atomic_uint64_t ro, ro_csa;
  atomic_uint64_t rw, rw_csa;
};
static OwnershipCounters ownership_counters;

static void OCAdd(atomic_uint64_t* c) {
  atomic_fetch_add(c, 1, memory_order_relaxed);
}

NOINLINE void OwnershipCount(Shadow cur, RawShadow* shadow_mem, AccessType typ,
                             bool csa_hit) {
  OwnershipCounters& c = ownership_counters;
  if (typ & kAccessAtomic) {
    OCAdd(&c.atomics);
    return;
  }
  bool any = false, foreign = false, foreign_conflict = false;
  bool cover = false, merge = false;
  bool cur_read = !!(typ & kAccessRead);
  for (uptr i = 0; i < kShadowCnt; i++) {
    Shadow old(LoadShadow(&shadow_mem[i]));
    if (old.raw() == Shadow::kEmpty || old.raw() == Shadow::kRodata)
      continue;
    any = true;
    AccessType old_typ;
    old.GetAccess(nullptr, nullptr, &old_typ);
    bool old_read = !!(old_typ & kAccessRead);
    if (old.sid() != cur.sid()) {
      foreign = true;
      if (!old_read || !cur_read)
        foreign_conflict = true;
      continue;
    }
    bool sup = (cur.access() & old.access()) == old.access();
    if (sup && cur.epoch() >= old.epoch() && !(!old_read && cur_read))
      cover = true;
    else if (cur.epoch() == old.epoch() && old_read == cur_read &&
             cur.access() != old.access())
      merge = true;
  }
  if (!any) {
    OCAdd(&c.empty);
    return;
  }
  if (foreign) {
    if (foreign_conflict) {
      OCAdd(&c.rw);
      if (csa_hit)
        OCAdd(&c.rw_csa);
    } else {
      OCAdd(&c.ro);
      if (csa_hit)
        OCAdd(&c.ro_csa);
    }
    return;
  }
  OCAdd(&c.priv);
  if (csa_hit) {
    OCAdd(&c.priv_csa);
    return;
  }
  if (cover)
    OCAdd(&c.priv_cover_ncsa);
  else if (merge)
    OCAdd(&c.priv_merge_ncsa);
}
```

Hook in the access path (`MemoryAccess`, same file):

```c
  LOAD_CURRENT_SHADOW(cur, shadow_mem);
  if (LIKELY(ContainsSameAccess(shadow_mem, cur, shadow, access, typ))) {
    if (UNLIKELY(flags()->ownership_counting))
      OwnershipCount(cur, shadow_mem, typ, true);
    return;
  }
  if (UNLIKELY(flags()->ownership_counting))
    OwnershipCount(cur, shadow_mem, typ, false);
```

Report at exit (`tsan_rtl.cpp`, `Finalize`):

```c
  if (flags()->ownership_counting)
    PrintOwnershipCounters();
```

---

## weekly_report_2026-07-17.md

# Weekly Report

1. Reworked the counting build (v0.2). Previously I classified ownership using the slot ids stored in shadow memory, but I found this gives wrong numbers (details below). Now I keep a separate table that records which thread id owns each 8-byte cell, and classify against that. The same table also simulates the planned filter on every access (cover / merge / flush) and counts hash collisions and identity corrections, so I can tell whether the numbers are trustworthy.
2. Added an `overhead_report` flag to the runtime that prints wall time and memory use at exit. I applied it to both my branch and a clean baseline branch, so later I can compare stock TSan against my modified TSan with the same output.
3. Wrote a working-set sweep benchmark for measuring cache effects (not run yet), plus short notes on how to build the compiler, compile a program with it, run the counter, and how to do the stock-vs-modified comparison.

## Result

TSan does not store thread ids in shadow memory, only slot ids, and a thread changes its slot after around 16K sync operations. My earlier numbers were distorted by this. With real thread ids:

```
Redis, ~390M accesses            slot-id based     thread-id based
private                              26%                 45%
read-shared                          29%                 10%
write-shared                         39%                 39%
```

So about 19% of all accesses looked shared but were actually one thread that had changed slot id. Validity checks: 0 hash collisions in the table, and only 45K identity corrections in 390M accesses.

Split of the private 45%:

| | share |
|---|---|
| exact repeats, already cheap under stock TSan | 75% |
| cover + merge (what the filter saves on top) | 19% |
| flush (filter falls back) | 4% |

## Summary

45% of Redis's accesses touch memory used by a single thread; these are the accesses the filter can skip. 19% of them (about 8.6% of all accesses) are cases where skipping saves work that stock TSan currently does. The 4% flush rate means the one-word filter state is almost always enough. Still to measure: the cache effect of keeping the private 45% away from the 16-byte shadow lines, which is what the sweep benchmark is for.

---

## weekly_report_2026-07-24.md

# Weekly Report

## Implementation

The ownership filter is implemented in the TSan runtime. It adds 4 bytes of
metadata per 8 bytes of application memory (a "note"), holding one shadow
word in TSan's existing bit layout. While a cell is used by a single thread,
its accesses are handled by the note alone and TSan's normal work is skipped:
no shadow load, no trace event, no race check. When the note can no longer
represent an access, the cached word is written into real shadow and normal
TSan takes over for that cell. Nothing is discarded, only moved, so the
detector still sees everything it would have seen.

Two modes. Verify mode runs the filter alongside unmodified TSan and counts
any case where the filter would have skipped an access that TSan then found
a race on. Elide mode skips the work. Verify mode reported zero violations on
all benchmarks, and both modes report the same races as unmodified TSan.

## Benchmarks

Large private buffer (256MB allocation, filled and read by one thread, then
published to a second):

| | time | peak memory |
|---|---|---|
| no TSan | 0.11 s | 257 MB |
| TSan | 2.85 s | 925 MB |
| TSan + filter | 3.27 s | 541 MB |

Metadata memory: 668MB to 284MB, 2.35x less. Of 507 million accesses, all
but 515 were absorbed by the note, so the shadow memory for the buffer was
never written and never committed by the OS.

Redis (io-threads 4, redis-benchmark, 50k requests per test):

| | throughput | server memory |
|---|---|---|
| TSan | 83,176 ops/sec | 66.0 MB |
| TSan + filter | 77,644 ops/sec | 68.9 MB |

6.6% slower, 4.4% more memory.

## Analysis

Redis executes roughly 390 million instrumented accesses; 29 million are
absorbed by the note. The remainder land on cells already handed over to
normal TSan, where the filter adds a check and gains nothing: every access
pays, 7% benefit. Counters: 28.9M absorbed, 9.0M flushed, 5.6M handovers,
8.05M claims.

Two causes:

1. Redis allocates many small objects. TSan writes their shadow at
   allocation time, so the pages are committed before the filter can prevent
   it and there is no memory left to save.
2. Memory is shared and recycled constantly (5.6M handovers against 8M
   claims), so cells stop being private almost as fast as they are created.

The large buffer case is the opposite: the allocation is above the threshold
where TSan initialises shadow eagerly, and the memory stays private for its
whole lifetime. That benchmark is favourable by construction and should be
read as a demonstration of the mechanism, not of typical benefit.

## Next steps

Optimisation is required before the filter is useful on server workloads.

1. Make accesses to already-shared memory skip the filter cheaply, so they
   stop paying for a check that cannot help.
2. Evaluate storing the note inside TSan's existing shadow word instead of a
   separate region, using a reserved slot id as the state marker. This
   removes the extra memory and the extra load, at the cost of the memory
   saving seen in the large buffer case. The Redis result suggests this may
   be the better trade.
3. Confirm reporting completeness: absorbed accesses are not recorded in
   TSan's event trace, so a race found against a flushed note word may lose
   its stack. Detection is unaffected.
