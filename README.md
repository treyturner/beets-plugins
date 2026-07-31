# Beets Plugins Workspace

This repository is a uv-managed Python monorepo for custom [Beets](https://beets.io/) plugins. Each plugin is independently versioned and packaged from its own directory under `plugins/`.

## Tooling

- **uv** powers dependency management, locking, and virtual environments for each plugin.
- **pytest** drives the test suite across all plugins (with coverage enforced in CI).
- **mypy** enforces strict type-safety per plugin (`uv run mypy` inside that plugin).
- **ruff** formats and lints per plugin (`uv run ruff format --check .` and `uv run ruff check .` inside that plugin).
- **pre-commit** runs per plugin using the config in `plugins/<name>/.pre-commit-config.yaml`.
- **GitHub Actions** automate testing, building, releasing, and PyPI publishes.

## Quick start

```bash
uv sync --all-groups                  # install repository tooling
pre-commit install                    # repository-wide hooks
./scripts/sync_plugins.py             # sync every available plugin
```

Optionally sync every plugin from the repo root with `./scripts/sync_plugins.py`.

## Per-plugin virtual environments

Each plugin under `plugins/` owns its dependencies and lives in its own `.venv`:

```
cd plugins/<name>
uv sync --group dev
```

If you prefer automation, run `./scripts/sync_plugins.py` from the repo root to
sync one (or all) plugins in one shot.

When you open `plugins/<name>` in VS Code or Cursor, the bundled
`.vscode/settings.json` inside that folder points the interpreter at `./.venv`,
so all testing/linting runs against the plugin’s dependencies.
Repository-level tooling is only needed for shared scripts/workflows.

## Adding a new plugin

1. Create `plugins/<name>` with a `pyproject.toml` that declares the package, entry points, and dependencies.
2. Scaffold a `src/beetsplug/<name>/` package and tests under `plugins/<name>/tests`.
3. Add plugin-local tooling (`[dependency-groups].dev`, `[tool.mypy]`, `[tool.ruff]`, and `.pre-commit-config.yaml`) following the repository conventions.
4. Update helper scripts or workflows if the plugin introduces unique build or publish needs.

## Workflow overview

- **Test / Build** – ensure the impacted plugin(s) still lint, test, and package correctly.
- **Coverage** – on every PR, coverage is computed for both the base ref and the PR head and the build fails if coverage drops.
- **Versioning** – optional manual workflow to bump a plugin's version outside the automated flow.
- **Release** – runs on pushes to `main`, detects the touched plugin, bumps its version via `semver`, runs tests, builds, publishes to PyPI, and tags the release.
- **Publish** – manual trusted-publisher release if you need to re-publish an existing artifact.

See `.github/workflows/` for exact behavior, including automatic plugin detection via `scripts/detect_plugins.py`.

## Contribution guidelines

1. Inside the plugin you're touching, run `uv sync --group dev` and `pre-commit install` to enable the plugin-local hooks (ruff format/check and mypy). Run coverage per plugin with `uv run pytest --cov=plugins/<name> --cov-report=term-missing`.
2. Keep feature branches focused on a single plugin so the release automation can confidently bump its version.
3. Merges to `main` automatically trigger the `release` workflow, which bumps the plugin version (patch by default) using the Python `semver` library, publishes to PyPI via trusted publishing, and pushes a `[skip release]` commit plus a `<plugin>-vX.Y.Z` tag. No manual intervention is needed unless the automation is bypassed.
