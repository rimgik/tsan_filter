# Specific Cases Where the Optimisation Helps

Concrete scenarios from real programs, per mechanism. The config example (initialise once, use over the whole execution) is analysed first and honestly: it wins in one phase and not the other, and seeing why sharpens where the wins actually are.

## 1. The config case, taken apart

```c
Config *cfg = malloc(sizeof *cfg);
parse_file(cfg, path);            // startup: one thread writes ~hundreds of fields
spawn_workers();                  // publish
// rest of execution: every thread reads cfg constantly, nobody writes
```

**Init phase: strong win (merge + cover).** `parse_file` writes field after field: 4-byte and 1-byte stores, disjoint masks, few sync events in between. Stock stores a shadow word per field write and overflows the 4-slot cells on byte-wise fields; the note merges each cell's writes into one word and touches only the 4-byte line. Caveat to state up front: if the compiler can *prove* this code runs before any thread exists, the upstreamed static pass (Paznikov's single-threaded-context analysis) deletes the instrumentation entirely and there is nothing left to win. Our margin is the unprovable remainder: config reloaded at runtime (SIGHUP handlers), plugin/late initialisation, anything behind a function pointer or shared library boundary.

**Read phase: no runtime win, and that is a theorem, but a real memory win.** On the first worker read the cell hands over, and it must: a future writer has to be checked against reader history, and the k-reader bound (C4 in the lower-bound note) says constant state cannot hold a reader set. Could we at least skip storing the readers' words? Also no: if a reader's word stays at an old epoch and a writer arrives ordered after the old epoch but concurrent with the real read, stock reports and we would not. Parity forces the stores. What remains true: stock's read-shared path is already its cheap path (read/read never triggers the vector-clock check, and repeats within an epoch dedup), and the leftover cost is 16-byte line traffic on stores, which parity says we must keep. So for the read phase the honest wins are: the **page table** (config pages are `stock`; accesses check one L1-resident entry instead of loading a dead per-cell note, and the note memory is reclaimed) and **CoW pattern pages** (millions of config-region cells hold near-identical read words; the census will show it; dedup collapses the shadow RSS). Memory, not speed.

## 2. Cases with a genuine runtime win

**Per-thread state that lives across synchronisation.** Statistics counters, RNG state, arena bump pointers, logging cursors, the `local_sum` of every worker loop. The surrounding loop synchronises (queue ops, mutexes), so the epoch moves every iteration, `ContainsSameAccess` misses every time, and stock pays a 16-byte store per access forever. The note covers each access for 4 bytes. This is the strongest recurring case, and it is permanent: this data never hands over.

```c
struct WorkerStats { u64 processed, errors, bytes; };  // one per thread, lives hours
```

**Producer-side message construction.** Serialise privately, publish once:

```c
Msg *m = arena_alloc(...);
fill_header(m); memcpy(m->payload, src, n);   // merge: masks grow, one epoch
queue_push(&q, m);                            // one flush + handover
```

Win proportional to (writes during construction) / 1 handover. Serialisation-heavy servers (RPC, loggers, DB write paths) do this millions of times per second.

**Growing containers in one thread.** `std::vector::push_back`, `std::string` append, hash-map rehash before the structure escapes: sequential same-type writes, classic merge, plus the zero-page effect while the container stays private.

**Arena and freelist allocator internals.** Allocator metadata is touched by its owner thread on every alloc/free, across arbitrary sync events: cover, permanently private.

**Startup that static analysis cannot prove single-threaded.** Dynamic library init, registry/factory patterns, lazily-built caches behind `pthread_once`: same shape as `parse_file` but reached through indirection the compiler gives up on.

## 3. Cases where it does not help (say these unprompted)

- Read-shared steady state (the config read phase): runtime parity cost is already near stock's floor; only memory improves.
- Write-shared hot data (the work queue itself): hands over immediately; the page table caps the loss at ~one L1 load.
- One cell alternating access shapes across epochs: flushes every time, strictly worse than stock until the give-up policy demotes it.

## 4. What to measure to confirm (all in the MVP counting build)

Per case above there is a counter: cover hits and merge hits split by allocation site would directly attribute wins to these idioms; the never-written-shadow-page fraction prices the zero-page effect; the census prices CoW for config-like regions; handover counts identify how much traffic is read-shared steady state. If the per-thread-state and construction idioms do not dominate single-thread traffic in real workloads, the runtime bet fails and the memory story (zero-page + CoW + census numbers) is what survives.
