"""Command planning and reconciliation, as pure functions.

Tier 1 of `research.md` §2.3: no filesystem beyond `tmp_path`, no subprocess,
no real installation touched. Everything here is reachable because `detect`
takes its inputs as arguments and the commands are *planned* separately from
being run — the same split that lets the CLI tests print a mutating command
without executing it.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from functualize._cli import package_ops
from functualize._cli.package_ops import (
    LossyReceiptError,
    MissingToolError,
    Receipt,
    Requirement,
)
from functualize._cli.runtime import Detection, InstallMode


def _detection(mode: InstallMode, owner: str | None = "functualize") -> Detection:
    return Detection(mode=mode, owning_distribution=owner)


class TestNameNormalization:
    def test_underscores_and_hyphens_are_the_same_package(self) -> None:
        assert package_ops.normalize("functualize_http") == package_ops.normalize(
            "Functualize-HTTP"
        )

    def test_runs_of_separators_collapse(self) -> None:
        """PEP 503 collapses `a__b` and `a.b` alike; a partial rule is worse
        than none, because it makes only *some* spellings compare equal."""
        assert package_ops.normalize("zope..interface") == "zope-interface"


class TestCapture:
    def test_it_reads_dist_info_directory_names(self, tmp_path: Path) -> None:
        (tmp_path / "requests-2.31.0.dist-info").mkdir()
        (tmp_path / "functualize_http-0.1.2.dist-info").mkdir()
        assert package_ops.capture([tmp_path]) == {
            "requests": "2.31.0",
            "functualize-http": "0.1.2",
        }

    def test_it_never_opens_metadata(self, tmp_path: Path) -> None:
        """The 70x cost difference this design exists for.

        A `dist-info` whose METADATA is unreadable still yields its name and
        version, which it could not if the version came from the file.
        """
        info = tmp_path / "requests-2.31.0.dist-info"
        info.mkdir()
        (info / "METADATA").write_bytes(b"\xff\xfe not utf-8 at all")
        assert package_ops.capture([tmp_path]) == {"requests": "2.31.0"}

    def test_a_directory_that_does_not_parse_is_skipped(self, tmp_path: Path) -> None:
        (tmp_path / "broken.dist-info").mkdir()
        (tmp_path / "requests-2.31.0.dist-info").mkdir()
        assert package_ops.capture([tmp_path]) == {"requests": "2.31.0"}

    def test_a_missing_directory_is_not_an_error(self, tmp_path: Path) -> None:
        assert package_ops.capture([tmp_path / "nope"]) == {}

    def test_the_live_environment_finds_functualize(self) -> None:
        """The production entry point, against the interpreter running us."""
        assert "functualize" in package_ops.capture_environment()


class TestNamesToRestore:
    def test_a_package_the_update_removed_is_restored(self) -> None:
        before = {"functualize": "0.1.2", "requests": "2.31.0"}
        after = {"functualize": "0.2.0"}
        assert package_ops.names_to_restore(before, after, ()) == ("requests",)

    def test_a_shipped_package_upgraded_in_place_is_not_pinned_back(self) -> None:
        """AC14g, and the reason the difference is over names alone.

        `certifi` moved 2024.2.2 -> 2025.1.1 because the upgrade updated it.
        Differencing over `(name, version)` pairs classifies that as a user
        addition and reinstalls the *old* version, silently undoing the
        upgrade's own dependency updates.
        """
        before = {"functualize": "0.1.2", "certifi": "2024.2.2"}
        after = {"functualize": "0.2.0", "certifi": "2025.1.1"}
        assert package_ops.names_to_restore(before, after, ()) == ()

    def test_an_escape_hatch_install_survives(self) -> None:
        """AC14f — never recorded, caught by the capture instead."""
        before = {"functualize": "0.1.2", "pandas": "2.2.0"}
        after = {"functualize": "0.2.0"}
        assert "pandas" in package_ops.names_to_restore(before, after, ())

    def test_records_are_restored_when_the_capture_missed_them(self) -> None:
        """AC14b — the belt to the capture's braces.

        A capture that failed leaves `before` empty; the manifest's records are
        still enough to put the user's plugins back.
        """
        assert package_ops.names_to_restore({}, {}, ("functualize-state-sqlite",)) == (
            "functualize-state-sqlite",
        )

    def test_a_record_still_present_after_the_update_is_not_reinstalled(self) -> None:
        """Reinstalling what is already there is noise, not safety."""
        assert (
            package_ops.names_to_restore({}, {"requests": "2.31.0"}, ("requests",))
            == ()
        )

    def test_the_two_sides_are_normalized_before_differencing(self) -> None:
        """The bug this normalization exists to prevent.

        Captures spell names with underscores and manifests with hyphens. Raw
        comparison makes *every* hyphenated package look like a user addition
        the update removed, and reconciliation reinstalls the whole environment.
        """
        before = {"functualize_http": "0.1.0"}
        after = {"functualize-http": "0.2.0"}
        assert package_ops.names_to_restore(before, after, ()) == ()


class TestPendingCapture:
    def test_it_round_trips(self, tmp_path: Path) -> None:
        assert package_ops.save_pending(tmp_path, {"requests": "2.31.0"})
        assert package_ops.load_pending(tmp_path) == {"requests": "2.31.0"}

    def test_absent_reads_as_none(self, tmp_path: Path) -> None:
        assert package_ops.load_pending(tmp_path) is None

    def test_corrupt_reads_as_none_rather_than_raising(self, tmp_path: Path) -> None:
        package_ops.pending_path(tmp_path).write_text("{not json", encoding="utf-8")
        assert package_ops.load_pending(tmp_path) is None

    def test_clearing_a_missing_file_is_not_an_error(self, tmp_path: Path) -> None:
        package_ops.clear_pending(tmp_path)

    def test_an_unwritable_directory_is_reported_not_raised(
        self, tmp_path: Path
    ) -> None:
        blocked = tmp_path / "wall"
        blocked.write_text("I am a file, not a directory", encoding="utf-8")
        assert package_ops.save_pending(blocked / "sub", {"a": "1"}) is False


class TestRequirementRoundTrip:
    """Shapes taken from real `uv-receipt.toml` files on the audit host."""

    def test_a_bare_name(self) -> None:
        assert Requirement("a0", {"name": "a0"}).to_pep508() == "a0"

    def test_extras(self) -> None:
        entry = {"name": "functualize", "extras": ["cli"]}
        assert Requirement("functualize", entry).to_pep508() == "functualize[cli]"

    def test_a_specifier(self) -> None:
        entry = {"name": "rich", "specifier": "==15.0.0"}
        assert Requirement("rich", entry).to_pep508() == "rich==15.0.0"

    def test_a_url(self) -> None:
        entry = {"name": "a0", "url": "https://example.invalid/a0.zip"}
        assert (
            Requirement("a0", entry).to_pep508()
            == "a0 @ https://example.invalid/a0.zip"
        )

    def test_a_marker(self) -> None:
        entry = {
            "name": "pywin32",
            "specifier": "==311",
            "marker": "sys_platform == 'win32'",
        }
        assert (
            Requirement("pywin32", entry).to_pep508()
            == "pywin32==311 ; sys_platform == 'win32'"
        )

    def test_an_unknown_key_refuses_rather_than_dropping_it(self) -> None:
        """The whole point of the type.

        `uv tool install` is declarative: it rewrites the receipt from the
        arguments given. A key this cannot render is not merely absent from one
        command — it is *removed from the environment*. Refusing is the only
        answer that does not silently change what is installed.
        """
        entry = {"name": "thing", "git": "https://example.invalid/thing.git"}
        with pytest.raises(LossyReceiptError, match="git"):
            Requirement("thing", entry).to_pep508()


class TestReceiptReading:
    def _write(self, prefix: Path, body: str) -> Path:
        prefix.mkdir(parents=True, exist_ok=True)
        (prefix / "uv-receipt.toml").write_text(body, encoding="utf-8")
        return prefix

    def test_a_real_shaped_receipt(self, tmp_path: Path) -> None:
        prefix = self._write(
            tmp_path,
            "[tool]\n"
            'requirements = [{ name = "functualize", extras = ["cli"] }]\n'
            'entrypoints = [{ name = "func", from = "functualize" }]\n',
        )
        receipt = package_ops.read_receipt(prefix)
        assert receipt is not None
        assert [r.name for r in receipt.requirements] == ["functualize"]

    def test_the_pinned_python_is_carried(self, tmp_path: Path) -> None:
        """Dropping it lets a re-install land on a different interpreter."""
        prefix = self._write(
            tmp_path,
            '[tool]\nrequirements = [{ name = "a0" }]\npython = "3.11"\n',
        )
        receipt = package_ops.read_receipt(prefix)
        assert receipt is not None
        assert receipt.python == "3.11"

    def test_no_receipt_reads_as_none(self, tmp_path: Path) -> None:
        assert package_ops.read_receipt(tmp_path) is None

    def test_malformed_toml_reads_as_none(self, tmp_path: Path) -> None:
        prefix = self._write(tmp_path, "[tool\nbroken")
        assert package_ops.read_receipt(prefix) is None


class TestReceiptMerge:
    def test_a_second_package_keeps_the_first(self) -> None:
        """AC17, as a unit.

        `uv tool` has no `add`/`inject`, so every prior requirement has to be
        restated or installing plugin B uninstalls plugin A.
        """
        receipt = Receipt(
            requirements=(
                Requirement("functualize", {"name": "functualize", "extras": ["cli"]}),
                Requirement("functualize-http", {"name": "functualize-http"}),
            )
        )
        args = package_ops.merge_receipt(
            receipt, "functualize", "functualize-state-sqlite"
        )
        assert args[:3] == ("tool", "install", "functualize[cli]")
        assert "functualize-http" in args
        assert "functualize-state-sqlite" in args

    def test_the_owner_is_the_positional_and_not_a_with(self) -> None:
        receipt = Receipt(
            requirements=(Requirement("functualize", {"name": "functualize"}),)
        )
        args = package_ops.merge_receipt(receipt, "functualize", "requests")
        assert args.index("functualize") == 2
        assert args.count("functualize") == 1

    def test_the_pinned_python_reaches_the_command(self) -> None:
        receipt = Receipt(
            requirements=(Requirement("functualize", {"name": "functualize"}),),
            python="3.11",
        )
        args = package_ops.merge_receipt(receipt, "functualize", "requests")
        assert args[-2:] == ("--python", "3.11")

    def test_no_receipt_still_produces_a_usable_command(self) -> None:
        args = package_ops.merge_receipt(None, "functualize", "requests")
        assert args == ("tool", "install", "functualize", "--with", "requests")

    def test_installing_something_already_present_does_not_duplicate_it(self) -> None:
        receipt = Receipt(
            requirements=(
                Requirement("functualize", {"name": "functualize"}),
                Requirement("requests", {"name": "requests"}),
            )
        )
        args = package_ops.merge_receipt(receipt, "functualize", "requests")
        assert args.count("requests") == 1

    def test_a_lossy_entry_stops_the_merge(self) -> None:
        receipt = Receipt(
            requirements=(
                Requirement("functualize", {"name": "functualize"}),
                Requirement("thing", {"name": "thing", "git": "ssh://x"}),
            )
        )
        with pytest.raises(LossyReceiptError):
            package_ops.merge_receipt(receipt, "functualize", "requests")

    def test_dropping_removes_only_the_named_package(self) -> None:
        receipt = Receipt(
            requirements=(
                Requirement("functualize", {"name": "functualize"}),
                Requirement("functualize-http", {"name": "functualize-http"}),
                Requirement("requests", {"name": "requests"}),
            )
        )
        args = package_ops.drop_from_receipt(receipt, "functualize", "functualize-http")
        assert "functualize-http" not in args
        assert "requests" in args


class TestUpdateCommands:
    def test_uv_tool_mode(self, monkeypatch) -> None:
        monkeypatch.setattr(package_ops, "resolve_uv", lambda: "/opt/uv")
        assert package_ops.update_commands(
            _detection(InstallMode.TOOL_UV), "/bin/func"
        ) == (("/opt/uv", "tool", "upgrade", "functualize"),)

    def test_pipx_mode(self, monkeypatch) -> None:
        monkeypatch.setattr(package_ops, "resolve_pipx", lambda: "/opt/pipx")
        assert package_ops.update_commands(
            _detection(InstallMode.TOOL_PIPX), "/bin/func"
        ) == (("/opt/pipx", "upgrade", "functualize"),)

    def test_standalone_mode_drives_the_binary_itself(self) -> None:
        """PyApp's own updater, at the renamed self-command."""
        assert package_ops.update_commands(
            _detection(InstallMode.STANDALONE), "/usr/local/bin/func"
        ) == (("/usr/local/bin/func", "pyapp", "update"),)

    def test_project_mode_moves_the_lock_before_syncing(self, monkeypatch) -> None:
        """`uv sync` alone reinstalls the pinned version — it is not an upgrade."""
        monkeypatch.setattr(package_ops, "resolve_uv", lambda: "/opt/uv")
        commands = package_ops.update_commands(
            _detection(InstallMode.PROJECT), "/bin/func"
        )
        assert commands == (
            ("/opt/uv", "lock", "--upgrade-package", "functualize"),
            ("/opt/uv", "sync"),
        )

    @pytest.mark.parametrize("mode", [InstallMode.TOOL_PIP, InstallMode.UNKNOWN])
    def test_a_degraded_mode_produces_no_command_at_all(
        self, mode: InstallMode
    ) -> None:
        """The backstop under the CLI's refusal branch.

        If the command layer ever forgets to check, planning must raise rather
        than hand back something runnable.
        """
        with pytest.raises(ValueError, match="not self-managing"):
            package_ops.update_commands(_detection(mode), "/bin/func")

    def test_an_unknown_owner_produces_no_command_either(self) -> None:
        with pytest.raises(ValueError):
            package_ops.update_commands(
                _detection(InstallMode.TOOL_UV, owner=None), "/bin/func"
            )

    def test_a_missing_manager_is_a_usage_problem_not_a_refusal(
        self, monkeypatch
    ) -> None:
        def _absent() -> str:
            raise MissingToolError("no uv")

        monkeypatch.setattr(package_ops, "resolve_uv", _absent)
        with pytest.raises(MissingToolError):
            package_ops.update_commands(_detection(InstallMode.TOOL_UV), "/bin/func")


