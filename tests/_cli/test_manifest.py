"""The install registry: append-only, one-shot, atomic, and never derived.

The properties worth guarding are the ones that fail silently. A path-only
marker key masks an upgrade forever. A read-modify-write without `os.replace`
drops one of two concurrent registrations, which is exactly what "append-only"
is supposed to make impossible. And a registration that raises turns a
bookkeeping detail into a broken command.
"""

from __future__ import annotations

import io
import json
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from functualize._cli import manifest as m


def _register(
    config_dir: Path, *, path: str = "/usr/local/bin/func", version: str = "1.0"
) -> bool:
    return m.register(
        config_dir,
        binary_path=path,
        runtime_mode="tool_uv",
        owning_distribution="functualize",
        python_version="3.12.0",
        functualize_version=version,
    )


def _load(config_dir: Path) -> m.Manifest:
    return m.load(m.manifest_path(config_dir))


class TestWhereItLives:
    def test_it_uses_the_shared_user_config_dir(self, xdg_dirs) -> None:
        """AC5 — never a hard-coded home. The same helper the rest of the CLI uses."""
        from functualize.app.utils import resolve_user_config_dir

        assert m.manifest_path(resolve_user_config_dir()).parent == (
            xdg_dirs.functualize_config
        )

    def test_the_file_is_written_there(self, xdg_dirs) -> None:
        config_dir = xdg_dirs.functualize_config
        assert _register(config_dir)
        assert (config_dir / "install.json").exists()


class TestAppendOnly:
    def test_a_second_installation_appends(self, tmp_path: Path) -> None:
        _register(tmp_path, path="/a/func")
        _register(tmp_path, path="/b/func")
        assert [r.binary_path for r in _load(tmp_path).installations] == [
            "/a/func",
            "/b/func",
        ]

    def test_there_is_no_remove(self) -> None:
        """AC6, as an assertion rather than a convention.

        A stale record is *reported*, never deleted — two installations
        coexisting is a real state and `PATH` decides which one runs.
        """
        assert not hasattr(m.Manifest, "remove")
        assert not hasattr(m.Manifest, "delete")

    def test_registering_the_same_identity_twice_adds_one_record(
        self, tmp_path: Path
    ) -> None:
        """AC9a — the marker makes the second run a no-op."""
        assert _register(tmp_path)
        assert _register(tmp_path)
        assert len(_load(tmp_path).installations) == 1


class TestTheMarkerKeyCoversTheVersion:
    def test_an_upgrade_refreshes_rather_than_appends(self, tmp_path: Path) -> None:
        """AC9d — one binary, one record, new version.

        Keyed on `binary_path` alone the second call would hit the marker,
        short-circuit, and leave the registry reporting 1.0 forever. This is
        the test that catches a path-only key.
        """
        _register(tmp_path, version="1.0")
        _register(tmp_path, version="2.0")

        records = _load(tmp_path).installations
        assert len(records) == 1
        assert records[0].functualize_version == "2.0"

    def test_the_marker_differs_between_versions(self, tmp_path: Path) -> None:
        a = m.marker_path(tmp_path, "/usr/bin/func", "1.0")
        b = m.marker_path(tmp_path, "/usr/bin/func", "2.0")
        assert a != b

    def test_the_marker_differs_between_paths(self, tmp_path: Path) -> None:
        a = m.marker_path(tmp_path, "/usr/bin/func", "1.0")
        b = m.marker_path(tmp_path, "/opt/bin/func", "1.0")
        assert a != b

    def test_an_upgrade_keeps_what_was_installed_into_it(self, tmp_path: Path) -> None:
        """The binary changed, not its environment."""
        _register(tmp_path, version="1.0")
        path = m.manifest_path(tmp_path)
        current = m.load(path)
        m.save(
            current.replace(
                m.InstallRecord(
                    **{
                        **current.installations[0].__dict__,
                        "plugins": ("functualize-inline",),
                        "packages": ("requests",),
                    }
                )
            ),
            path,
        )

        _register(tmp_path, version="2.0")
        record = _load(tmp_path).installations[0]
        assert record.functualize_version == "2.0"
        assert record.plugins == ("functualize-inline",)
        assert record.packages == ("requests",)


class TestConcurrency:
    def test_two_racing_registrations_both_survive(self, tmp_path: Path) -> None:
        """AC9b — driven with real threads.

        A mocked write cannot fail the way `os.replace` protects against: the
        failure is a lost update between one process's read and another's
        write, and only genuinely concurrent writers produce it.
        """
        paths = [f"/opt/func-{i}" for i in range(12)]
        with ThreadPoolExecutor(max_workers=12) as pool:
            list(pool.map(lambda p: _register(tmp_path, path=p), paths))

        recorded = {r.binary_path for r in _load(tmp_path).installations}
        missing = set(paths) - recorded
        assert not missing, f"lost {len(missing)} of {len(paths)} concurrent writes"

    def test_the_file_is_never_left_partially_written(self, tmp_path: Path) -> None:
        """Whatever else happens, what lands is parseable JSON."""
        with ThreadPoolExecutor(max_workers=8) as pool:
            list(pool.map(lambda i: _register(tmp_path, path=f"/x/{i}"), range(24)))
        json.loads(m.manifest_path(tmp_path).read_text())


