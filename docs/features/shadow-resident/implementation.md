# Shadow-resident implementation

[Shadow-resident guide](README.md) · [TSan reference](../../reference/tsan-v3.md)

## Compiler path

The LLVM pass applies the inline check to aligned ordinary 1-, 2-, 4-, and
8-byte reads and writes in eligible leaf functions. Atomics, unaligned and
16-byte accesses, ranges, volatile or compound operations, and non-eligible
functions keep stock instrumentation.

The pass loads the thread fast-state pointer and shadow-mapping constants once
per eligible function. For each access it calculates the ordinary shadow
address and constructs the same 32-bit word used by TSan.

The implementation is contained in
`llvm/lib/Transforms/Instrumentation/ThreadSanitizer.cpp`. Small runtime exports
provide the current fast-state pointer and platform shadow-mapping constants;
the filter does not add a new runtime tracking structure.

## Slot check

Slot 0 is loaded and compared first. Only its miss edge loads slots 1–3. Every
slot load is a relaxed 32-bit atomic load. Writes require an exact match. Reads
apply the same read-bit and read-only-marker handling as stock
`ContainsSameAccess`.

## Fallback

No inline path modifies shadow memory. If all comparisons miss, the original
`__tsan_read*` or `__tsan_write*` callback runs and performs full race checking,
clock handling, reporting, and shadow replacement.

The earlier slot-0-only experiment is retained as an archive tag. It was fast
for slot-0 workloads but slower than stock when the repeated word lived in a
later slot; the staged four-slot check fixes that case.
