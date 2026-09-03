"""Install-mode detection, driven entirely by supplied inputs.

Every case here asserts *the right answer*, never "not the wrong one" — a
`!= UNKNOWN` assertion passes for five of the six modes and would have caught
none of the bugs this ladder can have.

The reason `detect()` takes `prefix`, `environ`, `argv0` and `cwd` as arguments
lives here: `sys.prefix` cannot be set by an environment variable, so a version
that read it directly could only ever be exercised in whichever single mode the
suite happens to run under. Injection is what makes the other five reachable.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from functualize._cli.runtime import (
    Detection,
    InstallMode,
    RuntimeOverrideError,
    detect,
)

# A venv-shaped prefix that is not the base — so rung 6 cannot claim it.
_VENV = "/somewhere/project/.venv"
_BASE = "/usr"


def _detect(
    *,
    prefix: str = _VENV,
    base_prefix: str = _BASE,
    environ: dict[str, str] | None = None,
    argv0: str = "/somewhere/project/.venv/bin/func",
    cwd: Path | None = None,
    tmp_path: Path | None = None,
) -> Detection:
    """Call `detect` with an empty environment and an empty cwd by default.

    The default `cwd` is a directory with no `pyproject.toml`, so rung 5 stays
    silent unless a test deliberately arms it.
    """
    where = cwd if cwd is not None else (tmp_path or Path("/nonexistent-empty-dir"))
    return detect(
        prefix=prefix,
        base_prefix=base_prefix,
        environ=environ if environ is not None else {},
        argv0=argv0,
        cwd=where,
    )


class TestTheOverrideRung:
    @pytest.mark.parametrize("mode", list(InstallMode))
    def test_every_mode_is_reachable_by_override(
        self, mode: InstallMode, tmp_path: Path
    ) -> None:
        """The override must be able to name each mode, not most of them."""
        got = _detect(environ={"FUNCTUALIZE_RUNTIME": mode.value}, tmp_path=tmp_path)
        assert got.mode is mode

    def test_the_override_wins_over_every_other_signal(self, tmp_path: Path) -> None:
        """Rung 1 means rung 1 — a PyApp binary can still be pinned."""
        got = _detect(
            environ={"FUNCTUALIZE_RUNTIME": "project", "PYAPP": "1"},
            tmp_path=tmp_path,
        )
        assert got.mode is InstallMode.PROJECT

    def test_an_unknown_override_raises(self, tmp_path: Path) -> None:
        """Never a silent fallback: that reports a typo as a degraded install."""
        with pytest.raises(RuntimeOverrideError, match="not a known install mode"):
            _detect(environ={"FUNCTUALIZE_RUNTIME": "tool-uv"}, tmp_path=tmp_path)

    def test_an_empty_override_is_ignored(self, tmp_path: Path) -> None:
        """`FUNCTUALIZE_RUNTIME=` is an unset variable, not an error."""
        got = _detect(environ={"FUNCTUALIZE_RUNTIME": ""}, tmp_path=tmp_path)
        assert got.mode is InstallMode.UNKNOWN


class TestTheSignalRungs:
    def test_pyapp_means_standalone(self, tmp_path: Path) -> None:
        assert _detect(environ={"PYAPP": "1"}, tmp_path=tmp_path).mode is (
            InstallMode.STANDALONE
        )

    def test_pyapp_command_name_alone_means_standalone(self, tmp_path: Path) -> None:
        """PyApp exposes its management group's name; either signal is enough."""
        got = _detect(environ={"PYAPP_COMMAND_NAME": "pyapp"}, tmp_path=tmp_path)
        assert got.mode is InstallMode.STANDALONE

    def test_prefix_under_the_uv_tools_dir_means_tool_uv(self, tmp_path: Path) -> None:
        got = _detect(
            prefix="/home/u/.local/share/uv/tools/functualize",
            environ={"HOME": "/home/u"},
            tmp_path=tmp_path,
        )
        assert got.mode is InstallMode.TOOL_UV

    def test_uv_tool_dir_env_var_is_honoured(self, tmp_path: Path) -> None:
        got = _detect(
            prefix="/opt/uvtools/functualize",
            environ={"UV_TOOL_DIR": "/opt/uvtools"},
            tmp_path=tmp_path,
        )
        assert got.mode is InstallMode.TOOL_UV

    def test_xdg_data_home_relocates_the_uv_tools_dir(self, tmp_path: Path) -> None:
        got = _detect(
            prefix="/xdg/uv/tools/functualize",
            environ={"XDG_DATA_HOME": "/xdg", "HOME": "/home/u"},
            tmp_path=tmp_path,
        )
        assert got.mode is InstallMode.TOOL_UV

    def test_pipx_venvs_in_the_prefix_means_tool_pipx(self, tmp_path: Path) -> None:
        got = _detect(
            prefix="/home/u/.local/share/pipx/venvs/functualize", tmp_path=tmp_path
        )
        assert got.mode is InstallMode.TOOL_PIPX

    def test_prefix_equal_to_base_means_tool_pip(self, tmp_path: Path) -> None:
        got = _detect(prefix="/usr", base_prefix="/usr", tmp_path=tmp_path)
        assert got.mode is InstallMode.TOOL_PIP

    def test_an_unrecognised_venv_is_unknown(self, tmp_path: Path) -> None:
        """Never `standalone` — that hands a dev checkout bundled-uv commands."""
        got = _detect(prefix="/some/other/.venv", tmp_path=tmp_path)
        assert got.mode is InstallMode.UNKNOWN


