"""The vocabulary check: what a settings document carries that we do not know.

The check exists so that two surfaces can say the same thing about the same
file: the annotation on ``config path`` and ``config.unknown_keys`` in
``info --json``. Its contract is narrow on purpose -- it answers, it does not
act. A key it reports is still read exactly as before, and no exit code moves
because of it.
"""

from __future__ import annotations

import re
import tomllib
from pathlib import Path
from typing import TYPE_CHECKING

from functualize._cli.data.config_vocabulary import (
    UnknownKey,
    describe,
    find_unknown_keys,
    unknown_keys_in_layers,
)
from functualize._config.settings_layers import settings_layers
from functualize.plugin import FUNCTUALIZE_SETTINGS, ROOT_KEY

if TYPE_CHECKING:
    import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]

_TOML_BLOCK = re.compile(r"```toml\n(.*?)```", re.DOTALL)
_SECTION_HEADER = re.compile(r"^\[([A-Za-z0-9_.-]+)\]", re.MULTILINE)


def _find(content: str, *, name: str = ".functualize.toml") -> tuple[UnknownKey, ...]:
    """Run the check over a document, as a reader of ``name`` would."""
    return find_unknown_keys(
        tomllib.loads(content),
        file=Path(name),
        schema=FUNCTUALIZE_SETTINGS,
    )


def _keys(content: str) -> list[str]:
    return [finding.key for finding in _find(content)]


class TestWhatCountsAsAKnownKey:
    """The declaration decides, not a list maintained beside it."""

    def test_a_declared_key_is_not_reported(self) -> None:
        assert (
            _find(
                "dotenv = true\nimport_libs = []\n"
                '[cli]\noutput = "rich"\n'
                '[tui]\ntheme = "dark"\n'
                "[vault]\nkeyring_timeout = 5\n"
            )
            == ()
        )

    def test_root_is_a_known_top_level_key(self) -> None:
        """``root`` stops the upward walk; it is structure, not a setting."""
        assert _keys(f"{ROOT_KEY} = true\n") == []

    def test_a_job_section_table_is_not_a_key(self) -> None:
        """A ``[my-job]`` table names a job, so nothing in it is ours."""
        assert _find('[my-job]\ncommand = "deploy"\nretries = 3\n') == ()

    def test_an_array_of_tables_is_not_a_key(self) -> None:
        assert _find('[[vault_secret]]\nname = "token"\ngroup = "infra"\n') == ()

    def test_a_table_nested_in_a_section_is_not_a_key(self) -> None:
        assert _find('[tui.nested]\ntheme = "dark"\n') == ()

    def test_a_freeform_section_accepts_any_key(self) -> None:
        """``[aliases]`` maps a name the author chooses to a command."""
        assert _find('[aliases]\nserve = "jobs.serve"\nanything_at_all = "x"\n') == ()

    def test_an_unknown_section_is_not_inspected(self) -> None:
        assert _find("[not_a_section]\nnot_a_key = 1\n") == ()

    def test_a_key_read_from_a_job_file_is_not_a_settings_key(self) -> None:
        """``[discovery] jobs_directories`` lives at the top level only."""
        assert _keys('[discovery]\njobs_directories = ["jobs"]\n') == [
            "discovery.jobs_directories"
        ]


class TestFindings:
    """Every finding names its file and its key as the author wrote it."""

    def test_a_top_level_key_keeps_its_own_name(self) -> None:
        (finding,) = _find("definitely_not_a_setting = 1\n")

        assert finding.key == "definitely_not_a_setting"
        assert finding.suggestion is None
        assert finding.file == Path(".functualize.toml")

    def test_a_section_key_is_dotted(self) -> None:
        (finding,) = _find("[cli]\ninline_tuii = true\n")

        assert finding.key == "cli.inline_tuii"

    def test_a_close_declared_key_is_suggested(self) -> None:
        (finding,) = _find("roots = true\n")

        assert finding.suggestion == ROOT_KEY

    def test_a_misspelt_section_key_suggests_a_key_from_its_own_section(self) -> None:
        (finding,) = _find('[tui]\nthem = "dark"\n')

        assert finding.key == "tui.them"
        assert finding.suggestion == "tui.theme"

    def test_findings_follow_document_order(self) -> None:
        assert _keys(
            "zzz_top = 1\naaa_top = 3\n[cli]\nzzz_in_cli = 1\naaa_in_cli = 2\n"
        ) == ["zzz_top", "aaa_top", "cli.zzz_in_cli", "cli.aaa_in_cli"]


class TestDescribe:
    """One line per file, appended to the file's own line."""

    def test_no_findings_produces_no_text(self) -> None:
        assert describe(()) == ""

    def test_the_suffix_leads_with_the_separator(self) -> None:
        findings = _find("roots = true\nnothing_like_it = 1\n")

        assert describe(findings) == (
            ' — unknown key "roots" (did you mean "root"?);'
            ' unknown key "nothing_like_it"'
        )


