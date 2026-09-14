#!/usr/bin/env python3

import argparse
import hashlib
import json
import os
import platform
import re
import statistics
import subprocess
import sys
import tempfile
import time
from pathlib import Path


VARIANTS = ("stock", "parallel-note", "shadow-resident")
CODECS = {
    "h264": ["-c:v", "libx264", "-preset", "medium", "-crf", "23"],
    "h265": ["-c:v", "libx265", "-preset", "medium", "-crf", "28", "-tag:v", "hvc1"],
    "mjpeg": ["-c:v", "mjpeg", "-pix_fmt", "yuvj420p", "-q:v", "2"],
    "copy": ["-c:v", "copy", "-c:a", "copy"],
}


def run(command, **kwargs):
    return subprocess.run(command, text=True, check=True, **kwargs)


def compiler_identity(path):
    compiler = Path(path).resolve()
    output = run([str(compiler), "--version"], capture_output=True).stdout
    match = re.search(r"\([^\n]*? ([0-9a-f]{12,40})\)", output)
    return {
        "path": str(compiler),
        "sha256": hashlib.sha256(compiler.read_bytes()).hexdigest(),
        "version": output.splitlines()[0],
        "revision": match.group(1) if match else None,
    }


def preflight(args):
    suite = Path(args.suite).resolve()
    if not (suite / ".git").exists():
        raise SystemExit(f"not a Git checkout: {suite}")
    commit = run(
        ["git", "rev-parse", "HEAD"], cwd=suite, capture_output=True
    ).stdout.strip()
    expected = args.expected_commit
    if commit != expected:
        raise SystemExit(f"suite is at {commit}; expected {expected}")

    compilers = {
        name: compiler_identity(getattr(args, name.replace("-", "_")))
        for name in VARIANTS
    }
    if len({item["sha256"] for item in compilers.values()}) != len(VARIANTS):
        raise SystemExit("performance variants must use three distinct compiler binaries")

    clickhouse = suite / "nosql" / "clickhouse"
    missing = [
        str(path.relative_to(suite))
        for path in (
            clickhouse / "clickhouse",
            clickhouse / "data",
            clickhouse / "config.xml",
        )
        if not path.exists()
    ]
    record = {
        "host": {
            "node": platform.node(),
            "machine": platform.machine(),
            "kernel": platform.release(),
            "cpu_count": os.cpu_count(),
        },
        "suite": {"path": str(suite), "commit": commit},
        "compilers": compilers,
        "clickhouse": {"status": "blocked", "missing": missing},
    }
    destination = Path(args.output)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(record, indent=2) + "\n")
    print(json.dumps(record, indent=2))


def summarize(args):
    rows = json.loads(Path(args.input).read_text())
    grouped = {}
    for row in rows:
        grouped.setdefault((row["workload"], row["variant"]), []).append(row)
    summary = []
    for (workload, variant), selected in sorted(grouped.items()):
        if len(selected) != 7:
            raise SystemExit(f"{workload}/{variant}: expected 7 runs, got {len(selected)}")
        summary.append(
            {
                "workload": workload,
                "variant": variant,
                "runs": len(selected),
                "wall_median_s": statistics.median(r["wall_seconds"] for r in selected),
                "cpu_median_s": statistics.median(
                    r["user_seconds"] + r["system_seconds"] for r in selected
                ),
                "rss_median_kib": statistics.median(r["max_rss_kib"] for r in selected),
                "wall_stdev_s": statistics.stdev(r["wall_seconds"] for r in selected),
            }
        )
    print(json.dumps(summary, indent=2))


def balanced_order(run_number):
    order = list(VARIANTS)
    if (run_number // len(order)) % 2:
        order.reverse()
    offset = run_number % len(order)
    return order[offset:] + order[:offset]


def run_ffmpeg_once(binary, input_path, codec, variant, output_path):
    suffix = "mkv" if codec == "copy" else "avi" if codec == "mjpeg" else "mp4"
    command = [
        "/usr/bin/time", "-f", "__RESOURCE__ %U %S %M", str(binary),
        "-hide_banner", "-i", str(input_path), "-threads", str(os.cpu_count()),
        "-y", *CODECS[codec], "-loglevel", "error", f"{output_path}.{suffix}",
    ]
    environment = os.environ.copy()
    environment["LD_LIBRARY_PATH"] = str(binary.parent.parent / "lib")
    options = "report_bugs=0"
    if variant == "parallel-note":
        options += ":one_word_filter=1"
    environment["TSAN_OPTIONS"] = options
    started = time.perf_counter()
    result = subprocess.run(command, text=True, capture_output=True, env=environment)
    wall = time.perf_counter() - started
    output = result.stdout + result.stderr
    if result.returncode or "WARNING: ThreadSanitizer" in output:
        raise RuntimeError(f"FFmpeg {codec}/{variant} failed\n{output[-4000:]}")
    match = re.search(r"__RESOURCE__ ([0-9.]+) ([0-9.]+) (\d+)", output)
    if not match:
        raise RuntimeError(f"resource record missing for {codec}/{variant}")
    return {
        "workload": f"ffmpeg-{codec}",
        "variant": variant,
        "wall_seconds": wall,
        "user_seconds": float(match.group(1)),
        "system_seconds": float(match.group(2)),
        "max_rss_kib": int(match.group(3)),
    }


def ffmpeg(args):
    binaries = {
        name: Path(getattr(args, name.replace("-", "_"))).resolve()
        for name in VARIANTS
    }
    input_path = Path(args.input).resolve()
    for path in [*binaries.values(), input_path]:
        if not path.is_file():
            raise SystemExit(f"file not found: {path}")
    rows = []
    with tempfile.TemporaryDirectory(dir="/dev/shm") as temporary:
        output = Path(temporary) / "ffmpeg-output"
        for codec in CODECS:
            for variant in VARIANTS:
                run_ffmpeg_once(binaries[variant], input_path, codec, variant, output)
            for run_number in range(7):
                for sequence, variant in enumerate(balanced_order(run_number), 1):
                    row = run_ffmpeg_once(
                        binaries[variant], input_path, codec, variant, output
                    )
                    row.update(run=run_number + 1, sequence=sequence)
                    rows.append(row)
                    print(json.dumps(row), flush=True)
    destination = Path(args.output)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(rows, indent=2) + "\n")


def main():
    parser = argparse.ArgumentParser(description="tsan-experiments evaluation helper")
    commands = parser.add_subparsers(required=True)
    check = commands.add_parser("preflight")
    check.add_argument("--suite", required=True)
    check.add_argument("--stock", required=True)
    check.add_argument("--parallel-note", required=True)
    check.add_argument("--shadow-resident", required=True)
    check.add_argument("--expected-commit", required=True)
    check.add_argument("--output", required=True)
    check.set_defaults(function=preflight)

    report = commands.add_parser("summarize")
    report.add_argument("--input", required=True)
    report.set_defaults(function=summarize)

    video = commands.add_parser("ffmpeg")
    video.add_argument("--stock", required=True)
    video.add_argument("--parallel-note", required=True)
    video.add_argument("--shadow-resident", required=True)
    video.add_argument("--input", required=True)
    video.add_argument("--output", required=True)
    video.set_defaults(function=ffmpeg)
    args = parser.parse_args()
    args.function(args)


if __name__ == "__main__":
    main()
