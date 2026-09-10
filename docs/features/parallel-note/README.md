# Parallel-note filter

[Documentation](../../README.md) · [Implementation](implementation.md)

The parallel-note filter stores one exact TSan shadow word for each eight bytes
of supported application memory. It handles an access only while all history
needed by TSan fits exactly in that one word. Otherwise it transfers the word
to ordinary shadow and permanently uses normal TSan tracking for that cell.

```text
instrumented access
        |
        v
 parallel note word -- exact hit --> continue
        |
   merge exactly?
     | yes                         | no
     v                             v
 update note              copy history to ordinary shadow
                                  |
                                  v
                              normal TSan
```

## Branch and options

- Branch: `feat/parallel-note`
- Compiler: `-mllvm -tsan-one-word-filter`
- Runtime: `TSAN_OPTIONS=one_word_filter=1`
- Default: disabled

## Build, compile, and run

Follow the [Linux build guide](../../build-linux.md), then:

```sh
./tool/linux_tsan.sh compile-filter \
  "$BUILD" example.cpp "$HOME/build/example-note" -pthread
./tool/linux_tsan.sh run-filter "$HOME/build/example-note"
```

## Correctness

The design retains complete TSan history. An owner change alone is never a
reason to discard the earlier word. Unsupported accesses and failed exact
merges fall back to normal TSan before history is lost.

Run:

```sh
./tool/linux_tsan.sh check "$BUILD"
./tool/linux_tsan.sh check-openmp "$BUILD"
```

See [correctness testing](../../testing.md) for focused requirements.

## Current result

| Linux/AArch64 workload | Stock | Parallel note | Change | Peak RSS change |
| --- | ---: | ---: | ---: | ---: |
| Private cell, 300M writes | 0.5427 s | 0.3944 s | 27% faster | not recorded |
| Redis | 91,351 req/s | 63,123 req/s | 31% lower throughput | +43% |
| SQLite speedtest1 | 5.76 s | 9.92 s | 72% slower | +10% |
| NPB BT-W | 22.44 s CPU | 79.24 s CPU | 253% slower | +33% |

The private loop is a deliberate best case. Tested applications pay for the
extra mapping and lookup too often for the saved callbacks to recover the cost.

Full measurements are in [benchmark results](../../benchmarks/results.md).
See also [implementation details](implementation.md) and
[benchmark instructions](../../benchmarks/README.md).
