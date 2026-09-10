#!/usr/bin/env python3

import argparse
import csv
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path


MAP_PATTERN = re.compile(
    r"TSAN_OWNERSHIP_MAP shadow=([0-9a-f]+)-([0-9a-f]+) "
    r"profile=([0-9a-f]+)-([0-9a-f]+) page_size=(\d+)"
)
VMA_PATTERN = re.compile(r"^([0-9a-f]+)-([0-9a-f]+)\s")
DEFAULT_EVENTS = ",".join(
    (
        "cycles",
        "instructions",
        "branches",
        "branch-misses",
        "cache-references",
        "cache-misses",
        "L1-dcache-loads",
        "L1-dcache-load-misses",
        "dTLB-loads",
        "dTLB-load-misses",
        "page-faults",
        "context-switches",
    )
)


def parse_command(values):
    return values[1:] if values[:1] == ["--"] else values


def add_tsan_options(environment, *options):
    existing = environment.get("TSAN_OPTIONS", "")
    environment["TSAN_OPTIONS"] = ":".join(
        value for value in (existing, *options) if value
    )


def read_smaps(pid, ranges):
    totals = {"total": {"rss_kib": 0, "pss_kib": 0, "dirty_kib": 0}}
    totals.update(
        (name, {"rss_kib": 0, "pss_kib": 0, "dirty_kib": 0})
        for name in ranges
    )
    current = []
    with Path(f"/proc/{pid}/smaps").open() as source:
        for line in source:
            match = VMA_PATTERN.match(line)
            if match:
                begin, end = (int(value, 16) for value in match.groups())
                current = [
                    name
                    for name, (range_begin, range_end) in ranges.items()
                    if begin < range_end and end > range_begin
                ]
                continue
            if line.startswith("Rss:"):
                field = "rss_kib"
            elif line.startswith("Pss:"):
                field = "pss_kib"
            elif line.startswith("Private_Dirty:"):
                field = "dirty_kib"
            else:
                continue
            value = int(line.split()[1])
            totals["total"][field] += value
            for name in current:
                totals[name][field] += value
    return totals


def stream_output(stream, destination, map_state, quiet):
    for line in iter(stream.readline, ""):
        if not quiet:
            destination.write(line)
            destination.flush()
        match = MAP_PATTERN.search(line)
        if match:
            shadow_beg, shadow_end, profile_beg, profile_end, page_size = (
                int(value, 16) if index < 4 else int(value)
                for index, value in enumerate(match.groups())
            )
            map_state.update(
                {
                    "ranges": {
                        "shadow": (shadow_beg, shadow_end),
                        "ownership_profile": (profile_beg, profile_end),
                    },
                    "page_size": page_size,
                }
            )
            map_state["ready"].set()


def percentage(part, whole):
    return 100.0 * part / whole if whole else 0.0


def derived_ownership(raw):
    private_accesses = raw["private_accesses"]
    private_csa = raw["private_csa_hits"]
    pages = raw.get("shadow_pages", 0)
    sparse_pages = raw.get("shadow_pages_1_cell", 0) + raw.get(
        "shadow_pages_2_64_cells", 0
    )
    dense_pages = raw.get("shadow_pages_193_255_cells", 0) + raw.get(
        "shadow_pages_256_cells", 0
    )
    note_absorbed = raw.get("note_absorbed_accesses", 0)
    return {
        "private_cell_percent": percentage(
            raw["private_cells"], raw["first_touches"]
        ),
        "private_access_percent": percentage(
            private_accesses, raw["cell_touches"]
        ),
        "contains_same_access_percent": percentage(
            private_csa + raw["shared_csa_hits"], raw["cell_touches"]
        ),
        "private_not_contains_same_percent": percentage(
            private_accesses - private_csa, raw["cell_touches"]
        ),
        "note_absorbed_access_percent": percentage(
            note_absorbed, raw["cell_touches"]
        ),
        "note_absorbed_not_contains_same_percent": percentage(
            note_absorbed - raw.get("note_absorbed_csa_hits", 0),
            raw["cell_touches"],
        ),
        "shadow_exact_hit_percent": percentage(
            raw.get("shadow_exact_slot0_hits", 0)
            + raw.get("shadow_exact_late_hits", 0),
            raw.get("shadow_exact_eligible", 0),
        ),
        "potentially_avoidable_shadow_page_percent": percentage(
            raw.get("potentially_avoidable_shadow_pages", 0), pages
        ),
        "mixed_path_shadow_page_percent": percentage(
            raw.get("mixed_path_shadow_pages", 0), pages
        ),
        "fallback_only_shadow_page_percent": percentage(
            raw.get("fallback_only_shadow_pages", 0), pages
        ),
        "sparse_shadow_page_percent": percentage(sparse_pages, pages),
        "dense_shadow_page_percent": percentage(dense_pages, pages),
    }


def write_samples(path, rows):
    if not path or not rows:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="") as output:
        writer = csv.DictWriter(output, fieldnames=rows[0].keys())
        writer.writeheader()
        writer.writerows(rows)


def summarize_memory(samples, page_size):
    if not samples:
        return {"samples": 0}
    summary = {"samples": len(samples), "page_size": page_size}
    for region in ("total", "shadow", "ownership_profile"):
        for field in ("rss_kib", "pss_kib", "dirty_kib"):
            key = f"{region}_{field}"
            values = [row[key] for row in samples]
            summary[f"peak_{key}"] = max(values)
            summary[f"last_{key}"] = values[-1]
        summary[f"peak_{region}_resident_pages"] = (
            summary[f"peak_{region}_rss_kib"] * 1024 // page_size
        )
    return summary


