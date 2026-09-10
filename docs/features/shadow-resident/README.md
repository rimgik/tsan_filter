# Shadow-resident filter

[Documentation](../../README.md) · [Implementation](implementation.md)

The shadow-resident filter reuses TSan's existing four-word shadow cell. It
constructs the current access word inline and skips the runtime callback only
when an existing slot already represents that exact access. It adds no memory
mapping and stores no separate ownership state.

```text
instrumented access
        |
        v
 compare shadow slot 0 -- hit --> continue
        |
       miss
        v
 compare slots 1, 2, 3 -- hit --> continue
        |
       miss
        v
    normal TSan callback
```

## Branch and option

- Branch: `feat/shadow-resident-filter`
- Compiler: `-mllvm -tsan-shadow-resident-filter`
- Runtime option: none
- Default: disabled

## Build, compile, and run

Follow the [Linux build guide](../../build-linux.md), then:

```sh
./tool/linux_tsan.sh compile-shadow-resident \
  "$BUILD" example.cpp "$HOME/build/example-shadow" -pthread
./tool/linux_tsan.sh run-shadow-resident "$HOME/build/example-shadow"
```

## Correctness

An inline hit is the same early-return case already recognized by stock TSan's
`ContainsSameAccess`. A miss changes nothing before calling normal TSan. All
ordinary shadow history therefore remains available.

Run both full suites and the focused slot/handoff tests described in
[correctness testing](../../testing.md).

## Current result

| Linux/AArch64 workload | Stock CPU | Shadow-resident CPU | Change | Peak RSS change |
| --- | ---: | ---: | ---: | ---: |
| Private cell, 300M writes | 0.5488 s | 0.1718 s | about 69% faster | not recorded |
| NPB BT-W | 22.44 s | 15.75 s | 29.8% faster | +0.1% |
| NPB BT-A | 471.11 s | 319.62 s | 32.2% faster | +0.03% |
| NPB IS-B | 37.32 s | 37.39 s | +0.2% | +0.0% |
| NPB CG-A | 24.45 s | 24.32 s | -0.5% | -0.1% |

Redis, SQLite, IS, and CG currently establish neither a general speedup nor a
regression. BT is the main application-sized positive result.

Full measurements are in [benchmark results](../../benchmarks/results.md).
See also [implementation details](implementation.md) and the
[BT profiler analysis](../../profiler/results.md#why-bt-favours-shadow-resident-filtering).
