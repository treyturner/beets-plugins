#!/usr/bin/env python3
"""Enforce the workspace's initial-development version policy."""

from __future__ import annotations

import argparse
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from semver import VersionInfo

if __package__:
    from .version_policy import (
        ReleasePolicy,
        VersionPolicyError,
        load_release_policy,
        validate_plugin_version,
    )
else:  # pragma: no cover - exercised by subprocess tests
    from version_policy import (  # type: ignore[import-not-found,no-redef]
        ReleasePolicy,
        VersionPolicyError,
        load_release_policy,
        validate_plugin_version,
    )

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover
    import tomli as tomllib  # type: ignore


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--workspace-root",
        default=Path(__file__).resolve().parents[1],
        type=Path,
        help="Workspace root path",
    )
    parser.add_argument(
        "--plugins-dir",
        default="plugins",
        help="Directory containing independently versioned plugins",
    )
    parser.add_argument(
        "--policy-file",
        default="release-policy.toml",
        help="Release policy path relative to the workspace root",
    )
    parser.add_argument(
        "--plugin",
        action="append",
        default=[],
        help="Validate one plugin directory name; repeat to validate several",
    )
    parser.add_argument(
        "--github-output",
        type=Path,
        help="Optional path for writing single-plugin GitHub Actions outputs",
    )
    return parser.parse_args()


def load_version(pyproject_path: Path) -> str:
    with pyproject_path.open("rb") as handle:
        data = tomllib.load(handle)
    project = data.get("project", {})
    version = project.get("version")
    if not isinstance(version, str) or not version:
        raise VersionPolicyError(
            f"unable to read [project].version from {pyproject_path}"
        )
    return version


def plugin_pyprojects(
    workspace_root: Path,
    plugins_dir: str,
    plugin_names: Sequence[str],
) -> list[Path]:
    plugins_path = workspace_root / plugins_dir
    if not plugins_path.is_dir():
        raise VersionPolicyError(f"plugins directory not found: {plugins_path}")

    if plugin_names:
        pyprojects = [plugins_path / name / "pyproject.toml" for name in plugin_names]
        missing = [path for path in pyprojects if not path.is_file()]
        if missing:
            paths = ", ".join(str(path) for path in missing)
            raise VersionPolicyError(f"plugin pyproject not found: {paths}")
        return pyprojects

    return sorted(plugins_path.glob("*/pyproject.toml"))


def validate_plugin_pyprojects(
    pyprojects: Sequence[Path],
    policy: ReleasePolicy,
) -> list[tuple[Path, VersionInfo]]:
    validated = []
    errors = []
    for pyproject in pyprojects:
        try:
            version = load_version(pyproject)
            parsed = validate_plugin_version(pyproject.parent.name, version, policy)
        except (OSError, tomllib.TOMLDecodeError, VersionPolicyError) as exc:
            errors.append(f"{pyproject}: {exc}")
            continue
        validated.append((pyproject, parsed))

    if errors:
        raise VersionPolicyError("\n".join(errors))
    return validated


def write_github_output(
    validated: Sequence[tuple[Path, VersionInfo]],
    policy: ReleasePolicy,
    destination: Path | None,
) -> None:
    if destination is None:
        return
    if len(validated) != 1:
        raise VersionPolicyError("GitHub output requires exactly one validated plugin")

    pyproject, version = validated[0]
    plugin_name = pyproject.parent.name
    outputs: dict[str, Any] = {
        "plugin_name": plugin_name,
        "version": version,
        "stable": str(policy.is_stable(plugin_name)).lower(),
    }
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open("a", encoding="utf-8") as handle:
        for key, value in outputs.items():
            handle.write(f"{key}={value}\n")


def main() -> None:
    args = parse_args()
    try:
        workspace_root = args.workspace_root.resolve()
        policy = load_release_policy(workspace_root / args.policy_file)
        pyprojects = plugin_pyprojects(
            workspace_root,
            args.plugins_dir,
            args.plugin,
        )
        available_plugins = {
            path.parent.name
            for path in plugin_pyprojects(workspace_root, args.plugins_dir, ())
        }
        unknown_stable_plugins = policy.stable_plugins - available_plugins
        if unknown_stable_plugins:
            names = ", ".join(sorted(unknown_stable_plugins))
            raise VersionPolicyError(
                f"release-policy.toml references unknown stable plugins: {names}"
            )
        validated = validate_plugin_pyprojects(pyprojects, policy)
        write_github_output(validated, policy, args.github_output)
    except VersionPolicyError as exc:
        raise SystemExit(f"Version policy check failed:\n{exc}") from exc

    if not validated:
        print("No plugin packages found; version policy check passed.")
        return

    for pyproject, version in validated:
        print(f"Version policy check passed: {pyproject.parent.name} {version}")


if __name__ == "__main__":
    main()
