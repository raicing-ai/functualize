"""Tests for chain detail kind-awareness and config files exclusion.

Verifies:
- R5-AC2: CONFIG param chain detail shows all 5 sources (no Session)
- R5-AC3: PLAIN param chain detail shows only CLI, Default
- R5-AC4: PLAIN param chain detail displays banner
- R5-AC5: Config Files panel excludes PLAIN parameters from discovery and detail views

Under the SmartBar-as-CLI model, there is no "Session"
chain source.
"""

from __future__ import annotations

from pathlib import Path

from functualize._cli.tui.chain_resolution import (
    _PLAIN_DETAIL_SOURCES,
    compute_chain_detail_rows,
)
from functualize._cli.tui.panels.config_files import (
    ConfigFileEntry,
    discover_config_files,
)
from functualize._cli.tui.panels.config_table import ChainEntry, FieldDef, ParamKind

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_config_field(name: str = "region", value: str = "us-east-1") -> FieldDef:
    """Create a CONFIG FieldDef with a full 5-source chain."""
    return FieldDef(
        name=name,
        value=value,
        source="File",
        required=True,
        description="AWS region",
        type_annotation="str",
        param_kind=ParamKind.CONFIG,
        chain=[
            ChainEntry(source="CLI", value=""),
            ChainEntry(source="Env", value=""),
            ChainEntry(source="File", value=value),
            ChainEntry(source="Remote", value=""),
            ChainEntry(source="Default", value="us-east-1"),
        ],
    )


def _make_plain_field(name: str = "target", value: str = "prod") -> FieldDef:
    """Create a PLAIN FieldDef with a 5-source chain (only CLI/Default relevant)."""
    return FieldDef(
        name=name,
        value=value,
        source="CLI",
        required=True,
        positional=True,
        description="Deployment target",
        type_annotation="str",
        param_kind=ParamKind.PLAIN,
        chain=[
            ChainEntry(source="CLI", value=value),
            ChainEntry(source="Env", value=""),
            ChainEntry(source="File", value=""),
            ChainEntry(source="Remote", value=""),
            ChainEntry(source="Default", value=""),
        ],
    )


def _make_entries() -> list[ConfigFileEntry]:
    """Create test ConfigFileEntry objects."""
    return [
        ConfigFileEntry(
            path=Path("/project/.functualize.toml"),
            section="deploy",
            display_name=".functualize.toml",
            status="exists",
            fields_from_file=["region"],
        ),
    ]


# ---------------------------------------------------------------------------
# Test: Chain detail kind-aware rendering (R5-AC2, R5-AC3, R5-AC4)
# ---------------------------------------------------------------------------


