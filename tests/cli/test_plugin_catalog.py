"""`func builtin plugin available` — discovering plugins you do not have yet.

`plugin list` reads `importlib.metadata`, so it can only report what is already
installed. A user who has never heard of `functualize-mcp` had no way to learn
it exists, what kind of thing it is, or whether they want it.

The three kinds matter more than the listing does. An adapter adds commands
anyone might want; a domain publishes the protocol a capability is written
against; an implementation is a backend chosen for the infrastructure you
already run — and two implementations of one domain is a decision, not a richer
setup. Presenting them as one flat list actively misleads.

Everything here feeds `available_rows` its three inputs directly. A merge rule
exercised only against whatever happens to be installed is untestable in
precisely the cases that matter — including the one this checkout can never
reproduce, since its dev environment has every plugin synced.
"""

from __future__ import annotations

import tomllib
from pathlib import Path

import pytest

from functualize._cli.plugin_cmd import (
    CatalogEntry,
    ExtensionEntry,
    available_rows,
    load_catalog,
    recommended_distributions,
    render_available,
)

REPO_ROOT = Path(__file__).resolve().parents[2]


# ── The shipped manifest ─────────────────────────────────────────────────────


class TestManifestIsLoadable:
    def test_catalog_is_not_empty(self) -> None:
        assert load_catalog(), "the shipped manifest failed to load"

    def test_every_entry_classifies(self) -> None:
        """A group typo would silently produce an `unknown` kind."""
        unknown = [e.name for e in load_catalog() if e.kind == "unknown"]
        assert not unknown, f"unclassifiable groups in the manifest: {unknown}"

    def test_all_three_kinds_are_represented(self) -> None:
        assert {e.kind for e in load_catalog()} == {
            "adapter",
            "domain",
            "implementation",
        }

    def test_the_manifest_ships_inside_the_package(self) -> None:
        """A data file next to `.py` siblings is easy to leave out of a wheel."""
        from functualize._cli import plugin_cmd

        path = Path(plugin_cmd.__file__).parent / "data" / plugin_cmd.CATALOG_FILENAME
        assert path.is_file(), f"manifest missing at {path}"


class TestManifestMatchesReality:
    def test_every_distribution_exists(self) -> None:
        """AC-B12 — a manifest can name a package that was never published.

        `plugins/PUBLISHING.md` records exactly that happening:
        "`functualize-interactivity` appeared in earlier revisions of this
        document. No such package has ever existed in this repository."
        """
        missing = [
            e.distribution
            for e in load_catalog()
            if not (REPO_ROOT / "plugins" / e.distribution).is_dir()
        ]
        assert not missing, f"manifest names non-existent plugin dirs: {missing}"

    def test_recommended_set_matches_the_all_extra(self) -> None:
        """AC-B7 — two lists of "everything" is one too many.

        Adding a plugin to `[all]` without updating the manifest fails here.
        """
        data = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text())
        extra = {
            name
            for name in data["project"]["optional-dependencies"]["all"]
            if name.startswith("functualize-")
        }
        assert set(recommended_distributions()) == extra

    def test_bitwarden_is_deliberately_not_recommended(self) -> None:
        """AC-B8 — and here is why, so nobody "fixes" it.

        `bitwarden-sdk` publishes wheels for glibc, macOS and Windows only,
        with no sdist, so including it makes `functualize[all]` UNRESOLVABLE on
        both musl targets. `[all]` is what the standalone binary bakes
        (PYAPP_PROJECT_FEATURES=all), so the Alpine and distroless binaries
        could not be built at all. There is no PEP 508 marker for musl vs
        glibc, so it cannot be excluded conditionally.
        """
        assert "functualize-bitwarden" not in recommended_distributions()
        entry = next(
            e for e in load_catalog() if e.distribution == "functualize-bitwarden"
        )
        assert entry.recommended is False


# ── Merging catalog, installed, and remote ───────────────────────────────────


def _curated(name="mcp", dist="functualize-mcp", group="functualize.plugins", rec=True):
    return CatalogEntry(
        name=name,
        distribution=dist,
        group=group,
        description="d",
        recommended=rec,
    )


class TestMergeMarksWhatIsInstalled:
    def test_a_not_installed_plugin_is_marked_so(self) -> None:
        """The case this checkout cannot reproduce: its env has everything."""
        (row,) = available_rows([_curated()], [])
        assert row.installed is False
        assert row.recommended is True
        assert row.source == "catalog"

    def test_an_installed_plugin_is_marked_so(self) -> None:
        installed = [ExtensionEntry("mcp", "functualize-mcp", "functualize.plugins")]
        (row,) = available_rows([_curated()], installed)
        assert row.installed is True


class TestLiveMetadataWinsOverTheManifest:
    def test_kind_comes_from_the_installed_group(self) -> None:
        """AC-B5 — installed metadata is a fact; the manifest is a record."""
        stale = _curated(group="functualize.plugins")
        installed = [
            ExtensionEntry("mcp", "functualize-mcp", "functualize.state_providers")
        ]
        (row,) = available_rows([stale], installed)
        assert row.kind == "implementation", "manifest overrode live metadata"

    def test_kind_comes_from_the_manifest_when_absent(self) -> None:
        (row,) = available_rows([_curated(group="functualize.domains")], [])
        assert row.kind == "domain"


