#!/usr/bin/env python3
"""Create/synchronize per-plugin uv virtual environments."""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PLUGINS_DIR = ROOT / "plugins"


def _discover_plugins(names: list[str]) -> list[Path]:
    if not names:
        return sorted(
            p for p in PLUGINS_DIR.iterdir() if (p / "pyproject.toml").exists()
        )

    targets: list[Path] = []
    for raw in names:
        candidate = Path(raw)
        if not candidate.is_absolute():
            candidate = (ROOT / raw).resolve()
        if not (candidate / "pyproject.toml").exists():
            print(f"Skipping {candidate}: no pyproject.toml found", file=sys.stderr)
            continue
        targets.append(candidate)
    return targets


def _ensure_env(plugin: Path) -> bool:
    venv_dir = plugin / ".venv"
    if not venv_dir.exists():
        try:
            subprocess.run(["uv", "venv", ".venv"], cwd=plugin, check=True)
        except subprocess.CalledProcessError:
            return False

    try:
        subprocess.run(["uv", "sync"], cwd=plugin, check=True)
    except subprocess.CalledProcessError:
        return False
    return True


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Ensure each plugin directory under ./plugins has its own uv venv."
    )
    parser.add_argument(
        "plugins", nargs="*", help="Optional plugin directories to sync."
    )
    args = parser.parse_args()

    if not PLUGINS_DIR.exists():
        print(f"No plugins directory at {PLUGINS_DIR}", file=sys.stderr)
        return 1

    targets = _discover_plugins(args.plugins)
    if not targets:
        if args.plugins:
            print("No plugin directories found.", file=sys.stderr)
            return 1
        print("No plugin directories found; nothing to sync.")
        return 0

    status = 0
    for plugin in targets:
        print(f"==> {plugin.relative_to(ROOT)}")
        if not _ensure_env(plugin):
            status = 1
    return status


if __name__ == "__main__":
    raise SystemExit(main())
