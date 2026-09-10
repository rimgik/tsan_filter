# Adding a Fifth TSan Shadow Slot

## 1. The problem it fixes

Each 8-byte cell of application memory has exactly 4 shadow words. When a 5th
distinct access needs a slot, TSan destroys one of the 4, chosen by a counter
that ignores the cell's content (`tsan_rtl_access.cpp` L227-230). If a future
access would have raced against the destroyed word, that race is silently
missed. This is a documented, deliberate blind spot of TSan v3, and our Redis
data shows where it bites: write-shared cells are 38% of all accesses and
under contention they thrash (bench_shared: CSA hit rate ~0%, meaning the
cell's content turns over constantly, i.e. evictions are constant).

## 2. The design

Give every cell a 5th storage location for the word eviction would destroy.

- **Storage.** One u32 per 8 app bytes in a parallel region, addressed by
  flat arithmetic like `MemToShadow`. Zero = empty. Lazily mapped. Cost:
  overhead 2x -> 2.5x. Flag-gated.
- **Write hook (1 line region).** At the eviction site in `CheckRaces`,
  store the doomed word into the victim cell before overwriting it. Relaxed
  atomic store; if two evictions race, the loser's word is merely as dead as
  it would have been in stock.
- **Check hook (1 block).** In `CheckRaces`, after the 4-word loop found
  nothing: load the victim cell and apply the same arms (mask intersect,
  same sid, both-reads/atomics, happens-before, else report). This runs on
  the slow path only, after `ContainsSameAccess` has already missed, so the
  hot path is untouched. The current access is never stored into the victim
  cell; it is fed by evictions only.
- **Clearing (the one correctness obligation).** `free` zeroes the block's
  victim cells; `DoResetImpl` zeroes the region. A stale parked word
  surviving into a reallocated block would cause false positives. Everything
  else is fail-safe: a path that forgets to CHECK the victim cell simply
  behaves like stock, so partial integration is still sound.
- **Reporting.** A parked word was a real access, traced when it happened,
  so `RestoreStack` prints normal stacks. Caveat: victim words live longer
  than the 4-slot window, so their trace parts are more often recycled;
  some victim reports get suppressed the same way stock already suppresses
  unrestorable reports. Detection is strictly >= stock; reporting is
  best-effort like stock.

| | Stock | With victim slot |
|---|---|---|
| Hot path (CSA hit) | 16B load + compare | unchanged |
| Slow path | 4-arm loop | + 1 load + same arms |
| Eviction | word destroyed | word parked (1 store) |
| Detection | misses evicted history | catches the newest casualty |
| Memory | 2x | 2.5x |

## 3. Worked example: the race stock cannot see

`X` is one 8-byte cell. Masks in binary, bit 0 = byte 0.

Cast: T1 (sid 1), T2 (sid 2), T3 (sid 3). T2 spawns T3 *before* ever
synchronising with T1, so T3 is never ordered after T1. T2 then locks the
mutex T1 used, so T2 itself is safely ordered after T1.

| step | event | cell content (4 slots) | victim cell |
|---|---|---|---|
| 1 | T1 writes all 8 bytes of X: word **A** = {11111111, w, 1@100} | A | empty |
| 2 | T2 spawns T3 (T3 inherits no knowledge of T1) | A | empty |
| 3 | T2 locks the mutex T1 released: T2 now ordered after A | A | empty |
| 4 | T2 writes byte 0 at its epoch e: {00000001, w, 2@e} — vs A: ordered, no race | A, b0 | empty |
| 5 | T2 writes byte 1 at e+1 (a sync in between): {00000010, w, 2@e+1} | A, b0, b1 | empty |
| 6 | T2 writes byte 2: cell full | A, b0, b1, b2 | empty |
| 7 | T2 writes byte 3: no slot free, rotation evicts **A** | b0, b1, b2, b3 | **A parked** |
| 8 | T3 writes byte 7: {10000000, w, 3@f} | | |

Step 8 in stock TSan: T3's mask `10000000` intersects none of b0-b3 (bytes
0-3), every arm skips, no race found, word stored. **Silence.** But T3 was
never synchronised with T1, and A covered byte 7: T1-vs-T3 is a real
write-write race. Its only witness was A, and A is gone.

Step 8 with the victim slot: the 4-word loop finds nothing, the victim cell
is consulted: A = {11111111, w, 1@100}; masks intersect (byte 7), different
sid, write-write, T3's clock entry for slot 1 is below 100 (never synced),
**race reported**, with real stacks on both sides.

The mask-disjointness in the example is what makes it minimal and
deterministic; the *class* of miss is generic: any cell that hosts more than
4 concurrent histories loses one, and whatever raced only with the loser
becomes invisible. Contended cells (our 38% bucket) do this constantly.

## 4. Why this is the right first build

- The benchmark endorses its target: the biggest access bucket
  (write-shared, 38%) is exactly where evictions concentrate.
- Its value is independent of everything still unmeasured (tenure/churn,
  CSA overlap, cache behaviour).
- Lowest risk of anything on the roadmap: one clearing rule to get right,
  everything else fail-safe; no ownership states, no CAS protocol, no
  compiler change; ~200 lines.
- It builds the note's infrastructure (meta region, mapping, free/reset
  hooks) so nothing is throwaway if the write-back note is built later.
- Guaranteed result either way: "same speed, strictly more races" if rescues
  happen on real code; a measured "eviction misses are rare in practice" is
  still a publishable fact (TMon, 2026, attacks the same misses with
  hardware, so the question is recognised).

## 5. Evaluation plan

1. Deterministic rescue test: the scenario above as a lit test; stock
   silent, victim build reports.
2. Report diff on Redis/memcached under load: victim build's reports must be
   a superset of stock's; manually verify each addition is a true race.
3. Overhead: victim build vs stock on the same benchmarks, expect noise.
4. Rescue rate counter: how often the victim check fires and how often it
   reports, per workload.

## 6. Known integration question (deliberately deferred)

When the write-back note is built later, note words and victim words would
share the same u32 and both look like real shadow words; the combined design
needs a mode discriminator (steal a bit, or widen to u64). Standalone there
is no ambiguity: the cell is always a victim slot.
