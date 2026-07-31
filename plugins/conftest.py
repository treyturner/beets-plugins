from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType

_ROOT = Path(__file__).resolve().parents[1]
_ROOT_CONF = _ROOT / "conftest.py"

_SPEC = importlib.util.spec_from_file_location("_workspace_conftest", _ROOT_CONF)
if _SPEC is None or _SPEC.loader is None:
    raise ImportError(f"Unable to load root conftest at {_ROOT_CONF}")
_MODULE = importlib.util.module_from_spec(_SPEC)
assert isinstance(_MODULE, ModuleType)
_SPEC.loader.exec_module(_MODULE)


def pytest_configure() -> None:
    if hasattr(_MODULE, "pytest_configure"):
        _MODULE.pytest_configure()
