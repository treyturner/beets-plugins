#!/usr/bin/env python3
"""Compare coverage totals between a baseline and head report."""

from __future__ import annotations

import argparse
import xml.etree.ElementTree as ET
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


def extract_rate(report: Path) -> float:
    if not report.exists():
        raise SystemExit(f"Coverage report not found: {report}")
    tree = ET.parse(report)
    root = tree.getroot()
    rate = root.attrib.get("line-rate")
    if rate is None:
        raise SystemExit(f"Report {report} missing line-rate attribute")
    return float(rate)


def main() -> None:
    args = parse_args()
    head_rate = extract_rate(args.head)
    print(f"Head coverage: {head_rate:.4f}")

    if args.baseline is None:
        print("No baseline coverage provided; skipping comparison.")
        return

    base_rate = extract_rate(args.baseline)
    print(f"Baseline coverage: {base_rate:.4f}")

    if head_rate + args.tolerance < base_rate:
        delta = base_rate - head_rate
        raise SystemExit(
            f"Coverage decreased by {delta:.4f}. Allowed tolerance: {args.tolerance:.4f}."
        )

    print("Coverage preserved (no decrease detected).")


if __name__ == "__main__":
    main()
