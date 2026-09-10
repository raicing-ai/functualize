"""`app/adapters/` reaches the kernel through the public corridor, never directly.

Spec AC-1, AC-2. The adapters are the app's *boundary*: they translate what a
user typed into a request and a result into an exit code. Reaching into
`_engine/` to do it makes the boundary a participant, and it is how the same
question ends up answered in two places with two answers — which is exactly what
the TTY pre-flight had become (see `TestOneTerminalRoute` below).

This is a **structural** test. `lint-imports` cannot catch it: `app` and
`_engine` are not peers under the six contracts, so an `app → _engine` import is
legal to the linter and wrong to the architecture.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

_ADAPTERS = (
    Path(__file__).resolve().parents[2] / "src" / "functualize" / "app" / "adapters"
)
_DIRECT_IMPORT = re.compile(r"^\s*(?:from|import)\s+functualize\._engine\b", re.M)


def _adapter_files() -> list[Path]:
    files = sorted(_ADAPTERS.glob("*.py"))
    assert files, f"no adapter modules found under {_ADAPTERS}"
    return files


class TestNoAdapterImportsTheEngine:
    @pytest.mark.parametrize("path", _adapter_files(), ids=lambda p: p.name)
    def test_it_uses_the_public_corridor(self, path: Path) -> None:
        hits = _DIRECT_IMPORT.findall(path.read_text())

        assert not hits, (
            f"{path.name} imports `functualize._engine` directly. The corridor is "
            f"`functualize.types` for types and errors, `functualize.app.utils` "
            f"for behaviour probes; add it there rather than reaching past it."
        )

    def test_the_corridor_actually_carries_what_they_need(self) -> None:
        """The counterpart. Removing the imports is only half the job — if the
        corridor does not publish these, the next author reaches past it again."""
        from functualize.app.utils import has_eligible_ambient, terminal_available
        from functualize.types import MissingValueError

        assert callable(terminal_available)
        assert callable(has_eligible_ambient)
        assert issubclass(MissingValueError, Exception)


class TestOneTerminalRoute:
    """The duplication this task removed was not cosmetic.

    Both dispatch paths refused a `tty: TTY` job with the *same message* and
    **different exit codes** — the eager path raised
    `SystemExit(ExitCode.REFUSED)`, the lazy path called `sys.exit(1)`. So the
    identical refusal of the identical job reported differently depending on
    whether the discovery cache happened to be warm. `pitfalls.md` §23 is the
    scar from the last time these two paths disagreed.
    """

    def test_only_one_module_names_the_probe(self) -> None:
        naming = [
            p.name for p in _adapter_files() if "terminal_available" in p.read_text()
        ]

        assert naming == ["surface_gate.py"], (
            f"the TTY pre-flight is decided in {naming}; it must have one route"
        )

    def test_both_paths_refuse_with_the_same_code(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Asserted on the shared function, because there is now only one."""
        from functualize.app.adapters import surface_gate
        from functualize.types import ExitCode

        monkeypatch.setattr("functualize.app.utils.terminal_available", lambda: False)
        with pytest.raises(SystemExit) as exc:
            surface_gate.refuse_without_terminal("needs-a-tty")

        assert exc.value.code == ExitCode.REFUSED, (
            "a pre-flight refusal is REFUSED, not a generic 1 — nothing ran"
        )

    def test_a_real_terminal_does_not_refuse(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from functualize.app.adapters import surface_gate

        monkeypatch.setattr("functualize.app.utils.terminal_available", lambda: True)

        assert surface_gate.refuse_without_terminal("fine") is None