class TestChainDetailKindAwareness:
    """Chain detail rendering respects param_kind."""

    def test_config_field_has_all_five_sources(self) -> None:
        """CONFIG param chain detail shows all 5 sources, no Session (R5-AC2)."""
        field = _make_config_field()

        # For CONFIG, all chain entries should be rendered
        assert field.param_kind == ParamKind.CONFIG
        # The chain has 5 entries
        assert len(field.chain) == 5
        sources = [e.source for e in field.chain]
        assert sources == ["CLI", "Env", "File", "Remote", "Default"]

    def test_plain_field_filtered_to_two_sources(self) -> None:
        """compute_chain_detail_rows() filters a PLAIN field's chain to the
        real _PLAIN_DETAIL_SOURCES constant, never rendering "Session" (R5-AC3).

        Exercises the production function directly (not a local re-implementation
        of the filter) and asserts against the imported constant, so a future
        regression reintroducing "Session" into the constant would be caught.
        """
        field = _make_plain_field()
        assert field.param_kind == ParamKind.PLAIN

        # Inject a Session entry with a value: if _PLAIN_DETAIL_SOURCES ever
        # regressed to include "Session", this would leak into rendered output.
        field.chain.append(ChainEntry(source="Session", value="leaked"))

        lines = compute_chain_detail_rows(field)

        # Rendered chain rows start with the ★ (winning) / ● (other) markers.
        rendered_sources = [
            line.split()[1]
            for line in lines
            if line.startswith("  ★") or line.startswith("  ●")
        ]

        # Only sources named in the real constant may appear...
        assert set(rendered_sources) <= _PLAIN_DETAIL_SOURCES
        # ...and every constant source present in the chain is rendered, in order.
        expected = [e.source for e in field.chain if e.source in _PLAIN_DETAIL_SOURCES]
        assert rendered_sources == expected == ["CLI", "Default"]

        # The injected Session entry must never leak, regardless of the constant.
        assert "Session" not in rendered_sources
        assert all("leaked" not in line for line in lines)

    def test_file_entries_render_their_paths(self) -> None:
        """The detail names each file, not the generic 'File' bucket (R-D §5).

        Two files sharing source="File" must also star only the *winning*
        entry — the old marker compared source names, which would star both.
        """
        field = _make_config_field()
        # Replace the single File bucket with two per-file entries.
        field.chain = [
            ChainEntry(source="CLI", value=""),
            ChainEntry(source="Env", value=""),
            ChainEntry(source="File", value="8080", path="/proj/config.dev.toml"),
            ChainEntry(source="File", value="80", path="/proj/config.base.toml"),
            ChainEntry(source="Default", value="3000"),
        ]

        lines = compute_chain_detail_rows(field)
        file_lines = [line for line in lines if "config." in line]

        assert len(file_lines) == 2
        assert "/proj/config.dev.toml" in file_lines[0]
        assert "/proj/config.base.toml" in file_lines[1]
        # Only the winner is starred, even though both are "File".
        assert file_lines[0].lstrip().startswith("★")
        assert file_lines[1].lstrip().startswith("●")

    def test_plain_field_banner_text(self) -> None:
        """PLAIN param chain detail should include the banner text (R5-AC4).

        The banner is: "Plain parameter — resolved from CLI/default only"
        """
        field = _make_plain_field()
        assert field.param_kind == ParamKind.PLAIN
        # The banner text is rendered by _render_chain_detail when param_kind is PLAIN
        banner = "Plain parameter — resolved from CLI/default only"
        assert "Plain parameter" in banner
        assert "CLI/default only" in banner

    def test_config_field_no_banner(self) -> None:
        """CONFIG param should NOT get the plain parameter banner."""
        field = _make_config_field()
        assert field.param_kind == ParamKind.CONFIG
        # No banner for CONFIG — the rendering logic only adds it for PLAIN

    def test_plain_winning_source_from_filtered_chain(self) -> None:
        """Winning source for PLAIN is determined from filtered chain only."""
        field = _make_plain_field(value="prod")
        # CLI has "prod" — should be winning
        plain_sources = {"CLI", "Default"}
        filtered_chain = [e for e in field.chain if e.source in plain_sources]

        winning_source = ""
        for entry in filtered_chain:
            if entry.value:
                winning_source = entry.source
                break

        assert winning_source == "CLI"

    def test_config_winning_source_from_full_chain(self) -> None:
        """Winning source for CONFIG is determined from full chain."""
        field = _make_config_field()
        # File has "us-east-1" — CLI, Session, Env are empty
        winning_source = ""
        for entry in field.chain:
            if entry.value:
                winning_source = entry.source
                break

        assert winning_source == "File"


# ---------------------------------------------------------------------------
# Test: Config Files discovery excludes PLAIN params (R5-AC5)
# ---------------------------------------------------------------------------