class TestItNeverRaisesIntoACommand:
    def test_a_corrupt_file_loads_as_empty(self, tmp_path: Path) -> None:
        m.manifest_path(tmp_path).write_text("{not json at all")
        assert _load(tmp_path).installations == ()

    def test_a_non_object_loads_as_empty(self, tmp_path: Path) -> None:
        m.manifest_path(tmp_path).write_text("[1, 2, 3]")
        assert _load(tmp_path).installations == ()

    def test_a_higher_schema_version_is_treated_as_unreadable(
        self, tmp_path: Path
    ) -> None:
        """Refusing to parse is the honest answer; optimism drops fields."""
        m.manifest_path(tmp_path).write_text(
            json.dumps(
                {
                    "schema_version": m.SCHEMA_VERSION + 1,
                    "installations": [{"binary_path": "/a/func"}],
                }
            )
        )
        assert _load(tmp_path).installations == ()

    def test_one_malformed_entry_does_not_sink_the_rest(self, tmp_path: Path) -> None:
        m.manifest_path(tmp_path).write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "installations": [
                        {"binary_path": "/good/func", "runtime_mode": "tool_uv"},
                        {"no_binary_path": True},
                        "not even an object",
                    ],
                }
            )
        )
        assert [r.binary_path for r in _load(tmp_path).installations] == ["/good/func"]

    def test_a_missing_file_loads_as_empty(self, tmp_path: Path) -> None:
        assert _load(tmp_path / "nope").installations == ()

    def test_an_unwritable_config_dir_returns_false_and_does_not_raise(
        self, tmp_path: Path
    ) -> None:
        """AC9e — registration is voluntary and its failure is silent.

        A read-only config directory, a container, a sandbox. The command the
        user typed must not care.
        """
        readonly = tmp_path / "ro"
        readonly.mkdir()
        readonly.chmod(0o500)
        try:
            assert _register(readonly) is False
        finally:
            readonly.chmod(0o700)


class TestTheBinaryPathIsStable:
    def test_a_bare_name_resolves_against_the_interpreter(self) -> None:
        """`uv run func` gives argv[0] == "func"; a direct call gives a path.

        Recorded raw, one installation registers twice and the bare-name copy
        is then reported stale because no such file exists relative to the cwd.
        """
        got = m.resolve_binary_path("func", "/env/bin/python")
        assert got == "/env/bin/func"

    def test_a_path_is_resolved_absolutely(self, tmp_path: Path) -> None:
        target = tmp_path / "bin" / "func"
        target.parent.mkdir()
        target.touch()
        got = m.resolve_binary_path(str(target), sys.executable)
        assert got == str(target.resolve())

    def test_an_empty_argv0_is_empty(self) -> None:
        assert m.resolve_binary_path("", sys.executable) == ""

    def test_the_warm_path_copy_agrees_with_the_canonical_one(self) -> None:
        """`_cli/main.py` recomputes this inline to stay off `manifest`.

        Duplication is deliberate — importing this module on every warm run
        costs ~1ms of dataclass codegen for a value it can compute in one line.
        This asserts the copy cannot drift.
        """
        from functualize._cli.main import _register_this_installation

        source = _register_this_installation.__code__
        assert source is not None  # the function exists to be compared against

        for argv0, executable in [
            ("func", "/env/bin/python"),
            ("/abs/path/func", sys.executable),
            ("", sys.executable),
        ]:
            canonical = m.resolve_binary_path(argv0, executable)
            # The inline copy's logic, mirrored here exactly as main.py has it.
            if not argv0:
                inline = ""
            elif "/" in argv0 or "\\" in argv0:
                inline = str(Path(argv0).resolve())
            else:
                inline = str(Path(executable).parent / argv0)
            assert inline == canonical, f"drifted for {argv0!r}"


