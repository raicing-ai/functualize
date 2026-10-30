"""A class is a source, not an item (C3; AC-13).

Both providers that can be handed code rather than a directory — the entry-point
table and ``StaticProvider`` — have to fan a job class out into one job per
method, through the *same* builder the directory scan uses (3.1). A second copy
of that logic would eventually disagree about a class job's name, its group or
its merged declaration, and the disagreement would only show up when the same
class arrived by two routes.

The entry-point side has a constraint the static side does not: enumeration must
not import. It gets away with classifying a class without importing by reading
the module's **source** (``class_in_source``) — so a function entry point still
imports nothing, and only an entry point that names a job class pays for an
import, because a class can only be enumerated as a whole.

The case that has no source to read is a compiled or zipped distribution. There
the module keeps today's single lazy descriptor with ``function=None``, and the
first materialisation is where the class becomes visible — so that is where it
is reported, as a ``JobMaterializationError`` naming the entry point and the
class, not as a bogus ``failed to import module`` an operator would chase.
"""

from __future__ import annotations

import sys
import textwrap
import zipfile
from collections.abc import Iterator
from contextlib import ExitStack, contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any
from unittest.mock import patch

import pytest

from functualize._discovery.collisions import resolve_name_collisions
from functualize._discovery.providers import (
    DirectoryScanProvider,
    EntryPointProvider,
    Job,
    StaticProvider,
    _module_source_file,
)
from functualize._types.class_job import ClassJobMethod
from functualize._types.discovery_report import (
    CLASS_JOB_NAME_COLLISION,
    collecting_discovery_failures,
)
from functualize._types.errors import JobMaterializationError

if TYPE_CHECKING:
    from functualize._types.descriptors import JobDescriptor

#: A module-level ``JOB_GROUP`` plus a class with no ``@job(group=)``: the group
#: comes from ``JOB_GROUP`` + the class name, which is the substitution the
#: entry-point path has to reproduce (it reads ``JOB_GROUP`` off the module it
#: imported for the class). ``stop`` also carries a method-level ``@job`` so the
#: merged declaration and the per-method decorator keys are both exercised.
_CLASS_MODULE = """
from pydantic import BaseModel

from functualize.job import job

JOB_GROUP = "svc"

@job
class Postgres(BaseModel):
    \"\"\"A database.\"\"\"

    host: str = "localhost"

    def start(self) -> None: ...

    @job(tags=["slow"])
    def stop(self, force: bool = False) -> None: ...
"""

_FUNCTION_MODULE = """
from functualize.job import job

@job
def backup(target: str = "all") -> None:
    \"\"\"Back up.\"\"\"
"""


@dataclass
class _FakeEntryPoint:
    name: str
    value: str
    group: str = "functualize.jobs"


@contextmanager
def _with_entry_points(*eps: _FakeEntryPoint) -> Iterator[None]:
    """Patch every binding of ``entry_points`` this provider reads.

    The provider binds the name at import, and ``boot`` peeks at the table
    before constructing one, so patching only the module's own binding leaves
    the other call site reading the real installed table.
    """
    targets = (
        "functualize._discovery.providers.entry_points",
        "functualize._primitives.entry_points.entry_points",
    )
    with ExitStack() as stack:
        for target in targets:
            stack.enter_context(patch(target, return_value=tuple(eps)))
        yield


@contextmanager
def _importable_module(prefix: Path, name: str, source: str) -> Iterator[Path]:
    """Write ``name``.py under ``prefix``, importable as a top-level module."""
    prefix.mkdir(parents=True, exist_ok=True)
    (prefix / f"{name}.py").write_text(textwrap.dedent(source))
    monkeypatched = sys.path[:]
    sys.path.insert(0, str(prefix))
    sys.modules.pop(name, None)
    try:
        yield prefix / f"{name}.py"
    finally:
        sys.path[:] = monkeypatched
        sys.modules.pop(name, None)


def _import_spec_origin(name: str) -> str | None:
    import importlib.util

    spec = importlib.util.find_spec(name)
    return spec.origin if spec is not None else None


def _import(name: str) -> Any:
    import importlib

    return importlib.import_module(name)


def _project(tmp_path: Path) -> Path:
    """A directory that is both a scan root and a ``sys.path`` entry."""
    project = tmp_path / "project"
    project.mkdir()
    return project