class TestTheProjectRung:
    def test_a_declared_dependency_means_project(self, tmp_path: Path) -> None:
        (tmp_path / "pyproject.toml").write_text(
            '[project]\nname = "app"\ndependencies = ["functualize>=0.1"]\n'
        )
        assert _detect(cwd=tmp_path).mode is InstallMode.PROJECT

    def test_an_optional_dependency_counts(self, tmp_path: Path) -> None:
        (tmp_path / "pyproject.toml").write_text(
            '[project]\nname = "app"\n'
            '[project.optional-dependencies]\ndev = ["functualize[cli]"]\n'
        )
        assert _detect(cwd=tmp_path).mode is InstallMode.PROJECT

    def test_a_tool_table_counts_without_a_declared_dependency(
        self, tmp_path: Path
    ) -> None:
        """A workspace member or editable install configures without declaring."""
        (tmp_path / "pyproject.toml").write_text(
            '[project]\nname = "app"\n[tool.functualize]\nscan_depth = 2\n'
        )
        assert _detect(cwd=tmp_path).mode is InstallMode.PROJECT

    def test_an_unrelated_pyproject_does_not_count(self, tmp_path: Path) -> None:
        (tmp_path / "pyproject.toml").write_text(
            '[project]\nname = "app"\ndependencies = ["requests"]\n'
        )
        assert _detect(cwd=tmp_path).mode is InstallMode.UNKNOWN

    def test_the_walk_reaches_a_parent(self, tmp_path: Path) -> None:
        (tmp_path / "pyproject.toml").write_text(
            '[project]\nname = "app"\ndependencies = ["functualize"]\n'
        )
        nested = tmp_path / "src" / "pkg"
        nested.mkdir(parents=True)
        assert _detect(cwd=nested).mode is InstallMode.PROJECT

    def test_malformed_toml_is_not_a_project_and_does_not_raise(
        self, tmp_path: Path
    ) -> None:
        """Detection answers a question; it never raises into the command."""
        (tmp_path / "pyproject.toml").write_text("[project\nname = broken")
        assert _detect(cwd=tmp_path).mode is InstallMode.UNKNOWN

    def test_a_cheaper_rung_answers_before_the_walk(self, tmp_path: Path) -> None:
        """Ordering is binding: rung 5 is the only filesystem rung, and last.

        Armed with a real project *and* a PyApp signal, the answer must come
        from the environment. If this ever reports `project`, a filesystem rung
        has moved above a pure one.
        """
        (tmp_path / "pyproject.toml").write_text(
            '[project]\nname = "app"\ndependencies = ["functualize"]\n'
        )
        got = _detect(environ={"PYAPP": "1"}, cwd=tmp_path)
        assert got.mode is InstallMode.STANDALONE


class TestDegradedness:
    @pytest.mark.parametrize(
        ("mode", "expected"),
        [
            (InstallMode.STANDALONE, False),
            (InstallMode.TOOL_UV, False),
            (InstallMode.TOOL_PIPX, False),
            (InstallMode.PROJECT, False),
            (InstallMode.TOOL_PIP, True),
            (InstallMode.UNKNOWN, True),
        ],
    )
    def test_exactly_two_modes_are_degraded(
        self, mode: InstallMode, expected: bool
    ) -> None:
        assert mode.degraded is expected

    def test_an_unresolvable_owner_degrades_the_detection(self) -> None:
        """Knowing the environment is not enough to name a tool."""
        got = Detection(mode=InstallMode.TOOL_UV, owning_distribution=None)
        assert got.mode.degraded is False
        assert got.degraded is True


class TestTheOwningDistribution:
    def test_the_running_console_script_resolves_to_its_distribution(self) -> None:
        """`func` is installed by this checkout, so it maps to functualize.

        The one case that can be asserted against real metadata rather than a
        fixture — and the one that matters, since it is what `self update`
        names when nothing exotic is going on.
        """
        got = _detect(argv0="/anywhere/bin/func")
        assert got.owning_distribution == "functualize"

    def test_a_windows_suffix_is_stripped(self) -> None:
        got = _detect(argv0=r"C:\Tools\func.exe")
        assert got.owning_distribution == "functualize"

    def test_an_unknown_script_resolves_to_no_distribution(self) -> None:
        """`None`, never a guess — this is what forces the refusal path."""
        got = _detect(argv0="/anywhere/bin/not-a-real-console-script")
        assert got.owning_distribution is None

    def test_an_empty_argv0_resolves_to_no_distribution(self) -> None:
        assert _detect(argv0="").owning_distribution is None


class TestTheModeVocabularyIsThePublicOne:
    def test_members_serialize_to_their_documented_spelling(self) -> None:
        """These strings reach JSON output and the override variable."""
        assert [m.value for m in InstallMode] == [
            "standalone",
            "tool_uv",
            "tool_pipx",
            "project",
            "tool_pip",
            "unknown",
        ]
