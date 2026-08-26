# Brainstorm History

Consolidated from 4 separate brainstorm docs during the 2026-08-24 cleanup, in chronological order. Each section is the original doc verbatim, unedited.

---

## brainstorm_proposal.md (2026-05-31, earliest)

# Proposal Brainstorm — Ownership Meta-Shadow (Project 2)

_Scratch document for iterating on the design. Not the final report. High-level only — we pick a direction, then drill down._

> **Source note:** The percentages below come from OCTET, ReX, FastTrack,
> escape-analysis literature, and FIB. Check exact table labels against the
> cited papers before using the values in the final report.

---

## 0. What we're trying to beat

The baseline design (from the brief) is **2-state**: tag each 8-byte cell `Exclusive(owner)` at `malloc`; if a *different* thread touches it, demote to `Shared` forever and fall back to full TSan. Your two doubts are exactly the right ones:

- **(a)** What do the 8 bits encode? State? Owner? A per-byte bitmask?
- **(b)** One byte per *8* app bytes is coarse — if any one byte goes Shared, all 8 fall back, wasting the other 7 bytes' potential fast path.

Both questions collapse onto one empirical unknown: **what fraction of accesses are exclusive vs. read-shared vs. genuinely write-shared, and at what granularity does sharing actually happen?** So Section 1 is the research; Sections 2–3 are the designs that fall out of it.

---

## 1. The x% — what the literature says

