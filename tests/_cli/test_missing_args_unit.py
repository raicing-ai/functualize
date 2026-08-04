"""Unit tests for get_missing_required_args."""

from __future__ import annotations

import pytest

from functualize._cli.tui.missing_args import get_missing_required_args
from functualize._types.descriptors import FieldDescriptor, JobDescriptor

# ---------------------------------------------------------------------------
# Mock helpers
# ---------------------------------------------------------------------------


class MockApp:
    def __init__(self, jobs: list[JobDescriptor]) -> None:
        self._jobs = jobs

    def get_jobs(self) -> list[JobDescriptor]:
        return self._jobs


class MockIntrospector:
    def __init__(self, jobs: list[JobDescriptor]) -> None:
        self._app = MockApp(jobs)

    @property
    def job_names(self) -> list[str]:
        return [j.name for j in self._app.get_jobs()]


# ---------------------------------------------------------------------------
# Fixture helpers
# ---------------------------------------------------------------------------


def _field(name: str, *, required: bool = True) -> FieldDescriptor:
    return FieldDescriptor(
        name=name,
        type_annotation="str",
        default=None if required else "",
        description=f"{name} field",
        required=required,
    )


def _job(name: str, fields: list[FieldDescriptor]) -> JobDescriptor:
    return JobDescriptor(name=name, group=None, parameters=fields)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_unknown_job_returns_none():
    """tokens[0] not in introspector.job_names → returns None."""
    introspector = MockIntrospector([_job("deploy", [_field("env")])])
    result = await get_missing_required_args(introspector, ["unknown_job"])
    assert result is None


@pytest.mark.asyncio
async def test_all_required_args_provided():
    """All required fields provided → is_executable=True, missing_count=0."""
    introspector = MockIntrospector([_job("deploy", [_field("env"), _field("region")])])
    result = await get_missing_required_args(
        introspector, ["deploy", "--env", "staging", "--region", "us-east-1"]
    )
    assert result is not None
    assert result.is_executable is True
    assert result.missing_count == 0
    assert result.provided_fields == {"env": "staging", "region": "us-east-1"}


@pytest.mark.asyncio
async def test_two_missing_required_args():
    """Job with 3 required fields, only 1 provided → 2 missing."""
    introspector = MockIntrospector(
        [_job("deploy", [_field("env"), _field("region"), _field("version")])]
    )
    result = await get_missing_required_args(
        introspector, ["deploy", "--env", "staging"]
    )
    assert result is not None
    assert result.is_executable is False
    assert result.missing_count == 2
    missing_names = [f.name for f in result.missing_fields]
    assert "region" in missing_names
    assert "version" in missing_names


@pytest.mark.asyncio
async def test_five_missing_required_args():
    """Job with 5 required fields, none provided → 5 missing."""
    fields = [_field(f"field_{i}") for i in range(5)]
    introspector = MockIntrospector([_job("build", fields)])
    result = await get_missing_required_args(introspector, ["build"])
    assert result is not None
    assert result.is_executable is False
    assert result.missing_count == 5


@pytest.mark.asyncio
async def test_key_equals_value_syntax():
    """--key=value syntax is parsed correctly."""
    introspector = MockIntrospector([_job("deploy", [_field("env"), _field("region")])])
    result = await get_missing_required_args(introspector, ["deploy", "--env=staging"])
    assert result is not None
    assert result.provided_fields == {"env": "staging"}
    assert result.missing_count == 1
    missing_names = [f.name for f in result.missing_fields]
    assert "region" in missing_names


@pytest.mark.asyncio
async def test_optional_fields_not_in_missing():
    """Optional fields are NOT included in missing_fields even when not provided."""
    introspector = MockIntrospector(
        [
            _job(
                "deploy",
                [
                    _field("env", required=True),
                    _field("verbose", required=False),
                    _field("debug", required=False),
                ],
            )
        ]
    )
    result = await get_missing_required_args(introspector, ["deploy"])
    assert result is not None
    assert result.missing_count == 1
    missing_names = [f.name for f in result.missing_fields]
    assert missing_names == ["env"]
    # Optional fields should not appear
    assert "verbose" not in missing_names
    assert "debug" not in missing_names
