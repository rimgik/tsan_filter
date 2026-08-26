# The Write-Back Cell, End to End: A Worked Example

A fully concrete trace of the write-back design (S1 in `problem_minimal_state.md`) with real sids, epochs, and masks, covering every transition: fresh, cached, covered overwrite, mask-union, epoch refresh, flush on divergence, handover, and both the synced and racy outcomes.

## The cell

One `u32` per 8 application bytes at `MemToMeta(addr)`, holding a verbatim `RawShadow` word: mask (8 bits, bit $i$ = byte $i$ accessed), sid (8), epoch (14), is_read (1), is_atomic (1). Reserved encodings, none of which collide with a real word (real words have nonzero mask, epochs start at 1):

| Encoding | Meaning |
|---|---|
| all zero | untracked; run stock |
| mask=0, sid=$s$, epoch=$e$ | owned by slot $s$, no cached word yet (fresh from alloc) |
| sid=255 (`kFreeSid`) | handed over; run stock forever |
| anything else | cached word, owned by its sid field |

The owner's per-access rule (the cover lemma): the new access **covers** the cached word iff $m_{new} \supseteq m_{old}$, $e_{new} \geq e_{old}$, and not (old is write and new is read). Covered: overwrite the note. Equal epoch, same type: union the masks. Otherwise: **flush** the old word into real shadow (with trace event), then cache the new one. A trace event is appended exactly when the note's content changes — the same accesses stock traces, since accesses that leave the note unchanged are the ones stock's `ContainsSameAccess` dedups before its own trace append.

## The program

```c
struct Item { int32_t count; char flag; char pad[3]; };  // 8 bytes = one cell

// Thread T1 (attached to slot sid=3, epoch currently 5):
Item *it = malloc(sizeof *it);
for (int i = 0; i < 1000; i++) it->count++;   // read4 + write4, bytes 0-3
pthread_mutex_unlock(&m);                     // T1's epoch: 5 -> 6
it->count++;                                  // one more increment, now at epoch 6
it->flag = 1;                                 // write1, byte 4
// T2 (sid=7, epoch 12) either locks m first (synced) or not (racy):
int c = it->count;                            // read4, bytes 0-3
```

## The trace

Shadow starts all zero. "Note" is the meta cell. Masks in binary, bit 0 = byte 0.

| # | Event | Access (mask, type, sid@epoch) | Cover check | Note after | Shadow after | Lines touched |
|---|---|---|---|---|---|---|
| 0 | malloc (T1) | — | — | mask=0, sid=3, e=5 (fresh) | — | 4B meta |
| 1 | `count++` read | 00001111 r 3@5 | note fresh | {00001111, r, 3@5} | — | 4B meta |
| 2 | `count++` write | 00001111 w 3@5 | mask equal, read covered by write | {00001111, w, 3@5} | — | 4B meta |
| 3 | iterations 2..1000 | 00001111 r/w 3@5 | identical or covered | unchanged | — | 4B meta each |
| 4 | unlock: epoch 5 to 6 | — | — | unchanged | — | — |
| 5 | next `count++` | 00001111 r then w 3@6 | same mask/type, newer epoch: covered | {00001111, w, 3@6} | — | 4B meta |
| 6 | `flag = 1` | 00010000 w 3@6 | 00010000 not superset of 00001111: **not covered** | {00010000, w, 3@6} | slot0 = {00001111, w, 3@6} | 4B meta + 16B shadow (the flush) |
| 7 | T2 reads `count` | 00001111 r 7@12 | sid 7 differs from 3: **foreign** | sid=255 (handed over) | slot1 = {00010000, w, 3@6}, then stock runs | 4B meta + 16B shadow |

Step 5, why dropping the e=5 word is safe: any probe with $c < 5$ also has $c < 6$, and the e=6 word has the same mask and type, so it fires for every probe the e=5 word would have fired for. Stock does the identical thing (dominated overwrite); we do it on a 4-byte line.

Step 6 is the first time shadow is touched in the region's entire life — 1000+ accesses cost one 4-byte line each, where stock pays the 16-byte line every time. That, and nothing else, is the saving.

Step 7 in detail (the handover): T2's meta check sees a foreign sid, flushes the note into shadow slot 1, CASes the cell to sid=255, then falls through to completely stock TSan for its own access. Stock's scan now runs against real shadow:

- **Synced run** (T2 locked m): T2's clock entry for slot 3 is 6. Against slot0 {00001111, w, 3@6}: masks intersect, different sid, write involved, but $6 \geq 6$ — happens-before holds, no race. Against slot1: masks 00001111 and 00010000 don't intersect, skip. T2's read word {00001111, r, 7@12} is stored in slot2. Silence. Correct.
- **Racy run** (no lock): T2's clock entry for slot 3 is stale, say 2. Against slot0: masks intersect, $2 < 6$ — **race reported**, and both sides have real trace events (T1's word was traced when it entered the note at step 5), so `RestoreStack` reconstructs both stacks. This is the race v0.2 could detect but never print.
- **Byte-disjoint variant**: a third thread writes byte 7 (mask 10000000) with no synchronisation at all. Scan: 10000000 intersects neither 00001111 nor 00010000 — silence. Correct silence: stock says nothing, we say nothing. This is the false positive v0.2 would have raised (its tag had no mask).

After step 7 the cell is stock forever; every later access to it behaves byte-for-byte like unmodified TSan (or better, if the cell is reused as a victim slot).

## The accounting

Over the loop of $N$ iterations: stock touches the 16-byte shadow line $N$ times (all `ContainsSameAccess` hits except one store per epoch change); the write-back cell touches the 4-byte meta line $N$ times plus one 16-byte flush. Same number of loads — the win is that a 64-byte cache line of meta covers 128 bytes of application memory versus 32 for shadow, so on a large array of `Item`s the working set of the instrumentation is 4 times smaller, and shadow pages for items that never reach step 6 or 7 are never faulted in at all. For a single hot cell that stays in L1 either way, the win is nothing. The counting build's job is to find out which of those two worlds real programs live in.

Cases not shown: atomics (always flush and hand over — an atomic never races with an atomic but does race with the plain history, so it must see the flushed word), free (`MemoryRangeFreed` race-checks against shadow, so free flushes first, then zeroes the cells), `DoResetImpl` (zeroes meta along with shadow — stale epochs must not survive a reset), and a CAS loser on any transition (falls back to stock for that access, conservatively).