The whole premise (yours and the papers') is that *conflicting cross-thread accesses are rare*. The evidence, now with real numbers:

| Claim | Number | Source |
|---|---|---|
| Accesses that take OCTET's **fast path** (conform to current state, no sync) | **~99.7–99.9999%** of all accesses | OCTET results table (local PDF) |
| Accesses that trigger a **state change** (true conflict needing coordination) | **<0.001% to ~0.7%** | OCTET §eval — "than 0.001% … to 0.10–0.72% for a few benchmarks" |
| TSan/FastTrack instrumented checks that are **redundant/removable** | **~90%** removable in the limit (drops 68× → 7× overhead); ReX realizes ~31% | ReX, ECOOP'17 |
| Lock operations eliminable because objects are **thread-local** (escape analysis proxy) | **11–92%, median ~51%** | Choi et al. escape analysis |
| Objects stack-allocatable (never escape) | **>70%** in 3/10 benchmarks, **median ~19%** | escape-analysis lit |
| OCTET runtime overhead (the bar to beat) | **26%** avg (fast path alone +13%) | OCTET |
| FastTrack speedup from O(1) thread-local/read-shared fast paths | ~10× vs BasicVC | FastTrack, PLDI'09 |

**Per-object state breakdown matters more than the headline.** OCTET's own table reports, per benchmark, the split across `WrEx / RdEx / RdSh` accesses. The pattern: a few percent write-exclusive, the **large majority read-exclusive or read-shared**, and write-sharing is the tiny tail. Two extreme rows make the point: `luindex9` is **99.99982%** one state; but `sunflow9` is only **42%** locality with **58% read-shared** because threads interleave reads to shared read-only data. That `sunflow9` row is the whole argument for a read-shared state — see below.

**Two takeaways that drive the design:**

1. **Read-shared is a large, separate category — and sometimes the *dominant* one.** OCTET's `sunflow9` spends 58% of accesses on read-shared data; several others sit at 1–9% RdSh. This is data *read by many threads but never concurrently written*. A pure 2-state (Exclusive/Shared) design throws this entire category onto the TSan slow path. OCTET and FastTrack get much of their win precisely from keeping read-shared data on a fast path. **This is the single biggest weakness of the baseline design.**

2. **Almost all of this data is from Java / managed runtimes.** There is little published escape/sharing data for **C/C++ TSan workloads**. That gap is itself a defensible FYP contribution: *measure x% for C/C++ first*, then let the measured numbers justify the design. Cheap to build (a counting-only meta-shadow that never skips, just tallies exclusive/read-shared/shared hits) and it de-risks every design choice below.

**On granularity (your point b):** heap allocations are 16-byte aligned (glibc), so two *distinct* `malloc` regions never share one 8-byte meta cell. The only way the "wasted 7 bytes" problem bites is **within a single object** — sub-8-byte fields of one struct owned/shared differently. That is real but uncommon; the natural unit of ownership is the whole allocation. So point (b) is probably a *minor* effect — but confirm with the x% measurement before spending hot-path budget on per-byte tracking.

---

## 2. Design options (high-level)

All of them share: meta-shadow region via the existing `MemToMeta`; tag at `malloc`, reset at `free`; inline check in the LLVM pass; revocation on cross-thread access.

### Design A — Baseline, 2-state, 1 byte (the brief as written)
1 byte/cell = owner SID, with a sentinel value for `Shared`. Fast path: `metabyte == cur_sid → skip`. Mismatch → write `Shared`, fall back forever.

- **8 bits:** owner SID (TSan SIDs are 8-bit, 256 slots) + reserve e.g. `0xFF`=Shared, `0xFE`=uninitialized.
- **Perf concern:** separate meta region = +1 cache line per access worst case, but density is 1 byte/8 app bytes, so one 64-byte meta line covers 512 app bytes → good spatial locality, sequential scans amortize. Fast path ≈ load byte + cmp + one highly-predictable branch → short, near-branchless.
- **Theoretical gain:** memory +1/8 = **+12.5%** of app memory (vs TSan's own ~200%). If ~X% of accesses are exclusive and the check is ~10× cheaper than `CheckRaces`, the access-handling cost drops toward `(1−X) + X/10`; at X=70% that's ≈0.37 → ~2.7× on the instrumentation component (rough, Amdahl-bounded).
- **Pros:** simplest; smallest memory; cleanest hot path.
- **Cons:** **loses all read-shared benefit** (biggest flaw); permanent demotion never recovers; SID-as-owner is fragile (see §3).

### Design B — 3-state OCTET-like (Exclusive / Read-Shared / Shared), still 1 byte ⭐ recommended starting point
Add a **Read-Shared** state. Encode in the *same* 1 byte via SID + sentinels: byte = owner SID for Exclusive; `0xFF` = Read-Shared; `0xFE` = Shared(fallback); `0xFD` = uninit.

- Reads check `byte == my_sid || byte == RDSHARED → skip`. Writes check `byte == my_sid → skip`. A write to Read-Shared, or a read/write by a non-owner to Exclusive → transition.
- **Directly answers (a):** the 8 bits are best spent as **owner-SID-with-sentinels, not a bitmask.** A bitmask can't also hold the owner; 3 states fit cleanly in one byte.
- **Perf concern:** hot path is one or two compares — reads need an OR (two compares) but both predictable. Same cache profile as A. Still effectively branchless.
- **Theoretical gain:** captures the large read-shared category that A discards → strictly more accesses on the fast path, especially for read-mostly shared data. Same +12.5% memory.
- **Pros:** mirrors OCTET (`WrEx/RdEx/RdSh`) so it's **directly comparable to the papers**; biggest expected win for ~no extra memory.
- **Cons:** slightly longer read fast path; transition logic more involved (read→read-shared promotion).

### Design C — Per-byte bitmask within the cell (your "bitmask" idea)
Widen meta to 16 bits (reuse the existing u32 meta slot): 8-bit owner SID + 8-bit mask of which bytes are still exclusive-clean. Fast path: `(mask >> byte_off) & 1 && owner == sid`.

- **Perf concern:** adds shift+and to the hot path → longer, less branchless. Memory now 2 bytes/8 = **+25%** (or +50% if using the full u32).
- **Theoretical gain:** only helps when intra-cell sharing is common — which §1 suggests is rare.
- **Pros:** recovers the "wasted 7 bytes" when sub-object sharing does happen.
- **Cons:** more memory, longer hot path, gain likely small. **Only worth it if the x% measurement shows significant intra-cell mixed ownership.** Park it.

### Design D — Allocation-granularity tagging (reframes point b)
Keep per-8-byte meta, but at `malloc` set the *whole region* uniformly to one owner. Ownership unit = the allocation, not the cell.

- This isn't really a separate data structure — it's Design A/B with the insight that, given 16-byte alignment, cells never straddle allocations, so point (b) mostly dissolves. Worth stating explicitly in the proposal as the justification for staying at 1 byte/cell.

### Design E — FIB-style adaptive (future extension)
On top of B: don't demote permanently — allow re-promotion, predictive read-sharing, and per-access CAS fallback for high-rate write sharing (FIB's adaptive fail-over).

- **Pros:** handles the pathological write-shared case gracefully; matches FIB's contribution.
- **Cons:** most complex; correctness-sensitive. Propose as stretch goal / evaluation extension, not v1.

---

## 3. Cross-cutting correctness note (flag now, don't solve yet)

**SID is not a stable thread identity.** Per your TSan v3 notes, a thread can be **preempted and reassigned a new SID mid-execution**. So `metabyte == cur_sid` can be false *for the same thread* after preemption → unnecessary (but safe) fallback, losing benefit; and a recycled SID could in principle alias a different thread → must ensure that's only ever *safe-conservative*, never a missed race. Options to consider later: store TID instead (needs >8 bits), or pin ownership to `(SID, attach_epoch)`, or accept conservative fallback on SID change. **This needs care but doesn't block choosing A vs B vs C now.** Also: revocation writes must be atomic, and `free` must reset the meta (and handle SID reuse).

---

## 3b. CHOSEN DIRECTION — Design B, refined (the proposed system)

This is the design we are going with. Everything below supersedes the generic "Design B" sketch in §2.

### Motivation (state this for the supervisor)

The project targets **C/C++** (LLVM `compiler-rt` ThreadSanitizer). The baseline 2-state design (Exclusive/Shared) is rejected for one empirical reason: **read-shared data is too large a category to dump onto the slow path.**

- In OCTET's measurements (Java), the ownership fast path covers **~99.7–99.9999%** of all accesses, and true conflicts are **<0.001%–0.72%**. Read-shared is not a rounding error: `sunflow9` spends **58%** of accesses on read-shared data, and several DaCapo benchmarks sit at **1–9%** read-shared.
- ReX (ECOOP'17, C/C++ FastTrack) shows **~90%** of race-detection checks are redundant in the limit (overhead 68× → 7×).
- Escape-analysis studies report **11–92% (median ~51%)** of lock operations removable because data is thread-local.
- **Caveat to state honestly:** all of these are Java/JVM numbers (OCTET, FastTrack, escape analysis) or C/C++ *redundancy* numbers (ReX), not a direct C/C++ exclusive-vs-read-shared-vs-written-shared breakdown. **No such breakdown exists for C/C++ TSan workloads — measuring it is part of this project's contribution.**

A 2-state design would force every read-shared access (up to ~58% of accesses on some programs) through full TSan. That defeats the purpose. Hence we need a state that recognises read-shared data as safe.

### The key idea: derive the state from the *definition* of a data race

A data race requires **all** of: (1) two different threads access the location; (2) at least one access is a write; (3) the accesses are unordered. TSan's shadow word already handles (3). So the meta-shadow only needs to track enough to know when (1) **and** (2) are both live — because only then can a race exist and only then must we run TSan.

That is exactly **two orthogonal bits**:

| `(write_seen, shared)` | Meaning | Race possible? | Action |
|---|---|---|---|
| `00` | Exclusive, only reads so far | No | **skip TSan** |
| `01` | Read-shared (≥2 threads, no write) | No — rule (2) fails | **skip TSan** (the free win the baseline loses) |
| `10` | One thread, has written | No — rule (1) fails | **skip TSan** |
| `11` | Written **and** shared | **Yes** | **full TSan** |

`write_seen` is rule (2); `shared` is rule (1). We only begin real tracking when both bits are set (`11`). This 2-bit encoding *is* the Exclusive / Read-Shared / Shared trichotomy, but motivated directly by the race definition rather than bolted on — cleaner to justify and cheaper to check.

> We keep it to these two bits and deliberately **do not** add finer states (e.g. read-exclusive vs read-shared). Read-only data is handled implicitly by `write_seen = 0`; splitting it further buys little and lengthens the hot path. Revisit only if the measurement says otherwise.

### Soundness — the one subtle part (must get right)

While a location is `10` (owner A has written it, skipping TSan), **the shadow memory holds no record of A's write.** If thread B then touches it and we flip to `11`, TSan's shadow is empty, so B's access has nothing to race against → a real A-write/B-access race would be **missed**.

Fix: store the owner's identity and logical time in the meta cell, and **check happens-before at the exclusive→shared transition.** When B first touches an owned, written location:

```
if clock_B.Get(owner_sid) >= owner_epoch:   # B is ordered after A's last write
        safe — hand over / go shared, no race
else:                                        # concurrent
        this is the race — report it (or inject a synthetic access into TSan)
```

This is why the cell stores `(sid, epoch)` — not only to propagate state, but to stay sound across the transition. Store the epoch of the owner's **latest write** specifically (a later owner *read* concurrent with B's read is read-read, not a race; gating on the write epoch avoids false positives). Reset the cell on `free`/`realloc`.

### Memory layout — use a 32-bit word, not 16

`8 bits sid + 14 bits epoch + 2 state bits = 24 bits` → fits a single aligned 32-bit word. Rationale:

- **TSan's epoch is 14 bits.** The original `epoch & 0x3F` (6-bit) idea truncates it and breaks the happens-before check (epochs wrap every 64 increments; epoch bumps on every mutex unlock + 8 other sites). 14 bits is the minimum for a correct HB comparison.
- **16-bit is not faster than 32-bit.** A halfword aligned load/store is a single instruction on x86-64/ARM64 — the "CPUs like word size" concern is about *unaligned* access and *bitfield extraction*, not aligned 16- vs 32-bit loads. So the squeeze saves memory but buys zero speed.
- **32-bit is essentially free here.** TSan's existing meta shadow is *already* `u32` per 8 app bytes (`kMetaShadowSize = 4`) with `MemToMeta` mapping + allocation in place. A 32-bit cell reuses that infrastructure and gives natural aligned atomics (needed for race-free transitions).
- Cost: meta is +4 bytes / 8 app bytes = **+50% of app memory**, but trivial next to TSan's own ~5× shadow, and likely shared with the existing meta-shadow budget.

### Answers to the two design questions raised

- **Is setting `write_seen=1` on every write costly?** No, in the common case. For exclusive data the meta line is core-owned → store hits L1 (~1 cycle). Make it **unconditional/branchless** (always store, no test) to avoid a misprediction. It must be persisted (a later reader needs to know a write occurred), but per-access cost is negligible. The only expensive case is storing to a *shared* line — but shared+written data is going to TSan regardless.
- **Is 16-bit worth it vs 32-bit?** No — see layout above. Go 32-bit: needed for epoch precision, no speed penalty, reuses existing `u32` meta infra.

### Performance expectation

Hot path = one aligned 32-bit load + test of 2 bits + one predictable branch (+ a cheap unconditional store on writes). Skips full `CheckRaces` (SIMD shadow scan + clock lookups) on the `00/01/10` states. If the C/C++ measurement shows even a moderate exclusive+read-shared majority (Java suggests ≫90%), the instrumentation-handling cost drops sharply, bounded by Amdahl on the residual `11` accesses + the transition checks.

### Open questions tracked for this design

- **Epoch wrap even at 14 bits:** 16384 epochs is not huge for a long run. Need a wrap-safe HB comparison or a "stale → conservative fallback" rule.
- **SID instability (from §3):** owner SID can change under preemption → `(sid, epoch)` may go stale → must fall back conservatively, never miss a race.
- **Transition atomicity:** the `10 → 11` flip + HB check must be atomic against a concurrent third thread. A 32-bit CAS on the cell is the natural tool — design the protocol.
- **Where to inject the missed-race report** at the transition (synthetic shadow write vs direct report) so TSan's existing reporting machinery produces a proper diagnostic.
- **Granularity:** still 1 cell per 8 app bytes; per your point (b), 16-byte malloc alignment means cells don't straddle allocations, so the "wasted 7 bytes" is intra-object-only and likely minor. Confirm with measurement.

---

## 4. Recommendation / what I'd put to the supervisor

1. **Lead with measurement:** build a counting-only meta-shadow, report exclusive / read-shared / written-shared fractions for **C/C++** TSan workloads (the gap the Java numbers leave open). This both motivates and validates the design.
2. **Implement Design B refined (§3b):** 2-bit `(write_seen, shared)` state derived from the race definition, in a 32-bit meta cell `(sid:8, epoch:14, state:2)`, with a happens-before check at the exclusive→shared transition for soundness.
3. **Stretch:** FIB-style adaptive re-promotion / CAS fail-over (E).

---

## 5. Open questions for you

- Do we have a target benchmark suite for the x% measurement (SPEC, a real C/C++ app, TSan's own test suite)?
- Is the supervisor expecting a *novel* design or a solid *engineering* contribution? That changes how hard we lean on the measurement-as-contribution angle.
- Are you happy dropping the explicit read-exclusive/read-shared split (handling read-only implicitly via `write_seen=0`), or do you want to keep that option open for the measurement to decide?
- Confirm: is widening meta beyond 1 byte acceptable, or is "1 byte" a hard constraint from the brief?

---

## brainstorm_v2_designs.md (2026-05-31)

# Brainstorm v2 — Design Space Exploration (Ownership Filtering for TSan)

_Scratch doc. Open-ended exploration beyond the v0.2 proposal (the per-8-byte 2-bit filter). Goal: map the whole design space, then propose several genuinely distinct directions with trade-off analysis, so we can pick deliberately rather than defaulting to the first idea._

> **Research note:** Symbol locations were checked in the LLVM source:
> `MemToMeta` in `tsan_platform.h`, `MetaMap` in `tsan_sync.{h,cpp}`, and
> vector-clock logic in `tsan_clock.cpp`. The relevant constants are
> `kMetaShadowCell = 8` and `kMetaShadowSize = 4`.

---

## 1. The design space (three orthogonal axes)

Every ownership-filter design is a point in three dimensions. v0.2 sits at one corner; the interesting ideas live at the others.

**Axis A — Granularity** (what unit owns state):
per-8-byte cell (v0.2) → per-allocation/object (OCTET, FIB) → per-page (MMU).
Finer = precise but more memory + more transitions; coarser = cheap + dense but false sharing.

**Axis B — Division of labour** (who does the filtering):
runtime check (v0.2) → compiler/static (escape analysis, "Compiling Away the Overhead") → hardware (MMU page protection / Intel MPK).
Earlier in the pipeline = cheaper at run time but more conservative / less portable.

**Axis C — Adaptivity** (how state evolves):
one-way demote, permanent (v0.2) → re-promotable / temporal (FIB) → predictive (FIB predictive read-sharing, CAS fail-over).
More adaptive = recovers the fast path after brief sharing, but harder to keep cheap and race-free.

v0.2 = (cell, runtime, permanent). The designs below move along each axis.

---

## 2. Key reframing: *why a separate meta-shadow at all?*

TSan v3's hot path (`ContainsSameAccess`) already loads the four 4-byte shadow words as one 128-bit SIMD register and short-circuits when the current access matches an existing same-SID entry. So TSan *already* has a same-thread fast path. What does a separate ownership meta add?

**Answer: cache density, not new logic.** The shadow is 16 bytes per 8 app bytes (4 words × 4 B). An ownership meta is 4 bytes per 8 app bytes — **4× denser**. For thread-exclusive data, the filter can decide "skip" by touching only the dense 4-byte meta line and never pulling the 16-byte shadow line into cache at all. The win is **memory-bandwidth / cache-footprint**, which is exactly what dominates TSan's overhead on access-heavy code. This is the real justification for the meta, and it also tells us the meta must stay *small and dense* to be worth it — an argument for keeping cells tiny (reinforcing the 32-bit choice, and motivating object-granularity below).

This reframing also exposes FIB's lesson: FIB derives ownership from *existing* FastTrack metadata with **zero extra storage**. The TSan-v3 analogue (Design K) asks whether we even need new storage, or just a cheaper read of what's there.

---

## 3. Designs

Each design lists: hot-path character (cache-friendly? branchless? short?), theoretical gain (memory/CPU, with x% assumptions), and pros/cons vs the others. Recall the empirical backdrop (Java unless noted): fast-path-eligible accesses ~99.7–99.9999% (OCTET); read-shared up to 58% (sunflow9); ~90% of FastTrack checks redundant in the limit (ReX, C/C++); 11–92% (median ~51%) of objects thread-local by escape analysis.

### Design F — Object / allocation granularity (OCTET-faithful for C/C++)
Store one ownership word per *allocation*, not per 8-byte cell. Natural unit: the malloc block. TSan's allocator already has block metadata (`MBlock`); ownership could live there or in a side table keyed by block.

- **Hot path:** needs interior-pointer → block-base resolution to find the state. That is a lookup (TSan's `BlockBegin`-style), not a single load — *not branchless, possible extra cache miss*. Mitigation: the compiler often knows the base (field access off a known object), or cache the last (base,state) per thread.
- **Theoretical gain:** **memory collapses** — one word per object instead of one per 8 bytes (a 1 KB object: 4 B vs 512 B of meta, ~128× less). Far fewer state transitions (one per object lifetime, not per cell). Matches the unit at which programs actually share data.
- **Pros:** directly comparable to OCTET/FIB (both per-object) → strongest literature story; tiny memory; one transition per object; no intra-object "wasted 7 bytes" problem.
- **Cons:** the base-resolution lookup is the whole risk — if it can't be made ~1–2 instructions, it loses to v0.2's single dense load; **false sharing within a large object** (e.g. a big array written at one end, read at the other) forces the whole object to Shared.
- **Verdict:** the most defensible *alternative* to v0.2. The cell-vs-object granularity question is itself a publishable comparison.

### Design G — Static escape analysis + runtime hybrid ("Compiling Away" ∪ filter)
Compile-time LLVM pass proves which allocations/accesses never escape the allocating thread and emits **no instrumentation at all** for them. The runtime ownership filter (v0.2 or F) handles only the *may-escape* remainder.

- **Hot path:** provably-local accesses cost **literally zero** — no call, no check, no meta. The runtime filter guards only what static analysis can't prove.
- **Theoretical gain:** strictly dominates any runtime-only filter on the statically-provable subset (escape analysis says median ~51%, up to 92%, of objects qualify in Java; C/C++ less but non-trivial for stack/short-lived heap). Removes both the TSan call *and* the filter check for those.
- **Pros:** two contributions (a static pass + a runtime filter) that compose; aligns with the project's base paper (*Compiling Away the Overhead*); the static and dynamic parts cover each other's blind spots (static = sound-but-conservative, dynamic = precise-but-costly).
- **Cons:** sound escape analysis in C/C++ is hard (arbitrary pointers, separate compilation, `union`, casts) → conservative, catches a subset; significantly more engineering (compiler pass *and* runtime).
- **Verdict:** highest ceiling, highest effort. Strong if the project wants a compiler contribution, not just a runtime one.

### Design J — Adaptive re-promotion (FIB-faithful temporal locality)
Extend v0.2: instead of demoting to Shared *permanently*, allow a region to return to exclusive when sharing stops (FIB's "temporally thread-local"), plus FIB's two adaptive tricks — predictive read-sharing (jump straight to read-shared for data with ≥2 readers) and CAS fail-over for high-rate serialized write sharing.

- **Hot path:** unchanged for the common case (same dense load + bit test). Cost moves to the *transition* machinery (detecting quiescence / deciding to re-promote).
- **Theoretical gain:** captures the *handoff* pattern (producer/consumer, work queues, pools) where data is thread-local in windows — exactly where a permanent-demotion filter gives up after the first handoff. FIB reports near-zero common-case cost and up to 17× over CAS-only on such workloads.
- **Pros:** recovers the fast path after transient sharing; directly mirrors FIB → strong story; biggest expected win on real concurrent C/C++ (thread pools, allocators).
- **Cons:** detecting "sharing stopped" cheaply is hard (needs quiescence signal — epoch gap? generation counter?); risk of *thrashing* (ping-pong re-promote/demote); transition atomicity gets trickier.
- **Verdict:** the natural *v2* of v0.2 once the basic filter works. Propose as a planned extension, not v1.

### Design K — Zero-storage, derive ownership from existing shadow (FIB-style FTO analogue)
Add **no meta-shadow**. Instead, add a cheaper pre-check over the existing 4 shadow words: if all occupied words share the current SID, the region is exclusive-to-me → skip the rest.

- **Hot path:** still touches the 16-byte shadow line (no density win — see §2), but adds *no* new memory and *no* allocator hooks.
- **Theoretical gain:** **zero extra memory** (FIB's headline property). CPU gain only if the pre-check is cheaper than the full `CheckRaces` scan — marginal, since TSan already SIMD-checks same-SID.
- **Pros:** simplest to implement; no allocator changes; no meta region to map/manage.
- **Cons:** **forgoes the cache-density win** that is the main reason to have a meta at all (§2); largely duplicates TSan's existing `ContainsSameAccess`; little headroom.
- **Verdict:** useful as a *baseline to measure against* — it isolates how much the separate dense meta actually buys. Good for the evaluation, weak as the headline design.

### Design G′ (moonshot, likely rejected) — Hardware-assisted via MMU / Intel MPK
Map thread-exclusive pages so cross-thread access faults; a signal handler performs the transition. Or use Memory Protection Keys (MPK/`pkey`, 16 domains, userspace `WRPKRU` ~tens of cycles) to tag thread-private pages per domain.

- **Hot path:** the MMU does the filtering — *no added instructions* on owned accesses.
- **Theoretical gain:** in principle near-zero marginal cost on the fast path.
- **Cons (fatal for a primary design):** **page granularity (4 KB)** → catastrophic false sharing; **fault/signal handler cost** is microseconds per transition (vs nanoseconds); TLB shootdowns across cores; MPK has only 16 domains (≪ 256 slots); doesn't fit TSan's byte-level precision.
- **Verdict:** document as considered-and-rejected (shows design maturity); maybe a niche future note. Not viable as the main mechanism.

### Design I (add-on) — Redundancy-aware meta (fold in ReX)
Let the meta also short-circuit *redundant* repeated accesses (same thread, same location, already checked since the last sync) even in the Shared state — capturing the ~90% redundancy ReX identifies, on top of ownership.

- **Hot path:** one more bit-test; must be invalidated on epoch change (sync event) to stay sound.
- **Theoretical gain:** attacks a *second, independent* overhead source (redundancy), helping even genuinely shared data that ownership filtering can't.
- **Cons:** overlaps with TSan's existing `ContainsSameAccess`; correctness depends on correct invalidation at every one of the 9 epoch-increment sites.
- **Verdict:** a cheap bolt-on to whatever core design wins; worth a paragraph, not a redesign.

---

## 4. Comparison at a glance

| Design | Axis position | Memory | Hot path | Best at | Main risk |
|---|---|---|---|---|---|
| **v0.2** | cell / runtime / permanent | +4 B per 8 B | 1 dense load + bit test (branchless) | thread-private + read-shared | loses temporal handoff |
| **F** object | object / runtime / permanent | ~1 word/object (tiny) | base lookup + test | object-level sharing; memory | interior-ptr resolution cost |
| **G** static hybrid | cell / static+runtime / permanent | 0 for proven-local | **zero** for proven-local | statically-local data | C/C++ escape analysis is hard |
| **J** adaptive | cell / runtime / re-promote | +4 B per 8 B | same as v0.2 | producer/consumer, pools | thrashing; quiescence detection |
| **K** zero-storage | cell / runtime / permanent | **0** | shadow load (no density win) | memory-constrained | little gain over existing TSan |
| **G′** MMU/MPK | page / hardware | page tables | zero (MMU) | — | false sharing, fault cost |
| **I** redundancy | add-on | +1 bit | +1 test | shared+redundant data | invalidation correctness |

---

## 5. Synthesis / recommended path

A coherent, ambitious-but-staged plan that uses these together rather than picking one:

1. **Ship v0.2** (cell/runtime/permanent) as the working core — already specified, lowest risk.
2. **Evaluate granularity** by also building **Design F** (object) and **Design K** (zero-storage) as comparison points. This turns "which granularity?" into a measured result — a genuine research contribution, since no C/C++ data exists. §2's cache-density argument predicts cell or object beats K; the experiment confirms it.
3. **Add Design J** (adaptive re-promotion) once the core works — this is where the real C/C++ concurrency wins (thread pools, allocators, producer/consumer) and where it becomes competitive with FIB.
4. **If a compiler contribution is wanted, add Design G** (static escape pre-pass) — highest ceiling, composes cleanly with the runtime filter, and ties to the base paper.
5. Treat **I** (redundancy) as a cheap bolt-on and **G′** (MMU/MPK) as documented-and-rejected.

The throughline and likely thesis claim: **TSan overhead is dominated by cache traffic from the shadow, and most accesses are either thread-exclusive or read-shared; a dense ownership meta lets the hot path skip the shadow line entirely for those, with a static pre-pass removing the easy cases and adaptive re-promotion recovering the fast path after transient sharing.** That single sentence spans all three axes and positions the work directly against OCTET (object/managed), FIB (zero-storage/adaptive), and "Compiling Away" (static).

---

## 6. Open questions for the supervisor / next session
- Is a **compiler-pass contribution (G)** in scope, or keep it runtime-only?
- For **F**, can we get the interior-pointer→object-base in ~1–2 instructions (compiler-known base, or a per-thread last-block cache), or does the lookup kill it?
- For **J**, what's the cheapest sound **quiescence signal** for re-promotion (epoch gap, per-region generation counter, periodic sweep)?
- Do we want the evaluation framed as a **granularity study** (cell vs object vs zero-storage) — strong, novel, but more builds — or a single-design depth study?
- Confirm the **cache-density hypothesis (§2)** is the right central claim; if so, the eval must measure cache misses / bandwidth, not just wall-clock.

---

## brainstorm_v3_deep_comparison.md (2026-05-31)

# Brainstorm v3 — Low-Level Comparison & Action Plan

_Scratch doc. Goes lower-level than v1/v2: instruction-level hot paths, exact TSan source structure, the precise FIB/OCTET protocols, and a concrete reading + experiment list. Builds on `brainstorm_proposal.md` (v0.2 design) and `brainstorm_v2_designs.md` (design axes F/G/J/K/G′/I)._

> **Source basis (verified this session):** read the real TSan v3 hot path (`tsan_rtl_access.cpp`), the meta infrastructure (`tsan_sync.{h,cpp}`, `tsan_mman.cpp`), and the FIB / OCTET / "Compiling Away" papers directly. Code quotes below are from the LLVM checkout in this repo.

---

## 1. The actual TSan v3 hot path (so we know exactly what we're inserting into)

From `MemoryAccess()` — the function every `__tsan_readN/writeN` call reaches:

```cpp
RawShadow* shadow_mem = MemToShadow(addr);          // (1) address arithmetic, no load
FastState  fast_state = thr->fast_state;            // (2) thread-local, hot
Shadow     cur(fast_state, addr, size, typ);        // (3) build 32-bit word, regs only
m128 shadow = _mm_load_si128((m128*)shadow_mem);    // (4) ONE 16-byte SIMD load  ← cache
if (LIKELY(ContainsSameAccess(shadow_mem, cur, shadow, access, typ)))
    return;                                          // (5) common-case early out
// else: TryTraceMemoryAccess (append to event trace) → CheckRaces (slow)
```

Key facts this nails down:

- **The fast path is already short and branchless-ish.** Build a word, do one 16-byte aligned SIMD load, one SSE compare, predicted-taken branch, return. `ContainsSameAccess` (vectorized) is a handful of PCMPEQ/PMOVMSK ops.
- **The cost that remains is (4): the 16-byte shadow load.** On thread-private hot data this line is L1-resident and cheap; the pain is when the *working set is large* and the shadow (2× app memory) blows the cache — then every access is an extra cache miss. **This is the overhead our meta must attack, and confirms the v2 "cache-density" thesis: a 4-byte meta line covers 4× the app range of the 16-byte shadow line.**
- **`MemToShadow`/`MemToMeta` are pure address arithmetic** (shift + add against a per-platform base, e.g. `kMetaShadowBeg`). No lookup. So adding a meta load is *also* just arithmetic + one load — cheap, and crucially it can *replace* the shadow load on the fast path, not add to it.
- **`CheckRaces` (slow path) is the real cost** (quoted below) — a 4-iteration loop with per-slot `access&`, SID compare, `thr->clock.Get(old.sid())` (a vector-clock indexed load), and possible eviction. This is what we skip when the filter fires.

`CheckRaces` core (non-vectorized, clearest form):

```cpp
for (idx in 0..kShadowCnt) {            // kShadowCnt == 4
  Shadow old(LoadShadow(sp));
  if (old == kEmpty) { store cur; return false; }
  if (!(cur.access() & old.access())) continue;       // no byte overlap
  if (cur.sid() == old.sid()) { maybe update; continue; }   // same slot
  if (old.IsBothReadsOrAtomic(typ)) continue;
  if (thr->clock.Get(old.sid()) >= old.epoch()) continue;   // happens-before
  DoReportRace(...); return true;
}
```

Note `thr->clock.Get(old.sid())` — every genuinely-shared access pays a **vector-clock lookup**. That is the expensive operation an ownership filter avoids for exclusive/read-shared data.

---

## 2. The existing meta infrastructure — what we'd extend or parallel

From `tsan_sync.h` / `tsan_sync.cpp` / `tsan_mman.cpp`:

- **`MetaMap`** maps each 8-byte app region to one `u32` (`MemToMeta`). The `u32` is either 0 (empty), or `idx | kFlagBlock` (heap block) or `idx | kFlagSync` (sync var). Top 2 bits = flag, low 30 = index into a `DenseSlabAlloc`.
- **Allocator already hooks exist:** `OnUserAlloc` → `ctx->metamap.AllocBlock(thr, pc, p, sz)` writes `*MemToMeta(p) = idx | kFlagBlock`. `OnUserFree` → `FreeBlock` walks `MemToMeta(p)..MemToMeta(p+sz)` and clears. **These are exactly the tag/reset points our design needs — already there.**
- **`AllocBlock` stores an `MBlock`** containing `{ Tid tid; StackID stk; uptr siz; }` — *it already records the allocating thread id per block.* That is ownership data we can read for free at allocation.
- **`GetBlock(p)` resolves interior pointer → block** by reading `MemToMeta(p)` and dereferencing the slab. So object-granularity ownership (Design F) has a ready-made base-resolution path — but it's a load + slab map (`block_alloc_.Map(idx)`), i.e. *one dependent load*, not free.

This is a big deal for the design choice: **the allocator already knows the owning TID per block, and already writes a per-8-byte meta word.** Two of our four implementation milestones (tag at malloc, reset at free) are essentially "extend code that already runs."

**Caution:** the existing per-8-byte `u32` meta is *occupied* by block/sync indices. We can't silently reuse it. Options: (a) a **second, parallel meta region** (new `mmap`, our own `MemToOwnMeta`) — cleanest, +4 B/8 B; (b) **steal spare bits** — the block index uses 30 bits under `kFlagBlock`, leaving little; risky; (c) store ownership **in the `MBlock`** itself (object granularity, Design F) — zero new mapping, but needs the `GetBlock` lookup on the hot path. (a) vs (c) is the core engineering fork.

---

## 3. The two reference protocols, precisely (now that I've read them)

### OCTET (object granularity, optimistic, Java)
- **States:** `WrEx(T)` write-exclusive, `RdEx(T)` read-exclusive, `RdSh` read-shared (≈ MESI M/E/S). Object allocated in `WrEx(allocator)`.
- **Fast path:** `if (obj.state == WrEx_T) { ... }` — a single load+compare against the thread's own state; no atomics, no fence. RdSh reads check a per-thread `rdShCount` counter vs a global (cheap, no CAS).
- **Slow path:** conflicting access → **round-trip coordination**: requester blocks, owner(s) respond at **safe points**, state flips via a fenced/atomic update. Cost is proportional to *conflicts*, not accesses.
- **Result:** 26% avg overhead; fast path alone +13%.
- **Limitation OCTET itself states:** "object granularity does not suffice for accurate fine-grained data race detection." That's the gap TSan (byte-level) and FIB (field-level) fill — and a reason our filter should stay *finer* than OCTET.

### FIB / FastTrack-Ownership (field granularity, zero-storage, Java)
- **Two states only:** `Excl(t)` and `Shared(S)`. **Derived from existing metadata** — the last-reads field `R_x`: if `R_x = c@t` (single epoch owned by t) → `Excl(t)`; if `R_x = v` (a read-map/vector) → `Shared`. **No extra storage at all.**
- **The race check subsumes the ownership check** — "the first step of a data race check subsumes the ownership check." One joint test shows both "I own this" and "no race."
- **Coordination is cooperative, at yield points** (not preemptive): a non-owner *requests*, the owner performs the transition + race check on its behalf when it reaches a yield point. Owners thus run synchronization-free.
- **Pessimistic locking = 20–90% of FastTrack's overhead** (the cost FIB removes); FIB ≈ unsynchronized in the common case, 50× better than pessimistic, up to 17× over CAS.
- **Adaptive extensions:** *predictive read-sharing* (jump to Shared preemptively when read-sharing is likely) and *adaptive fail-over to local CAS* under high serialized write-sharing.

**Crucial contrast for us:** FIB derives ownership from FastTrack's *vector-clock-style* metadata. **TSan v3 does not store FastTrack-style last-reads per location** — it stores 4 SID+epoch shadow words with random eviction. So a *faithful* FIB port to TSan is not free: TSan's shadow doesn't carry the invariant FIB exploits. This is a genuine research subtlety (and a possible contribution: "what's the TSan-shaped analogue of FTO?").

---

## 4. Low-level comparison of the designs

Hot-path "cost" = what executes on a thread-private access (the 99% case). "Miss cost" = extra cache lines touched.

| Design | Fast-path instructions (exclusive access) | Extra cache lines vs stock TSan | New storage | Transition mechanism | Soundness risk |
|---|---|---|---|---|---|
| **Stock TSan** | build word + 1×16 B SIMD load + cmp + branch | — (baseline) | — | n/a (always full) | accepted (random eviction) |
| **v0.2** (cell/2-bit/perm) | meta arith + 1×4 B load + 2-bit test + branch; *skip shadow load* | **−** (4 B meta line replaces 16 B shadow line → fewer misses) | +4 B/8 B (parallel region) | atomic store / CAS on `10→11`, HB check once | stale SID; epoch wrap; transition atomicity |
| **F** (object) | `MemToMeta` + **dependent slab load** (`GetBlock`) + state test | +1 (meta) but block metadata already hot at alloc | reuse `MBlock` (≈0 new) | one transition per object lifetime | false sharing within big objects |
| **G** (static+runtime) | provably-local: **zero** (no call emitted). Rest: as v0.2 | 0 for elided accesses | 0 for elided | n/a for elided | escape analysis must be sound (conservative) |
| **J** (adaptive re-promote) | same as v0.2 | same as v0.2 | +4 B/8 B (+ maybe a generation/epoch) | re-promote on quiescence; CAS fail-over | thrash; quiescence detection correctness |
| **K** (zero-storage) | reads the 16 B shadow anyway, adds a same-SID pre-test | 0 (no density win) | **0** | none (just a check) | low — mostly a measurement baseline |
| **I** (redundancy/BigFoot-style) | +1 bit test; invalidate at sync | +1 bit | +1 bit | clear on epoch change | invalidation at all 9 epoch sites |

**Reading the table:**

- **v0.2 is the only design that *reduces* cache lines touched** by replacing the 16-byte shadow load with a 4-byte meta load on the fast path. Given §1 (overhead = shadow cache misses on large working sets), that is the single most important property. **It is the right core.**
- **F's whole risk is one dependent load** (`*MemToMeta` → `block_alloc_.Map(idx)`). That load is on the critical path and may itself miss. But F's memory is ~0 extra and it matches how programs share data (per object). Verdict unchanged from v2: best *alternative*, strongest as a *comparison arm*, not obviously a win.
- **K touches the same 16-byte line as stock TSan**, so it can't win on bandwidth — it only saves the `CheckRaces` loop work. Confirms K's role: a *control* to isolate "how much does the dense separate meta actually buy vs just a cheaper check." Build it precisely for that contrast.
- **G is the highest-ceiling and now has a concrete incumbent**: the "Compiling Away" paper (Paznikov et al., NUS, Dec 2025) already does 5 static analyses (escape, lock-ownership, single-writer/multi-reader, dominance redundancy) for **1.34× geomean, 2.5× peak**, and is *being upstreamed into TSan*. **Implication: a pure static-elimination project would now be competing with an accepted upstream work.** Our runtime filter is *complementary* (it catches what static analysis can't prove — the dynamic majority), which is a cleaner positioning than going head-to-head.

---

## 5. Sharpened recommendation

The research tightens v2's plan into a specific, defensible thesis:

> **Claim:** TSan v3's residual overhead on large working sets is dominated by shadow-memory cache traffic. A dense (4 B/8 B) ownership meta-shadow with a 2-bit race-derived state lets the hot path consult a 4×-denser line and skip both the 16-byte shadow load and the vector-clock lookup for the thread-exclusive and read-shared accesses that dominate real C/C++ workloads — a regime no prior system measures, since OCTET/FIB are Java and object/field-VC-based, and the recent static work (Paznikov 2025) removes a *different*, statically-provable subset.

Concretely:
1. **Core = v0.2** (cell, 2-bit, parallel meta). It's the only design that cuts cache traffic; the allocator hooks it needs already exist (`AllocBlock`/`FreeBlock` already write `MemToMeta` and record TID).
2. **Build F and K as comparison arms** → turns "granularity?" and "is the dense meta worth it?" into measured results. Novel: no C/C++ numbers exist.
3. **Position against, not on top of, the static work** — cite Paznikov 2025 as the static complement; our dynamic filter catches the unprovable majority. Optionally compose (run both) as a stretch result.
4. **Adaptivity (J) and redundancy (I)** are v2 extensions once the core lands.

The honest risk to name up front: **a faithful FIB-style "derive ownership from existing metadata" (K-plus) does not port cleanly to TSan**, because TSan's shadow lacks FastTrack's last-reads invariant. Either we add storage (v0.2/F) or we define a new TSan-shaped ownership-from-shadow rule — itself a possible contribution.

---

## 6. Concrete next actions

### Reading (prioritised)
1. **BigFoot (PLDI'17)** and **RedCard (ECOOP'13)** — static check *coalescing/coarsening* and release-free-span redundancy (~40–61% fewer checks). Directly informs Design I and the granularity story; closest prior art to "skip redundant checks." *(found this session; not yet read)*
2. **"Compiling Away the Overhead" (Paznikov et al., 2512.05555, Dec 2025)** — read in full, not just abstract. It's the incumbent static work being upstreamed; we must position precisely against its 5 analyses and 1.34× result.
3. **OCTET (OOPSLA'13)** and **FIB (OOPSLA'17)** — finish for the Prerequisites §2/§3 (still `[TBD]` in draft.md). I now have the protocol details extracted (this doc §3) to seed them.
4. **Tree Clocks (POPL'22)** and **"Dynamic Race Detection with O(1) Samples" (POPL'23)** — adjacent SOTA; one paragraph each in related work to show command of the field.
5. **FastTrack (PLDI'09)** — the ownership-from-metadata source FIB builds on; needed to explain why it doesn't port free to TSan.

### Codebase study (to de-risk implementation)
6. Read **`tsan_platform.h` MemToMeta/MemToShadow macros** fully — confirm the shift/base arithmetic and whether a *parallel* meta region can be carved (spare VA between `kMetaShadowBeg/End`).
7. Read **vectorized `CheckRaces` (tsan_rtl_access.cpp, ~L305–351)** and **`thr->clock.Get`** (`tsan_clock.cpp`) — quantify exactly what the filter skips.
8. Trace **`AllocBlock`/`FreeBlock`/`MoveMemory`** for the realloc and range-free edge cases our reset logic must mirror.
9. Find the **LLVM instrumentation pass** (`llvm/lib/Transforms/Instrumentation/ThreadSanitizer.cpp`) — where the inlined fast-path check (milestone 4) would be emitted.

### Experiments (the measurement contribution)
10. **Build vanilla TSan** from this checkout; reproduce a known race + a clean run. (Unblocks everything.)
11. **Milestone-0 / counting meta:** add a parallel meta that only *classifies* each access (exclusive / read-shared / written-shared) and counts — never skips. Run on a small C/C++ suite to get the **first C/C++ ownership-state breakdown**. This single number decides whether the whole approach is worth it and is publishable on its own.
12. **Microbench the cache hypothesis:** a working-set-sweep benchmark (small → ≫LLC) under stock TSan, measuring `perf` cache misses, to confirm overhead tracks shadow misses. This validates the central claim before building the full filter.

### Decisions needed from supervisor
- Parallel meta region (a) vs ownership-in-`MBlock`/object granularity (c)?
- Is competing-with / composing-with the upstreamed static work (Paznikov) acceptable framing?
- Scope: single-design depth (v0.2) vs granularity study (v0.2 + F + K)?

---

## brainstorm_v4_attack_plan.md (2026-07-07, latest)

# Brainstorm v4: Attack Plan (2026-07)

## 0. Working rules

- Canonical docs: `soundness_limit.md` (theory), `one_word_filter.md` (design and risks), `writeback_worked_example.md` (concrete trace). Everything else is working notes.
- Use terse prose and LaTeX for mathematics. Regenerate report PDFs with
  `bash convert.sh <in.md> <out.pdf>` when required.
- Do not assert that an operation is expensive or cheap without a measurement
  or source. Earlier claims about vector-clock lookup and skipping the scan
  were retracted for this reason.
- The desired "improves but never hurts" property is ruled out by consequence
  C2 of the lower-bound argument.

## 1. State of play

Proven (do not redo): v0.2-family tags are impossible (lower bound); cover lemma + merge rule are the exact per-cell forgetting rules; no sound filter dominates stock TSan; read-shared elision needs $k$ words for $k$ readers; the only levers are expected-case compression, relocation/amortisation, and cross-cell sharing.

Designed but unvalidated: write-back cell (note = owner's most recent verbatim shadow word, flush on non-cover, handover on foreign sid) + victim slot. Main doubt: `ContainsSameAccess` already makes exact repeats cheap, so the note only wins on covered-but-not-identical accesses plus line density. Unknown fraction.

Decided: measurement comes before any build. Nothing gets implemented until the counting build prices the bets.

## 2. Points of attack

Ordered by expected value. Each has: idea, first step, kill criterion.

### A. Counting build (do first, everything depends on it)

Instrument TSan to count, never to skip. Add a side meta region (own mmap, mirror `MemToMeta` arithmetic in `tsan_platform.h`), simulate the note per cell, and count per access: state (a/b/c), cover hit, merge hit, flush, handover, would-be `ContainsSameAccess` hit, residue size class (1/2/3/4+). Flag-gated (`TSAN_OPTIONS`), print histogram at exit. Files: `tsan_rtl_access.cpp` (`MemoryAccess`), `tsan_mman.cpp` (`OnUserAlloc`/`OnUserFree`), `tsan_rtl.cpp` (`DoResetImpl`, exit report). Baseline must include the Paznikov pass once it lands upstream; otherwise note the caveat in every number.

Deliverables regardless of outcome: first published exclusive/read-shared/write-shared breakdown for C/C++ TSan workloads; residue-size distribution; dedup potential (see E). This is the guaranteed-contribution track.

Also add: a periodic scan that hashes all live 16-byte shadow cells and counts distinct values vs total. That one number decides direction E.

### B. Theory track (cheap, safe, parallel)

Write the lower bound properly: full proofs, the $k$-reader bound (C4) spelled out, Charron-Bost (1991) cited as precedent, FastTrack's formal section checked for overlap (believed none: FastTrack proves sufficiency of adaptive representation with growable state; nobody proves necessity against a bounded lossy detector). Generalise if easy: the bound holds for any detector whose per-location state is a bounded multiset of (mask, type, epoch) words, i.e. it is about TSan's *shape*, not TSan. A clean 6-8 page writeup is a defensible FYP chapter and possibly a workshop paper. No experiments needed.

### C. Write-back cell (gated)

Build only if A shows: covered-but-not-identical accesses are a large fraction AND working sets commonly exceed cache so line density matters. Kill criterion: cover+merge hits minus `ContainsSameAccess` overlap < ~30% of accesses, or ping-pong rate high. If killed, keep the design doc as the existence proof that the levers are usable.

### D. Victim slot (small, always safe)

Independent of everything: park stock's evicted words in the (otherwise idle) meta cell, consult on slow path. Only adds history, cannot be wrong, catches races stock misses. Cheap to build once the meta region from A exists. Evaluation: synthetic eviction-pressure tests + count rescued reports on real suites. Risk: rescues may be rare; then it is a paragraph, not a chapter. TMon (CCPE 2026) attacks the same misses with hardware; cite it as evidence the problem is recognised.

### E. Cross-cell sharing (the "shared metadata" direction G asked about)

The per-cell bound does not forbid sharing identical state across cells. Java's SlimFast does this with GC and object references; the mechanism does not port. But two C-world precedents show GC-less versions exist:

- **Memcheck** (Nethercote & Seward 2007, "How to Shadow Every Byte of Memory"): 2-bit compressed common-case encoding inline + sparse exception table for rare full-precision bytes, and distinguished secondary maps shared by uniform regions, copied on write. Production quality, C, no GC. This is exactly "compact common case + spill", the same shape the lower bound forces, applied to memory *layout*.
- **Umbra** (Zhao et al., CGO 2010): segmented shadow mapping with granularity scaling, only materialising shadow where needed.

Port candidates for TSan v3, in increasing ambition:
1. **Zero-page preservation (free dedup).** With any elision scheme, private data's shadow stays all-zero, and untouched shadow pages are backed by the kernel's shared zero page. Memory win with no interning machinery at all. Measure in A: fraction of shadow pages never written under a simulated note.
2. **Distinguished-page analogue.** Pages of shadow whose cells all hold the same single word (array initialised by one thread, one epoch, full mask) collapse to one descriptor; copy-on-write on divergence. Needs a page-level side table and a check on the slow path only. Blocked by: mutation frequency (epoch bumps rewrite whole pages worth of state unless the descriptor holds the note-equivalent instead of raw words). Work out on paper first.
3. **MBlock region descriptors.** One note per malloc block instead of per cell (TSan already stores per-block `MBlock{tid,...}`). Amortises the +4B/cell premium and the check. Blocker: interior-pointer to block-base lookup on the hot path; possibly compiler-assisted (Paznikov's infra can often prove "access = base + const").

Kill criterion for E as a whole: the distinct-cell-value scan from A shows low redundancy in real C/C++ workloads. If redundancy is high, E2/E3 become the main design track and the write-back cell becomes its per-cell fallback.

### F. Hybrid static-dynamic amortisation

TSan already has range entry points (`__tsan_read_range`/`write_range`). A compiler pass (or cooperation with Paznikov's) that turns per-element loop instrumentation into one range call makes the note check per-loop instead of per-access, which beats the "check must be cheaper than what it removes" problem by dividing the check cost by N. Dynamic check coalescing is unpublished as far as this project knows (RedCard/BigFoot do it statically for Java). First step: measure how much instrumentation in real binaries sits in coalescable loops (objdump/IR pass over benchmarks). This may be the strongest attack if E's redundancy number is high, since ranges and regions compose.

### G. Completeness pivot (if all performance tracks die)

Flip the goal: same speed, catch more. Victim slot as headline + port TMon's two anti-overwrite tweaks to software + optionally a mode with more shadow words per cell for hot cells. Everything here is sound by construction; evaluation is race counts, not speedups. Safe, novel enough, less exciting.

### H. Floor (always available)

The honest negative-result narrative: "Why FastTrack-line optimisations do not transfer to TSan v3: a lower bound and a measurement of the remaining slack." Consists of B + A + the SlimFast/FIB/OCTET portability analysis (all lean on growable per-var objects, GC, safepoints, or metadata locks; TSan v3 has none). This is a coherent FYP thesis on its own. Everything above only adds to it.

## 3. Contingency tree

```
A (counting build)
├─ residue-1 fraction high + cache-miss-bound → build C, then D; E1 free on top
├─ redundancy scan high → E2/E3 main track, F to amortise checks, C as fallback
├─ coalescable-loop fraction high → F main track (needs compiler work)
├─ everything low → G (completeness pivot) + H (write it up)
└─ in all branches: B (theory) and the A numbers themselves are deliverables
```

## 4. Reading list (priority order)

1. SlimFast, IPDPS 2018 (repo: github.com/stilltracy/SlimFast; thesis: repository.upenn.edu/edissertations/3641) — for the redundancy argument and what not to copy.
2. Song & Lee 2014, "Efficient Data Race Detection for C/C++ Programs Using Dynamic Granularity" (IEEE 6877300) — region-then-split, C/C++, but Pin baseline inflates gains.
3. Nethercote & Seward 2007, "How to Shadow Every Byte of Memory Used by a Program" (valgrind.org/docs/shadow-memory2007.pdf) — compressed encodings + distinguished maps, the GC-less sharing precedent.
4. Umbra, CGO 2010 (commit.csail.mit.edu/papers/2010/zhao-cgo10-umbra.pdf) — shadow mapping/granularity machinery.
5. TMon, CCPE 2026 — before any novelty claim about the victim slot.
6. Paznikov, arXiv 2512.05555, full read + the LLVM Discourse upstreaming thread — baseline composition, and whether their pass exposes loop/region facts F can reuse.
7. FastTrack PLDI 2009 formal section + Charron-Bost 1991 — for B.

## 5. Concrete next actions

1. Build stock LLVM/TSan from the local `llvm-project` checkout (commit pinned in `tsan_v3_soundness.md`), run its test suite, confirm green baseline.
2. Implement the counting build (A). Start with just the a/b/c state counters; add residue simulation second; add the cell-hash scan third.
3. Pick benchmarks: 2-3 TSan-clean multithreaded apps (memcached or redis under load, plus one PARSEC/SPLASH subset, plus the two microbenchmarks: thread-local-heavy and write-shared-heavy).
4. Write up B in parallel on days when the build fights back.
5. Commit `report/` to git.
