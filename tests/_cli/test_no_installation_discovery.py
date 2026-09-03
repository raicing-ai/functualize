"""AC9f — nothing learns about *other* installations by looking for them.

The registry is voluntary: an installation appears in `install.json` because it
ran and recorded itself. Discovery was measured and rejected -- executing five
installations to read their versions costs ~2.1 s serial, and a filesystem walk
looking for repositories has no honest root, against a ~39 us file read.

This is asserted structurally rather than by review, because the tempting
"improvement" is small and local: one `shutil.which` loop in `self doctor` and
the property is gone, with every other test still green.

**Three things here are deliberately *not* discovery**, and the distinction is
the whole content of this file:

- resolving `uv` or `pipx` on `PATH` -- that is finding the *package manager*
  this mode's commands are built from, not finding another functualize;
- `iterdir()` over the running interpreter's own site directories -- that is
  the update capture reading the environment it is about to rebuild;
- `subprocess` -- running the command the user confirmed, or re-running *this*
  CLI as a boot probe. Neither interrogates another binary.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

_SUBSYSTEM = (
    "runtime.py",
    "manifest.py",
    "package_ops.py",
    "self_cmd.py",
    "plugin_cmd.py",
)

_SRC = Path(__file__).resolve().parents[2] / "src" / "functualize" / "_cli"

#: Calls that would be discovery wherever they appeared in this subsystem.
#: `which` is absent on purpose -- see the module docstring.
_FORBIDDEN = {
    "walk",  # os.walk: a filesystem crawl for installations
    "glob",  # Path.glob / glob.glob over anything but the owned env
    "rglob",
    "listdir",
}


@pytest.fixture(scope="module")
def trees() -> dict[str, ast.Module]:
    return {
        name: ast.parse((_SRC / name).read_text(encoding="utf-8"))
        for name in _SUBSYSTEM
    }


def _called_names(tree: ast.Module) -> set[str]:
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            func = node.func
            if isinstance(func, ast.Attribute):
                found.add(func.attr)
            elif isinstance(func, ast.Name):
                found.add(func.id)
    return found


class TestNothingCrawlsTheFilesystem:
    @pytest.mark.parametrize("name", _SUBSYSTEM)
    def test_no_forbidden_call(self, trees, name: str) -> None:
        offenders = _called_names(trees[name]) & _FORBIDDEN
        assert not offenders, (
            f"{name} calls {sorted(offenders)}. Learning about installations by "
            f"crawling the filesystem is what the voluntary registry replaces."
        )

    def test_the_check_can_actually_fail(self) -> None:
        """The guard against a vacuous structural test.

        A parse-and-compare that never matched anything would pass this whole
        file no matter what the modules did.
        """
        tree = ast.parse("import os\nos.walk('/')\n")
        assert _called_names(tree) & _FORBIDDEN == {"walk"}


class TestPathIsConsultedOnlyForAPackageManager:
    def test_which_is_called_only_from_the_two_resolvers(self) -> None:
        """`shutil.which` is legitimate for finding uv and pipx and for nothing
        else. Confined to two named functions so a third use has to be a
        deliberate edit to this test."""
        tree = ast.parse((_SRC / "package_ops.py").read_text(encoding="utf-8"))
        holders = {
            node.name
            for node in ast.walk(tree)
            if isinstance(node, ast.FunctionDef)
            and "which" in _called_names(ast.Module(body=node.body, type_ignores=[]))
        }
        assert holders == {"resolve_uv", "resolve_pipx"}

    @pytest.mark.parametrize(
        "name", ["runtime.py", "manifest.py", "self_cmd.py", "plugin_cmd.py"]
    )
    def test_no_other_module_touches_path(self, trees, name: str) -> None:
        assert "which" not in _called_names(trees[name])


class TestTheRegistryIsReadNeverDerived:
    def test_manifest_spawns_nothing(self, trees) -> None:
        """Executing another installation to read its version is the 2.1 s
        approach this design exists to avoid."""
        called = _called_names(trees["manifest.py"])
        assert not called & {"run", "call", "Popen", "check_output"}

    def test_manifest_imports_no_subprocess(self) -> None:
        source = (_SRC / "manifest.py").read_text(encoding="utf-8")
        assert "import subprocess" not in source

    def test_runtime_detection_spawns_nothing(self) -> None:
        """Detection answers from `sys.prefix`, the environment and metadata.
        A subprocess here would put a process spawn on the path of every
        command that reports its own install mode."""
        source = (_SRC / "runtime.py").read_text(encoding="utf-8")
        assert "subprocess" not in source
