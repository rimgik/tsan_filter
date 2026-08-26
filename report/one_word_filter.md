# One-Word Filter for TSan v3

ThreadSanitizer v3 stores four 32-bit shadow words for every aligned eight
bytes of application memory. This design adds a parallel region containing one
additional 32-bit word per application cell. The extra word is a temporary,
exact representation of the cell's history, not merely an ownership tag.

The objective is parity with stock TSan: the filter must neither lose a race
that stock would report nor invent a race that stock would suppress. Stock's
own bounded-history behaviour is retained.

## 1. Representation

A note has the same layout as `RawShadow`:

| Bits | Field |
| --- | --- |
| 0–7 | access mask |
| 8–15 | slot ID (SID) |
| 16–29 | epoch |
| 30 | read flag |
| 31 | atomic flag |

The all-zero value means **shared**: the cell uses standard TSan shadow memory
from then on. A non-zero value is a real shadow word that must be preserved.

The mapping covers TSan's low application and heap ranges. `MemToOneWord`
translates an application address by arithmetic, with one four-byte note for
each eight-byte application cell. Pages are reserved at startup and backed on
demand.

## 2. Exact merge

Let an access be `(mask, sid, epoch, type)`. Two accesses with different SIDs
cannot share a note. With the same SID, access `B` dominates `A` when:

1. `mask(A)` is a subset of `mask(B)`;
2. `epoch(A) <= epoch(B)`; and
3. `type(B)` is at least as race-producing as `type(A)`.

A write is more race-producing than a read, and a non-atomic access is more
race-producing than an atomic access. Because those two `RawShadow` bits use
the opposite polarity, the type join is a bitwise AND.

If either word dominates the other, the dominated word may be forgotten. If
epoch and type are identical, arbitrary masks may instead be unioned. The
result is:

```text
mask   = mask(A) | mask(B)
epoch  = max(epoch(A), epoch(B))
read   = read(A) & read(B)
atomic = atomic(A) & atomic(B)
```

This fieldwise join is valid only after one of the exactness conditions has
passed. Applying it to arbitrary accesses can construct a synthetic word that
does not have the same race answers as the original history.

## 3. Runtime path

For an ordinary aligned access, the runtime loads the note:

- If it is zero, the runtime immediately uses standard TSan.
- If the incoming word merges exactly, a compare-and-exchange publishes the
  merged value. A note already covering the incoming access returns without a
  store.
- If the SID differs or no exact merge exists, the runtime hands over.
- Special access types also hand over.

Handover first copies the note into ordinary shadow slot zero and then changes
the note to zero with a release compare-and-exchange. A failed compare-and-
exchange retries with the newer note, so a concurrent merge is not discarded.
Threads that observe zero with an acquire load can then process their current
access against the transferred history using standard TSan.

The key invariant is:

> A cell is private precisely while its complete retained history is
> representable by one exact shadow word. The first access requiring a second
> word permanently moves the cell to normal TSan tracking.

Unaligned accesses, 16-byte accesses, range operations, frees, and other paths
hand over every affected note before using ordinary shadow. Reset clears both
regions. Allocation's imitated write is placed in the note and ordinary shadow
is cleared, so later handover preserves the same initial history.

## 4. Compiler fast path

The compiler option `-mllvm -tsan-one-word-filter` emits an inline probe for
eligible accesses. The probe checks that the runtime feature is enabled, maps
the application address to its note, loads it, and compares it with the current
shadow word. An exact equality skips the callback; a read is also covered by an
otherwise identical write.

The current implementation limits this path to little-endian targets, aligned
ordinary accesses of one, two, four, or eight bytes, and functions without
non-intrinsic calls. These limits keep the generated control flow small and
avoid caching thread fast-state data across calls that may change it. Every
miss invokes the existing TSan callback, where the general merge and handover
logic runs.

Both compiler instrumentation and runtime support are disabled by default. The
runtime is enabled with `TSAN_OPTIONS=one_word_filter=1`.

## 5. Cost and limitation

The note density is four bytes per eight application bytes, adding 50% of
application size to TSan's metadata reservation. A successful inline hit may
avoid the callback and the 16-byte ordinary shadow cell. A runtime merge still
adds note loads, branches, tracing when the note changes, and an atomic update.
After handover, every access pays the note check before performing stock work.

This explains the measured result. Repeated writes to one favourable private
cell are much faster, but the tested application workloads are slower and use
more resident memory. The exact filter is therefore a useful sound baseline
and a demonstration of the representability boundary, not a general
replacement for stock TSan.

See [`../results/summary.md`](../results/summary.md) for measurements and
[`soundness_limit.md`](soundness_limit.md) for the lower-bound argument.