class TestThirdPartyPlugins:
    def test_an_installed_plugin_the_manifest_never_heard_of_is_listed(self) -> None:
        """The reason kind is derived rather than enumerated."""
        installed = [
            ExtensionEntry("vault", "somebody-elses-plugin", "functualize.plugins")
        ]
        rows = available_rows([], installed)
        assert [(r.name, r.kind, r.source) for r in rows] == [
            ("vault", "adapter", "installed")
        ]

    def test_a_novel_provider_group_classifies(self) -> None:
        """AC-B4 — no such group exists here; it must still classify."""
        installed = [ExtensionEntry("v", "third-party", "functualize.vault_providers")]
        (row,) = available_rows([], installed)
        assert row.kind == "implementation"

    def test_the_core_distribution_is_not_offered(self) -> None:
        """Core publishes its own groups; it is not something you install."""
        installed = [ExtensionEntry("toml", "functualize", "functualize.plugins")]
        assert available_rows([], installed) == []

    def test_an_unreadable_distribution_is_skipped(self) -> None:
        installed = [ExtensionEntry("x", None, "functualize.plugins")]
        assert available_rows([], installed) == []


class TestRemoteRows:
    def test_remote_rows_are_marked_uncurated(self) -> None:
        rows = available_rows([], [], ["functualize-somebody-else"])
        (row,) = rows
        assert row.source == "remote"
        assert row.installed is False
        assert row.recommended is False
        assert row.kind == "unknown", (
            "a package index cannot know the entry-point group; that lives in "
            "the distribution's metadata"
        )

    def test_a_remote_name_already_curated_is_not_duplicated(self) -> None:
        rows = available_rows([_curated()], [], ["functualize-mcp"])
        assert len(rows) == 1
        assert rows[0].source == "catalog"


# ── Rendering ────────────────────────────────────────────────────────────────


class TestRendering:
    def test_rows_are_grouped_under_kind_headings(self) -> None:
        rows = available_rows(
            [
                _curated("mcp", "functualize-mcp", "functualize.plugins"),
                _curated("state", "functualize-state", "functualize.domains"),
                _curated(
                    "bws", "functualize-bitwarden", "functualize.remote_providers"
                ),
            ],
            [],
        )
        text = "\n".join(render_available(rows))
        assert "ADAPTERS" in text
        assert "DOMAINS" in text
        assert "IMPLEMENTATIONS" in text
        assert text.index("ADAPTERS") < text.index("IMPLEMENTATIONS")

    def test_an_empty_listing_says_so(self) -> None:
        assert render_available([]) == ["  no plugins known"]


# ── The offline guarantee ────────────────────────────────────────────────────


class TestWorksOffline:
    def test_no_socket_is_opened_without_remote(self, cli_run, monkeypatch) -> None:
        """AC-B3 — offline is the default, and "default" must mean no request."""

        def _forbidden(*args, **kwargs):
            raise AssertionError("plugin available opened a socket without --remote")

        monkeypatch.setattr("socket.socket", _forbidden)
        result = cli_run(["builtin", "plugin", "available"])
        assert result.exit_code == 0
        assert "ADAPTERS" in result.stdout

    def test_json_output_is_parseable(self, cli_run) -> None:
        """AC-B2 — the fields an agent reads."""
        import json

        result = cli_run(["builtin", "plugin", "available", "--format", "json"])
        assert result.exit_code == 0
        rows = json.loads(result.stdout)
        assert rows
        assert set(rows[0]) == {
            "name",
            "distribution",
            "kind",
            "description",
            "installed",
            "recommended",
            "source",
        }


class TestRemoteDegradesGracefully:
    def test_a_network_failure_still_lists_the_catalog(
        self, cli_run, monkeypatch
    ) -> None:
        """AC-B11 — a listing is worth more than an error."""

        def _boom(*args, **kwargs):
            raise OSError("no network")

        monkeypatch.setattr(
            "functualize._cli.plugin_cmd._fetch_remote_distributions", _boom
        )
        result = cli_run(["builtin", "plugin", "available", "--remote"])
        assert result.exit_code == 0
        assert "ADAPTERS" in result.stdout
        assert "could not reach PyPI" in result.stderr


# ── install --recommended ────────────────────────────────────────────────────


class TestInstallRecommended:
    def test_it_is_mutually_exclusive_with_a_package_name(self, cli_run) -> None:
        result = cli_run(
            ["builtin", "plugin", "install", "--recommended", "some-package"]
        )
        assert result.exit_code != 0
        assert "cannot be combined" in result.stderr

    def test_naming_nothing_is_a_usage_error(self, cli_run) -> None:
        result = cli_run(["builtin", "plugin", "install"])
        assert result.exit_code != 0
        assert "--recommended" in result.stderr

    def test_it_plans_every_recommended_package(self, cli_run, monkeypatch) -> None:
        """AC-B9 — the same mechanism, a different input.

        Stops at the plan: actually running installs in a test would mutate the
        developer's environment.
        """
        planned: list[str] = []

        def _fake_install_commands(detection, name):
            planned.append(name)
            return (("uv", "pip", "install", name),)

        monkeypatch.setattr(
            "functualize.app.packaging.install_commands", _fake_install_commands
        )
        monkeypatch.setattr(
            "functualize._cli.package_ops.run_commands", lambda commands: 0
        )
        result = cli_run(["builtin", "plugin", "install", "--recommended", "--yes"])

        assert result.exit_code == 0, result.stderr
        assert planned == list(recommended_distributions())


def test_recommended_set_is_non_empty() -> None:
    assert recommended_distributions()


@pytest.mark.parametrize("distribution", recommended_distributions())
def test_recommended_entries_are_all_curated(distribution: str) -> None:
    assert distribution.startswith("functualize-")
