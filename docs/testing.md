# Correctness testing

[Documentation](README.md) · [Linux build](build-linux.md)

Run correctness checks before timing a feature.

## Full suites

```sh
./tool/linux_tsan.sh check "$BUILD"
./tool/linux_tsan.sh check-openmp "$BUILD"
```

The latest Linux/AArch64 build completed `check-tsan` with 358 passes and
`check-openmp` with 419 passes, with no unexpected failures.

## Required checks

For every feature:

- Run the feature's LLVM instrumentation test.
- Compile and run an intentional data race; TSan must report it.

The application-suite control uses
`mvp/benchmarks/bench_intentional_race.c` under each separately built variant.
- Confirm that the feature is disabled unless its documented option is used.
- Compare against a separately built stock compiler.

The parallel note additionally tests exact merge, same-owner hits, owner
change, failed-merge fallback, allocator tagging, and detection using history
recorded before a transition.

The shadow-resident filter tests slot-0 hits, hits in slots 1–3, all-slot
misses, reads, writes, and runtime fallback. The ordered-handoff benchmark
places the repeated word outside slot 0 without introducing a race.

The profiler tests known private/shared ratios, every page-density bucket,
exact-note counters, shadow-slot counters, Linux `smaps` collection, and an
ordinary TSan race report.

Focused tests complement the full suites; they do not replace them.

## Run focused tests

Use the matching filter on each feature branch:

```sh
# Compiler-pass test.
cmake --build "$BUILD" --target opt FileCheck
python3 "$BUILD/bin/llvm-lit" -sv --filter=one-word-filter \
  "$BUILD/test/Instrumentation/ThreadSanitizer"

# Runtime tests. The wildcard selects the configured host architecture.
python3 "$BUILD/bin/llvm-lit" -sv --filter=one_word_filter \
  "$BUILD/runtimes/runtimes-bins/compiler-rt/test/tsan"/*Config
```

For shadow resident, replace the filters with `shadow-resident` and
`shadow_resident_filter`. For the profiler runtime tests, use
`ownership_profile`. A filtered command must list and run at least one test;
an empty selection is a failed validation.
