#!/usr/bin/env python3
"""Guardrails to keep work contained to a single plugin."""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from collections.abc import Iterable, Sequence
from pathlib import Path

try:  # Python 3.11+
    import tomllib
except ModuleNotFoundError:  # pragma: no cover
    import tomli as tomllib  # type: ignore


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--mode",
        choices=("staged", "branch"),
        default="staged",
        help="Which diff to inspect: staged files or the entire branch compared to --base",
    )
    parser.add_argument(
        "--base",
        default=os.environ.get("SINGLE_PLUGIN_BASE", "origin/main"),
        help="Base ref to compare against when --mode=branch",
    )
    parser.add_argument(
        "--plugins-dir",
        default="plugins",
        help="Directory that contains plugin folders",
    )
    parser.add_argument(
        "--allow-root-only",
        action="store_true",
        help="Permit commits/branches that only touch root-level files",
    )
    parser.add_argument(
        "--env-override",
        default="ALLOW_MULTIPLE_PLUGINS",
        help="Environment variable name that, when set to '1', bypasses the check",
    )
    return parser.parse_args()


def load_plugin_names(plugins_dir: Path) -> set[str]:
    names: set[str] = set()
    for child in plugins_dir.iterdir():
        if not child.is_dir():
            continue
        pyproject = child / "pyproject.toml"
        if not pyproject.exists():
            continue
        with pyproject.open("rb") as handle:
            data = tomllib.load(handle)
        project = data.get("project", {})
        package_name = project.get("name")
        if package_name:
            names.add(child.name)
    return names


def gather_files(mode: str, base: str) -> Sequence[str]:
    if mode == "staged":
        cmd = ["git", "diff", "--cached", "--name-only"]
    else:
        cmd = ["git", "diff", "--name-only", f"{base}...HEAD"]
    try:
        output = subprocess.check_output(cmd, text=True)
    except (
        subprocess.CalledProcessError
    ) as exc:  # pragma: no cover - git failure is fatal
        print(exc, file=sys.stderr)
        sys.exit(1)
    return [line.strip() for line in output.splitlines() if line.strip()]


def detect_plugins(files: Iterable[str], plugin_names: set[str]) -> set[str]:
    touched: set[str] = set()
    prefix = "plugins/"
    for path in files:
        if not path.startswith(prefix):
            continue
        remainder = path[len(prefix) :]
        segments = remainder.split("/", 1)
        if not segments:
            continue
        candidate = segments[0]
        if candidate in plugin_names:
            touched.add(candidate)
    return touched


def main() -> None:
    args = parse_args()

    if os.environ.get(args.env_override) == "1":
        print("Bypassing single-plugin guard via environment override.")
        return

    root = Path(__file__).resolve().parents[1]
    plugins_dir = root / args.plugins_dir
    if not plugins_dir.exists():
        print(f"Plugins directory not found: {plugins_dir}", file=sys.stderr)
        sys.exit(1)

    plugin_names = load_plugin_names(plugins_dir)
    if not plugin_names:
        print(
            "No plugins discovered; ensure each plugin has a pyproject.toml",
            file=sys.stderr,
        )
        sys.exit(1)

    files = gather_files(args.mode, args.base)

    if not files:
        print("No files to inspect; skipping plugin enforcement.")
        return

    touched_plugins = detect_plugins(files, plugin_names)

    if not touched_plugins:
        if args.allow_root_only:
            print("Only root files were modified.")
            return
        print(
            "This change does not touch any plugin. "
            "If this is intentional, rerun with --allow-root-only",
            file=sys.stderr,
        )
        sys.exit(1)

    if len(touched_plugins) > 1:
        sorted_plugins = ", ".join(sorted(touched_plugins))
        print(
            "Multiple plugins detected in this change: "
            f"{sorted_plugins}. Split your work so each commit/branch focuses on a single plugin.",
            file=sys.stderr,
        )
        sys.exit(1)

    plugin = next(iter(touched_plugins))
    print(f"Single-plugin check passed for '{plugin}'.")


if __name__ == "__main__":
    main()