class TestTheOwningDistributionIsNeverHardcoded:
    """AC31, asserted where it can actually fail.

    In the test suite `argv[0]` is `func`, so the *correct* owner is the
    literal string `functualize` and asserting on its absence proves nothing.
    Naming a different owner is what separates a resolved value from a constant.
    """

    @pytest.mark.parametrize(
        ("mode", "patch"),
        [
            (InstallMode.TOOL_UV, "resolve_uv"),
            (InstallMode.TOOL_PIPX, "resolve_pipx"),
            (InstallMode.PROJECT, "resolve_uv"),
        ],
    )
    def test_update_names_the_owner(self, monkeypatch, mode, patch) -> None:
        monkeypatch.setattr(package_ops, patch, lambda: "/opt/tool")
        flat = " ".join(
            token
            for command in package_ops.update_commands(
                _detection(mode, owner="weather-app"), "/bin/weather-app"
            )
            for token in command
        )
        assert "weather-app" in flat
        assert "functualize" not in flat

    @pytest.mark.parametrize(
        ("mode", "patch"),
        [
            (InstallMode.TOOL_UV, "resolve_uv"),
            (InstallMode.TOOL_PIPX, "resolve_pipx"),
        ],
    )
    def test_install_names_the_owner(self, monkeypatch, mode, patch, tmp_path) -> None:
        monkeypatch.setattr(package_ops, patch, lambda: "/opt/tool")
        monkeypatch.setattr(package_ops.sys, "prefix", str(tmp_path))
        flat = " ".join(
            token
            for command in package_ops.install_commands(
                _detection(mode, owner="weather-app"), "requests"
            )
            for token in command
        )
        assert "weather-app" in flat
        assert "functualize" not in flat


