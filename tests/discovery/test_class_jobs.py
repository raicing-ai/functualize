"""A job class's methods become descriptors (C1, C2; F1, F1-a, F1-b).

Discovery reads a job class from its own namespace: the class's own ``@job`` is
the opt-in (F1-b), so a subclass that inherits one registers nothing. An
abstract class is a finding, not a job (F1-a) — but only when it carries its own
``@job``; without one it is not a candidate at all.

Every public instance method becomes one descriptor. The declaration is merged
**once**, here, and handed to the ``ClassJobMethod`` proxy as its own
``__functualize_job__``; ``JobDescriptor.declaration`` is that same object, so a
later stage that tries to recompute it fails an identity assertion instead of
drifting silently (F2).

No instance is constructed anywhere on this path (AC-4): discovery reads the
class, never an object of it.
"""

from __future__ import annotations

import textwrap
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pytest

from functualize._discovery.cached_provider import CachedDirectoryScanProvider
from functualize._discovery.sync import extract_module
from functualize._primitives.locator import ResourceLocator
from functualize._types.class_job import ClassJobMethod
from functualize.app import FunctualizeApp, JobSources

if TYPE_CHECKING:
    from functualize._types.descriptors import JobDescriptor
    from functualize._types.discovery_report import DiscoveryFailure
    from functualize._types.job_declaration import JobDeclaration

# C1, plus the attributes that must NOT become jobs and the instance counter
# AC-4 reads. ``CONSTRUCTED`` is a ClassVar so pydantic does not treat it as a
# model field, and ``_``-prefixed names are dropped by the method walk.
_C1 = '''
from typing import ClassVar

from pydantic import BaseModel

from functualize.job import Shell, job
from functualize.job.decorators import Guards
from functualize.types import Secret


@job(group="pg")
class Postgres(BaseModel):
    CONSTRUCTED: ClassVar[list[str]] = []

    host: str = "localhost"
    port: int = 5432
    password: Secret[str]

    def __init__(self, **data):
        type(self).CONSTRUCTED.append(type(self).__name__)
        super().__init__(**data)

    def start(self, sh: Shell) -> None:
        """Start the server."""

    @job(guards=Guards(preconditions=["network-up"]))
    def stop(self, sh: Shell, force: bool = False) -> None:
        """Stop the server."""

    def _present(self) -> bool:
        return True

    @property
    def url(self) -> str:
        return "postgres://localhost"

    @classmethod
    def from_url(cls, url: str):
        return cls()

    @staticmethod
    def helper() -> int:
        return 1
'''

# F1-b: ``TunedPostgres`` inherits ``__functualize_job__``; only the class that
# declares its own ``@job`` is a job class.
_OWN_NAMESPACE_ONLY = """
from pydantic import BaseModel

from functualize.job import job


@job(group="postgres")
class LocalPostgres(BaseModel):
    host: str = "localhost"

    def start(self) -> None: ...

    def stop(self) -> None: ...


class TunedPostgres(LocalPostgres):
    port: int = 6432
"""

# F1-a: an abstract class *with* its own ``@job`` is a finding.
_ABSTRACT_WITH_JOB = """
from abc import abstractmethod

from pydantic import BaseModel

from functualize.job import job


@job(group="pg")
class AbstractPostgres(BaseModel):
    host: str = "localhost"

    @abstractmethod
    def start(self) -> None: ...

    @abstractmethod
    def stop(self) -> None: ...
"""

# F1-a: an abstract class *without* ``@job`` is not a candidate at all.
_ABSTRACT_WITHOUT_JOB = """
from abc import abstractmethod

from pydantic import BaseModel


class AbstractNothing(BaseModel):
    @abstractmethod
    def start(self) -> None: ...
"""

# A method whose own ``@job(group=...)`` disagrees with its class's group.
_GROUP_CONFLICT = """
from pydantic import BaseModel

from functualize.job import job


@job(group="pg")
class Postgres(BaseModel):
    def start(self) -> None: ...

    @job(group="other")
    def stop(self) -> None: ...
"""