def _scan(project: Path) -> list[JobDescriptor]:
    return list(DirectoryScanProvider([str(project)], project_root=project).list_jobs())


def _shape(descriptors: list[JobDescriptor]) -> dict[str, tuple[Any, ...]]:
    """The projection every source must agree on for the same class."""
    return {
        descriptor.name: (
            descriptor.group,
            descriptor.python_name,
            descriptor.owner_class,
            descriptor.decorators,
            tuple(field.name for field in descriptor.config_fields),
            descriptor.declaration,
        )
        for descriptor in descriptors
    }


class TestFunctionEntryPointImportsNothing:
    """The rule the class branch must not spend: metadata stays metadata."""

    def test_the_job_module_never_enters_sys_modules(self, tmp_path: Path) -> None:
        project = _project(tmp_path)
        with _importable_module(project, "jobs_fn", _FUNCTION_MODULE):
            provider = EntryPointProvider()
            with _with_entry_points(_FakeEntryPoint("backup", "jobs_fn:backup")):
                (job,) = provider.list_jobs()

            assert "jobs_fn" not in sys.modules
            assert job.name == "backup"
            assert job.function is None
            assert job.module_path == "jobs_fn"
            assert job.source_file == "<entry_point>"


class TestClassEntryPoint:
    def test_one_descriptor_per_method_with_owner_class(self, tmp_path: Path) -> None:
        project = _project(tmp_path)
        with _importable_module(project, "jobs_pg", _CLASS_MODULE):
            provider = EntryPointProvider()
            with _with_entry_points(_FakeEntryPoint("pg", "jobs_pg:Postgres")):
                jobs = list(provider.list_jobs())

        # The entry point's own name is not used: the class names its jobs, and
        # the group comes from the module's ``JOB_GROUP`` above the class name.
        assert [job.name for job in jobs] == ["svc.postgres.start", "svc.postgres.stop"]
        for job in jobs:
            assert job.owner_class == "Postgres"
            assert job.source == "<entry_point>"
            assert job.source_file == "<entry_point>"
            assert job.module_path == "jobs_pg"
            assert isinstance(job.function, ClassJobMethod)
            assert job.function.job_class.__name__ == "Postgres"
        assert [job.python_name for job in jobs] == ["start", "stop"]


class TestStaticProviderClassItems:
    def test_a_class_yields_the_classes_own_jobs(self, tmp_path: Path) -> None:
        project = _project(tmp_path)
        with _importable_module(project, "jobs_pg", _CLASS_MODULE):
            postgres = _import("jobs_pg").Postgres

            jobs = list(StaticProvider([postgres]).list_jobs())

        assert [job.name for job in jobs] == ["svc.postgres.start", "svc.postgres.stop"]
        assert {job.owner_class for job in jobs} == {"Postgres"}
        assert {job.source for job in jobs} == {"<static>"}

    def test_the_same_class_scans_and_wraps_identically(self, tmp_path: Path) -> None:
        """One builder, so the two sources describe the same class the same way."""
        project = _project(tmp_path)
        with _importable_module(project, "jobs_pg", _CLASS_MODULE):
            postgres = _import("jobs_pg").Postgres
            static = list(StaticProvider([postgres]).list_jobs())
            scanned = _scan(project)
            entry_point_jobs = EntryPointProvider()
            with _with_entry_points(_FakeEntryPoint("pg", "jobs_pg:Postgres")):
                from_entry_point = list(entry_point_jobs.list_jobs())

        assert _shape(static) == _shape(scanned) == _shape(from_entry_point)

    def test_a_job_instance_wrapping_a_class_is_refused(self, tmp_path: Path) -> None:
        project = _project(tmp_path)
        with _importable_module(project, "jobs_pg", _CLASS_MODULE):
            postgres = _import("jobs_pg").Postgres

            with pytest.raises(ValueError) as excinfo:
                StaticProvider([Job(function=postgres)])

        # C3's text: the class names its own jobs and group, so renaming them
        # through a wrapper would describe something the class does not say.
        assert "names its own jobs and group" in str(excinfo.value)
        assert "Postgres" in str(excinfo.value)

    def test_a_function_item_is_unchanged(self) -> None:
        from functualize.job import job

        @job
        def standalone(x: int = 1) -> None: ...

        (descriptor,) = StaticProvider([standalone]).list_jobs()

        assert descriptor.name == "standalone"
        assert descriptor.owner_class is None
        assert descriptor.function is standalone


