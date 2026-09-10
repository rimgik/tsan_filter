# Soundness requirement

[Documentation index](../README.md) · [TSan tracking](tsan-v3.md)

Memory that has been used by only one thread so far may later be accessed by a
different thread. At that transition, TSan still needs the earlier thread ID,
epoch, byte mask, read/write type, and atomic type.

```text
Thread A writes x repeatedly        currently private
Thread B later writes x             ownership transition
No synchronization exists           race with A's last write
```

If the private phase stored only “owned by A”, the transition would not contain
enough information to perform TSan's overlap, ordering, and access-type checks.
Discarding the shadow word can therefore miss a race that stock TSan reports.

The parallel-note design remains sound by retaining one exact TSan word and
falling back before that word becomes insufficient. The shadow-resident design
never removes ordinary history. An approximate ownership-only filter may be a
performance experiment, but it must not be described as equivalent to TSan.
