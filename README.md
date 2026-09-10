# TSan Fast-Filter Experiments

This project tests whether ThreadSanitizer (TSan) can avoid repeated runtime
work without losing race-detection history.

Three LLVM branches contain the current work:

| Branch | Purpose | Current result |
| --- | --- | --- |
| [`feat/parallel-note`](https://github.com/rimgik/llvm-project/tree/feat/parallel-note) | Stores one exact TSan word in a parallel metadata region. | Sound, but slower and larger on tested applications. |
| [`feat/shadow-resident-filter`](https://github.com/rimgik/llvm-project/tree/feat/shadow-resident-filter) | Checks the existing four TSan shadow slots before calling the runtime. | Strong synthetic and BT gains; neutral on several applications. |
| [`feat/workload-profiler`](https://github.com/rimgik/llvm-project/tree/feat/workload-profiler) | Measures ownership, exact-hit opportunities, and shadow-page density. | Diagnostic only; normal TSan tracking remains enabled. |

The parallel note was 27% faster on a deliberately favourable private loop,
but 31% lower-throughput on Redis and 72% slower on SQLite. The
shadow-resident filter reduced BT Class W CPU time by about 30% with unchanged
peak RSS. IS and CG were indistinguishable from stock in the Linux VM.

Start with the [documentation index](docs/README.md). It links the Linux build,
usage, correctness, implementation, profiler, benchmark, and reference guides.

The LLVM fork is included as a submodule. Downloaded benchmarks, build trees,
raw traces, and private working notes are intentionally excluded.
