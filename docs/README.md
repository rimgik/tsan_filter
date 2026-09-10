# Documentation

[Back to project README](../README.md)

## Table of contents

### Getting started

- [Build LLVM and TSan on Linux](build-linux.md)
- [Test correctness](testing.md)

### Designs

- [Parallel-note filter](features/parallel-note/README.md)
  - [Implementation details](features/parallel-note/implementation.md)
- [Shadow-resident filter](features/shadow-resident/README.md)
  - [Implementation details](features/shadow-resident/implementation.md)

### Evaluation

- [Run the benchmarks](benchmarks/README.md)
- [Benchmark results](benchmarks/results.md)
- [Use the workload profiler](profiler/README.md)
  - [Metric definitions](profiler/metrics.md)
  - [Profiler results and analysis](profiler/results.md)
- [NPB OpenMP setup](benchmarks/npb-openmp.md)

### Background

- [How TSan v3 tracks an access](reference/tsan-v3.md)
- [Why sound filtering must retain history](reference/soundness.md)
- [Related research papers](../article/README.md)

Historical proposals, generated PDFs, and superseded results are retained
under `docs/archive/`, but they are not part of the current documentation path.