# AC-5's shape: a base ``JOB_TAGS``, a subclass ``JOB_TAGS`` that repeats one
# tag, class-level ``@job(tags=)``, and a method with its own tags + guards.
_MERGED_TAGS = """
from typing import ClassVar

from pydantic import BaseModel

from functualize.job import job
from functualize.job.decorators import Guards


class Database(BaseModel):
    JOB_TAGS: ClassVar[tuple[str, ...]] = ("t1", "shared")
    host: str = "localhost"


@job(group="pg", tags=["class"])
class Local(Database):
    JOB_TAGS: ClassVar[tuple[str, ...]] = ("shared", "local")

    def start(self) -> None: ...

    @job(tags=["mine"], guards=Guards(preconditions=["network-up"]))
    def stop(self, force: bool = False) -> None: ...
"""

# Identity field owned by the class; a method that sets its own wins.
_VISIBILITY = """
from pydantic import BaseModel

from functualize.job import job
from functualize.job.decorators import Guards


@job(group="pg", visibility="internal")
class Postgres(BaseModel):
    def start(self) -> None: ...

    @job(visibility="external")
    def stop(self) -> None: ...

    @job(guards=Guards(preconditions=["network-up"]))
    def status(self) -> None: ...
"""

# A module-level JOB_GROUP with no class group: the class name is the group
# segment under the module's namespace.
_NESTED = """
from pydantic import BaseModel

from functualize.job import job

JOB_GROUP = "pg"


@job
class Postgres(BaseModel):
    def start(self) -> None: ...
"""

# The class lives here and is only re-exported by ``pkg/__init__.py``.
_DEFINED_ELSEWHERE = """
from pydantic import BaseModel

from functualize.job import job


@job(group="pg")
class Postgres(BaseModel):
    def start(self) -> None: ...
"""

_REEXPORTING_INIT = """
from defined_elsewhere import Postgres

__all__ = ["Postgres"]
"""


def _jobs_dir(tmp_path: Path) -> Path:
    d = tmp_path / "jobs"
    d.mkdir()
    return d


def _write(jobs_dir: Path, name: str, source: str) -> Path:
    path = jobs_dir / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(textwrap.dedent(source))
    return path


def _provider(tmp_path: Path, jobs_dir: Path) -> CachedDirectoryScanProvider:
    locator = (
        ResourceLocator()
        .search_explicit(tmp_path / "cache")
        .write_to_explicit(tmp_path / "cache")
    )
    return CachedDirectoryScanProvider(
        directories=[str(jobs_dir)], locator=locator, project_root=tmp_path
    )


def _scan_and_findings(
    tmp_path: Path, jobs_dir: Path
) -> tuple[list[JobDescriptor], list[DiscoveryFailure]]:
    """A scan reports its findings through the provider, not the caller's
    scope: the provider opens its own collection scope, which nests."""
    provider = _provider(tmp_path, jobs_dir)
    jobs = list(provider.list_jobs())
    return jobs, provider.discovery_failures


def _scan(tmp_path: Path, jobs_dir: Path) -> list[JobDescriptor]:
    return _scan_and_findings(tmp_path, jobs_dir)[0]


def _by_name(jobs: list[JobDescriptor]) -> dict[str, JobDescriptor]:
    return {job.name: job for job in jobs}


def _proxy(job: JobDescriptor) -> ClassJobMethod:
    """The descriptor's ``function`` as the class-job proxy it must be."""
    fn = job.function
    assert isinstance(fn, ClassJobMethod), f"{job.name} is not a class job"
    return fn


def _declaration(job: JobDescriptor) -> JobDeclaration:
    assert job.declaration is not None, f"{job.name} carries no declaration"
    return job.declaration


def _class_of(job: JobDescriptor) -> type[Any]:
    return _proxy(job).job_class


def _carried(job: JobDescriptor) -> JobDeclaration:
    """The declaration the proxy holds as its **own** ``__functualize_job__``.

    Read from the instance dict, not through attribute access: the proxy must
    not be delegating this one to the method it wraps.
    """
    carried: JobDeclaration = vars(_proxy(job))["__functualize_job__"]
    return carried


