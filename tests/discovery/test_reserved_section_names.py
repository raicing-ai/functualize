"""A name that is spoken for twice: a job called `shell`, a `[shell]` table.

Settings sections used to be written where jobs live. ``[shell] program = …``
belonged in ``config.base.toml`` beside ``[deploy]``; it now belongs in
``.functualize.toml``. Both documents are still read, both still hold tables
with the same shape, and neither says which one a given table is for — so a
job called ``shell`` and a ``[shell]`` table in a job config file are two ways
to write a name that means a setting.

Both are reported through the discovery-failure channel, with one new
``error_type`` beside ``JobNameCollision``:

| shape | record |
|---|---|
| a job or group whose address is a declared section | the address and the section it collides with |
| a `[section]` table in a job config file | the file, and the document the table belongs in |

Neither changes behaviour, which is the point of using a report and not an
error. The job registers and runs; the table merges as it always did. What the
record buys is that the day someone wonders why ``[shell]`` stopped taking
effect, the answer is already written down.

The config-file half is produced by `FileSource`, and the boot path builds its
chain outside any collection scope — so the record is currently produced but
not yet shown by ``func builtin info``. The row it belongs to is the check, not
the surface; the test below asserts the record where it is made.
"""

from __future__ import annotations

import json
import os
import subprocess  # noqa: S404 - the CLI's own behaviour is under test
import sys
from pathlib import Path

import pytest

from functualize._config.providers.toml import TomlFormatProvider
from functualize._config.sources import FileSource
from functualize._discovery.collisions import resolve_name_collisions
from functualize._primitives.locator import ResourceLocator
from functualize._types.descriptors import JobDescriptor
from functualize._types.discovery_report import (
    RESERVED_SECTION_NAME,
    DiscoveryFailure,
    collecting_discovery_failures,
)


def _descriptor(
    name: str,
    group: str | None = None,
    source_file: str = "/project/jobs/tools.py",
) -> JobDescriptor:
    return JobDescriptor(
        name=name,
        group=group,
        module_path="jobs.tools",
        source_file=source_file,
    )


def _report(
    descriptors: list[JobDescriptor],
) -> tuple[list[str], list[DiscoveryFailure]]:
    """Run the one dedupe-and-report pass, and return what each side saw."""
    with collecting_discovery_failures() as failures:
        kept = resolve_name_collisions(descriptors)
    return [descriptor.name for descriptor in kept], list(failures)


def _reserved(failures: list[DiscoveryFailure]) -> list[DiscoveryFailure]:
    return [f for f in failures if f.error_type == RESERVED_SECTION_NAME]


def _file_source(directory: Path, name: str, document: str) -> FileSource:
    (directory / name).write_text(document, encoding="utf-8")
    return FileSource(
        ResourceLocator().search_explicit(str(directory)),
        format_providers={".toml": TomlFormatProvider()},
        pattern=name,
    )


class TestAJobNamedAfterASection:
    """`def shell()` answers to the word a settings table is spelled with."""

    def test_it_is_reported(self) -> None:
        _kept, failures = _report([_descriptor("shell")])

        (failure,) = _reserved(failures)
        assert failure.module == "jobs.tools"
        assert failure.path == "/project/jobs/tools.py"
        assert "[shell]" in failure.message

    def test_the_job_is_still_registered(self) -> None:
        kept, _failures = _report([_descriptor("shell"), _descriptor("deploy")])

        assert sorted(kept) == ["deploy", "shell"]

    def test_the_message_says_what_the_name_costs(self) -> None:
        """A finding that only says "reserved" leaves the reader to guess."""
        _kept, failures = _report([_descriptor("shell")])

        (failure,) = _reserved(failures)
        assert "never reaches this job's configuration" in failure.message

    def test_a_group_formed_by_a_reserved_name_is_reported(self) -> None:
        """`shell.deploy` is the group `shell` — the word is what collides."""
        _kept, failures = _report([_descriptor("deploy", group="shell")])

        (failure,) = _reserved(failures)
        assert failure.message.startswith("'shell.deploy'")

    def test_a_nested_group_is_reported_on_the_reserved_segment(self) -> None:
        _kept, failures = _report([_descriptor("run", group="shell.sudo")])

        (failure,) = _reserved(failures)
        assert "[shell]" in failure.message

    def test_a_job_that_also_collides_is_reported_for_both(self) -> None:
        """Two claimants and a reserved name are two facts, not one."""
        _kept, failures = _report(
            [
                _descriptor("shell", source_file="/project/jobs/a.py"),
                _descriptor("shell", source_file="/project/jobs/b.py"),
            ]
        )

        kinds = sorted(f.error_type for f in failures)
        assert kinds == [
            "JobNameCollision",
            "ReservedSectionName",
            "ReservedSectionName",
        ]

    def test_every_claimant_file_is_named_once(self) -> None:
        """Both files need the rename, so both are named — once each."""
        _kept, failures = _report(
            [
                _descriptor("shell", source_file="/project/jobs/a.py"),
                _descriptor("shell", source_file="/project/jobs/b.py"),
            ]
        )

        reserved = sorted(f.path for f in _reserved(failures))
        assert reserved == ["/project/jobs/a.py", "/project/jobs/b.py"]

    def test_it_reaches_the_cli_and_the_job_still_runs(self, tmp_path: Path) -> None:
        """AC23. `func shell` runs; `info --json` names the section."""
        project = tmp_path / "project"
        (project / "jobs").mkdir(parents=True)
        (project / ".functualize.toml").write_text(
            'jobs_directories = ["jobs"]\n', encoding="utf-8"
        )
        (project / "jobs" / "shell.py").write_text(
            'def shell() -> None:\n    """Say hello."""\n    print("shell ran")\n',
            encoding="utf-8",
        )

        run = _func(project, "shell")
        assert run.returncode == 0, run.stderr
        assert "shell ran" in run.stdout

        info = _func(project, "builtin", "info", "--json")
        assert info.returncode == 0, info.stderr
        failures = [
            entry
            for entry in json.loads(info.stdout)["discovery_failures"]
            if entry["error_type"] == RESERVED_SECTION_NAME
        ]
        (failure,) = failures
        assert "[shell]" in failure["message"]
        assert failure["path"].endswith("jobs/shell.py")


