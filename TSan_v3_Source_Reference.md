# TSan v3 — Source Code Reference
_Extracted from LLVM main branch, May 2026_

> All links point to `github.com/llvm/llvm-project/blob/main/compiler-rt/lib/tsan/rtl/`

---

## File Index

| File | Purpose | Link |
|---|---|---|
| `tsan_defs.h` | Core constants, types, access flags | [link](https://github.com/llvm/llvm-project/blob/main/compiler-rt/lib/tsan/rtl/tsan_defs.h) |
| `tsan_shadow.h` | Shadow word struct, FastState struct | [link](https://github.com/llvm/llvm-project/blob/main/compiler-rt/lib/tsan/rtl/tsan_shadow.h) |
| `tsan_rtl_access.cpp` | Hot path: MemoryAccess, CheckRaces, ContainsSameAccess | [link](https://github.com/llvm/llvm-project/blob/main/compiler-rt/lib/tsan/rtl/tsan_rtl_access.cpp) |
| `tsan_rtl.cpp` | Runtime init, slot management, SlotAttachAndLock | [link](https://github.com/llvm/llvm-project/blob/main/compiler-rt/lib/tsan/rtl/tsan_rtl.cpp) |
| `tsan_platform.h` | MemToShadow, MemToMeta, virtual address layout | [link](https://github.com/llvm/llvm-project/blob/main/compiler-rt/lib/tsan/rtl/tsan_platform.h) |

---

## 1. Core Constants — `tsan_defs.h`

```cpp
// Thread slot pool size — only 256 slots exist, threads time-share them
constexpr uptr kThreadSlotCount = 256;
constexpr Sid  kFreeSid = static_cast<Sid>(255);  // sentinel: no owner

// Epoch: 14-bit logical clock per slot
constexpr uptr  kEpochBits = 14;
constexpr Epoch kEpochLast = static_cast<Epoch>((1 << 14) - 1);  // 16383

// Shadow memory dimensions
const uptr kShadowCnt      = 4;    // shadow words per 8-byte app cell
const uptr kShadowCell     = 8;    // app bytes per shadow cell
enum class RawShadow : u32 {};     // each shadow word = 4 bytes (32-bit!)
const uptr kShadowSize     = sizeof(RawShadow);  // = 4
const uptr kShadowMultiplier = kShadowSize * kShadowCnt / kShadowCell;
//                           = 4 * 4 / 8 = 2   → shadow is 2× app size

// Meta shadow (sync objects, mutexes)
const uptr kMetaShadowCell = 8;    // app bytes per meta cell
const uptr kMetaShadowSize = 4;    // u32 per meta cell
```

**Key point:** `kShadowMultiplier = 2`, so TSan v3 uses **2× memory overhead** for shadow,
down from ~4× in v2. This halving came from shrinking the shadow word from 64-bit to 32-bit.

### Access Type Flags

```cpp
enum : AccessType {
  kAccessWrite       = 0,
  kAccessRead        = 1 << 0,   // set for reads
  kAccessAtomic      = 1 << 1,   // set for atomic instructions (std::atomic, __atomic_*)
  kAccessVptr        = 1 << 2,   // vtable pointer read/write
  kAccessFree        = 1 << 3,   // synthetic access during free()
  kAccessCheckOnly   = 1 << 5,   // check races but don't store to shadow
  kAccessSlotLocked  = 1 << 7,   // called with TidSlot already locked
};
```

---

## 2. Shadow Word Layout — `tsan_shadow.h`

### FastState (32-bit) — stored in thread-local, used to build shadow words

```cpp
struct Parts {
  u32 unused0_        : 8;
  u32 sid_            : 8;   // which slot this thread is currently using
  u32 epoch_          : 14;  // kEpochBits = 14
  u32 unused1_        : 1;
  u32 ignore_accesses_: 1;   // if set, skip all race checks
};
```

### Shadow (32-bit) — what is stored in shadow memory

```cpp
struct Parts {
  u8  access_;         // 8-bit bitmask: which bytes of the 8-byte cell were accessed
                       // e.g. bytes 0-1 → 0b00000011, bytes 4-7 → 0b11110000
  Sid sid_;            // 8-bit slot ID of the accessing thread
  u16 epoch_  : 14;   // logical clock at time of access
  u16 is_read_: 1;    // 1 = read, 0 = write
  u16 is_atomic_: 1;  // 1 = atomic instruction (std::atomic etc.)
};
static_assert(sizeof(Shadow) == 4);  // confirmed: exactly 32 bits
```

**Shadow word = (SID, epoch, access_bitmask, is_read, is_atomic)**
No Thread ID stored — only the **Slot ID**. See Section 4 for how slots work.

### Special shadow values

```cpp
Shadow::kEmpty   // = 0, slot is unused
Shadow::kRodata  // marks .rodata section (reads from here can never race)
Shadow::FreedMarker()   // marks freed memory (stored in slot 0 after free)
Shadow::FreedInfo(sid, epoch)  // stores who freed it (stored in slot 1)
```

### Key methods

```cpp
// Intersection check — do two accesses touch the same bytes?
// Just a bitwise AND on the access bitmasks:
bool intersects = (cur.access() & old.access()) != 0;

// Are both accesses reads, or is either atomic? (→ no race possible)
bool IsBothReadsOrAtomic(AccessType new_typ) const;
// Returns true if: (old.is_read_ && new is read) OR (old.is_atomic_ && new is atomic)

// Is old access "weaker or equal" to new in terms of read/atomic ordering?
bool IsRWWeakerOrEqual(AccessType new_typ) const;
// Used to decide if we can overwrite the old slot with the new access
```

---

## 3. Memory Access Hot Path — `tsan_rtl_access.cpp`

### Entry point: `MemoryAccess()`

```cpp
void MemoryAccess(ThreadState* thr, uptr pc, uptr addr, uptr size, AccessType typ) {
  RawShadow* shadow_mem = MemToShadow(addr);   // compute shadow address

  FastState fast_state = thr->fast_state;       // current (SID, epoch, ignore_bit)
  Shadow cur(fast_state, addr, size, typ);       // build shadow word for this access

  // SIMD: load all 4 shadow words as a single 128-bit register
  LOAD_CURRENT_SHADOW(cur, shadow_mem);

  // --- FAST PATH 1: identical access already in shadow → skip everything ---
  if (LIKELY(ContainsSameAccess(shadow_mem, cur, shadow, access, typ)))
    return;

  // --- FAST PATH 2: ignore bit set (inside ignore region) ---
  if (UNLIKELY(fast_state.GetIgnoreBit()))
    return;

  // Log to trace buffer (for stack reconstruction on race report)
  if (!TryTraceMemoryAccess(thr, pc, addr, size, typ))
    return TraceRestartMemoryAccess(thr, pc, addr, size, typ);

  // --- SLOW PATH: check all 4 shadow words for races ---
  CheckRaces(thr, shadow_mem, cur, shadow, access, typ);
}
```

### `ContainsSameAccess()` — the first fast path

Checks if the **exact same access** by the **same slot** is already in the shadow.
With SIMD (SSE4.2), all 4 shadow words are compared in parallel with a single `_mm_cmpeq_epi32`.

If true → this thread already recorded this access, nothing can have changed → **return immediately**.
This is a critical optimisation — hits very frequently in loops accessing the same locations.

### `CheckRaces()` — the race detection core

```cpp
bool CheckRaces(ThreadState* thr, RawShadow* shadow_mem, Shadow cur, ...) {
  bool stored = false;

  for (uptr idx = 0; idx < kShadowCnt; idx++) {  // iterate all 4 slots
    Shadow old(LoadShadow(&shadow_mem[idx]));

    // Empty slot → store here if we haven't yet
    if (old.raw() == Shadow::kEmpty) {
      if (!stored) StoreShadow(&shadow_mem[idx], cur.raw());
      return false;
    }

    // No byte overlap → skip
    if (!(cur.access() & old.access()))
      continue;

    // Same slot (same thread) → update if weaker access recorded
    if (cur.sid() == old.sid()) {
      if (cur.access() == old.access() && old.IsRWWeakerOrEqual(typ)) {
        StoreShadow(&shadow_mem[idx], cur.raw());
        stored = true;
      }
      continue;
    }

    // Different slot: both reads or either atomic → no race
    if (old.IsBothReadsOrAtomic(typ))
      continue;

    // Different slot: check happens-before via vector clock
    // thr->clock.Get(sid) returns the last epoch we "saw" from slot sid
    if (thr->clock.Get(old.sid()) >= old.epoch())
      continue;  // old access happened-before → safe

    // RACE DETECTED
    DoReportRace(thr, shadow_mem, cur, old, typ);
    return true;
  }

  // No race found, no empty slot found → evict pseudo-randomly
  if (!stored) {
    uptr index = atomic_load_relaxed(&thr->trace_pos) / sizeof(Event) % kShadowCnt;
    StoreShadow(&shadow_mem[index], cur.raw());
  }
  return false;
}
```

**Eviction note:** When all 4 slots are occupied by genuinely concurrent accesses, one is evicted
using `trace_pos % kShadowCnt` — pseudo-random but deterministic. This means TSan can
theoretically miss a race (tiny probability). This is an accepted trade-off.

---

## 4. Thread Slots & Epochs — `tsan_rtl.cpp`

### v2 vs v3: how the clock model changed

| | TSan v2 | TSan v3 |
|---|---|---|
| Thread identity in shadow | 16-bit Thread ID (TID) | 8-bit Slot ID (SID) |
| Clock in shadow | 42-bit scalar clock | 14-bit epoch |
| Clock increments | **On every memory access** | **At slot attach + every release-type sync event** |
| Max concurrent threads | Limited by TID bits | 256 active at once (slot pool) |
| Shadow word size | 64-bit | 32-bit |

In **v2**, the pseudocode shows `IncrementThreadClock(tid)` called on *every* `HandleMemoryAccess`.
Each individual access got a unique `(TID, clock)` — fine-grained but expensive (64-bit shadow words).

In **v3**, the epoch advances at: slot attach **and** every release-type sync event
(`MutexUnlock`, `Release`, `ReleaseStore`, `ReleaseStoreAcquire`, `ThreadCreate`, `ThreadFinish`).
All regular memory accesses within an interval share the **same epoch**.

### `IncrementEpoch` — verified 9 call sites in source

```cpp
void IncrementEpoch(ThreadState *thr) {
  Epoch epoch = EpochInc(thr->fast_state.epoch());
  if (!EpochOverflow(epoch)) {
    Sid sid = thr->fast_state.sid();
    thr->clock.Set(sid, epoch);
    thr->fast_state.SetEpoch(epoch);
    thr->slot->SetEpoch(epoch);
    TraceTime(thr);
  }
}
```

Called from: `SlotAttachAndLock`, `MutexUnlock`, `MutexReadUnlock`, `MutexReadOrWriteUnlock`,
`Release`, `ReleaseStore`, `ReleaseStoreAcquire`, `ThreadCreate`, `ThreadFinish`.

### Why v3 is still correct despite coarser epochs

If two accesses share the same `(SID, epoch)`, they belong to the **same thread's tenure
within a single synchronisation interval** — they cannot race with each other.
Happens-before across threads is tracked by the **vector clock** (`thr->clock`),
updated at every sync event — same as v2.

### What (SID, epoch) actually identifies

```
Slot 1, epoch 10  ← tid 100 attaches
    tid 100: write X  → shadow {sid=1, epoch=10}
    tid 100: write Y  → shadow {sid=1, epoch=10}
    tid 100: unlock mutex → epoch increments to 11

Slot 1, epoch 11  ← still tid 100, but after a release event
    tid 100: write Z  → shadow {sid=1, epoch=11}

Slot 1, epoch 12  ← tid 200 attaches (tid 100 was preempted or finished)
    tid 200: write X  → shadow {sid=1, epoch=12}
```

`slot->journal` records `{tid, epoch}` at every attach, so (SID, epoch) → tid lookup is possible.

---

### Slot Lifecycle — CRITICAL for Project 2

#### The slot_queue is an LRU list of ALL 256 slots

All slots live in `ctx->slot_queue` at all times (even while in use).
When a thread needs a slot, `FindSlotAndLock` pops the **front** (least recently used)
and pushes it to the **back**:

```cpp
// tsan_rtl.cpp:276 — FindSlotAndLock (simplified)
slot = ctx->slot_queue.PopFront();
ctx->slot_queue.PushBack(slot);  // moves to back immediately
slot->mtx.Lock();

if (slot->thr) {
    // PREEMPTION: this slot is still in use by another thread!
    slot->SetEpoch(slot->thr->fast_state.epoch());
    slot->thr = nullptr;   // ← victim thread does not know yet (lazy)
}
```

#### Preemption is lazy — the victim finds out at next `SlotLock`

`SlotLock` is called at the start of every instrumented memory access:

```cpp
// tsan_rtl.cpp:365
void SlotLock(ThreadState* thr) {
  TidSlot* slot = thr->slot;
  slot->mtx.Lock();
  thr->slot_locked = true;
  if (LIKELY(thr == slot->thr && thr->fast_state.epoch() != kEpochLast))
    return;  // fast path: still the owner
  // ← gets here if preempted OR epoch exhausted
  SlotDetachImpl(thr, false);
  slot->mtx.Unlock();
  SlotAttachAndLock(thr);  // ← grabs a NEW slot, new SID
}
```

**Key implication**: between preemption and the next `SlotLock`, the thread's
`fast_state.sid()` still holds the *old* SID. The epoch at that new attach is the
first thing that changes. A thread can change SID mid-execution.

#### TidSlot struct — no generation counter exists

```cpp
// tsan_rtl.h:143
struct alignas(SANITIZER_CACHE_LINE_SIZE) TidSlot {
  Mutex mtx;
  Sid sid;                       // fixed slot index (0–255)
  atomic_uint32_t raw_epoch;     // changes at attach + every sync event
  ThreadState *thr;              // current owner (nullptr if unowned/preempted)
  Vector<TidEpoch> journal;      // log of (tid, epoch) at each attach — for race reports
  INode node;                    // intrusive list node for slot_queue
};
```

There is **no generation counter**. The only way to distinguish tenures is `(SID, epoch_at_attach)`.

#### `SlotAttachAndLock` — where epoch is set

```cpp
// tsan_rtl.cpp:304
void SlotAttachAndLock(ThreadState* thr) {
  TidSlot* slot = FindSlotAndLock(thr);
  slot->thr = thr;
  thr->slot = slot;
  Epoch epoch = EpochInc(slot->epoch());   // ← epoch increments HERE at attach
  slot->SetEpoch(epoch);
  thr->fast_state.SetSid(slot->sid);
  thr->fast_state.SetEpoch(epoch);
  thr->clock.Set(slot->sid, epoch);
  slot->journal.PushBack({thr->tid, epoch}); // ← records attach-time epoch
}
```

**The epoch at attach time (`slot->journal.back().epoch`) uniquely identifies a tenure.**
This is distinct from the current `fast_state.epoch()` which advances at every sync event.

### SID is NOT TID % 256

Slots are allocated from the LRU queue, not derived from TID.
The same SID can be held by a completely different thread at any time via preemption.
A thread can also change SID mid-execution if it gets preempted and re-attaches.

### Slot epoch exhaustion

When a slot's epoch hits `kEpochLast` (16383), `DoReset()` is triggered:
entire shadow memory is wiped, all slot epochs reset to zero, all slots re-queued.
This is a global, expensive reset — but rare (needs 16383 attaches per slot).

---

## 5. Memory Mappings — `tsan_platform.h`

### `MemToShadow(addr)` — app address → shadow address

```cpp
// For x86_64 (Mapping48AddressSpace):
uptr shadow = ((addr & ~(kShadowMsk | (kShadowCell - 1))) ^ kShadowXor)
              * kShadowMultiplier + kShadowAdd;
// Returns pointer to the FIRST of 4 shadow words for the 8-byte cell containing addr
RawShadow* shadow_mem = MemToShadow(addr);
// shadow_mem[0..3] are the 4 shadow words
```

This is a **direct mapping** — no memory accesses needed, just arithmetic.

### `MemToMeta(addr)` — app address → meta shadow address

```cpp
u32* meta = (u32*)(((addr & ~(kShadowMsk | (kMetaShadowCell - 1)))
                    / kMetaShadowCell * kMetaShadowSize)
                   | kMetaShadowBeg);
```

Returns a `u32*` — one 32-bit meta word per 8 bytes of app memory.
Currently used for **sync objects** (mutexes, etc.).
**Project 2 extends this concept** by adding a second meta layer for ownership tracking.

### Virtual address layout (x86_64, 48-bit VMA)

```
0000 0000 1000 - 0200 0000 0000  app: main binary + MAP_32BIT   (2 TB)
1000 0000 0000 - 3000 0000 0000  SHADOW MEMORY                 (32 TB)
3000 0000 0000 - 3800 0000 0000  META SHADOW (sync objects)     (8 TB)
5500 0000 0000 - 5a00 0000 0000  app: PIE binaries              (5 TB)
7200 0000 0000 - 7300 0000 0000  app: heap                      (1 TB)
7a00 0000 0000 - 8000 0000 0000  app: modules + main stack      (6 TB)
```

Shadow and meta shadow regions are **pre-reserved** but use lazy physical allocation.

---

## 6. What This Means for Project 2

```
App memory (8 bytes)
        │
        ├─► MemToShadow(addr) ──► shadow_mem[0..3]   (4 × u32 = 16 bytes)
        │                          TSan's existing race detection state
        │
        ├─► MemToMeta(addr) ────► meta[0]             (1 × u32 = 4 bytes)
        │                          Currently: sync object metadata
        │
        └─► MemToOwnership(addr) ► ownership[0]       (1 × u32 = 4 bytes)  ← NEW
                                   Project 2: ownership state + (SID, attach_epoch)
```

### Ownership Metadata Design

**Why (SID, attach_epoch) not just SID:**
- Slots can be preempted mid-execution → same SID reassigned to a different thread
- `fast_state.epoch()` drifts at every sync event → can't use for identity
- `attach_epoch` = epoch set at `SlotAttachAndLock`, constant for the entire tenure
- (SID, attach_epoch) uniquely identifies one thread's tenure of a slot

**Implementation:** Add `thr->attach_epoch` to `ThreadState`, set in `SlotAttachAndLock`:
```cpp
thr->attach_epoch = epoch;  // new field: stable for entire tenure, unlike fast_state.epoch()
```

**Ownership u32 layout:**
```
bits [31:30] = state:  00=UNOWNED, 01=EXCLUSIVE, 10=SHARED
bits [21:8]  = attach_epoch  (14 bits)
bits [7:0]   = SID           (8 bits)

UNOWNED  = 0x00000000
SHARED   = 0x80000000  (or any sentinel with state=10)
EXCLUSIVE = 0x40000000 | (attach_epoch << 8) | sid
```

**Fast-path check (before MemoryAccess):**
```cpp
u32 meta = *MemToOwnership(addr);
if (meta == kOwnerUnowned || meta == kOwnerShared) goto full_tsan;

// EXCLUSIVE: check both SID and attach_epoch
Sid  stored_sid    = meta & 0xFF;
Epoch stored_epoch = (meta >> 8) & 0x3FFF;
if (stored_sid == thr->fast_state.sid() && stored_epoch == thr->attach_epoch)
    return;  // ← fast path: same tenure, skip TSan entirely

// Different thread → revoke
atomic_store(MemToOwnership(addr), kOwnerShared);  // CAS for safety
// fall through to full TSan
```

**Hook points:**
- `malloc` interceptor → write `EXCLUSIVE | (attach_epoch << 8) | sid` to ownership region
- `free` interceptor → write `UNOWNED` (0)
- `DoReset()` (epoch overflow) → also reset entire ownership region

**Memory overhead:** 4 bytes per 8 app bytes = +50% on top of shadow → total ~3× app size.
Can reduce to u16 (2 bytes per 8 bytes = +25%) by packing tighter if needed.