class TestInstallCommands:
    def test_standalone_targets_the_bundled_interpreter_explicitly(
        self, monkeypatch
    ) -> None:
        """Without `--python`, uv picks an interpreter by its own discovery
        rules — which in a shell with an activated venv is somebody else's."""
        monkeypatch.setattr(package_ops, "resolve_uv", lambda: "/opt/uv")
        monkeypatch.setattr(package_ops, "owned_python", lambda: "/pyapp/bin/python")
        assert package_ops.install_commands(
            _detection(InstallMode.STANDALONE), "requests"
        ) == (
            ("/opt/uv", "pip", "install", "--python", "/pyapp/bin/python", "requests"),
        )

    def test_pipx_uses_its_real_injection_verb(self, monkeypatch) -> None:
        monkeypatch.setattr(package_ops, "resolve_pipx", lambda: "/opt/pipx")
        assert package_ops.install_commands(
            _detection(InstallMode.TOOL_PIPX), "requests"
        ) == (("/opt/pipx", "inject", "functualize", "requests"),)

    def test_project_mode_edits_the_project(self, monkeypatch) -> None:
        monkeypatch.setattr(package_ops, "resolve_uv", lambda: "/opt/uv")
        assert package_ops.install_commands(
            _detection(InstallMode.PROJECT), "requests"
        ) == (("/opt/uv", "add", "requests"),)

    def test_uv_tool_mode_reconstructs_the_receipt(self, monkeypatch, tmp_path) -> None:
        (tmp_path / "uv-receipt.toml").write_text(
            '[tool]\nrequirements = [{ name = "functualize", extras = ["cli"] },'
            ' { name = "functualize-http" }]\n',
            encoding="utf-8",
        )
        monkeypatch.setattr(package_ops, "resolve_uv", lambda: "/opt/uv")
        monkeypatch.setattr(package_ops.sys, "prefix", str(tmp_path))
        (command,) = package_ops.install_commands(
            _detection(InstallMode.TOOL_UV), "requests"
        )
        assert "functualize-http" in command
        assert "requests" in command

    @pytest.mark.parametrize("mode", [InstallMode.TOOL_PIP, InstallMode.UNKNOWN])
    def test_degraded_modes_plan_nothing(self, mode: InstallMode) -> None:
        with pytest.raises(ValueError):
            package_ops.install_commands(_detection(mode), "requests")


