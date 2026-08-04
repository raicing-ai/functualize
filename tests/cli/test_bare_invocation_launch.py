"""C3.3 — bare-invocation shell launch for a self-contained CliAdapter app.

The load-bearing constraint is the one the AC states last: **func's own
behavior is unchanged externally**. `func`'s bare path is handled pre-boot in
`_cli/main.py::_handle_bare` and never reaches the adapter callback, so this is
additive for project apps rather than a change to func.
"""

from __future__ import annotations

import click
import pytest

from functualize.app.adapters import cli as cli_mod


@pytest.fixture
def tty(monkeypatch: pytest.MonkeyPatch) -> None:
    """Pretend we own a terminal.

    Patches the `_bare_tty_available` predicate rather than `sys.stdin`/
    `sys.stdout`: these tests are about the *branch*, and binding them to
    global stream state made them order-dependent — another module's fixture
    leaving a replaced stream behind flipped the answer. `_bare_tty_available`
    itself is covered directly in `TestTtyProbe`.
    """
    monkeypatch.setattr(cli_mod, "_bare_tty_available", lambda: True)


class _Ctx:
    """The narrow slice of click.Context that `_handle_bare_invocation` uses."""

    def __init__(self) -> None:
        self.helped = False
        self.exited_with: int | None = None

    def get_help(self) -> str:
        self.helped = True
        return "USAGE: myapp [OPTIONS] COMMAND"

    def exit(self, code: int = 0) -> None:
        self.exited_with = code
        raise click.exceptions.Exit(code)


def _run(ctx: _Ctx, app: object = None) -> None:
    with pytest.raises(click.exceptions.Exit):
        cli_mod._handle_bare_invocation(ctx, app)  # type: ignore[arg-type]


class TestSettingResolution:
    def test_enabled_by_default(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """A project app gets the shell without configuring anything."""
        monkeypatch.setattr(
            "functualize._cli.data.func_settings.FuncSettingsStore.discover",
            classmethod(
                lambda cls: type("S", (), {"effective_values": lambda s: {}})()
            ),
        )
        assert cli_mod._inline_tui_enabled() is True

    @pytest.mark.parametrize("value", ["false", "False", "0", "no", "off"])
    def test_opt_out_spellings(
        self, monkeypatch: pytest.MonkeyPatch, value: str
    ) -> None:
        monkeypatch.setattr(
            "functualize._cli.data.func_settings.FuncSettingsStore.discover",
            classmethod(
                lambda cls: type(
                    "S", (), {"effective_values": lambda s: {"cli.inline_tui": value}}
                )()
            ),
        )
        assert cli_mod._inline_tui_enabled() is False

    def test_unreadable_config_still_enables(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A broken config file must not silently disable the shell."""

        def _boom(cls: object) -> None:
            raise OSError("unreadable")

        monkeypatch.setattr(
            "functualize._cli.data.func_settings.FuncSettingsStore.discover",
            classmethod(_boom),
        )
        assert cli_mod._inline_tui_enabled() is True


class TestBareBranch:
    def test_tty_and_enabled_launches_the_shell(
        self, tty: None, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(cli_mod, "_inline_tui_enabled", lambda: True)
        launched: list[object] = []
        monkeypatch.setattr(
            cli_mod, "_launch_shell", lambda app: (launched.append(app), 7)[1]
        )

        ctx = _Ctx()
        sentinel = object()
        _run(ctx, sentinel)

        assert launched == [sentinel]
        assert ctx.exited_with == 7, "the shell's exit code must propagate"
        assert not ctx.helped

    def test_opt_out_prints_help_even_at_a_tty(
        self, tty: None, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Otherwise it would not be an opt-out."""
        monkeypatch.setattr(cli_mod, "_inline_tui_enabled", lambda: False)
        monkeypatch.setattr(
            cli_mod,
            "_launch_shell",
            lambda app: pytest.fail("must not launch when opted out"),
        )

        ctx = _Ctx()
        _run(ctx)

        assert ctx.helped
        assert ctx.exited_with == 0

    def test_non_tty_prints_help(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """No terminal to hand a shell; a piped run wants something parseable."""
        monkeypatch.setattr(cli_mod, "_bare_tty_available", lambda: False)
        monkeypatch.setattr(cli_mod, "_inline_tui_enabled", lambda: True)

        ctx = _Ctx()
        _run(ctx)

        assert ctx.helped
        assert ctx.exited_with == 0

    def test_the_setting_is_checked_before_the_tty(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Opting out must not depend on having a terminal to opt out from."""
        monkeypatch.setattr(cli_mod, "_bare_tty_available", lambda: False)
        calls: list[str] = []
        monkeypatch.setattr(
            cli_mod, "_inline_tui_enabled", lambda: (calls.append("setting"), False)[1]
        )

        ctx = _Ctx()
        _run(ctx)
        assert calls == ["setting"]


class TestFuncItselfIsUnchanged:
    def test_the_setting_exists_in_the_catalog(self) -> None:
        from functualize._cli.data.func_settings import DEFAULT_VALUES, SETTINGS_ORDER

        assert "cli.inline_tui" in SETTINGS_ORDER
        assert DEFAULT_VALUES["cli.inline_tui"] == "true"

    def test_it_is_a_recognized_config_key(self) -> None:
        from functualize._cli.config import _RECOGNIZED_KEYS

        assert "inline_tui" in _RECOGNIZED_KEYS["cli"]

    def test_funcs_bare_path_does_not_route_through_the_adapter(self) -> None:
        """`func` handles bare invocation pre-boot, in `main.py::_handle_bare`.

        Asserted so the "unchanged externally" claim rests on the code rather
        than on nobody having noticed a difference.
        """
        import inspect

        from functualize._cli import main

        assert hasattr(main, "_handle_bare")
        source = inspect.getsource(main._handle_bare)
        assert "launch_inline_tui" in source


class TestTtyProbe:
    """`_bare_tty_available` itself — the piece the branch tests stub out."""

    def test_true_when_both_streams_are_ttys(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import sys

        monkeypatch.setattr(sys.stdin, "isatty", lambda: True, raising=False)
        monkeypatch.setattr(sys.stdout, "isatty", lambda: True, raising=False)
        assert cli_mod._bare_tty_available() is True

    def test_false_when_stdin_is_not(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import sys

        monkeypatch.setattr(sys.stdin, "isatty", lambda: False, raising=False)
        monkeypatch.setattr(sys.stdout, "isatty", lambda: True, raising=False)
        assert cli_mod._bare_tty_available() is False

    def test_a_stream_without_isatty_is_not_a_tty(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Some hosts replace the streams with objects that are not file-like."""
        import sys

        monkeypatch.setattr(sys, "stdin", object())
        assert cli_mod._bare_tty_available() is False
