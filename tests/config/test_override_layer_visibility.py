"""A value set at runtime must be the value every surface reports.

`JobConfigView` has three layers, and `get()` consults them in this order:

    1. the in-memory override layer (`config.set(...)`)
    2. the resolution chain (env -> file -> remote -> default)
    3. the caller's fallback

`resolve_job_fields` — the seam that exists so displays cannot disagree with
the run — used to reach past the view for `config_view._chain` and read layer 2
directly. So a value deposited through `config.set()` was what the run used and
*not* what `info --job` or `builtin env` showed: the one seam written to stop
displays lying had the lie built into it.

The gap: nothing tested the seam against a view with a non-empty override
layer. Every fixture went straight from environment to chain, which is the
one path where reaching past the view happens to give the right answer.
"""

from __future__ import annotations

import pytest
from pydantic import BaseModel, Field

from functualize._config.chain import ResolutionChain
from functualize._config.job_config import JobConfigView, resolve_job_config
from functualize._config.resolved_field import resolve_job_fields
from functualize._config.sources import DefaultSource, EnvSource


class SyncConfig(BaseModel):
    api_url: str = Field(default="https://default.example.com")
    region: str = Field(default="us-east-1")


@pytest.fixture()
def view() -> JobConfigView:
    """A view over a real chain, scoped to the `sync` section."""
    chain = ResolutionChain([EnvSource(), DefaultSource({})])
    return JobConfigView(resolution_chain=chain, default_section_prefix="sync")


def _by_name(fields):
    return {f.name: f for f in fields}


class TestTheOverrideLayerIsVisible:
    def test_an_override_is_reported_with_its_value(self, view):
        view.set("api_url", "https://set-at-runtime.example.com")

        field = _by_name(resolve_job_fields(SyncConfig, "sync", view))["api_url"]

        assert field.value == "https://set-at-runtime.example.com", (
            "the resolution seam does not see the override layer, so every "
            "surface reports a value the run will not use"
        )

    def test_an_override_is_reported_as_an_override(self, view):
        """Reporting the right value under the wrong provenance is half a lie."""
        view.set("api_url", "https://set-at-runtime.example.com")

        field = _by_name(resolve_job_fields(SyncConfig, "sync", view))["api_url"]

        assert field.source == "override"
        assert field.is_set

    def test_an_override_outranks_the_environment(self, view, monkeypatch):
        """It outranks env for the run, so it must outrank env for the display."""
        monkeypatch.setenv("SYNC_REGION", "eu-west-1")
        view.set("region", "ap-south-1")

        field = _by_name(resolve_job_fields(SyncConfig, "sync", view))["region"]

        assert field.value == "ap-south-1"

    def test_the_display_agrees_with_what_the_run_receives(self, view):
        """The property the seam exists for, asserted directly."""
        view.set("api_url", "https://set-at-runtime.example.com")

        reported = _by_name(resolve_job_fields(SyncConfig, "sync", view))["api_url"]
        received = resolve_job_config(SyncConfig, "sync", view, cli_values={})

        assert reported.value == received.api_url


class TestWithoutAnOverrideNothingChanges:
    def test_the_chain_still_answers(self, view, monkeypatch):
        """Guard the guard: the override layer must not shadow normal lookups."""
        monkeypatch.setenv("SYNC_REGION", "eu-west-1")

        field = _by_name(resolve_job_fields(SyncConfig, "sync", view))["region"]

        assert field.value == "eu-west-1"
        assert field.source == "env"

    def test_a_model_default_still_answers(self, view):
        field = _by_name(resolve_job_fields(SyncConfig, "sync", view))["api_url"]

        assert field.value == "https://default.example.com"
        assert field.source == "default"
