"""Pin ordinary child output before the opt-in capture path is added."""

from click.testing import CliRunner

from functualize.app.config import JobSources
from functualize.app.core import FunctualizeApp


class TestDefaultPathUnchanged:
    def test_child_and_parent_both_emit_without_capture(self, tmp_path) -> None:
        jobs = tmp_path / "jobs"
        jobs.mkdir()
        (jobs / "chain.py").write_text(
            "from functualize.job import RunContext, Stdout\n"
            "def child(out: Stdout):\n"
            "    out.emit({'step': 'a'})\n"
            "def parent(rc: RunContext, out: Stdout):\n"
            "    result = rc.invoke('child')\n"
            "    assert 'emitted' not in result.metadata\n"
            "    assert 'writes' not in result.metadata\n"
            "    out.emit({'step': 'parent'})\n"
        )
        app = FunctualizeApp(
            name="capture-baseline", job_sources=JobSources(directories=[str(jobs)])
        )

        result = CliRunner().invoke(
            app.cli_command, ["--emit-format", "json", "parent"]
        )

        assert result.exit_code == 0, result.output
        assert result.stdout == '{"step":"a"}\n{"step":"parent"}\n'
