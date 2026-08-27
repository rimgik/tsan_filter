#!/usr/bin/env python3

import argparse
import csv
import math
import re
import shutil
import statistics
import subprocess
import time
from pathlib import Path


def parse_variant(value):
    name, separator, binary = value.partition("=")
    if not separator or not name or not binary:
        raise argparse.ArgumentTypeError("expected NAME=BINARY")
    return name, binary


def run_command(variant, args, cpu, metric_pattern, measure_rss):
    name, binary = variant
    command = [binary, *args]
    if cpu is not None:
        command = ["taskset", "-c", cpu, *command]
    if measure_rss:
        command = [
            "/usr/bin/time",
            "-f",
            "__TSAN_RSS_KIB__=%M",
            *command,
        ]

    started = time.perf_counter()
    result = subprocess.run(command, text=True, capture_output=True)
    wall_seconds = time.perf_counter() - started
    output = result.stdout + "\n" + result.stderr
    if result.returncode:
        raise RuntimeError(
            f"{name} exited with {result.returncode}\n"
            f"command: {' '.join(command)}\n{output}"
        )

    match = metric_pattern.search(output)
    if not match:
        raise RuntimeError(f"metric not found in {name} output\n{output}")
    rss_match = re.search(r"__TSAN_RSS_KIB__=(\d+)", result.stderr)
    return float(match.group(1)), wall_seconds, (
        int(rss_match.group(1)) if rss_match else None
    )


def rotated_order(variants, run):
    count = len(variants)
    order = variants if (run // count) % 2 == 0 else list(reversed(variants))
    offset = run % count
    return order[offset:] + order[:offset]


def paired_change(rows, baseline, candidate):
    by_run = {}
    for row in rows:
        by_run.setdefault(row["run"], {})[row["variant"]] = row["metric"]
    logs = [
        math.log(values[candidate] / values[baseline])
        for values in by_run.values()
        if baseline in values and candidate in values
    ]
    mean = statistics.fmean(logs)
    error = 0.0
    if len(logs) > 1:
        error = 1.96 * statistics.stdev(logs) / math.sqrt(len(logs))
    return (
        100.0 * math.expm1(mean),
        100.0 * math.expm1(mean - error),
        100.0 * math.expm1(mean + error),
    )


def main():
    parser = argparse.ArgumentParser(
        description="Run benchmark variants in balanced order and compare them."
    )
    parser.add_argument(
        "--variant",
        action="append",
        type=parse_variant,
        required=True,
        metavar="NAME=BINARY",
    )
    parser.add_argument("--runs", type=int, default=15)
    parser.add_argument("--warmups", type=int, default=1)
    parser.add_argument("--cpu", help="taskset CPU list, for example 2 or 2-3")
    parser.add_argument(
        "--metric-regex",
        default=r"seconds=([0-9]+(?:\.[0-9]+)?)",
    )
    parser.add_argument("--csv", type=Path, required=True)
    parser.add_argument("--no-rss", action="store_true")
    parser.add_argument("benchmark_args", nargs=argparse.REMAINDER)
    options = parser.parse_args()
    if options.benchmark_args[:1] == ["--"]:
        options.benchmark_args = options.benchmark_args[1:]

    if options.runs < 2 or options.warmups < 0:
        parser.error("--runs must be at least 2 and --warmups cannot be negative")
    names = [name for name, _ in options.variant]
    if len(names) < 2 or len(names) != len(set(names)):
        parser.error("provide at least two variants with unique names")
    for _, binary in options.variant:
        if not Path(binary).is_file():
            parser.error(f"binary does not exist: {binary}")
    if options.cpu is not None and shutil.which("taskset") is None:
        parser.error("--cpu requires taskset")
    measure_rss = not options.no_rss
    if measure_rss and not Path("/usr/bin/time").is_file():
        parser.error("install /usr/bin/time or use --no-rss")

    metric_pattern = re.compile(options.metric_regex)
    for _ in range(options.warmups):
        for variant in options.variant:
            run_command(
                variant,
                options.benchmark_args,
                options.cpu,
                metric_pattern,
                measure_rss,
            )

    rows = []
    for run in range(options.runs):
        for sequence, variant in enumerate(rotated_order(options.variant, run)):
            metric, wall_seconds, rss_kib = run_command(
                variant,
                options.benchmark_args,
                options.cpu,
                metric_pattern,
                measure_rss,
            )
            row = {
                "run": run + 1,
                "sequence": sequence + 1,
                "variant": variant[0],
                "metric": metric,
                "wall_seconds": wall_seconds,
                "max_rss_kib": rss_kib,
            }
            rows.append(row)
            print(
                f"run={run + 1} variant={variant[0]} "
                f"metric={metric:.6f} rss_kib={rss_kib}"
            )

    options.csv.parent.mkdir(parents=True, exist_ok=True)
    with options.csv.open("w", newline="") as output:
        writer = csv.DictWriter(output, fieldnames=rows[0].keys())
        writer.writeheader()
        writer.writerows(rows)

    print("\nSummary")
    for name in names:
        values = [row["metric"] for row in rows if row["variant"] == name]
        print(
            f"{name}: mean={statistics.fmean(values):.6f} "
            f"median={statistics.median(values):.6f} "
            f"stdev={statistics.stdev(values):.6f}"
        )

    baseline = names[0]
    print(f"\nPaired metric change relative to {baseline}")
    for candidate in names[1:]:
        if any(
            row["metric"] <= 0
            for row in rows
            if row["variant"] in (baseline, candidate)
        ):
            raise RuntimeError("paired ratio requires positive metric values")
        change, low, high = paired_change(rows, baseline, candidate)
        print(
            f"{candidate}: {change:+.3f}% "
            f"(approx. 95% CI [{low:+.3f}%, {high:+.3f}%])"
        )


if __name__ == "__main__":
    main()