class TestSettingsLayers:
    """The reader unwraps ``[tool.functualize]`` and the layers keep that."""

    def test_a_pyproject_table_is_unwrapped_by_the_reader(self, tmp_path: Path) -> None:
        """A sibling ``[tool.ruff]`` is not in scope, so it is not reported."""
        (tmp_path / "pyproject.toml").write_text(
            "[tool.functualize]\nroots = true\n[tool.ruff]\nline-length = 88\n",
            encoding="utf-8",
        )

        layers = settings_layers(
            FUNCTUALIZE_SETTINGS, tmp_path, global_dir=tmp_path / "nowhere"
        )
        findings = unknown_keys_in_layers(layers, FUNCTUALIZE_SETTINGS)

        assert [finding.key for finding in findings] == ["roots"]
        assert findings[0].file == tmp_path / "pyproject.toml"

    def test_each_finding_names_the_file_it_came_from(self, tmp_path: Path) -> None:
        (tmp_path / ".functualize.toml").write_text("root = true\n", encoding="utf-8")
        nested = tmp_path / "nested"
        nested.mkdir()
        (nested / ".functualize.toml").write_text('tema = "dark"\n', encoding="utf-8")
        global_dir = tmp_path / "global"
        global_dir.mkdir()
        (global_dir / "config.toml").write_text(
            '[tui]\ntheme = "dark"\nnot_a_tui_key = 1\n', encoding="utf-8"
        )

        layers = settings_layers(FUNCTUALIZE_SETTINGS, nested, global_dir=global_dir)
        findings = unknown_keys_in_layers(layers, FUNCTUALIZE_SETTINGS)

        assert [(f.file.name, f.key) for f in findings] == [
            (".functualize.toml", "tema"),
            ("config.toml", "tui.not_a_tui_key"),
        ]

    def test_a_missing_global_file_contributes_nothing(self, tmp_path: Path) -> None:
        (tmp_path / ".functualize.toml").write_text("root = true\n", encoding="utf-8")

        layers = settings_layers(
            FUNCTUALIZE_SETTINGS, tmp_path, global_dir=tmp_path / "nowhere"
        )

        assert unknown_keys_in_layers(layers, FUNCTUALIZE_SETTINGS) == ()


class TestShippedDocuments:
    """Every settings document we publish parses as declared keys only."""

    def test_every_shipped_settings_document_is_known(self) -> None:
        """Examples, evals and docs carry no key the declaration rejects."""
        documents = _shipped_settings_documents()

        assert documents, "the sweep found no document to check"
        findings = [
            finding
            for path, table in documents
            for finding in find_unknown_keys(
                table, file=path, schema=FUNCTUALIZE_SETTINGS
            )
        ]
        assert describe(findings) == ""


def _shipped_settings_documents() -> list[tuple[Path, dict[str, object]]]:
    """Settings documents under ``examples/``, ``evals/`` and ``docs/``."""
    documents: list[tuple[Path, dict[str, object]]] = []
    for root in ("examples", "evals", "docs"):
        for path in sorted((REPO_ROOT / root).rglob("*.toml")):
            table = _settings_table(path)
            if table is not None:
                documents.append((path, table))
        for path in sorted((REPO_ROOT / root).rglob("*.md")):
            documents.extend(_documented_tables(path))
    return documents


def _settings_table(path: Path) -> dict[str, object] | None:
    """The settings table of a shipped config file, or None if it is not one."""
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError):
        return None
    if path.name == "pyproject.toml":
        table = data.get("tool", {}).get("functualize")
        return table if isinstance(table, dict) else None
    if path.name == ".functualize.toml" or path.parent.name == "functualize":
        return data
    return None


def _documented_tables(path: Path) -> list[tuple[Path, dict[str, object]]]:
    """TOML blocks in a document that show a settings file.

    A block counts when it declares a section the walk knows about; a fragment
    of some other file's config (``[project] dependencies``, a job config
    fragment) is not a settings document and is not in scope. Two configs
    printed one after another do not parse as one document, and a block that
    does not parse is not a document at all.
    """
    sections = FUNCTUALIZE_SETTINGS.sections()
    block: str
    documents: list[tuple[Path, dict[str, object]]] = []
    for block in _TOML_BLOCK.findall(path.read_text(encoding="utf-8")):
        if not sections & set(_SECTION_HEADER.findall(block)):
            continue
        try:
            documents.append((path, tomllib.loads(block)))
        except tomllib.TOMLDecodeError:
            continue
    return documents


def test_the_documentation_sweep_checks_settings_blocks_only(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The sweep is neither vacuous nor indiscriminate.

    A documented settings block with a typo is reported; a two-config block
    that does not parse as one document and a ``[project]`` fragment are not
    settings documents and are skipped.
    """
    content = (
        "```toml\n[tui]\nthem = 'dark'\n```\n"
        "```toml\n[deploy]\nname = 'a'\n[deploy]\nname = 'b'\n```\n"
        '```toml\ndependencies = ["functualize"]\n```\n'
    )
    path = tmp_path / "guide.md"
    path.write_text(content, encoding="utf-8")

    documents = _documented_tables(path)

    assert len(documents) == 1
    assert [
        describe(find_unknown_keys(table, file=path, schema=FUNCTUALIZE_SETTINGS))
        for _, table in documents
    ] == [' — unknown key "tui.them" (did you mean "tui.theme"?)']
