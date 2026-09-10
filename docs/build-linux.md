# Build LLVM and TSan on Linux

[Documentation](README.md)

## Requirements

Ubuntu 24.04 or another recent Linux distribution is recommended.

```sh
sudo apt-get update
sudo apt-get install build-essential clang cmake ninja-build python3 ccache git
git clone --recurse-submodules https://github.com/rimgik/tsan_filter.git
cd tsan_filter
```

Keep source and build paths free of spaces. LLVM's test runner does not quote
every generated path correctly.

## Select a branch

```sh
git -C llvm-project fetch origin
git -C llvm-project switch feat/parallel-note
```

Replace the branch with `feat/shadow-resident-filter` or
`feat/workload-profiler` when building that feature.

## Build

```sh
BUILD="$HOME/build/tsan"
./tool/linux_tsan.sh configure llvm-project "$BUILD"
./tool/linux_tsan.sh build "$BUILD"
```

This builds Release-mode Clang, TSan, LLVM OpenMP, and Archer for the native
CPU. A later runtime edit normally needs only the second command. The helper
uses `ccache` when available; set `JOBS=4` to limit parallel compilation.

Build pristine stock TSan from commit `73e729f7b2f0` in a separate source and
build directory. A feature binary with its option disabled is not a reliable
stock comparison because its compiler instrumentation may still differ.

## Compile a program

```sh
./tool/linux_tsan.sh compile-stock \
  "$BUILD" example.cpp "$HOME/build/example-tsan" -pthread
./tool/linux_tsan.sh run-stock "$HOME/build/example-tsan"
```

Use the feature-specific compile and run command shown in the relevant
[feature guide](README.md#start-here). Recompile programs after rebuilding
compiler-rt because the TSan runtime is linked into each executable.

## OpenMP

Use the corresponding `compile-openmp-*` command. At run time, point OpenMP at
the Archer library built with LLVM:

```sh
export OMP_TOOL=enabled
export OMP_TOOL_LIBRARIES="$BUILD/runtimes/runtimes-bins/openmp/tools/archer/libarcher.so"
export OMP_NUM_THREADS=4 OMP_DYNAMIC=FALSE OMP_PROC_BIND=close OMP_PLACES=cores
```

Archer tells TSan about OpenMP synchronization. It does not replace TSan.

Related: [correctness testing](testing.md) and [running benchmarks](benchmarks/README.md).
