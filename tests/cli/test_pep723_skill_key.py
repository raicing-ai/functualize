"""`[tool.functualize] skill` is a known key.

`_KNOWN_TOOL_KEYS` held exactly `{"job"}`, so a single-file script declaring
the skill it belongs to earned a warning on **every run**. The warning is the
right design for an unrecognised key — silence is how a misspelled setting
looks exactly like a setting with no effect — which is precisely why the key
has to be recognised rather than the warning suppressed.

**Transitional, and counted.** `ScriptMetadata.skill` is parsed and exposed;
nothing reads it. That is deliberate — the file format should settle before a
consumer exists — but it knowingly creates a fourth instance of the class
`.spec/STATUS.md` calls *"the worst of the three states"*: accepted,
validated, and read by nothing. STATUS follow-up #29 keeps it counted.
"""

from __future__ import annotations

from pathlib import Path

from functualize._cli.pep723 import _KNOWN_TOOL_KEYS, parse_script_metadata


def _script(tmp_path: Path, tool_table: str, *, name: str = "s.py") -> Path:
    """Write a PEP 723 script whose `[tool.functualize]` table is `tool_table`.

    Deliberately not built with `textwrap.dedent`: a multi-line `tool_table`
    has no indentation of its own, which makes the common prefix empty and
    leaves the `# /// script` marker indented — where `_SCRIPT_BLOCK_RE`'s
    `^# /// script` cannot match it, and every parse silently returns None.
    """
    path = tmp_path / name
    path.write_text(
        "# /// script\n"
        '# dependencies = ["httpx"]\n'
        "#\n"
        "# [tool.functualize]\n"
        f"{tool_table}\n"
        "# ///\n"
        "\n"
        "def run() -> None:\n"
        "    pass\n"
    )
    return path


class TestTheKnownKeySet:
    def test_it_holds_both_keys(self) -> None:
        assert frozenset({"job", "skill"}) == _KNOWN_TOOL_KEYS


class TestSkillParsesWithoutAWarning:
    def test_no_warning_and_the_value_is_exposed(self, tmp_path: Path, capsys) -> None:
        meta = parse_script_metadata(_script(tmp_path, '# skill = "deploy-flow"'))
        captured = capsys.readouterr()
        assert meta is not None
        assert meta.skill == "deploy-flow"
        assert captured.err == ""

    def test_both_keys_together(self, tmp_path: Path, capsys) -> None:
        meta = parse_script_metadata(
            _script(tmp_path, '# job = "run"\n# skill = "deploy-flow"')
        )
        assert capsys.readouterr().err == ""
        assert meta is not None
        assert meta.job == "run"
        assert meta.skill == "deploy-flow"

    def test_the_dependencies_still_parse_alongside(self, tmp_path: Path) -> None:
        meta = parse_script_metadata(_script(tmp_path, '# skill = "x"'))
        assert meta is not None
        assert meta.dependencies == ["httpx"]

    def test_absent_is_none(self, tmp_path: Path) -> None:
        meta = parse_script_metadata(_script(tmp_path, '# job = "run"'))
        assert meta is not None
        assert meta.skill is None

    def test_an_empty_string_is_none(self, tmp_path: Path) -> None:
        """Same rule `job` already follows: an empty value is not a value."""
        meta = parse_script_metadata(_script(tmp_path, '# skill = ""'))
        assert meta is not None
        assert meta.skill is None

    def test_a_non_string_is_none(self, tmp_path: Path) -> None:
        meta = parse_script_metadata(_script(tmp_path, "# skill = 42"))
        assert meta is not None
        assert meta.skill is None


class TestAnUnknownKeyStillWarns:
    """The behaviour this must not weaken. Adding a key to the set is not the
    same as widening the set to everything."""

    def test_it_warns_and_names_both_known_keys(self, tmp_path: Path, capsys) -> None:
        parse_script_metadata(_script(tmp_path, '# bogus = "x"'))
        err = capsys.readouterr().err
        assert "unknown key(s)" in err
        assert "bogus" in err
        assert "job" in err
        assert "skill" in err

    def test_a_near_miss_still_warns(self, tmp_path: Path, capsys) -> None:
        """`skills` is not `skill`. A plural typo is exactly what the warning
        exists to catch."""
        parse_script_metadata(_script(tmp_path, '# skills = "x"'))
        assert "skills" in capsys.readouterr().err

    def test_an_unknown_key_does_not_suppress_a_known_one(self, tmp_path: Path) -> None:
        meta = parse_script_metadata(
            _script(tmp_path, '# skill = "deploy-flow"\n# bogus = "x"')
        )
        assert meta is not None
        assert meta.skill == "deploy-flow"
