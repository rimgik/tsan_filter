#!/usr/bin/env python3
"""Build selected GMAP NPB-CPP OpenMP workloads with TSan variants."""

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
DEFAULT_SOURCE = ROOT / "benchmark_code" / "NPB-CPP"
DEFAULT_OUTPUT = ROOT / "benchmark_result" / "npb-cpp"
MANIFEST = ROOT / "benchmarks" / "npb_cpp_openmp.json"


def load_manifest():
    with MANIFEST.open() as source:
        return json.load(source)


def compiler_spec(value):
    name, separator, compiler = value.partition("=")
    if not separator or not name or not compiler:
        raise argparse.ArgumentTypeError("expected VARIANT=/path/to/clang++")
    return name, Path(compiler)


def selected(values, allowed, label):
    result = [item.upper() if label == "benchmark" else item for item in values]
    unknown = sorted(set(result) - set(allowed))
    if unknown:
        raise SystemExit(f"unknown {label}: {', '.join(unknown)}")
    return result


def run(command, cwd):
    print("+", " ".join(str(part) for part in command))
    subprocess.run(command, cwd=cwd, check=True)


def build(options):
    manifest = load_manifest()
    source = options.source.resolve()
    suite_source = source / manifest["suite_directory"]
    if not (suite_source / "Makefile").is_file():
        raise SystemExit(
            f"NPB-CPP OpenMP source not found at {suite_source}. "
            "Clone the revision in benchmarks/npb_cpp_openmp.json first."
        )

    source_revision = subprocess.check_output(
        ["git", "-C", str(source), "rev-parse", "HEAD"], text=True
    ).strip()
    if source_revision != manifest["revision"]:
        raise SystemExit(
            f"NPB-CPP is at {source_revision}; expected {manifest['revision']}"
        )

    compilers = dict(options.compiler)
    variants = selected(options.variant, manifest["variants"], "variant")
    benchmarks = selected(options.benchmark, manifest["benchmarks"], "benchmark")
    for variant in variants:
        compiler = compilers.get(variant)
        if compiler is None:
            raise SystemExit(f"missing --compiler {variant}=/path/to/clang++")
        if not compiler.is_file():
            raise SystemExit(f"compiler does not exist: {compiler}")

    output = options.output.resolve()
    build_root = output / "build"
    binary_root = output / "bin"
    openmp_runtime = options.openmp_runtime.resolve() if options.openmp_runtime else None
    if openmp_runtime and not (openmp_runtime / "libomp.so").is_file():
        raise SystemExit(f"libomp.so not found in {openmp_runtime}")
    openmp_include = options.openmp_include.resolve() if options.openmp_include else None
    if openmp_include and not (openmp_include / "omp.h").is_file():
        raise SystemExit(f"omp.h not found in {openmp_include}")
    if options.replace:
        for variant in variants:
            shutil.rmtree(build_root / variant, ignore_errors=True)
            for benchmark in benchmarks:
                (binary_root / variant / options.workload_class / benchmark.lower()).unlink(
                    missing_ok=True
                )

    openmp_link_flags = (
        [f"-L{openmp_runtime}", f"-Wl,-rpath,{openmp_runtime}"]
        if openmp_runtime
        else []
    )
    openmp_compile_flags = [f"-idirafter{openmp_include}"] if openmp_include else []
    base_compile_flags = [
        "-O2",
        "-gline-tables-only",
        "-std=c++14",
        "-fopenmp",
        "-fsanitize=thread",
        *openmp_compile_flags,
        *options.extra_flag,
    ]
    base_link_flags = [
        "-O2",
        "-gline-tables-only",
        "-fopenmp",
        "-fsanitize=thread",
        *openmp_link_flags,
        *options.extra_flag,
    ]
    binary_root.mkdir(parents=True, exist_ok=True)
    for variant in variants:
        worktree = build_root / variant
        if worktree.exists():
            raise SystemExit(
                f"build directory already exists: {worktree}; use --replace to rebuild it"
            )
        shutil.copytree(suite_source, worktree)
        compiler = compilers[variant]
        compile_flags = [
            *base_compile_flags,
            *manifest["variants"][variant]["compiler_flags"],
        ]
        make_variables = [
            f"CC={compiler}",
            f"CLINK={compiler}",
            f"UCC={compiler} -fopenmp {' '.join(openmp_compile_flags + openmp_link_flags)}",
            f"CFLAGS={' '.join(compile_flags)}",
            f"CLINKFLAGS={' '.join(base_link_flags)}",
            "C_LIB=-lm",
        ]
        for benchmark in benchmarks:
            run(
                ["make", benchmark, f"CLASS={options.workload_class}", *make_variables],
                worktree,
            )
            built = worktree / "bin" / f"{benchmark.lower()}.{options.workload_class}"
            if not built.is_file():
                raise SystemExit(f"NPB did not produce {built}")
            destination = binary_root / variant / options.workload_class / benchmark.lower()
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(built, destination)

    build_manifest = {
        "upstream_revision": source_revision,
        "class": options.workload_class,
        "benchmarks": benchmarks,
        "openmp_include": str(openmp_include) if openmp_include else None,
        "openmp_runtime": str(openmp_runtime) if openmp_runtime else None,
        "variants": {
            name: {
                "compiler": str(compilers[name]),
                "compiler_flags": manifest["variants"][name]["compiler_flags"],
                "runtime_options": manifest["variants"][name]["runtime_options"],
            }
            for name in variants
        },
    }
    manifest_path = output / f"build-manifest-{options.workload_class}.json"
    if manifest_path.is_file():
        previous = json.loads(manifest_path.read_text())
        compatible = all(
            previous.get(key) == build_manifest[key]
            for key in (
                "upstream_revision",
                "class",
                "openmp_include",
                "openmp_runtime",
            )
        )
        if compatible:
            build_manifest["benchmarks"] = list(
                dict.fromkeys(previous.get("benchmarks", []) + benchmarks)
            )
            build_manifest["variants"] = {
                **previous.get("variants", {}),
                **build_manifest["variants"],
            }
    with manifest_path.open("w") as destination:
        json.dump(build_manifest, destination, indent=2)
        destination.write("\n")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    build_parser = subparsers.add_parser("build")
    build_parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    build_parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    build_parser.add_argument("--openmp-include", type=Path)
    build_parser.add_argument("--openmp-runtime", type=Path)
    build_parser.add_argument("--compiler", action="append", type=compiler_spec, required=True)
    build_parser.add_argument("--variant", action="append", required=True)
    build_parser.add_argument("--benchmark", action="append")
    build_parser.add_argument(
        "--class", dest="workload_class", choices=["S", "W", "A", "B"], default="S"
    )
    build_parser.add_argument("--extra-flag", action="append", default=[])
    build_parser.add_argument("--replace", action="store_true")
    build_parser.set_defaults(function=build)
    options = parser.parse_args()
    if options.command == "build" and options.benchmark is None:
        options.benchmark = ["BT", "IS", "CG"]
    options.function(options)


if __name__ == "__main__":
    try:
        main()
    except subprocess.CalledProcessError as error:
        sys.exit(error.returncode)