class TestWhatIsNotReported:
    """The check is the declared sections, not a substring of one."""

    @pytest.mark.parametrize(
        "name", ["shells", "shell-tool", "my-shell", "plugin", "vaults"]
    )
    def test_a_name_the_declaration_does_not_declare(self, name: str) -> None:
        _kept, failures = _report([_descriptor(name)])

        assert failures == []

    def test_a_declared_section_is_what_matches(self) -> None:
        _kept, failures = _report([_descriptor("tui")])

        assert [f.error_type for f in failures] == [RESERVED_SECTION_NAME]


class TestOncePerAddress:
    def test_the_same_address_twice_records_one_finding(self) -> None:
        """A rescan sees the same job again; the operator should see one line."""
        descriptor = _descriptor("shell")

        _kept, failures = _report([descriptor, descriptor])

        assert len(failures) == 1

    def test_nothing_is_recorded_outside_a_scope(self) -> None:
        """The scan owns the collection; a caller that is not scanning gets silence."""
        kept = resolve_name_collisions([_descriptor("shell")])

        assert [descriptor.name for descriptor in kept] == ["shell"]


class TestASettingsTableInAJobConfig:
    """AC27. `[shell]` in `config.base.toml` is settings, in the wrong file."""

    def test_it_is_reported_with_the_file_and_where_it_belongs(
        self, tmp_path: Path
    ) -> None:
        with collecting_discovery_failures() as failures:
            _file_source(
                tmp_path, "config.base.toml", '[shell]\nprogram = "/bin/zsh"\n'
            )

        (failure,) = _reserved(failures)
        assert failure.path.endswith("config.base.toml")
        assert failure.message.startswith("[shell] in ")
        assert ".functualize.toml [shell]" in failure.message

    def test_a_jobs_own_table_is_not_reported(self, tmp_path: Path) -> None:
        with collecting_discovery_failures() as failures:
            _file_source(
                tmp_path, "config.base.toml", '[deploy]\nregion = "eu-west-1"\n'
            )

        assert failures == []

    def test_the_table_still_merges(self, tmp_path: Path) -> None:
        """Advisory: the record must not change what the chain resolves."""
        source = _file_source(
            tmp_path, "config.base.toml", '[shell]\nprogram = "/bin/zsh"\n'
        )

        assert source.get("program", section="shell") == "/bin/zsh"

    def test_a_nested_table_is_not_a_top_level_section(self, tmp_path: Path) -> None:
        with collecting_discovery_failures() as failures:
            _file_source(
                tmp_path, "config.base.toml", '[deploy.shell]\nprogram = "/bin/zsh"\n'
            )

        assert failures == []

    def test_the_command_still_exits_zero(self, tmp_path: Path) -> None:
        """AC27's second half: reporting is never a failure."""
        project = tmp_path / "project"
        project.mkdir()
        (project / ".functualize.toml").write_text("", encoding="utf-8")
        (project / "config.base.toml").write_text(
            '[shell]\nprogram = "/bin/zsh"\n', encoding="utf-8"
        )

        info = _func(project, "builtin", "info", "--json")

        assert info.returncode == 0, info.stderr


def _func(project: Path, *argv: str) -> subprocess.CompletedProcess[str]:
    """Run the real CLI in `project`, with its own XDG homes."""
    env = {
        **os.environ,
        "XDG_CONFIG_HOME": str(project / ".xdg" / "config"),
        "XDG_CACHE_HOME": str(project / ".xdg" / "cache"),
        "XDG_STATE_HOME": str(project / ".xdg" / "state"),
        "XDG_DATA_HOME": str(project / ".xdg" / "data"),
    }
    return subprocess.run(  # noqa: S603
        [sys.executable, "-m", "functualize", *argv],
        cwd=project,
        env=env,
        capture_output=True,
        text=True,
        timeout=180,
        check=False,
    )
