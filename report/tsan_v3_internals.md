# TSan v3 Internals: Shadow, Hot Path, Slots

The definitive reference for this project. Everything cites the local checkout at commit `10f84995b430` (`llvmorg-23-init`). Files abbreviated: `access` = `compiler-rt/lib/tsan/rtl/tsan_rtl_access.cpp`, `rtl` = `tsan_rtl.cpp`, `shadow` = `tsan_shadow.h`.

## 1. The shadow word (shadow L57-82)

One 32-bit `RawShadow` records one access:

| field | bits | meaning |
|---|---|---|
| access mask | 8 | bit $i$ set = byte $i$ of the 8-byte cell touched |
| sid | 8 | slot id (0-255), NOT a thread id |
| epoch | 14 | the slot's counter value at the time of access |
| is_read | 1 | |
| is_atomic | 1 | |

Per 8 aligned application bytes there is a **cell** of 4 such words (`kShadowCnt = 4`), found by pure arithmetic (`MemToShadow`, no lookup). 16 bytes of shadow per 8 app bytes = the 2x memory overhead. Special values: all-zero = empty; `kRodata` = read-only data marker (epoch 0, impossible for real words).

## 2. The instrumented access flow (access L420-448)

Every compiled read/write calls `MemoryAccess`:

1. **Build** `cur` from (my sid, my slot's current epoch, mask, type) (L437-438).
2. **CSA** = `ContainsSameAccess`: one 16-byte SIMD load of the whole cell, four parallel **exact 32-bit equality** compares against `cur` (SIMD L238-280, scalar L171-192). For reads, the read bit is OR-ed into the loaded words first, so a read also matches an identical earlier write; `kRodata` matches any read. Exact match: return. No store, no trace. Change one mask bit or one epoch tick and CSA misses.
3. Ignore-bit check; **trace append** (`TryTraceMemoryAccess`, L445): one 8-byte `Event` into the thread's ring buffer, later used by `RestoreStack` to print report stacks.
4. **CheckRaces** (L195-232), loop over the 4 words in order:
   - word empty: store `cur` here, return (empties form a suffix, nothing racy follows) (L201-205)
   - masks do not intersect: skip (L206)
   - same sid: if masks **exactly equal** and old type weaker-or-equal (`IsRWWeakerOrEqual`, shadow L111-128), overwrite in place; continue either way, own sid never races (L208-215)
   - both reads, or both atomics: skip (`IsBothReadsOrAtomic`, shadow L100-109) (L216)
   - happens-before: `thr->clock.Get(old.sid()) >= old.epoch()`: skip (L218)
   - otherwise: **report** and return, first hit wins (L220)
5. Nothing stored and no slot free: **evict** at index `(trace_pos / sizeof(Event)) % 4` (L227-230). Content-blind: the victim is whatever index the thread's global event counter lands on. Deterministic per execution, uncorrelated with the cell.

**Cost profile.** CSA hit = the light path: one 16-byte load plus compares (63% of accesses on Redis). CSA miss adds the trace append, the 4-arm loop (the `clock.Get` is a dependent load into the thread's own 512-byte clock array, usually L1-resident), and a 4-byte store. Reports are rare and expensive. On large working sets the dominant cost is the 16-byte shadow line traffic itself, which is why v3 halved word size from v2 and why our meta note targets line density.

An unharvested hint from the authors at L241-246: recognizing a *superset* access as "same" was considered and skipped as too expensive for this path. That gap is exactly what our cover rule generalizes (mask superset instead of equality) and our merge rule extends (equal-epoch same-type mask union, proved lossless; union across different epochs is provably unsound, it manufactures false positives).

## 3. Slots and epochs (rtl L260-366)

Threads do not own identity in shadow; they borrow one of **256 slots**. The mental model: 256 notebooks, each with 16,384 numbered lines (14-bit epoch). One rule: whoever holds a notebook writes on its next blank line. Line numbers belong to the notebook, never to the writer.

- **Attach** (`SlotAttachAndLock`, L304-326): new epoch = `EpochInc(slot->epoch())` (L311), i.e. the slot's last value + 1, regardless of who held it or why they left. The thread's old epoch does not travel with it. The tenancy is logged in the slot's journal (`{tid, epoch}`, L325), which is what makes `(sid, epoch)` map to exactly one thread within a generation.
- **The thread's state**: `fast_state = (sid, epoch)` = current notebook and line, ticking at every release-type operation (unlock, release, thread create/finish, ~9 sites). Separately, `thr->clock[256]` = its view of every slot's timeline, advanced only by real synchronization (acquire merges the sync object's clock). Attach sets only the thread's own new entry (`clock.Set`, L324); nothing else is acquired.
- **Detach/preempt**: the departing thread parks its final epoch in the slot (L296, L356) for the next borrower. Preemption happens when all 256 slots are held and someone needs one: the LRU holder is evicted (L293-298) and notices at its next access (`SlotLock`).
- **Exhaustion**: a slot at `kEpochLast` is retired, skipped by the finder (L280-284). When no usable slot remains: **`DoReset`** (L286-288, impl L144) wipes all shadow, all slot counters, all vector clocks at once (per-thread generation check L316-318). Budget: 256 x 16384, about 4.2M sync operations per generation.

Why next-blank-line and never restart: other threads hold bookmarks (`clock[s] = e` = "genuinely synchronized with slot s's timeline up to e"). Monotonic per-slot counters guarantee a bookmark can never claim to cover lines written after it was placed. A restarted counter would make every old bookmark falsely cover the new tenant's work: missed races against the whole process, not just one thread.

## 4. The three blind spots (all deliberate)

1. **Cell eviction** (L227-230): the 5th concurrent history entry destroys one of 4, content-blind. Races against the destroyed word are lost. This is what a victim slot can catch.
2. **Tenancy seams**: successive tenants of a slot are forced into a happens-before order (same-sid arm L208 treats them as one thread; attach continuing the counter makes the new tenant's clock entry cover the predecessor's epochs). Races between tenant $n$ and tenant $n+1$ of the same slot are undetectable. Narrow by design: the alternative (restart at 0) would lose races against everyone holding old bookmarks.
3. **Reset amnesia**: `DoReset` forgets all history; races spanning the boundary are lost. Happens every ~4.2M syncs.

Plus a reporting-only gap: a detected race whose old word has no matching trace event left (`RestoreStack` fails, trace ring recycled) is silently dropped.

"Parity with stock" for this project means: we may forget anything stock forgets (the three spots above), and must forget nothing else. Cover and merge were proved sound at *slot* granularity, so sid theft changes report attribution at worst, never detection; this is exactly as blind as stock's own same-sid rule, no blinder.
