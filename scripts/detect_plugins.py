#!/usr/bin/env python3
"""Detect which plugin(s) are affected by a set of file paths."""

from __future__ import annotations

import argparse
import json
import os
from collections.abc import Iterable, Sequence
from pathlib import Path
from typing import Any

try:  # Python 3.11+
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - fallback for older interpreters
    import tomli as tomllib  # type: ignore


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--plugins-dir",
        default="plugins",
        help="Path (relative to the workspace root) that contains plugin packages",
    )
    parser.add_argument(
        "--workspace-root",
        default=Path(__file__).resolve().parents[1],
        type=Path,
    )
    parser.add_argument(
        "--files",
        nargs="*",
        default=(),
        help="Explicit file paths to inspect",
    )
    parser.add_argument(
        "--files-from",
        type=Path,
        help="Read newline-delimited file paths from the given file",
    )
    parser.add_argument(
        "--plugin",
        dest="manual_plugin",
        help="Manually specify the plugin to process (comma separated for several)",
    )
    parser.add_argument(
        "--default",
        dest="default_plugin",
        help=(
            "Fallback plugin to use when no files resolve "
            "(use 'all' to target the entire workspace)"
        ),
    )
    parser.add_argument(
        "--allow-multiple",
        action="store_true",
        help="Allow more than one plugin to be selected",
    )
    parser.add_argument(
        "--allow-empty",
        action="store_true",
        help="Exit successfully when no plugin can be determined",
    )
    parser.add_argument(
        "--github-output",
        type=Path,
        help="Optional path for writing GitHub Actions outputs",
    )
    return parser.parse_args()


def load_plugins(workspace_root: Path, plugins_dir: str) -> dict[str, dict[str, str]]:
    plugins_path = (workspace_root / plugins_dir).resolve()
    if not plugins_path.exists():
        raise SystemExit(f"Plugins directory not found: {plugins_path}")

    mapping: dict[str, dict[str, str]] = {}
    for child in sorted(plugins_path.iterdir()):
        if not child.is_dir():
            continue
        pyproject = child / "pyproject.toml"
        if not pyproject.exists():
            continue
        with pyproject.open("rb") as handle:
            data = tomllib.load(handle)
        project = data.get("project", {})
        name = project.get("name")
        if not name:
            continue
        mapping[child.name] = {
            "directory": str(child.relative_to(workspace_root)).replace("\\", "/"),
            "package": name,
        }
    return mapping


def normalize_paths(files: Iterable[str]) -> list[str]:
    normalized: list[str] = []
    for entry in files:
        clean = entry.strip()
        if not clean:
            continue
        clean = clean.replace("\\", "/")
        clean = clean.removeprefix("./")
        normalized.append(clean)
    return normalized


def read_files_from(path: Path | None) -> Sequence[str]:
    if path is None or not path.is_file():
        return []
    content = path.read_text().splitlines()
    return tuple(content)


def resolve_manual_plugins(arg_value: str | None) -> list[str]:
    manual_value = arg_value or os.getenv("PLUGIN_NAME") or os.getenv("PLUGIN")
    if not manual_value:
        return []
    return [
        chunk.strip()
        for chunk in manual_value.replace(";", ",").split(",")
        if chunk.strip()
    ]


def write_github_output(outputs: dict[str, Any], destination: Path | None) -> None:
    if destination is None:
        return
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open("a", encoding="utf-8") as handle:
        for key, value in outputs.items():
            handle.write(f"{key}={value}\n")


def main() -> None:
    args = parse_args()
    workspace_root = args.workspace_root.resolve()
    plugins = load_plugins(workspace_root, args.plugins_dir)

    files: list[str] = []
    files.extend(normalize_paths(args.files))
    files.extend(normalize_paths(read_files_from(args.files_from)))

    selected: list[str] = []

    manual_plugins = resolve_manual_plugins(args.manual_plugin)
    if manual_plugins:
        selected.extend(manual_plugins)

    if not selected:
        detected = set()
        prefix = args.plugins_dir.strip("/") + "/"
        for file_path in files:
            if not file_path.startswith(prefix):
                continue
            parts = file_path[len(prefix) :].split("/", 1)
            if not parts:
                continue
            candidate = parts[0]
            if candidate in plugins:
                detected.add(candidate)
        selected.extend(sorted(detected))

    if not selected and args.default_plugin:
        if args.default_plugin.lower() == "all":
            selected.extend(sorted(plugins))
        else:
            selected.append(args.default_plugin)

    if not selected:
        if args.allow_empty:
            empty_outputs: dict[str, Any] = {
                "plugin_count": "0",
                "plugin_names": "",
                "plugin_matrix": "[]",
            }
            summary = {
                "selected": [],
                "available": sorted(plugins),
                "files": files,
            }
            print(json.dumps(summary, indent=2))
            write_github_output(empty_outputs, args.github_output)
            return
        raise SystemExit(
            "Unable to determine plugin. Provide --plugin, set PLUGIN_NAME, "
            "or ensure files are inside plugins/<name>."
        )

    unique_selected = []
    seen = set()
    for name in selected:
        key = name.lower()
        if key in seen:
            continue
        seen.add(key)
        if name not in plugins:
            raise SystemExit(
                f"Unknown plugin '{name}'. Available: {', '.join(sorted(plugins))}."
            )
        unique_selected.append(name)

    if not args.allow_multiple and len(unique_selected) > 1:
        raise SystemExit(
            "Multiple plugins detected. Rerun with --allow-multiple "
            "or specify --plugin to pick one."
        )

    outputs: dict[str, Any] = {
        "plugin_count": str(len(unique_selected)),
        "plugin_names": ",".join(unique_selected),
        "plugin_matrix": json.dumps(unique_selected),
    }

    if len(unique_selected) == 1:
        name = unique_selected[0]
        outputs.update(
            {
                "plugin_name": name,
                "plugin_path": plugins[name]["directory"],
                "package_name": plugins[name]["package"],
            }
        )
    else:
        paths = [plugins[name]["directory"] for name in unique_selected]
        packages = [plugins[name]["package"] for name in unique_selected]
        outputs.update(
            {
                "plugin_paths": ",".join(paths),
                "package_names": ",".join(packages),
            }
        )

    summary = {
        "selected": unique_selected,
        "available": sorted(plugins),
        "files": files,
    }
    print(json.dumps(summary, indent=2))
    write_github_output(outputs, args.github_output)


if __name__ == "__main__":
    main()
