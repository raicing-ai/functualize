"""Load the repository's reference router as a module, not as a package.

The example lives outside the installed package and outside this test
package, so it is loaded by path. The module is registered in ``sys.modules``
under a private name before its body executes — the decorators inside it
resolve the workflow registry by module identity — and reused on later calls,
so every cell boots the same module object. The example file itself is never
modified.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

__all__ = ["load_router"]

#: ``tests/hermetic_eval/_router.py`` → the repository root.
_REPO_ROOT = Path(__file__).resolve().parents[2]
_MODULE_NAME = "hermetic_router_reference"
_ROUTER_PATH = _REPO_ROOT / "examples" / "standalone" / "hermetic_router" / "router.py"


def load_router() -> ModuleType:
    """Return the reference router module, importing it once per process."""
    loaded = sys.modules.get(_MODULE_NAME)
    if loaded is not None:
        return loaded
    spec = importlib.util.spec_from_file_location(_MODULE_NAME, _ROUTER_PATH)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load the reference router from {_ROUTER_PATH}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[_MODULE_NAME] = module
    spec.loader.exec_module(module)
    return module
