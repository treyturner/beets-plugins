"""Shared policy for independently versioned plugin releases."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import cast

from semver import VersionInfo

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover
    import tomli as tomllib  # type: ignore

POLICY_SCHEMA_VERSION = 1


class VersionPolicyError(ValueError):
    """Raised when release policy or a package version is invalid."""


@dataclass(frozen=True)
class ReleasePolicy:
    """The plugins allowed to publish stable versions."""

    stable_plugins: frozenset[str]

    def is_stable(self, plugin_name: str) -> bool:
        return plugin_name in self.stable_plugins


def load_release_policy(policy_path: Path) -> ReleasePolicy:
    try:
        with policy_path.open("rb") as handle:
            data = tomllib.load(handle)
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise VersionPolicyError(
            f"unable to load release policy {policy_path}: {exc}"
        ) from exc

    schema_version = data.get("schema_version")
    if schema_version != POLICY_SCHEMA_VERSION:
        raise VersionPolicyError(
            f"{policy_path} has unsupported schema_version {schema_version!r}; "
            f"expected {POLICY_SCHEMA_VERSION}"
        )

    raw_stable_plugins = data.get("stable_plugins")
    if not isinstance(raw_stable_plugins, list) or not all(
        isinstance(name, str) and name for name in raw_stable_plugins
    ):
        raise VersionPolicyError(
            f"{policy_path} stable_plugins must be a list of non-empty strings"
        )

    stable_plugins = cast(list[str], raw_stable_plugins)
    if len(stable_plugins) != len(set(stable_plugins)):
        raise VersionPolicyError(
            f"{policy_path} stable_plugins contains duplicate plugin names"
        )

    return ReleasePolicy(frozenset(stable_plugins))


def validate_plugin_version(
    plugin_name: str,
    version: str,
    policy: ReleasePolicy,
) -> VersionInfo:
    try:
        parsed = VersionInfo.parse(version)
    except ValueError as exc:
        raise VersionPolicyError(
            f"invalid semantic version '{version}': {exc}"
        ) from exc

    if parsed.major != 0 and not policy.is_stable(plugin_name):
        raise VersionPolicyError(
            f"plugin '{plugin_name}' version {parsed} is protected by the 0.x.y "
            "guardrail; add its directory name to release-policy.toml "
            "stable_plugins before publishing a stable release"
        )
    return parsed