class TestClassBodyBecomesDescriptors:
    def test_c1_class_yields_exactly_its_public_methods(self, tmp_path: Path) -> None:
        jobs_dir = _jobs_dir(tmp_path)
        _write(jobs_dir, "pg.py", _C1)

        jobs = _scan(tmp_path, jobs_dir)

        assert sorted(job.name for job in jobs) == ["pg.start", "pg.stop"]
        assert {job.owner_class for job in jobs} == {"Postgres"}
        assert {job.python_name for job in jobs} == {"start", "stop"}
        assert {job.group for job in jobs} == {"pg"}
        # ``sh`` is framework-injected, so only the method's own option is a
        # user-facing parameter.
        assert [p.name for p in _by_name(jobs)["pg.stop"].parameters] == ["force"]

    def test_non_method_attributes_are_not_jobs(self, tmp_path: Path) -> None:
        jobs_dir = _jobs_dir(tmp_path)
        _write(jobs_dir, "pg.py", _C1)

        jobs = _scan(tmp_path, jobs_dir)

        assert {"_present", "url", "from_url", "helper"}.isdisjoint(
            job.python_name or "" for job in jobs
        )

    def test_config_fields_come_from_the_class(self, tmp_path: Path) -> None:
        jobs_dir = _jobs_dir(tmp_path)
        _write(jobs_dir, "pg.py", _C1)

        jobs = _scan(tmp_path, jobs_dir)

        (start,) = [job for job in jobs if job.name == "pg.start"]
        fields = {field.name for field in start.config_fields or ()}
        assert {"host", "port", "password"} <= fields

    def test_discovery_constructs_no_instance(self, tmp_path: Path) -> None:
        """AC-4: the class is read, never instantiated."""
        jobs_dir = _jobs_dir(tmp_path)
        _write(jobs_dir, "pg.py", _C1)

        jobs = _scan(tmp_path, jobs_dir)

        (start,) = [job for job in jobs if job.name == "pg.start"]
        assert _class_of(start).CONSTRUCTED == []


class TestOptInIsOwnDefinitionOnly:
    def test_subclass_without_its_own_job_registers_nothing(
        self, tmp_path: Path
    ) -> None:
        jobs_dir = _jobs_dir(tmp_path)
        _write(jobs_dir, "postgres.py", _OWN_NAMESPACE_ONLY)

        jobs = _scan(tmp_path, jobs_dir)

        assert sorted(job.name for job in jobs) == ["postgres.start", "postgres.stop"]
        assert {job.owner_class for job in jobs} == {"LocalPostgres"}

    def test_abstract_class_without_its_own_job_produces_nothing(
        self, tmp_path: Path
    ) -> None:
        jobs_dir = _jobs_dir(tmp_path)
        _write(jobs_dir, "nothing.py", _ABSTRACT_WITHOUT_JOB)

        jobs, findings = _scan_and_findings(tmp_path, jobs_dir)

        assert jobs == []
        assert [f for f in findings if f.error_type == "AbstractJobClass"] == []


class TestAbstractJobClass:
    def test_abstract_class_with_its_own_job_is_a_finding(self, tmp_path: Path) -> None:
        jobs_dir = _jobs_dir(tmp_path)
        _write(jobs_dir, "abstract_pg.py", _ABSTRACT_WITH_JOB)

        jobs, findings = _scan_and_findings(tmp_path, jobs_dir)

        assert jobs == []
        (finding,) = [f for f in findings if f.error_type == "AbstractJobClass"]
        assert "AbstractPostgres" in finding.message
        assert "start" in finding.message
        assert "stop" in finding.message
        assert finding.module == "abstract_pg"
        assert finding.path.endswith("abstract_pg.py")


