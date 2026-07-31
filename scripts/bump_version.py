#!/usr/bin/env python3
"""Bump the semantic version for a plugin's pyproject."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any

from semver import VersionInfo

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover
    import tomli as tomllib  # type: ignore


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--plugin", required=True, help="Plugin directory name under plugins/"
    )
    parser.add_argument(
        "--workspace-root",
        default=Path(__file__).resolve().parents[1],
        type=Path,
        help="Workspace root path",
    )
    parser.add_argument(
        "--part",
        choices=("patch", "minor", "major"),
        default="patch",
        help="Which portion of the version to increment",
    )
    parser.add_argument(
        "--version",
        help="Explicit version to set instead of calculating a bump",
    )
    parser.add_argument(
        "--github-output",
        type=Path,
        help="Optional path for writing GitHub Actions outputs",
    )
    return parser.parse_args()


def load_version(pyproject_path: Path) -> str:
    with pyproject_path.open("rb") as handle:
        data = tomllib.load(handle)
    project = data.get("project", {})
    version = project.get("version")
    if not isinstance(version, str) or not version:
        raise SystemExit(f"Unable to read [project].version from {pyproject_path}")
    return version


def bump_version(version: str, part: str) -> str:
    parsed = VersionInfo.parse(version)
    if part == "major":
        return str(parsed.bump_major())
    if part == "minor":
        return str(parsed.bump_minor())
    return str(parsed.bump_patch())


def write_version(pyproject_path: Path, new_version: str) -> None:
    pattern = re.compile(r'(?m)^(version\s*=\s*")(?P<value>[^\"]+)(")')
    content = pyproject_path.read_text(encoding="utf-8")
    updated, count = pattern.subn(rf"\1{new_version}\3", content, count=1)
    if count != 1:
        raise SystemExit(f"Failed to update version line inside {pyproject_path}")
    pyproject_path.write_text(updated, encoding="utf-8")


def write_output(outputs: dict[str, Any], destination: Path | None) -> None:
    if destination is None:
        return
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open("a", encoding="utf-8") as handle:
        for key, value in outputs.items():
            handle.write(f"{key}={value}\n")


def main() -> None:
    args = parse_args()
    plugin_dir = args.workspace_root / "plugins" / args.plugin
    pyproject = plugin_dir / "pyproject.toml"
    if not pyproject.exists():
        raise SystemExit(f"Plugin pyproject not found: {pyproject}")

    current_version = load_version(pyproject)
    if args.version:
        try:
            new_version = str(VersionInfo.parse(args.version))
        except ValueError as exc:  # pragma: no cover - invalid user input
            raise SystemExit(f"Invalid version '{args.version}': {exc}") from exc
    else:
        new_version = bump_version(current_version, args.part)

    if current_version == new_version:
        print(f"Version unchanged: {current_version}")
    else:
        write_version(pyproject, new_version)
        print(f"Bumped {args.plugin} from {current_version} to {new_version}")

    outputs = {
        "plugin": args.plugin,
        "previous_version": current_version,
        "new_version": new_version,
    }
    write_output(outputs, args.github_output)
    print(json.dumps(outputs))


if __name__ == "__main__":
    main()
