"""A name a class job claims is registered to nobody (C5; F5, AC-6, AC-14).

A plain-function collision has always meant "two spellings, the last one runs,
the other is reported". A class job cannot be resolved that way: its name comes
from a class the user wrote with its siblings, so running one arbitrary method
of it — or somebody else's function — under that name hides the mistake. The
collision is strict instead: neither claimant registers, and the record names
every claimant with its file.

The record is a *different* ``error_type`` from the function-collision one, so
``as_dict``'s four-key payload keeps meaning exactly what it meant.
"""

from __future__ import annotations

import textwrap
from pathlib import Path

from functualize._discovery.providers import DirectoryScanProvider
from functualize._types.discovery_report import (
    CLASS_JOB_NAME_COLLISION,
    JOB_NAME_COLLISION,
)

_TWO_CLASSES_AND_A_HEALTHY_ONE = """
from pydantic import BaseModel

from functualize.job import job


@job(group="postgres")
class OtherPostgres(BaseModel):
    def start(self) -> None: ...

    def stop(self) -> None: ...


@job(group="postgres")
class LocalPostgres(BaseModel):
    def start(self) -> None: ...

    def stop(self) -> None: ...


@job(group="pg")
class Pg(BaseModel):
    def status(self) -> None: ...
"""

_CLASS_AGAINST_A_FUNCTION = """
from pydantic import BaseModel

from functualize.job import job


@job(group="postgres")
def start() -> None: ...


@job(group="postgres")
class Postgres(BaseModel):
    def start(self) -> None: ...
"""

_TWO_SPELLINGS = """
from functualize.job import job


@job
def build_wheel() -> None: ...


@job
def buildWheel() -> None: ...


@job
def healthy() -> None: ...
"""


def _jobs_dir(tmp_path: Path) -> Path:
    directory = tmp_path / "jobs"
    directory.mkdir()
    return directory


def _write(directory: Path, name: str, source: str) -> Path:
    path = directory / name
    path.write_text(textwrap.dedent(source))
    return path


def _scan(directory: Path) -> tuple[list[str], list[object]]:
    provider = DirectoryScanProvider([str(directory)], project_root=directory.parent)
    names = sorted(descriptor.name for descriptor in provider.list_jobs())
    return names, list(provider.discovery_failures)


class TestTwoClassJobsClaimingOneName:
    def test_neither_class_job_registers_and_the_rest_of_the_file_does(
        self, tmp_path: Path
    ) -> None:
        directory = _jobs_dir(tmp_path)
        _write(directory, "databases.py", _TWO_CLASSES_AND_A_HEALTHY_ONE)

        names, findings = _scan(directory)

        # `postgres.start` and `postgres.stop` are claimed twice each; `pg.*`
        # from the same module is untouched.
        assert names == ["pg.status"]
        assert len(findings) == 2

    def test_every_finding_names_both_classes_and_the_file(
        self, tmp_path: Path
    ) -> None:
        directory = _jobs_dir(tmp_path)
        source = _write(directory, "databases.py", _TWO_CLASSES_AND_A_HEALTHY_ONE)

        _, findings = _scan(directory)

        for failure, method in zip(findings, ("start", "stop"), strict=True):
            assert failure.as_dict()["error_type"] == CLASS_JOB_NAME_COLLISION
            message = failure.as_dict()["message"]
            # The assertion is on the rendered message, not the detail tuple:
            # a formatter that printed the bare method name would name both
            # claimants `start`.
            assert f"'OtherPostgres.{method}'" in message
            assert f"'LocalPostgres.{method}'" in message
            assert str(source) in message
            assert f"'postgres.{method}'" in message

    def test_the_record_carries_the_qualified_claimants(self, tmp_path: Path) -> None:
        directory = _jobs_dir(tmp_path)
        _write(directory, "databases.py", _TWO_CLASSES_AND_A_HEALTHY_ONE)

        _, findings = _scan(directory)

        collision = findings[0].collision  # type: ignore[attr-defined]
        assert collision.canonical_name == "postgres.start"
        # Claim order, not definition order: the record does not move between
        # boots.
        assert [name for name, _ in collision.claimants] == [
            "LocalPostgres.start",
            "OtherPostgres.start",
        ]

    def test_the_four_key_payload_is_unchanged(self, tmp_path: Path) -> None:
        directory = _jobs_dir(tmp_path)
        _write(directory, "databases.py", _TWO_CLASSES_AND_A_HEALTHY_ONE)

        _, findings = _scan(directory)

        for failure in findings:
            assert set(failure.as_dict()) == {  # type: ignore[attr-defined]
                "module",
                "path",
                "error_type",
                "message",
            }


class TestAClassJobAgainstAFunction:
    def test_the_class_job_and_the_function_both_stay_out(self, tmp_path: Path) -> None:
        directory = _jobs_dir(tmp_path)
        _write(directory, "postgres.py", _CLASS_AGAINST_A_FUNCTION)

        names, findings = _scan(directory)

        assert names == []
        (failure,) = findings
        assert failure.as_dict()["error_type"] == CLASS_JOB_NAME_COLLISION
        message = failure.as_dict()["message"]
        # The function's own name, not the method spelling of it.
        assert "'start'" in message
        assert "'Postgres.start'" in message


class TestTwoPlainFunctionsAreUntouched:
    def test_the_last_claimant_still_wins_and_the_message_is_unchanged(
        self, tmp_path: Path
    ) -> None:
        directory = _jobs_dir(tmp_path)
        source = _write(directory, "tasks.py", _TWO_SPELLINGS)

        names, findings = _scan(directory)

        assert names == ["build-wheel", "healthy"]
        (failure,) = findings
        # Golden: the plain-function record and its rendering are untouched.
        assert failure.as_dict() == {
            "module": "tasks",
            "path": str(source),
            "error_type": JOB_NAME_COLLISION,
            "message": (
                "'buildWheel' (in 'tasks') and 'build_wheel' (in 'tasks') both "
                "resolve to the job 'build-wheel'. Job names are normalized to "
                "lowercase-hyphenated form, so these are one address: "
                "'build_wheel' is registered and 'buildWheel' is not available. "
                "Rename one."
            ),
        }
