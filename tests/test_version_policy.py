from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from scripts.bump_version import bump_version
from scripts.version_policy import (
    ReleasePolicy,
    VersionPolicyError,
    validate_plugin_version,
)

ROOT = Path(__file__).resolve().parents[1]
BUMP_SCRIPT = ROOT / "scripts" / "bump_version.py"
VALIDATE_SCRIPT = ROOT / "scripts" / "validate_versions.py"


def write_policy(workspace: Path, *stable_plugins: str) -> Path:
    values = ", ".join(f'"{name}"' for name in stable_plugins)
    policy = workspace / "release-policy.toml"
    policy.write_text(
        f"schema_version = 1\nstable_plugins = [{values}]\n",
        encoding="utf-8",
    )
    return policy


def write_plugin(workspace: Path, name: str, version: str) -> Path:
    plugin_dir = workspace / "plugins" / name
    plugin_dir.mkdir(parents=True)
    pyproject = plugin_dir / "pyproject.toml"
    pyproject.write_text(
        f'[project]\nname = "beets-{name}"\nversion = "{version}"\n',
        encoding="utf-8",
    )
    return pyproject


def run_script(script: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(script), *args],
        check=False,
        capture_output=True,
        text=True,
    )


class VersionPolicyTest(unittest.TestCase):
    def test_protected_plugin_accepts_zero_major_versions(self) -> None:
        policy = ReleasePolicy(frozenset())

        self.assertEqual(
            str(validate_plugin_version("demo", "0.1.0", policy)),
            "0.1.0",
        )
        self.assertEqual(
            str(validate_plugin_version("demo", "0.2.0-rc.1", policy)),
            "0.2.0-rc.1",
        )

    def test_protected_plugin_rejects_stable_version(self) -> None:
        with self.assertRaisesRegex(VersionPolicyError, "0.x.y guardrail"):
            validate_plugin_version("demo", "1.0.0", ReleasePolicy(frozenset()))

    def test_stable_registry_exempts_plugin(self) -> None:
        policy = ReleasePolicy(frozenset({"demo"}))

        self.assertEqual(
            str(validate_plugin_version("demo", "1.0.0", policy)),
            "1.0.0",
        )

    def test_bump_supports_all_semver_components(self) -> None:
        self.assertEqual(bump_version("0.9.9", "patch"), "0.9.10")
        self.assertEqual(bump_version("0.9.9", "minor"), "0.10.0")
        self.assertEqual(bump_version("0.9.9", "major"), "1.0.0")
        with self.assertRaisesRegex(ValueError, "Unsupported"):
            bump_version("0.9.9", "invalid")

    def test_workspace_validator_rejects_unregistered_stable_version(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            workspace = Path(temporary_directory)
            write_policy(workspace)
            write_plugin(workspace, "demo", "1.0.0")

            result = run_script(
                VALIDATE_SCRIPT,
                "--workspace-root",
                str(workspace),
            )

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("demo", result.stderr)
        self.assertIn("0.x.y guardrail", result.stderr)

    def test_workspace_validator_reports_stable_plugin_for_publish(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            workspace = Path(temporary_directory)
            write_policy(workspace, "demo")
            write_plugin(workspace, "demo", "1.0.0")
            github_output = workspace / "github-output.txt"

            result = run_script(
                VALIDATE_SCRIPT,
                "--workspace-root",
                str(workspace),
                "--plugin",
                "demo",
                "--github-output",
                str(github_output),
            )
            outputs = github_output.read_text(encoding="utf-8")

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("demo 1.0.0", result.stdout)
        self.assertIn("plugin_name=demo", outputs)
        self.assertIn("version=1.0.0", outputs)
        self.assertIn("stable=true", outputs)

    def test_workspace_validator_rejects_unknown_registry_entry(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            workspace = Path(temporary_directory)
            (workspace / "plugins").mkdir()
            write_policy(workspace, "missing")

            result = run_script(
                VALIDATE_SCRIPT,
                "--workspace-root",
                str(workspace),
            )

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("unknown stable plugins: missing", result.stderr)

    def test_workspace_validator_allows_empty_scaffold(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            workspace = Path(temporary_directory)
            (workspace / "plugins").mkdir()
            write_policy(workspace)

            result = run_script(
                VALIDATE_SCRIPT,
                "--workspace-root",
                str(workspace),
            )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("No plugin packages found", result.stdout)

    def test_bump_script_rejects_protected_major_without_writing(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            workspace = Path(temporary_directory)
            write_policy(workspace)
            pyproject = write_plugin(workspace, "demo", "0.9.9")

            result = run_script(
                BUMP_SCRIPT,
                "--workspace-root",
                str(workspace),
                "--plugin",
                "demo",
                "--part",
                "major",
            )
            content = pyproject.read_text(encoding="utf-8")

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("0.x.y guardrail", result.stderr)
        self.assertIn('version = "0.9.9"', content)

    def test_bump_script_promotes_registered_plugin(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            workspace = Path(temporary_directory)
            write_policy(workspace, "demo")
            pyproject = write_plugin(workspace, "demo", "0.9.9")

            result = run_script(
                BUMP_SCRIPT,
                "--workspace-root",
                str(workspace),
                "--plugin",
                "demo",
                "--part",
                "major",
            )
            content = pyproject.read_text(encoding="utf-8")

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Bumped demo from 0.9.9 to 1.0.0", result.stdout)
        self.assertIn('version = "1.0.0"', content)


if __name__ == "__main__":
    unittest.main()
