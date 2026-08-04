"""T-GO-1 acceptance: the ``GroupOptions`` base class.

Covers the plan's [A] criteria for T-GO-1:
- a subclass records its bound path on ``__group_path__``;
- ``Option``-marked fields are introspectable via ``model_fields``;
- the class is publicly exported beside ``Option``;
- the Pydantic v2 ``__init_subclass__(group=)`` hook does not clash with
  BaseModel's own machinery (scrutiny obs 1).
"""

from __future__ import annotations

from typing import Annotated

import pytest


def test_public_export_beside_option() -> None:
    """GroupOptions is importable from functualize.job, next to Option."""
    import functualize.job as job_api
    from functualize.job import GroupOptions, Option  # noqa: F401

    assert "GroupOptions" in job_api.__all__


def test_subclass_records_group_path() -> None:
    from functualize.job import GroupOptions

    class DeployOptions(GroupOptions, group="deploy"):
        env: str = "staging"

    assert DeployOptions.__group_path__ == "deploy"


def test_base_class_has_empty_path() -> None:
    """The base itself binds to no group (the __init_subclass__ hook fires
    only for subclasses)."""
    from functualize.job import GroupOptions

    assert GroupOptions.__group_path__ == ""


def test_group_path_is_not_a_model_field() -> None:
    """__group_path__ is a ClassVar, never a pydantic field."""
    from functualize.job import GroupOptions

    class DeployOptions(GroupOptions, group="deploy"):
        env: str = "staging"

    assert "__group_path__" not in DeployOptions.model_fields
    assert list(DeployOptions.model_fields) == ["env"]


def test_option_marked_fields_are_introspectable() -> None:
    """Fields carry Option markers in their annotation metadata, reachable
    the same way job-parameter markers are."""
    from functualize.job import GroupOptions, Option

    class DeployOptions(GroupOptions, group="deploy"):
        env: Annotated[str, Option("-e", help="Target environment")] = "staging"
        dry_run: Annotated[bool, Option("--dry-run")] = False

    # Pydantic resolves Annotated metadata at class creation and stores the
    # markers on FieldInfo — the same access path downstream tasks use.
    env_markers = [
        m for m in DeployOptions.model_fields["env"].metadata if isinstance(m, Option)
    ]
    assert len(env_markers) == 1
    assert env_markers[0].short == "-e"
    assert env_markers[0].help == "Target environment"

    dry_markers = [
        m
        for m in DeployOptions.model_fields["dry_run"].metadata
        if isinstance(m, Option)
    ]
    assert dry_markers[0].long == "--dry-run"


def test_nested_subclass_accumulates_fields_and_rebinds_path() -> None:
    """A deeper subclass inherits fields and may rebind to a deeper path."""
    from functualize.job import GroupOptions

    class DeployOptions(GroupOptions, group="deploy"):
        env: str = "staging"

    class WebOptions(DeployOptions, group="deploy.web"):
        replicas: int = 1

    assert WebOptions.__group_path__ == "deploy.web"
    assert set(WebOptions.model_fields) == {"env", "replicas"}


def test_minimal_subclass_no_fields_no_clash() -> None:
    """Scrutiny obs 1: the one-line empty subclass must construct cleanly —
    proving __init_subclass__(group=) does not collide with BaseModel."""
    from functualize.job import GroupOptions

    class Foo(GroupOptions, group="t"):
        pass

    assert Foo.__group_path__ == "t"
    assert Foo().model_dump() == {}


def test_validation_still_works() -> None:
    """It is a real Pydantic model — validation is inherited for free."""
    from functualize.job import GroupOptions

    class DeployOptions(GroupOptions, group="deploy"):
        replicas: int = 1

    assert DeployOptions(replicas="3").replicas == 3  # coercion
    with pytest.raises(ValueError):
        DeployOptions(replicas="not-an-int")
