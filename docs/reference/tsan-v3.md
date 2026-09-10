# TSan v3 access tracking

[Documentation index](../README.md)

Clang inserts calls such as `__tsan_read4` and `__tsan_write8` around ordinary
memory accesses. The runtime receives the current thread, program counter,
address, size, and access type.

```text
program load/store
      |
      v
LLVM TSan instrumentation
      |
      v
__tsan_read* / __tsan_write*
      |
      v
MemoryAccess
      |
      +--> construct current 32-bit shadow word
      +--> compare four stored shadow slots
      +--> report an unordered conflicting access
      +--> update or replace shadow history
```

One 32-bit TSan v3 word records an eight-byte access mask, thread slot ID,
epoch, read/write bit, and atomic bit. Four words are stored for each aligned
eight-byte application cell.

Two accesses race when they overlap, are not ordered by synchronization, come
from different threads, and at least one is a non-atomic write. Exact repeated
accesses can return early through `ContainsSameAccess`; this is the case moved
inline by the shadow-resident filter.
