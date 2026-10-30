"""Decorators recorded from a class body (C2; F4, AC-5).

``extract_function_decorators`` still keys top-level functions by their bare
name, byte-identically. It now also keys each method ``"<Class>.<method>"``, and
that value carries the class's own decorators as well as the method's: the
class-level ``@job`` is what makes the method a job at all (D8), so a
``require_job_decorators`` filter has to see it. That is what lets
``JobDecoratorFilter(["job"])`` admit a class job whose method carries no
decorator of its own.

One level of nesting is deliberate — a job method lives directly in its class
body, and nothing deeper has a key this mapping can spell.
"""

from __future__ import annotations

import textwrap
from pathlib import Path

from functualize._discovery.providers import DirectoryScanProvider
from functualize._primitives.job_filter import JobDecoratorFilter, JobPostfixFilter
from functualize._primitives.pre_filter import extract_function_decorators

_CLASS_DECORATORS = """
from pydantic import BaseModel

from functualize.job import job


def cache(fn):
    # A transparent decorator: nothing survives on the function object, so the
    # recorded set has to come from the source AST.
    return fn


@job
def alpha() -> None: ...


@job(group="pg")
class Pg(BaseModel):
    def start(self) -> None: ...

    @cache
    def stop(self) -> None: ...
"""

_NESTED_CLASS = """
from pydantic import BaseModel

from functualize.job import job


def cache(fn):
    return fn


@job(group="pg")
class Outer(BaseModel):
    class Inner(BaseModel):
        @cache
        def go(self) -> None: ...
"""

_POSTFIXED_METHOD = """
from pydantic import BaseModel

from functualize.job import job


@job(group="pg")
class Pg(BaseModel):
    def deploy_job(self) -> None: ...

    def start(self) -> None: ...
"""

_PLAIN_CLASS = """
from pydantic import BaseModel


def cache(fn):
    return fn


class Helper(BaseModel):
    @cache
    def go(self) -> None: ...
"""


def _jobs_dir(tmp_path: Path) -> Path:
    d = tmp_path / "jobs"
    d.mkdir()
    return d


def _write(jobs_dir: Path, name: str, source: str) -> Path:
    path = jobs_dir / name
    path.write_text(textwrap.dedent(source))
    return path


def _names(job_filter: object, jobs_dir: Path) -> list[str]:
    provider = DirectoryScanProvider([str(jobs_dir)], job_filter=job_filter)  # type: ignore[arg-type]
    return sorted(descriptor.name for descriptor in provider.list_jobs())


class TestExtractedMapping:
    def test_methods_are_keyed_class_qualified_with_the_class_decorators(
        self, tmp_path: Path
    ) -> None:
        jobs_dir = _jobs_dir(tmp_path)
        source = _write(jobs_dir, "pg.py", _CLASS_DECORATORS)

        assert extract_function_decorators(source) == {
            # Top-level functions keep their bare key, unchanged.
            "cache": (),
            "alpha": ("job",),
            # The method's own decorators first, then its class's.
            "Pg.start": ("job",),
            "Pg.stop": ("cache", "job"),
        }

    def test_a_bare_method_name_is_not_a_key(self, tmp_path: Path) -> None:
        """The bare key belongs to top-level functions only — otherwise a
        method would pick up a same-named function's decorators."""
        jobs_dir = _jobs_dir(tmp_path)
        source = _write(jobs_dir, "pg.py", _CLASS_DECORATORS)

        recorded = extract_function_decorators(source)

        assert "start" not in recorded
        assert "stop" not in recorded

    def test_a_class_nested_in_a_class_is_not_keyed(self, tmp_path: Path) -> None:
        jobs_dir = _jobs_dir(tmp_path)
        source = _write(jobs_dir, "outer.py", _NESTED_CLASS)

        recorded = extract_function_decorators(source)

        # Only the module-level decorator helper is keyed; ``Inner.go`` gets
        # no key at all.
        assert recorded == {"cache": ()}


class TestJobDecoratorFilter:
    def test_admits_a_class_job_whose_method_carries_no_decorator(
        self, tmp_path: Path
    ) -> None:
        """D8: the class's ``@job`` is the decorator that matters."""
        jobs_dir = _jobs_dir(tmp_path)
        _write(jobs_dir, "pg.py", _CLASS_DECORATORS)

        provider = DirectoryScanProvider(
            [str(jobs_dir)], job_filter=JobDecoratorFilter(["job"])
        )
        jobs = {descriptor.name: descriptor for descriptor in provider.list_jobs()}

        assert sorted(jobs) == ["alpha", "pg.start", "pg.stop"]
        # AC-5: a class job's descriptor carries a non-empty decorator set.
        assert jobs["pg.start"].decorators == ("job",)
        assert jobs["pg.stop"].decorators == ("cache", "job")

    def test_a_method_level_decorator_still_selects_on_its_own(
        self, tmp_path: Path
    ) -> None:
        jobs_dir = _jobs_dir(tmp_path)
        _write(jobs_dir, "pg.py", _CLASS_DECORATORS)

        assert _names(JobDecoratorFilter(["cache"]), jobs_dir) == ["pg.stop"]

    def test_an_unrelated_decorator_rejects_the_class_job(self, tmp_path: Path) -> None:
        jobs_dir = _jobs_dir(tmp_path)
        _write(jobs_dir, "pg.py", _CLASS_DECORATORS)

        assert _names(JobDecoratorFilter(["something_else"]), jobs_dir) == []

    def test_a_plain_class_method_is_not_a_job_however_decorated(
        self, tmp_path: Path
    ) -> None:
        """The class-qualified key is recorded for every method, but only a
        class with its own ``@job`` contributes descriptors."""
        jobs_dir = _jobs_dir(tmp_path)
        _write(jobs_dir, "helper.py", _PLAIN_CLASS)

        assert _names(JobDecoratorFilter(["cache"]), jobs_dir) == []


class TestJobPostfixFilter:
    def test_the_postfix_judges_the_method_name(self, tmp_path: Path) -> None:
        """The canonical name is ``pg.deploy-job``; only the *method* name
        carries the underscore the filter is about."""
        jobs_dir = _jobs_dir(tmp_path)
        _write(jobs_dir, "pg.py", _POSTFIXED_METHOD)

        assert _names(JobPostfixFilter("_job"), jobs_dir) == ["pg.deploy-job"]