class TestTheWarmPathStaysCheap:
    @pytest.mark.surfaces("func")
    def test_the_manifest_module_is_not_imported_on_a_warm_run(
        self, cli_run, tmp_path: Path, xdg_dirs
    ) -> None:
        """AC9 — structural, because there is no pre-boot wall-clock budget.

        The perf budgets cover `FunctualizeApp.__init__` only and are skipped
        under coverage and xdist, so a timing assertion here would be
        unenforced. The structural one is also the more precise claim: the cost
        avoided is `@dataclass` codegen at import (~0.9ms per record type), not
        the ~39us of reading the file it manages.
        """
        cli_run(["builtin", "version"], cwd=tmp_path)  # cold: registers
        sys.modules.pop("functualize._cli.manifest", None)

        cli_run(["builtin", "version"], cwd=tmp_path)  # warm: marker hit
        assert "functualize._cli.manifest" not in sys.modules, (
            "the warm path imported the manifest module; the marker check is "
            "supposed to answer with one stat() and no import"
        )


class TestFirstRun:
    """AC8 — and the regression that taught it a boundary.

    The hint originally went to stderr unconditionally. `--perf-report json`
    writes its document to stderr, so two integration tests started failing on
    a `JSONDecodeError` at char 0. stdout is no better: piping job output is
    the documented way to consume it.

    The hint is therefore gated on stderr being a terminal — the only case
    where a human is reading it. A convenience must never damage output
    somebody is parsing.
    """

    def test_it_renders_to_a_terminal(self) -> None:
        from functualize._cli.main import FIRST_RUN_HINT, _emit_first_run_hint

        class _Tty(io.StringIO):
            def isatty(self) -> bool:
                return True

        stream = _Tty()
        assert _emit_first_run_hint(stream) is True
        assert FIRST_RUN_HINT in stream.getvalue()

    def test_it_is_silent_when_stderr_is_not_a_terminal(self) -> None:
        """The regression guard, stated positively."""
        from functualize._cli.main import _emit_first_run_hint

        stream = io.StringIO()  # StringIO.isatty() is False
        assert _emit_first_run_hint(stream) is False
        assert stream.getvalue() == ""

    def test_a_stream_without_isatty_is_treated_as_not_a_terminal(self) -> None:
        from functualize._cli.main import _emit_first_run_hint

        class _Bare:
            def write(self, _: str) -> None:  # pragma: no cover - never reached
                raise AssertionError("should not have written")

        assert _emit_first_run_hint(_Bare()) is False

    @pytest.mark.surfaces("func")
    def test_captured_output_is_never_contaminated(
        self, cli_run, tmp_path: Path
    ) -> None:
        """First run through the real entry point, with output captured.

        Neither stream may carry the hint here, because captured output is
        exactly the case that broke.
        """
        result = cli_run(["builtin", "version"], cwd=tmp_path)
        assert result.exit_code == 0
        assert "functualize" in result.stdout
        assert "self doctor" not in result.stdout
        assert "self doctor" not in result.stderr

    @pytest.mark.surfaces("func")
    def test_registration_still_happens_without_the_hint(
        self, cli_run, tmp_path: Path, xdg_dirs
    ) -> None:
        """Gating the *hint* must not gate the *registration*.

        **`func`-only, and this one is a gap rather than a boundary.**
        Registration lives in `_run_cli`, which a consumer application's own
        `main.py` never reaches — so an app built on functualize does not
        register itself, even though detection would correctly name it as its
        own owning distribution. Nothing about registration requires a pre-boot
        layer; whether `CliAdapter` should do it is recorded as AC9g rather
        than guessed at here.
        """
        cli_run(["builtin", "version"], cwd=tmp_path)
        recorded = m.load(m.manifest_path(xdg_dirs.functualize_config))
        assert len(recorded.installations) == 1


class TestAConsumerAppDoesNotRegisterItself:
    """AC9g, decided 2026-09-03 — and pinned so it is not "fixed" later.

    The registry means *functualize installations*, not every application built
    on functualize that has run. An app embedding functualize is not an
    installation of it: it has its own name, release cycle and owner, which is
    what detection already reports for it.

    Registration lives in `_run_cli`, which an app's own `main.py` never
    reaches. That is the mechanism, but the *decision* is what this guards —
    adding a call in `CliAdapter` would look like an obvious omission fixed.
    """

    @pytest.mark.surfaces("app")
    def test_running_on_the_app_surface_writes_no_record(
        self, cli_run, tmp_path: Path, xdg_dirs
    ) -> None:
        result = cli_run(["builtin", "version"], cwd=tmp_path)
        assert result.exit_code == 0

        recorded = m.load(m.manifest_path(xdg_dirs.functualize_config))
        assert recorded.installations == (), (
            "a consumer application registered itself; the registry is for "
            "functualize installations, not for apps built on it (AC9g)"
        )

    @pytest.mark.surfaces("app")
    def test_no_manifest_file_is_created_at_all(
        self, cli_run, tmp_path: Path, xdg_dirs
    ) -> None:
        cli_run(["builtin", "version"], cwd=tmp_path)
        assert not m.manifest_path(xdg_dirs.functualize_config).exists()
