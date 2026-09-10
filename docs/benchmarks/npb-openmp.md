# NPB OpenMP

[Benchmark index](README.md)

The harness uses GMAP NPB-CPP revision
`5bc1e2c4aca09f4ebae370b80f8f335a76e162ef`. BT is a structured
pseudo-application, IS is integer sort, and CG is an irregular sparse-matrix
kernel.

```sh
git clone https://github.com/GMAP/NPB-CPP.git benchmark_code/NPB-CPP
git -C benchmark_code/NPB-CPP checkout 5bc1e2c4aca09f4ebae370b80f8f335a76e162ef
```

Build selected variants with `tool/npb_cpp.py`. The compiler paths must point
to the corresponding stock, note, shadow-resident, and profiler builds.

```sh
./tool/npb_cpp.py build \
  --openmp-include "$BUILD/lib/clang/24/include" \
  --openmp-runtime "$BUILD/runtimes/runtimes-bins/openmp/runtime/src" \
  --compiler stock="$HOME/build/stock/bin/clang++" \
  --compiler shadow-resident="$HOME/build/shadow/bin/clang++" \
  --variant stock --variant shadow-resident \
  --benchmark BT --class W
```

Use Class W for routine BT testing, IS Class B and CG Class A for larger runs.
BT Class A takes about 115 seconds for stock in the development VM and the note
variant exceeds 120 seconds, so it is not the default balanced workload.

Every run must print `Verification = SUCCESSFUL`. Set `OMP_TOOL_LIBRARIES` as
shown in the [Linux build guide](../build-linux.md).