class TestOwnedPython:
    def test_it_does_not_follow_the_venv_symlink(self) -> None:
        """A venv's `bin/python` is a symlink to the base interpreter, and
        following it hands back a Python that sees none of the environment's
        packages. The symlink *is* the environment."""
        import sys

        assert package_ops.owned_python() == __import__("os").path.abspath(
            sys.executable
        )

    def test_it_is_absolute(self) -> None:
        assert Path(package_ops.owned_python()).is_absolute()


class TestExecution:
    def test_commands_run_in_order(self, monkeypatch) -> None:
        seen: list[list[str]] = []
        monkeypatch.setattr(
            package_ops, "_call", lambda argv: seen.append(list(argv)) or 0
        )
        assert package_ops.run_commands([["a"], ["b"]]) == 0
        assert seen == [["a"], ["b"]]

    def test_a_failure_stops_the_rest(self, monkeypatch) -> None:
        """`uv sync` must not run when `uv lock` failed — it would install the
        old pin and report success."""
        seen: list[list[str]] = []

        def _call(argv):
            seen.append(list(argv))
            return 7

        monkeypatch.setattr(package_ops, "_call", _call)
        assert package_ops.run_commands([["a"], ["b"]]) == 7
        assert seen == [["a"]]

    def test_rendering_quotes_paths_with_spaces(self) -> None:
        assert package_ops.render(["/a b/uv", "sync"]) == '"/a b/uv" sync'