class TestBothSourcesClaimOneName:
    def test_the_same_class_from_two_sources_registers_nothing(
        self, tmp_path: Path
    ) -> None:
        """3.3's strict rule, reached from the providers rather than a scan."""
        project = _project(tmp_path)
        with _importable_module(project, "jobs_pg", _CLASS_MODULE):
            postgres = _import("jobs_pg").Postgres
            static = list(StaticProvider([postgres]).list_jobs())
            scanned = _scan(project)

            with collecting_discovery_failures() as findings:
                kept = resolve_name_collisions([*static, *scanned])

        assert kept == []
        assert len(findings) == 2
        assert {
            finding.collision.canonical_name
            for finding in findings
            if finding.collision
        } == {
            "svc.postgres.start",
            "svc.postgres.stop",
        }
        for finding in findings:
            assert finding.as_dict()["error_type"] == CLASS_JOB_NAME_COLLISION
            assert "'Postgres." in finding.message
            assert "Neither is registered" in finding.message


class TestMalformedEntryPoint:
    def test_a_value_naming_no_module_is_warned_and_skipped(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        project = _project(tmp_path)
        with _importable_module(project, "jobs_pg", _CLASS_MODULE):
            provider = EntryPointProvider()
            with _with_entry_points(
                _FakeEntryPoint("broken", ":Postgres"),
                _FakeEntryPoint("pg", "jobs_pg:Postgres"),
            ):
                jobs = list(provider.list_jobs())

        assert [job.name for job in jobs] == [
            "svc.postgres.start",
            "svc.postgres.stop",
        ]
        assert "Skipping malformed entry point 'broken'" in caplog.text


class TestZippedDistribution:
    """No source to read: today's lazy descriptor, and the class reported later."""

    def _wheel(self, tmp_path: Path, name: str, source: str) -> Path:
        wheel = tmp_path / "dists" / f"{name}-0.0.0-py3-none-any.whl"
        wheel.parent.mkdir()
        with zipfile.ZipFile(wheel, "w") as archive:
            archive.writestr(f"{name}.py", textwrap.dedent(source))
        return wheel

    @contextmanager
    def _on_path(self, wheel: Path, name: str) -> Iterator[None]:
        saved = sys.path[:]
        sys.path.insert(0, str(wheel))
        sys.modules.pop(name, None)
        try:
            yield
        finally:
            sys.path[:] = saved
            sys.modules.pop(name, None)

    def test_enumeration_keeps_one_lazy_descriptor(self, tmp_path: Path) -> None:
        wheel = self._wheel(tmp_path, "plugmod", _CLASS_MODULE)
        with self._on_path(wheel, "plugmod"):
            # The refusal is about the *source*, not the import: the origin is a
            # path inside the archive, so opening it raises NotADirectoryError
            # (errno 20) and there is nothing to classify.
            with pytest.raises(NotADirectoryError) as excinfo:
                Path(_import_spec_origin("plugmod") or "").read_text(encoding="utf-8")
            assert excinfo.value.errno == 20
            assert _module_source_file("plugmod") is None
            assert "plugmod" not in sys.modules

            provider = EntryPointProvider()
            with _with_entry_points(_FakeEntryPoint("pg", "plugmod:Postgres")):
                jobs = list(provider.list_jobs())

            assert len(jobs) == 1
            (job,) = jobs
            assert job.function is None
            assert job.name == "pg"
            assert job.module_path == "plugmod"
            assert "plugmod" not in sys.modules

    def test_materialisation_names_the_entry_point_and_the_class(
        self, tmp_path: Path
    ) -> None:
        wheel = self._wheel(tmp_path, "plugmod", _CLASS_MODULE)
        with self._on_path(wheel, "plugmod"):
            provider = EntryPointProvider()
            with (
                _with_entry_points(_FakeEntryPoint("pg", "plugmod:Postgres")),
                pytest.raises(JobMaterializationError) as excinfo,
            ):
                provider.get_job("pg")

        message = str(excinfo.value)
        assert "'pg'" in message
        assert "'Postgres'" in message
        assert "plugmod" in message
        # The import succeeded. Saying it failed would send an operator to
        # `sys.path`, where nothing is wrong.
        assert "failed to import module" not in message
        assert excinfo.value.job_name == "pg"
        assert excinfo.value.module_path == "plugmod"