class TestMethodGroupConflict:
    def test_method_group_conflict_is_a_finding_and_no_descriptor(
        self, tmp_path: Path
    ) -> None:
        jobs_dir = _jobs_dir(tmp_path)
        _write(jobs_dir, "pg.py", _GROUP_CONFLICT)

        jobs, findings = _scan_and_findings(tmp_path, jobs_dir)

        assert [job.name for job in jobs] == ["pg.start"]
        (finding,) = [f for f in findings if f.error_type == "MethodGroupConflict"]
        assert "Postgres.stop" in finding.message
        assert "'other'" in finding.message
        assert "'pg'" in finding.message


class TestMergedDeclaration:
    def test_tags_merge_author_class_then_job_tags_in_declared_order(
        self, tmp_path: Path
    ) -> None:
        jobs_dir = _jobs_dir(tmp_path)
        _write(jobs_dir, "tags.py", _MERGED_TAGS)

        jobs = _by_name(_scan(tmp_path, jobs_dir))

        # Method tags, then @job(tags=), then JOB_TAGS outward along the MRO
        # (nearest first), with the repeated "shared" kept at its first spot.
        assert _declaration(jobs["pg.stop"]).tags == (
            "mine",
            "class",
            "shared",
            "local",
            "t1",
        )
        assert _declaration(jobs["pg.start"]).tags == (
            "class",
            "shared",
            "local",
            "t1",
        )

    def test_method_guards_survive_the_merge(self, tmp_path: Path) -> None:
        jobs_dir = _jobs_dir(tmp_path)
        _write(jobs_dir, "tags.py", _MERGED_TAGS)

        jobs = _by_name(_scan(tmp_path, jobs_dir))

        guards = _declaration(jobs["pg.stop"]).guards
        assert guards is not None
        assert guards.preconditions == ("network-up",)
        assert _declaration(jobs["pg.start"]).guards is None

    def test_job_tags_lives_in_the_class_dict_not_model_fields(
        self, tmp_path: Path
    ) -> None:
        """The documented spelling: a ``ClassVar``, so pydantic keeps it out of
        ``model_fields`` and discovery has to read ``__dict__``."""
        jobs_dir = _jobs_dir(tmp_path)
        _write(jobs_dir, "tags.py", _MERGED_TAGS)

        jobs = _scan(tmp_path, jobs_dir)

        job_class = _class_of(jobs[0])
        assert "JOB_TAGS" in job_class.__dict__
        assert "JOB_TAGS" not in job_class.model_fields

    def test_declaration_is_the_same_object_the_proxy_carries(
        self, tmp_path: Path
    ) -> None:
        """F2: merged once. Recomputing anywhere downstream breaks this."""
        jobs_dir = _jobs_dir(tmp_path)
        _write(jobs_dir, "tags.py", _MERGED_TAGS)

        jobs = _by_name(_scan(tmp_path, jobs_dir))

        for job in jobs.values():
            assert job.declaration is not None
            assert job.declaration is _carried(job)
        # And that shared object already carries the class-level ``JOB_TAGS``
        # even though ``stop`` declares tags of its own.
        assert _carried(jobs["pg.stop"]).tags == (
            "mine",
            "class",
            "shared",
            "local",
            "t1",
        )

    def test_class_visibility_applies_when_the_method_declares_none(
        self, tmp_path: Path
    ) -> None:
        jobs_dir = _jobs_dir(tmp_path)
        _write(jobs_dir, "visibility.py", _VISIBILITY)

        jobs = _by_name(_scan(tmp_path, jobs_dir))

        assert _declaration(jobs["pg.start"]).visibility == "internal"

    def test_method_visibility_overrides_the_class(self, tmp_path: Path) -> None:
        jobs_dir = _jobs_dir(tmp_path)
        _write(jobs_dir, "visibility.py", _VISIBILITY)

        jobs = _by_name(_scan(tmp_path, jobs_dir))

        assert _declaration(jobs["pg.stop"]).visibility == "external"

    def test_method_declaration_without_visibility_keeps_the_default(
        self, tmp_path: Path
    ) -> None:
        """Known limitation, pinned so a fix has to change this line.

        ``JobDeclaration.visibility`` has no "unset" value — it defaults to
        ``"external"`` — so a method whose own ``@job(guards=...)`` says
        nothing about visibility is indistinguishable from one that asked for
        ``"external"``. The class's ``"internal"`` therefore does not reach it.
        Giving ``visibility`` a sentinel is what removes this test.
        """
        jobs_dir = _jobs_dir(tmp_path)
        _write(jobs_dir, "visibility.py", _VISIBILITY)

        jobs = _by_name(_scan(tmp_path, jobs_dir))

        assert _declaration(jobs["pg.status"]).visibility == "external"