class TestPathInstalls:
    """The shapes a *local path* install writes — found by running it.

    `uv tool install "/src[cli]"` writes
    `{name = "functualize", extras = ["cli"], directory = "/src"}`. Nothing in
    the unit tests had that shape, so the merge refused every `plugin install`
    in a container built that way. The refusal was correct; the gap was that
    `directory` is perfectly renderable and was not being rendered.
    """

    def test_a_directory_renders_as_the_path_the_user_typed(self) -> None:
        entry = {"name": "functualize", "extras": ["cli"], "directory": "/src"}
        assert Requirement("functualize", entry).to_pep508() == "/src[cli]"

    def test_a_directory_without_extras(self) -> None:
        entry = {"name": "functualize-http", "directory": "/src/plugins/http"}
        assert Requirement("functualize-http", entry).to_pep508() == "/src/plugins/http"

    def test_a_path_install_merges_without_refusing(self) -> None:
        receipt = Receipt(
            requirements=(
                Requirement(
                    "functualize",
                    {"name": "functualize", "extras": ["cli"], "directory": "/src"},
                ),
            )
        )
        args = package_ops.merge_receipt(receipt, "functualize", "functualize-http")
        assert args == (
            "tool",
            "install",
            "/src[cli]",
            "--with",
            "functualize-http",
        )

    def test_the_owner_is_matched_by_name_not_by_rendered_string(self) -> None:
        """A path install renders as `/src[cli]`; matching on that would never
        recognise it as the owning distribution, and it would be restated as a
        `--with` while a bare `functualize` took the positional -- reinstalling
        the published version over the local one."""
        receipt = Receipt(
            requirements=(
                Requirement(
                    "functualize",
                    {"name": "functualize", "extras": ["cli"], "directory": "/src"},
                ),
                Requirement("requests", {"name": "requests"}),
            )
        )
        args = package_ops.merge_receipt(receipt, "functualize", "new-thing")
        assert args[2] == "/src[cli]"
        assert "functualize" not in args


