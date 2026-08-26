# Where Cover/Merge Wins: Two Examples

Stock TSan's fast path (`ContainsSameAccess`) already handles *exact* repeated accesses: if the new shadow word is bit-identical to a stored one (same mask, type, sid, epoch), it returns after one SIMD load. So the write-back note only pays off on accesses that are **not identical but still covered or merged**. The claim "most single-thread wins are cover/merge" rests on two very common idioms.

## Example 1: cover, private accumulator in a loop with synchronisation

```c
long local_sum = 0;                  // thread-private
while (running) {
    Task t = queue_pop(&q);         // mutex unlock inside -> epoch++ each iteration
    local_sum += t.value;           // same 8 bytes, same mask, same type, NEW epoch
}
```

Every `queue_pop` releases a lock, so the thread's epoch increments each iteration. The next `local_sum` access builds a shadow word identical to last iteration's *except for the epoch*. `ContainsSameAccess` compares raw words, so it misses every iteration, and stock runs the full store path into the 16-byte shadow line each time.

The note: same mask, same type, newer epoch, this is a **cover**, one 4-byte overwrite.

This pattern is any per-thread counter, statistics field, cursor, RNG state, or arena bump pointer inside a loop that contains *any* synchronisation (queue operations, mutexes, condition variables, atomics on other data). In server-style code that describes most hot loops.

| Per `local_sum` access | Stock | Note |
|---|---|---|
| `ContainsSameAccess` hit? | no (epoch differs) | n/a |
| Memory touched | 16-byte shadow line, load + store | 4-byte note, load + store |

## Example 2: merge, initialising a buffer field-by-field

```c
struct Msg *m = malloc(64);
m->type  = 5;                       // 4-byte write, mask 00001111, epoch e
m->flags = 2;                       // 4-byte write, mask 11110000, same epoch e
// ... fill the rest, then publish to another thread
```

Two writes to the same 8-byte cell, disjoint masks, same epoch: never bit-identical, so `ContainsSameAccess` misses both and stock stores two separate shadow words. A byte-wise loop (`for (i) buf[i] = f(i)`) is worse: 8 distinct words per cell, overflowing stock's 4 slots and forcing eviction.

The note: equal epoch, same type, this is a **merge**, the masks union into one word (`11111111`) built up by 4-byte stores. Eight byte-writes collapse into one exact word.