def ownership_command(options):
    command = parse_command(options.command)
    if not command:
        raise SystemExit("ownership requires a command after --")
    if not sys.platform.startswith("linux"):
        raise SystemExit("ownership profiling and smaps sampling require Linux")

    options.output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(prefix="tsan-ownership-", suffix=".json") as tmp:
        environment = os.environ.copy()
        add_tsan_options(
            environment,
            "ownership_profile=1",
            f"ownership_profile_allocations={int(not options.no_allocation_owner)}",
            f"ownership_profile_wait_for_range={int(options.wait_for_range)}",
            f"ownership_profile_path={tmp.name}",
        )
        started = time.monotonic()
        process = subprocess.Popen(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
            env=environment,
        )
        map_state = {"ready": threading.Event()}
        readers = (
            threading.Thread(
                target=stream_output,
                args=(process.stdout, sys.stdout, map_state, options.quiet),
            ),
            threading.Thread(
                target=stream_output,
                args=(process.stderr, sys.stderr, map_state, options.quiet),
            ),
        )
        for reader in readers:
            reader.start()

        samples = []
        while process.poll() is None:
            if not map_state["ready"].wait(options.interval):
                continue
            try:
                values = read_smaps(process.pid, map_state["ranges"])
            except (FileNotFoundError, ProcessLookupError):
                break
            row = {"elapsed_seconds": time.monotonic() - started}
            for region, fields in values.items():
                for field, value in fields.items():
                    row[f"{region}_{field}"] = value
            samples.append(row)
            time.sleep(options.interval)

        for reader in readers:
            reader.join()
        elapsed = time.monotonic() - started
        if not map_state["ready"].is_set():
            raise SystemExit("ownership-profile mapping announcement was not found")
        try:
            raw = json.loads(Path(tmp.name).read_text())
        except (FileNotFoundError, json.JSONDecodeError) as error:
            raise SystemExit(f"invalid ownership-profile output: {error}") from error

    result = {
        "command": command,
        "exit_status": process.returncode,
        "elapsed_seconds": elapsed,
        "ownership": raw,
        "derived": derived_ownership(raw),
        "memory": summarize_memory(samples, map_state["page_size"]),
    }
    options.output.write_text(json.dumps(result, indent=2) + "\n")
    write_samples(options.smaps_csv, samples)

    derived = result["derived"]
    memory = result["memory"]
    print("\nOwnership summary")
    print(f"private cells: {derived['private_cell_percent']:.2f}%")
    print(f"private-phase accesses: {derived['private_access_percent']:.2f}%")
    print(
        "private accesses not already handled by ContainsSameAccess: "
        f"{derived['private_not_contains_same_percent']:.2f}%"
    )
    print(
        "exact-note absorbed accesses: "
        f"{derived['note_absorbed_access_percent']:.2f}%"
    )
    print(
        "potentially avoidable shadow pages: "
        f"{derived['potentially_avoidable_shadow_page_percent']:.2f}%"
    )
    print(
        f"page density: {derived['sparse_shadow_page_percent']:.2f}% sparse, "
        f"{derived['dense_shadow_page_percent']:.2f}% dense"
    )
    if memory["samples"]:
        print(
            f"peak shadow RSS: {memory['peak_shadow_rss_kib']} KiB "
            f"({memory['peak_shadow_resident_pages']} pages)"
        )
        print(
            "peak ownership-profile RSS: "
            f"{memory['peak_ownership_profile_rss_kib']} KiB "
            f"({memory['peak_ownership_profile_resident_pages']} pages)"
        )
    print(f"result: {options.output}")
    if process.returncode:
        print(f"benchmark exit status: {process.returncode}", file=sys.stderr)
        raise SystemExit(process.returncode if process.returncode > 0 else 1)


def perf_command(options):
    command = parse_command(options.command)
    if not command:
        raise SystemExit("perf requires a command after --")
    if shutil.which("perf") is None:
        raise SystemExit("perf is not installed")
    if options.cpu is not None:
        if shutil.which("taskset") is None:
            raise SystemExit("--cpu requires taskset")
        command = ["taskset", "-c", options.cpu, *command]
    options.output.parent.mkdir(parents=True, exist_ok=True)
    invocation = [
        "perf",
        "stat",
        "-x",
        ",",
        "-r",
        str(options.runs),
        "-e",
        options.events,
        "-o",
        str(options.output),
        "--",
        *command,
    ]
    raise SystemExit(subprocess.run(invocation).returncode)


def main():
    parser = argparse.ArgumentParser(
        description="Characterize TSan ownership, resident mappings, and PMU cost."
    )
    subparsers = parser.add_subparsers(dest="mode", required=True)

    ownership = subparsers.add_parser("ownership")
    ownership.add_argument("--output", type=Path, required=True)
    ownership.add_argument("--smaps-csv", type=Path)
    ownership.add_argument("--interval", type=float, default=0.05)
    ownership.add_argument("--no-allocation-owner", action="store_true")
    ownership.add_argument("--wait-for-range", action="store_true")
    ownership.add_argument("--quiet", action="store_true")
    ownership.add_argument("command", nargs=argparse.REMAINDER)
    ownership.set_defaults(function=ownership_command)

    perf = subparsers.add_parser("perf")
    perf.add_argument("--output", type=Path, required=True)
    perf.add_argument("--runs", type=int, default=7)
    perf.add_argument("--cpu")
    perf.add_argument("--events", default=DEFAULT_EVENTS)
    perf.add_argument("command", nargs=argparse.REMAINDER)
    perf.set_defaults(function=perf_command)

    options = parser.parse_args()
    if getattr(options, "interval", 0.05) <= 0:
        parser.error("--interval must be positive")
    options.function(options)


if __name__ == "__main__":
    main()