class TestEditableInstalls:
    """Editability is a flag, not part of a requirement string."""

    def test_it_has_no_requirement_string_form(self) -> None:
        entry = {"name": "functualize", "directory": "/src", "editable": True}
        with pytest.raises(LossyReceiptError, match="editable"):
            Requirement("functualize", entry).to_pep508()

    def test_the_owner_is_restated_with_the_editable_flag(self) -> None:
        """Rendering it as a plain path would reinstall it non-editably --
        silently changing what is installed, which is the failure the whole
        reconstruction exists to prevent."""
        receipt = Receipt(
            requirements=(
                Requirement(
                    "functualize",
                    {
                        "name": "functualize",
                        "extras": ["cli"],
                        "directory": "/src",
                        "editable": True,
                    },
                ),
            )
        )
        args = package_ops.merge_receipt(receipt, "functualize", "requests")
        assert args[:4] == ("tool", "install", "--editable", "/src[cli]")

    def test_a_non_owner_editable_uses_with_editable(self) -> None:
        receipt = Receipt(
            requirements=(
                Requirement("functualize", {"name": "functualize"}),
                Requirement(
                    "functualize-http",
                    {
                        "name": "functualize-http",
                        "directory": "/src/plugins/http",
                        "editable": True,
                    },
                ),
            )
        )
        args = package_ops.merge_receipt(receipt, "functualize", "requests")
        assert "--with-editable" in args
        assert "/src/plugins/http" in args

    def test_editable_false_is_not_treated_as_editable(self) -> None:
        entry = {"name": "x", "directory": "/d", "editable": False}
        assert Requirement("x", entry).to_pep508() == "/d"

    def test_an_editable_entry_naming_no_directory_refuses(self) -> None:
        """There is nothing to point `--editable` at."""
        entry = {"name": "x", "editable": True}
        with pytest.raises(LossyReceiptError, match="directory"):
            Requirement("x", entry).install_args(primary=True)


class TestDropAndMergeShareOneRebuild:
    def test_dropping_a_path_install_keeps_the_path_form(self) -> None:
        receipt = Receipt(
            requirements=(
                Requirement(
                    "functualize",
                    {"name": "functualize", "extras": ["cli"], "directory": "/src"},
                ),
                Requirement("functualize-http", {"name": "functualize-http"}),
                Requirement("requests", {"name": "requests"}),
            )
        )
        args = package_ops.drop_from_receipt(receipt, "functualize", "functualize-http")
        assert args[2] == "/src[cli]"
        assert "functualize-http" not in args
        assert "requests" in args

    def test_dropping_the_python_pin_is_never_silent(self) -> None:
        receipt = Receipt(
            requirements=(Requirement("functualize", {"name": "functualize"}),),
            python="3.11",
        )
        for args in (
            package_ops.merge_receipt(receipt, "functualize", "x"),
            package_ops.drop_from_receipt(receipt, "functualize", "x"),
        ):
            assert args[-2:] == ("--python", "3.11")
