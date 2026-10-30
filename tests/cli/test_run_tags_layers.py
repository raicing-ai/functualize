"""The three run-tag layers, merged per key with the later layer winning.

Lowest to highest: the user's global config (`[run] tags`), then
`FUNCTUALIZE_RUN_TAGS`, then `--run-tag`. Across layers a repeated key is an
override; within one layer it is refused, naming that layer. The project file
is not a layer at all.

The config file is read quietly here. `read_global_config` reports a broken
file once, at boot; reading it through that function before boot as well
printed every config warning twice.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from functualize._cli.run_tags import RunTagError, parse_env
from tests.conftest import surfaces

pytestmark = surfaces("func")

_JOB = {"release.py": "def release():\n    print('released')\n"}


def _records(*roots: Path) -> list[dict[str, Any]]:
    found: list[dict[str, Any]] = []
    for root in roots:
        for path in root.rglob("runs.json"):
            found.extend(json.loads(path.read_text()).get("runs", {}).values())
    return found


def _write_config(xdg_dirs: Any, text: str) -> None:
    xdg_dirs.functualize_config.mkdir(parents=True, exist_ok=True)
    (xdg_dirs.functualize_config / "config.toml").write_text(text)


def test_env_comma_tail_is_refused_as_a_value() -> None:
    with pytest.raises(RunTagError) as error:
        parse_env("note:a,b")
    assert str(error.value) == (
        "FUNCTUALIZE_RUN_TAGS item 1 'note:a,b': a run tag value cannot contain ','."
    )


def test_env_space_after_comma_still_separates_tags(
    cli_run, project_tree, xdg_dirs, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("FUNCTUALIZE_RUN_TAGS", "harness:claude, model:opus")
    root = project_tree(jobs=_JOB)

    result = cli_run(["release"], cwd=root)

    assert result.exit_code == 0, result.stderr
    assert [record["run_tags"] for record in _records(root, xdg_dirs.cache)] == [
        {"harness": "claude", "model": "opus"}
    ]
    assert parse_env("") == {}
    assert parse_env(" , ") == {}
    with pytest.raises(RunTagError, match="missing ':'"):
        parse_env("missing-colon")


class TestThreeLayersMerge:
    def test_config_env_and_flag_merge_per_key(
        self, cli_run, project_tree, xdg_dirs, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """AC2: `{host:laptop, tier:1}` + `{tier:2, model:opus}` + `{model:sonnet}`."""
        _write_config(xdg_dirs, '[run]\ntags = ["host:laptop", "tier:1"]\n')
        monkeypatch.setenv("FUNCTUALIZE_RUN_TAGS", "tier:2,model:opus")
        root = project_tree(jobs=_JOB)

        result = cli_run(["--run-tag", "model:sonnet", "release"], cwd=root)

        assert result.exit_code == 0, result.stderr
        assert [r["run_tags"] for r in _records(root, xdg_dirs.cache)] == [
            {"host": "laptop", "tier": "2", "model": "sonnet"}
        ]

    def test_env_items_are_trimmed_and_blanks_skipped(
        self, cli_run, project_tree, xdg_dirs, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """AC4: `${CLAUDECODE:+harness:claude}, model:opus` with CLAUDECODE unset."""
        monkeypatch.setenv("FUNCTUALIZE_RUN_TAGS", ", model:opus")
        root = project_tree(jobs=_JOB)

        result = cli_run(["release"], cwd=root)

        assert result.exit_code == 0, result.stderr
        assert [r["run_tags"] for r in _records(root, xdg_dirs.cache)] == [
            {"model": "opus"}
        ]

    def test_the_project_file_is_not_a_layer(
        self, cli_run, project_tree, xdg_dirs
    ) -> None:
        """AC12: `[run] tags` in `.functualize.toml` contributes nothing."""
        root = project_tree(functualize_toml='[run]\ntags = ["repo:x"]\n', jobs=_JOB)

        result = cli_run(["release"], cwd=root)

        assert result.exit_code == 0, result.stderr
        assert "[run]" not in result.stderr
        assert [r["run_tags"] for r in _records(root, xdg_dirs.cache)] == [{}]


class TestDuplicates:
    """AC9: across layers a key merges; inside one layer it is refused."""

    @pytest.mark.parametrize(
        ("config", "env", "flags", "expected"),
        [
            pytest.param(
                '[run]\ntags = ["s:1"]\n', "s:2", [], {"s": "2"}, id="env>config"
            ),
            pytest.param(None, "s:2", ["s:3"], {"s": "3"}, id="flag>env"),
            pytest.param(
                '[run]\ntags = ["s:1"]\n', None, ["s:3"], {"s": "3"}, id="flag>config"
            ),
        ],
    )
    def test_a_key_across_layers_merges(
        self,
        cli_run,
        project_tree,
        xdg_dirs,
        monkeypatch: pytest.MonkeyPatch,
        config: str | None,
        env: str | None,
        flags: list[str],
        expected: dict[str, str],
    ) -> None:
        if config is not None:
            _write_config(xdg_dirs, config)
        if env is not None:
            monkeypatch.setenv("FUNCTUALIZE_RUN_TAGS", env)
        root = project_tree(jobs=_JOB)
        argv = [arg for flag in flags for arg in ("--run-tag", flag)]

        result = cli_run([*argv, "release"], cwd=root)

        assert result.exit_code == 0, result.stderr
        assert [r["run_tags"] for r in _records(root, xdg_dirs.cache)] == [expected]

    @pytest.mark.parametrize(
        ("config", "env", "flags", "message"),
        [
            pytest.param(
                None,
                None,
                ["s:1", "s:2"],
                "run tag key 's' is given twice (--run-tag s:1, --run-tag s:2).",
                id="flag",
            ),
            pytest.param(
                None,
                "s:1,s:2",
                [],
                "FUNCTUALIZE_RUN_TAGS gives run tag key 's' twice (items 1 and 2).",
                id="env",
            ),
            pytest.param(
                '[run]\ntags = ["s:1", "s:2"]\n',
                None,
                [],
                "[run] tags gives run tag key 's' twice (items 1 and 2).",
                id="config",
            ),
        ],
    )
    def test_a_key_twice_in_one_layer_is_refused_naming_it(
        self,
        cli_run,
        project_tree,
        xdg_dirs,
        monkeypatch: pytest.MonkeyPatch,
        config: str | None,
        env: str | None,
        flags: list[str],
        message: str,
    ) -> None:
        if config is not None:
            _write_config(xdg_dirs, config)
        if env is not None:
            monkeypatch.setenv("FUNCTUALIZE_RUN_TAGS", env)
        root = project_tree(jobs=_JOB)
        argv = [arg for flag in flags for arg in ("--run-tag", flag)]

        result = cli_run([*argv, "release"], cwd=root)

        assert result.exit_code == 2
        assert f"Error: {message}" in result.stderr
        assert "released" not in result.stdout
        assert _records(root, xdg_dirs.cache) == []


class TestTheConfigLayerIsReadQuietly:
    def test_no_source_is_an_empty_read_only_map(self, xdg_dirs) -> None:
        from functualize._cli.main import _merge_run_tags

        merged = _merge_run_tags(None)

        assert dict(merged) == {}
        with pytest.raises(TypeError):
            merged["k"] = "v"  # type: ignore[index]

    @pytest.mark.parametrize(
        "text",
        [
            pytest.param("[run\n", id="malformed-toml"),
            pytest.param('run = "a:b"\n', id="run-not-a-table"),
            pytest.param("[cli]\noutput = 'json'\n", id="no-run-section"),
        ],
    )
    def test_a_config_without_usable_tags_contributes_none_silently(
        self, xdg_dirs, capsys: pytest.CaptureFixture[str], text: str
    ) -> None:
        from functualize._cli.main import _merge_run_tags

        _write_config(xdg_dirs, text)

        assert dict(_merge_run_tags(["a:b"])) == {"a": "b"}
        assert capsys.readouterr().err == ""

    def test_a_stray_key_beside_the_tags_stays_off_the_run_path(
        self, cli_run, project_tree, xdg_dirs
    ) -> None:
        """The run path is quiet: ADR-042 reports unknown keys on the surfaces
        that inspect configuration, never on stderr. A stray key beside `tags`
        must not stop the declared key from being read, and the pre-boot read
        still adds nothing of its own."""
        _write_config(xdg_dirs, '[run]\ntags = ["a:b"]\nbogus = 1\n')
        root = project_tree(jobs=_JOB)

        result = cli_run(["release"], cwd=root)

        assert result.exit_code == 0, result.stderr
        assert result.stderr == ""
        assert [r["run_tags"] for r in _records(root, xdg_dirs.cache)] == [{"a": "b"}]
