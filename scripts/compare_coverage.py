#!/usr/bin/env python3
"""Compare coverage totals between a baseline and head report."""

from __future__ import annotations

import argparse
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--baseline", type=Path, help="Coverage XML report for the base revision"
    )
    parser.add_argument(
        "--head",
        type=Path,
        required=True,
        help="Coverage XML report for the PR head",
    )
    parser.add_argument(
        "--tolerance",
        type=float,
        default=0.0,
        help="Allowed coverage drop (fractional). Default: 0 (no drop allowed)",
    )
    return parser.parse_args()


@dataclass(frozen=True)
class CoverageCounts:
    covered: int
    valid: int

    @property
    def rate(self) -> float:
        return self.covered / self.valid if self.valid else 0.0


def extract_counts(report: Path) -> dict[str, CoverageCounts]:
    if not report.exists():
        raise SystemExit(f"Coverage report not found: {report}")
    tree = ET.parse(report)
    root = tree.getroot()

    counts: dict[str, CoverageCounts] = {}
    for class_node in root.findall(".//class"):
        filename = class_node.attrib.get("filename")
        if not filename:
            continue
        lines = class_node.findall("./lines/line")
        counts[filename.replace("\\", "/")] = CoverageCounts(
            covered=sum(int(line.attrib.get("hits", "0")) > 0 for line in lines),
            valid=len(lines),
        )

    if not counts:
        raise SystemExit(f"Report {report} does not contain per-file coverage data")
    return counts


def plugin_name(filename: str) -> str | None:
    parts = filename.split("/")
    if len(parts) >= 3 and parts[0] == "plugins":
        return parts[1]
    return None


def combine_counts(
    files: dict[str, CoverageCounts], plugin_names: set[str] | None = None
) -> CoverageCounts:
    selected = (
        counts
        for filename, counts in files.items()
        if plugin_names is None or plugin_name(filename) in plugin_names
    )
    covered = 0
    valid = 0
    for counts in selected:
        covered += counts.covered
        valid += counts.valid
    return CoverageCounts(covered=covered, valid=valid)


def main() -> None:
    args = parse_args()
    head_files = extract_counts(args.head)
    head_counts = combine_counts(head_files)
    print(f"Head coverage: {head_counts.rate:.4f}")

    if args.baseline is None:
        print("No baseline coverage provided; skipping comparison.")
        return

    base_files = extract_counts(args.baseline)
    baseline_plugins = {
        name for filename in base_files if (name := plugin_name(filename)) is not None
    }
    base_counts = combine_counts(base_files, baseline_plugins or None)
    comparable_head_counts = combine_counts(head_files, baseline_plugins or None)
    if comparable_head_counts.valid == 0:
        raise SystemExit("Head report has no coverage data comparable to the baseline")

    head_rate = comparable_head_counts.rate
    base_rate = base_counts.rate
    if baseline_plugins:
        new_plugins = {
            name
            for filename in head_files
            if (name := plugin_name(filename)) is not None
            and name not in baseline_plugins
        }
        print(f"Comparable head coverage: {head_rate:.4f}")
        if new_plugins:
            print(
                "New plugins excluded from baseline comparison: "
                + ", ".join(sorted(new_plugins))
            )
    print(f"Baseline coverage: {base_rate:.4f}")

    if head_rate + args.tolerance < base_rate:
        delta = base_rate - head_rate
        raise SystemExit(
            f"Coverage decreased by {delta:.4f}. Allowed tolerance: {args.tolerance:.4f}."
        )

    print("Coverage preserved (no decrease detected).")


if __name__ == "__main__":
    main()
