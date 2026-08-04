# Beets Plugins Workspace

This repository is a uv-managed Python monorepo for custom [Beets](https://beets.io/) plugins. It currently contains:

- **tidalv1** – TIDAL v1 sources for the built-in lyrics and fetchart plugins.
- **nohirescd** – import filtering and library audits for high-resolution audio matched to CD releases.

Both plugins support Python 3.10–3.14. Each plugin is independently versioned and packaged from its own directory under `plugins/`.

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

cd plugins/tidalv1
uv sync                               # install plugin deps + dev tools
pre-commit install
uv run pytest
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
- **Publish** – manually builds, publishes, and tags the selected plugin's committed version through PyPI Trusted Publishing.

See `.github/workflows/` for exact behavior, including automatic plugin detection via `scripts/detect_plugins.py`.

## Version policy

Plugins are protected on the SemVer initial-development line (`0.x.y`) by default. The reviewed exemption registry is [`release-policy.toml`](release-policy.toml): a plugin may use `1.x` or later only when its directory name appears in `stable_plugins`. Shared CI validates the registry and every plugin version, and the build, release, and manual publish workflows validate the selected plugin again before producing or uploading a distribution.

To promote a plugin to a stable API:

1. Add its `plugins/<name>` directory name to `stable_plugins` in `release-policy.toml` through normal review and merge that policy change.
2. Run the manual **Versioning** workflow for that plugin with a `major` increment. The policy-aware bump creates `1.0.0` and commits it with `[skip release]`, preventing the automatic release workflow from applying another patch increment.
3. Run the manual **Publish** workflow for that plugin. It validates and builds the exact committed version, publishes it through PyPI Trusted Publishing, and creates the `<plugin>-vX.Y.Z` tag.

After promotion, normal merges use the same automatic patch-release process without the `0.x.y` restriction. Removing a stable exemption while the plugin has a `1.x` or later version fails validation.

Conventional Commit labels do not select a version increment in this repository. `feat`, `fix`, `!`, and `BREAKING CHANGE` have no special release effect: automatic releases always apply a patch increment. The `[skip release]` marker is the only commit-message control and suppresses the automatic release workflow.

## Contribution guidelines

1. Inside the plugin you're touching, run `uv sync --group dev` and `pre-commit install` to enable the plugin-local hooks (ruff format/check and mypy). Run coverage per plugin with `uv run pytest --cov=plugins/<name> --cov-report=term-missing`.
2. Keep feature branches focused on a single plugin so the release automation can confidently bump its version.
3. Merges to `main` automatically trigger the `release` workflow, which bumps the plugin version (patch by default) using the Python `semver` library, publishes to PyPI via trusted publishing, and pushes a `[skip release]` commit plus a `<plugin>-vX.Y.Z` tag. No manual intervention is needed unless the automation is bypassed.
