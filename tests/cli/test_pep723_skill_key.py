"""`[tool.functualize] skill` is not a key: it warns, and that is the design.

The key was accepted, parsed onto `ScriptMetadata.skill` and read by nothing —
the state `.spec/STATUS.md` calls the worst of the three, because a field the
format promises and no code consumes looks exactly like a feature waiting to be
wired up. No consumer arrived, so the key is gone from the declared
`SCRIPT_METADATA` and the file format says so by *warning*:

    Warning: s.py: unknown key(s) in [tool.functualize]: skill. Known: job.

Warning, not error: refusing to run a script over one stale key would be worse
than the typo it protects against, and a newer functualize may still add keys
this version has not heard of. Silence would be worse than either — that is how
a key with no effect looks exactly like a key that works.

`job` is unaffected: it is still the one declared key, and a script that
carries both still runs the job it names.
"""

from __future__ import annotations

from dataclasses import fields
from pathlib import Path

from functualize._cli.pep723 import ScriptMetadata, parse_script_metadata
from functualize.plugin import SCRIPT_METADATA


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


class TestTheDeclaredKeys:
    def test_the_declaration_holds_job_only(self) -> None:
        assert frozenset({"job"}) == SCRIPT_METADATA

    def test_the_metadata_has_no_skill_field(self) -> None:
        assert [f.name for f in fields(ScriptMetadata)] == ["dependencies", "job"]


class TestSkillWarns:
    def test_the_warning_names_the_key_and_the_known_set(
        self, tmp_path: Path, capsys
    ) -> None:
        parse_script_metadata(_script(tmp_path, '# skill = "deploy-flow"'))

        err = capsys.readouterr().err
        assert "unknown key(s)" in err
        assert "skill" in err
        assert "Known: job." in err

    def test_the_script_still_parses(self, tmp_path: Path, capsys) -> None:
        meta = parse_script_metadata(_script(tmp_path, '# skill = "deploy-flow"'))

        assert meta is not None
        assert meta.dependencies == ["httpx"]
        assert meta.job is None

    def test_the_plural_is_a_different_unknown_key(
        self, tmp_path: Path, capsys
    ) -> None:
        parse_script_metadata(_script(tmp_path, '# skills = "deploy-flow"'))

        assert "skills" in capsys.readouterr().err


class TestJobIsUnaffected:
    def test_job_alone_does_not_warn(self, tmp_path: Path, capsys) -> None:
        meta = parse_script_metadata(_script(tmp_path, '# job = "run"'))

        assert capsys.readouterr().err == ""
        assert meta is not None
        assert meta.job == "run"

    def test_a_script_carrying_both_still_runs_its_job(
        self, tmp_path: Path, capsys
    ) -> None:
        """The old key is reported once; the working key is not collateral."""
        meta = parse_script_metadata(
            _script(tmp_path, '# job = "run"\n# skill = "deploy-flow"')
        )

        err = capsys.readouterr().err
        assert "skill" in err
        assert "job," not in err.split("Known:", 1)[1]
        assert meta is not None
        assert meta.job == "run"

    def test_no_functualize_table_means_no_job_and_no_warning(
        self, tmp_path: Path, capsys
    ) -> None:
        path = tmp_path / "plain.py"
        path.write_text("# /// script\n# dependencies = []\n# ///\n")

        meta = parse_script_metadata(path)

        assert capsys.readouterr().err == ""
        assert meta is not None and meta.job is None


class TestAnUnknownKeyStillWarns:
    """The behaviour this must not weaken: one key, not every key."""

    def test_it_warns_and_names_the_known_key(self, tmp_path: Path, capsys) -> None:
        parse_script_metadata(_script(tmp_path, '# bogus = "x"'))

        err = capsys.readouterr().err
        assert "unknown key(s)" in err
        assert "bogus" in err
        assert "Known: job." in err

    def test_a_near_miss_still_warns(self, tmp_path: Path, capsys) -> None:
        """`jo` is not `job`. A truncated typo is exactly what this catches."""
        parse_script_metadata(_script(tmp_path, '# jo = "run"'))

        assert "jo" in capsys.readouterr().err
