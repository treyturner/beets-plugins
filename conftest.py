from __future__ import annotations

import os
import sys
from pathlib import Path

_CONFIGURED = False


def _load_root_env(root: Path) -> None:
    """Load key/value pairs from .env into the process environment."""

    env_path = root / ".env"
    if not env_path.exists():
        return

    for raw_line in env_path.read_text().splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip())


def pytest_configure() -> None:
    """Ensure each plugin's src directory is importable and .env is honored."""

    global _CONFIGURED
    if _CONFIGURED:
        return
    _CONFIGURED = True

    root = Path(__file__).parent
    _load_root_env(root)

    plugins_dir = root / "plugins"
    if not plugins_dir.exists():
        return

    for candidate in plugins_dir.iterdir():
        src = candidate / "src"
        if src.is_dir():
            sys.path.insert(0, str(src))