class TestGroupSpelling:
    def test_a_bare_job_class_nests_under_the_module_job_group(
        self, tmp_path: Path
    ) -> None:
        """``JOB_GROUP`` stays the namespace; the class name is the segment
        below it, normalized.
        """
        jobs_dir = _jobs_dir(tmp_path)
        _write(jobs_dir, "pg.py", _NESTED)

        jobs = _by_name(_scan(tmp_path, jobs_dir))

        assert list(jobs) == ["pg.postgres.start"]
        assert jobs["pg.postgres.start"].group == "pg.postgres"
        assert _declaration(jobs["pg.postgres.start"]).group == "pg.postgres"


class TestReexport:
    def test_class_reexported_through_a_package_init_is_not_registered_there(
        self, tmp_path: Path
    ) -> None:
        jobs_dir = _jobs_dir(tmp_path)
        _write(jobs_dir, "pkg/defined_elsewhere.py", _DEFINED_ELSEWHERE)
        init = _write(jobs_dir, "pkg/__init__.py", _REEXPORTING_INIT)

        # The scan never walks into packages, so the re-export is exercised on
        # the same entry point the scan uses. ``extract_module`` puts the
        # module's own directory on ``sys.path``, so the sibling import binds.
        reexported = extract_module(str(init), tmp_path)
        defined = extract_module(
            str(jobs_dir / "pkg" / "defined_elsewhere.py"), tmp_path
        )

        assert reexported.jobs == []
        assert [job.name for job in defined.jobs] == ["pg.start"]


class TestAcceptanceGate:
    """AC-1's descriptor set and AC-5's tag order on ``app.get_jobs()``."""

    _AC1 = '''
    from typing import ClassVar

    from pydantic import BaseModel

    from functualize.job import Shell, job
    from functualize.job.decorators import Guards


    class Database(BaseModel):
        JOB_TAGS: ClassVar[tuple[str, ...]] = ("t1",)
        host: str = "db.internal"


    @job(group="pg")
    class Postgres(Database):
        def start(self, sh: Shell) -> None:
            """Start."""

        @job(guards=Guards(preconditions=["network-up"]), tags=["mine"])
        def stop(self, sh: Shell) -> None:
            """Stop."""
    '''

    def test_get_jobs_lists_exactly_pg_start_and_pg_stop(self, tmp_path: Path) -> None:
        jobs_dir = _jobs_dir(tmp_path)
        _write(jobs_dir, "pg.py", self._AC1)

        app = FunctualizeApp(
            "a", job_sources=JobSources(directories=[str(jobs_dir)], lazy=False)
        )

        assert sorted(job.name for job in app.get_jobs()) == ["pg.start", "pg.stop"]

    def test_get_jobs_carries_ac5_tag_order_and_guards(self, tmp_path: Path) -> None:
        jobs_dir = _jobs_dir(tmp_path)
        _write(jobs_dir, "pg.py", self._AC1)

        app = FunctualizeApp(
            "a", job_sources=JobSources(directories=[str(jobs_dir)], lazy=False)
        )
        jobs = {job.name: job for job in app.get_jobs()}

        declarations = {name: job.declaration for name, job in jobs.items()}
        assert declarations["pg.stop"] is not None
        assert declarations["pg.stop"].tags == ("mine", "t1")
        assert declarations["pg.stop"].guards is not None
        assert declarations["pg.stop"].guards.preconditions == ("network-up",)
        assert declarations["pg.start"] is not None
        assert declarations["pg.start"].tags == ("t1",)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-v"]))