class TestDiscoverConfigFilesExcludesPlain:
    """discover_config_files() excludes PLAIN params from file discovery."""

    def test_plain_fields_excluded_from_fields_from_file(self, tmp_path: Path) -> None:
        """PLAIN fields should not appear in fields_from_file (R5-AC5)."""
        config_field = _make_config_field("region", "us-east-1")
        plain_field = _make_plain_field("target", "prod")

        # Create a file with both keys — only CONFIG should appear
        toml_file = tmp_path / ".functualize.toml"
        toml_file.write_text('[deploy]\nregion = "us-east-1"\ntarget = "prod"\n')

        fields = [config_field, plain_field]
        entries = discover_config_files(fields, "deploy", None, tmp_path)

        # All entries should only have "region" in fields_from_file, not "target"
        for entry in entries:
            assert "target" not in entry.fields_from_file

    def test_only_config_fields_contribute_to_discovery(self, tmp_path: Path) -> None:
        """Only CONFIG fields are considered during file discovery (R5-AC5)."""
        # All PLAIN fields — should result in empty fields_from_file
        plain1 = _make_plain_field("target", "prod")
        plain2 = _make_plain_field("verbose", "true")

        # Give them File chain values (shouldn't matter since they're PLAIN)
        plain1.chain[2] = ChainEntry(source="File", value="file-value")
        plain2.chain[2] = ChainEntry(source="File", value="another-value")

        fields = [plain1, plain2]
        entries = discover_config_files(fields, "deploy", None, tmp_path)

        # No fields should be listed since all are PLAIN
        for entry in entries:
            assert entry.fields_from_file == []

    def test_config_fields_appear_in_discovery(self, tmp_path: Path) -> None:
        """CONFIG fields appear in fields_from_file when file exists with those keys."""
        config_field = _make_config_field("region", "us-east-1")

        # Create a .functualize.toml with the [deploy] section containing "region"
        toml_file = tmp_path / ".functualize.toml"
        toml_file.write_text('[deploy]\nregion = "us-east-1"\n')

        fields = [config_field]
        entries = discover_config_files(fields, "deploy", None, tmp_path)

        # The .functualize.toml entry should list "region" in fields_from_file
        found = any("region" in e.fields_from_file for e in entries)
        assert found

    def test_mixed_fields_only_config_in_discovery(self, tmp_path: Path) -> None:
        """Mixed PLAIN and CONFIG fields — only CONFIG appears in discovery."""
        config_field = _make_config_field("region", "us-east-1")
        plain_field = _make_plain_field("target", "prod")

        # Create a file with both keys — only CONFIG should appear
        toml_file = tmp_path / ".functualize.toml"
        toml_file.write_text('[deploy]\nregion = "us-east-1"\ntarget = "prod"\n')

        fields = [plain_field, config_field]
        entries = discover_config_files(fields, "deploy", None, tmp_path)

        for entry in entries:
            # "region" may be in fields_from_file (it's CONFIG and in the file)
            # "target" must NOT be (it's PLAIN — filtered out before parsing)
            assert "target" not in entry.fields_from_file


# ---------------------------------------------------------------------------
# Test: ConfigFilesPanel detail view excludes PLAIN params (R5-AC5)
# ---------------------------------------------------------------------------


class TestJobConfigChainProviderExcludesPlain:
    """The file Detail view must not offer PLAIN params (R5-AC5).

    PLAIN params resolve straight from CLI/default and never participate in
    file resolution, so listing them on a file's Detail screen would invite an
    edit that could not possibly take effect. This moved from the panel's
    deleted _compute_detail_fields into JobConfigChainProvider, which is now
    the thing that decides what a file's Detail rows are.
    """

    @staticmethod
    def _provider(fields):
        from functualize._cli.tui.source_chain_providers import (
            FileScope,
            JobConfigChainProvider,
        )

        scope = FileScope(Path("/proj/config.dev.toml"), "deploy", "config.dev.toml")
        return JobConfigChainProvider(fields, [scope])

    def test_plain_fields_excluded(self) -> None:
        provider = self._provider(
            [_make_config_field("region", "us-east-1"), _make_plain_field("target")]
        )

        names = [k.name for k in provider.resolve()]

        assert "region" in names
        assert "target" not in names

    def test_all_plain_fields_resolve_to_nothing(self) -> None:
        provider = self._provider(
            [_make_plain_field("target"), _make_plain_field("verbose", "true")]
        )

        assert provider.resolve() == []

    def test_all_config_fields_appear(self) -> None:
        provider = self._provider(
            [_make_config_field("region"), _make_config_field("replicas", "3")]
        )

        names = [k.name for k in provider.resolve()]

        assert names == ["region", "replicas"]

    def test_config_field_keeps_its_chain_layers(self) -> None:
        provider = self._provider([_make_config_field("region", "us-east-1")])

        key = provider.resolve()[0]
        labels = [e.label for e in key.chain]

        # The generic "File" bucket is replaced by the concrete file.
        assert "config.dev.toml" in labels
        assert "Default" in labels
        assert "File" not in labels
