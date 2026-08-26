# One-Word Filter MVP

The MVP adds a parallel note region to TSan v3. Each aligned eight-byte
application cell has one 32-bit note containing the same fields as a TSan
shadow word: access mask, SID, epoch, read/write, and atomic/non-atomic.

While every access to a cell can be represented exactly by one word, TSan keeps
the history in the note region. If an incoming access cannot be merged exactly,
the runtime writes the note into ordinary shadow slot zero and processes the
incoming access with standard TSan. The note is then zero, which permanently
marks that cell as shared.

## Exact merge rule

For two words with the same SID, one word may replace the other when its access
mask is a superset, its epoch is at least as new, and its type is at least as
race-producing. A write is more race-producing than a read, and a non-atomic
access is more race-producing than an atomic access. Words with identical epoch
and type may also union their masks.

This restriction matters: combining arbitrary words field by field can invent
a synthetic access that never occurred and can hide a race. If no exact merge
exists, the runtime falls back instead.

## Fast path

The LLVM pass inlines the note lookup for aligned, ordinary one-, two-, four-,
and eight-byte accesses in eligible leaf functions. It skips the runtime call
only when the note already covers the access. All other cases call TSan.

Unaligned accesses, 16-byte accesses, range operations, atomics, unsupported
address ranges, and special shadow values use the fallback path.

## Build

Clone this repository with its LLVM submodule, then configure LLVM:

```sh
git clone --recurse-submodules https://github.com/rimgik/tsan_filter.git
cd tsan_filter/llvm-project
cmake -S llvm -B build -G Ninja \
  -DCMAKE_BUILD_TYPE=Release \
  -DLLVM_ENABLE_PROJECTS=clang \
  -DLLVM_ENABLE_RUNTIMES=compiler-rt \
  -DLLVM_TARGETS_TO_BUILD=Native \
  -DCOMPILER_RT_BUILD_XRAY=OFF \
  -DCOMPILER_RT_BUILD_MEMPROF=OFF \
  -DCOMPILER_RT_BUILD_LIBFUZZER=OFF \
  -DCOMPILER_RT_BUILD_ORC=OFF
ninja -C build clang compiler-rt
```

Build the focused benchmark in both modes:

```sh
./build/bin/clang++ -O2 -fsanitize=thread \
  ../mvp/benchmarks/bench_private_write.cpp -o stock

./build/bin/clang++ -O2 -fsanitize=thread \
  -mllvm -tsan-one-word-filter \
  ../mvp/benchmarks/bench_private_write.cpp -o filtered
```

Run them with the same iteration count:

```sh
TSAN_OPTIONS=one_word_filter=0 ./stock 300000000
TSAN_OPTIONS=one_word_filter=1 ./filtered 300000000
```

Recompile test programs after rebuilding `compiler-rt`, because the TSan
runtime is linked into the executable.

## Validation

The implementation and the stock runtime should report the same races on
regression tests. The main checks are:

```sh
ninja -C build check-tsan
ninja -C build check-llvm-transforms-instrumentation
```

Performance measurements must keep diagnostic counters disabled and compare
separate stock and filtered binaries over multiple runs. See
[`results/summary.md`](../results/summary.md) for the current measurements.
