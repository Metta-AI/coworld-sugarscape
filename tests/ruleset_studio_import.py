"""Load the hyphenated Ruleset Studio server module for focused tests."""

from __future__ import annotations

import importlib.util
from pathlib import Path
import sys
from types import ModuleType


def load_studio_server(path: Path) -> ModuleType:
    spec = importlib.util.spec_from_file_location("ruleset_studio_server", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module
