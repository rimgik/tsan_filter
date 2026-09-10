# Parallel-note implementation

[Parallel-note guide](README.md) · [TSan reference](../../reference/tsan-v3.md)

## Compiler path

For an eligible aligned 1-, 2-, 4-, or 8-byte access, the LLVM TSan pass maps
the application address to the note, builds the current access word, and tests
the common exact-hit case before emitting the normal TSan callback path.

The compiler change is in
`llvm/lib/Transforms/Instrumentation/ThreadSanitizer.cpp`. Runtime merging and
handover are in `compiler-rt/lib/tsan/rtl/tsan_rtl_access.cpp`; fixed mappings
are defined by `tsan_platform.h` and initialized by `tsan_platform_posix.cpp`.
Allocator integration is in `tsan_mman.cpp`.

## Runtime path

The runtime reserves a fixed, non-eagerly-committed note range containing one
32-bit word per eight application bytes. Linux uses low application memory and
one platform-dependent allocation range. Allocator interceptors initialize
supported allocations with the allocating thread's current TSan word.

Each note word contains the access-byte mask, thread slot ID, epoch, read/write
bit, and atomic bit. Two words can become one only when one safely dominates
the other, or when their epoch and type are identical and their masks can be
united.

## Fallback

A different owner, unsupported access, or inexact merge revokes the note path.
The retained word is inserted into ordinary TSan shadow before the incoming
access uses normal `MemoryAccess`. Later accesses to that cell stay on normal
TSan. This ordering is what preserves races involving the earlier private
phase.

The note uses additional resident pages when touched. Sparse virtual mappings
do not guarantee RSS savings because touching one cell materializes its page,
and real workloads usually mix note-eligible and fallback cells on the same
ordinary-shadow page.

See [soundness](../../reference/soundness.md) for the reason history cannot be
replaced with only an ownership ID.
