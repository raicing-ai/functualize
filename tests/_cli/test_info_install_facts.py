"""`builtin info` reports how this func was installed.

The property worth guarding is not that the fields exist — it is that they are
distinguishable from the ones already there. `info` prints a `Mode:` line for
*state storage* whose value can also be the word `standalone`, meaning "no
project directory found" rather than "the pre-baked binary". Two lines reading
`standalone` and meaning different things is the failure this labelling avoids.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from functualize._cli.info import install_facts


class TestTheFactsThemselves:
    def test_the_overview_form_carries_mode_and_owner(self) -> None:
        facts = install_facts(include_manifest=False)
        assert set(facts) == {"mode", "owning_distribution"}

    def test_the_full_form_adds_the_manifest(self) -> None:
        facts = install_facts(include_manifest=True)
        assert "manifest" in facts

    def test_the_manifest_summary_counts_rather_than_lists(self) -> None:
        """The overview is a summary; enumerating belongs to `self doctor`."""
        manifest = install_facts(include_manifest=True)["manifest"]
        if manifest is not None:
            assert set(manifest) == {"path", "installations", "stale"}

    def test_a_pinned_mode_is_reported(self, monkeypatch) -> None:
        monkeypatch.setenv("FUNCTUALIZE_RUNTIME", "tool_pipx")
        assert install_facts(include_manifest=False)["mode"] == "tool_pipx"

    def test_it_never_raises_into_info(self, monkeypatch) -> None:
        """`info` must not die because a detail about the install is unreadable."""
        monkeypatch.setenv("FUNCTUALIZE_RUNTIME", "not-a-mode")
        facts = install_facts(include_manifest=False)
        assert facts == {"mode": None, "owning_distribution": None}


class TestTheJsonPayload:
    def test_info_all_json_carries_the_install_block(
        self, cli_run, tmp_path: Path
    ) -> None:
        """AC20 — nested under `install`, not flattened into the top level."""
        result = cli_run(["builtin", "info", "all", "--json"], cwd=tmp_path)
        assert result.exit_code == 0
        payload = json.loads(result.stdout)

        assert "install" in payload
        assert "mode" in payload["install"]
        assert "owning_distribution" in payload["install"]
        assert "manifest" in payload["install"]

    def test_the_top_level_has_no_bare_mode_key(self, cli_run, tmp_path: Path) -> None:
        """AC20a, in the JSON. Nesting is what keeps the two senses apart.

        A parser reading `payload["mode"]` must not be able to get the install
        mode by accident — the document already has another notion of mode.
        """
        result = cli_run(["builtin", "info", "all", "--json"], cwd=tmp_path)
        payload = json.loads(result.stdout)
        assert "mode" not in payload

    def test_the_pinned_mode_reaches_the_payload(self, cli_run, tmp_path: Path) -> None:
        result = cli_run(
            ["builtin", "info", "all", "--json"],
            cwd=tmp_path,
            env={"FUNCTUALIZE_RUNTIME": "standalone"},
        )
        assert json.loads(result.stdout)["install"]["mode"] == "standalone"


class TestTheTextRendering:
    def test_plain_output_labels_it_install_mode(self, cli_run, tmp_path: Path) -> None:
        """AC20a — the label carries the disambiguation, not the value."""
        result = cli_run(
            ["builtin", "info"],
            cwd=tmp_path,
            env={
                "FUNCTUALIZE_CLI_OUTPUT": "plain",
                "FUNCTUALIZE_RUNTIME": "standalone",
            },
        )
        assert "install mode: standalone" in result.stdout

    def test_both_senses_are_distinguishable_when_both_read_standalone(
        self, cli_run, tmp_path: Path
    ) -> None:
        """The collision this labelling exists for, exercised directly.

        `tmp_path` has no `.functualize/`, so state storage reports
        `standalone`. Pinning the install mode to `standalone` too puts both
        senses of the word in one document — and a reader must still be able to
        tell which is which.
        """
        result = cli_run(
            ["builtin", "info", "all"],
            cwd=tmp_path,
            env={
                "FUNCTUALIZE_CLI_OUTPUT": "plain",
                "FUNCTUALIZE_RUNTIME": "standalone",
            },
        )
        assert "install mode: standalone" in result.stdout
        # Whatever else the document says about "standalone", the install
        # sense is the labelled one and is not a bare `mode:` line.
        assert "\nmode: standalone" not in result.stdout


class TestNoNewCommandsWereAdded:
    def test_there_is_no_self_paths(self, cli_run, tmp_path: Path) -> None:
        """AC21 — O3 folded these in rather than shipping two more commands."""
        result = cli_run(["builtin", "self", "paths"], cwd=tmp_path)
        assert result.exit_code != 0

    def test_there_is_no_self_config_info(self, cli_run, tmp_path: Path) -> None:
        result = cli_run(["builtin", "self", "config-info"], cwd=tmp_path)
        assert result.exit_code != 0

    def test_config_path_still_answers_where_the_files_are(
        self, cli_run, tmp_path: Path
    ) -> None:
        """The command the folded ones would have duplicated is untouched."""
        result = cli_run(["builtin", "config", "path"], cwd=tmp_path)
        assert result.exit_code == 0


@pytest.mark.surfaces("app")
def test_a_consumer_app_reports_its_own_distribution(cli_run, tmp_path: Path) -> None:
    """The fourth audience: `info` on an app built on functualize.

    Detection resolves the owner from the running console script, so an app
    gets its own name here rather than `functualize` — which is the whole
    reason every mutating command names the axis-2 distribution.
    """
    result = cli_run(["builtin", "info", "all", "--json"], cwd=tmp_path)
    assert result.exit_code == 0
    assert "install" in json.loads(result.stdout)
