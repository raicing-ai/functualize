"""Jobs published under ``functualize.jobs`` are discovered and runnable.

They were not. ``EntryPointProvider`` was written, unit-tested, exported from
``_discovery/__init__``, and **never instantiated anywhere in ``src/``** — the
fourth capability in this codebase to ship built, covered and unreachable
(`contributor/guides/wiring-discipline.md`). Meanwhile `_cli/plugin_cmd`
deliberately excluded the group from `plugin list`, reasoning that a
distribution publishing there "is supplying work for functualize to run". The
code reserved and protected a mechanism nothing consumed.

Two properties are load-bearing here and both hold *by construction* rather
than by invalidation logic, which is why this file leans on them:

* **Enumeration imports nothing.** `EntryPoint.name`/`.value` are metadata.
  The module is imported on demand, once, by the same lazy machinery the warm
  cache path uses.
* **There is no second source of truth.** The entry-point table is re-read
  each boot, so cold and warm agree and an uninstall cannot leave a ghost.
"""

from __future__ import annotations

from contextlib import ExitStack, contextmanager
from dataclasses import dataclass
from unittest.mock import patch

import pytest

from functualize._discovery.providers import EntryPointProvider


@dataclass
class _FakeEntryPoint:
    name: str
    value: str
    group: str = "functualize.jobs"


#: A module that exists and is importable, with a known callable attribute.
#: Using a real module keeps `_import_real_function` in the loop instead of
#: stubbing out the thing under test.
_REAL_MODULE = "functualize._primitives.command_paths"
_REAL_ATTR = "job_path"


@contextmanager
def _with_entry_points(*eps):
    """Patch every binding of ``entry_points`` that this feature reads.

    Two call sites, deliberately: the provider enumerates the table, and
    ``boot.wire_entry_point_jobs`` peeks at it first so it can skip
    constructing a provider for an empty group. The provider binds the name at
    module import and so needs its own patch; boot imports inside the function,
    so patching the primitive reaches that one. Patching only one leaves the
    other reading the real environment.
    """
    targets = (
        "functualize._discovery.providers.entry_points",
        "functualize._primitives.entry_points.entry_points",
    )
    with ExitStack() as stack:
        for target in targets:
            stack.enter_context(patch(target, return_value=tuple(eps)))
        yield


class TestEnumerationImportsNothing:
    """The property that made this safe to wire into every boot."""

    def test_list_jobs_does_not_import_the_module(self) -> None:
        provider = EntryPointProvider()
        with (
            _with_entry_points(
                _FakeEntryPoint("backup", f"{_REAL_MODULE}:{_REAL_ATTR}")
            ),
            patch("importlib.import_module") as mock_import,
        ):
            jobs = provider.list_jobs()

        assert [j.name for j in jobs] == ["backup"]
        assert mock_import.call_args_list == [], (
            "enumeration imported a module; that forfeits warm-boot-zero-imports "
            "for anyone who installs a job-publishing distribution"
        )

    def test_enumerated_descriptor_is_lazy(self) -> None:
        """`function is None`, exactly as the warm cache path produces."""
        provider = EntryPointProvider()
        with _with_entry_points(
            _FakeEntryPoint("backup", f"{_REAL_MODULE}:{_REAL_ATTR}")
        ):
            (job,) = provider.list_jobs()

        assert job.function is None
        assert job.source_file == "<entry_point>"
        assert job.module_path == _REAL_MODULE
        assert job.attribute_name == _REAL_ATTR


class TestMaterialization:
    def test_get_job_resolves_the_real_callable(self) -> None:
        provider = EntryPointProvider()
        with _with_entry_points(
            _FakeEntryPoint("backup", f"{_REAL_MODULE}:{_REAL_ATTR}")
        ):
            job = provider.get_job("backup")

        assert job is not None
        assert callable(job.function)
        assert job.function.__name__ == _REAL_ATTR

    def test_materialization_keeps_entry_point_provenance(self) -> None:
        """Rebuilding from the function must not lose where it came from."""
        provider = EntryPointProvider()
        with _with_entry_points(
            _FakeEntryPoint("backup", f"{_REAL_MODULE}:{_REAL_ATTR}")
        ):
            job = provider.get_job("backup")

        assert job is not None
        assert job.module_path == _REAL_MODULE
        assert job.source_file == "<entry_point>"

    def test_materialization_is_memoized(self) -> None:
        provider = EntryPointProvider()
        with _with_entry_points(
            _FakeEntryPoint("backup", f"{_REAL_MODULE}:{_REAL_ATTR}")
        ):
            first = provider.get_job("backup")
            second = provider.get_job("backup")

        assert first is second

    def test_python_spelling_also_resolves(self) -> None:
        """`func build_wheel` finds the job registered as `build-wheel`."""
        provider = EntryPointProvider()
        with _with_entry_points(
            _FakeEntryPoint("build_wheel", f"{_REAL_MODULE}:{_REAL_ATTR}")
        ):
            assert provider.get_job("build-wheel") is not None
            assert provider.get_job("build_wheel") is not None


class TestNaming:
    def test_entry_point_name_wins_over_the_function_name(self) -> None:
        """A distribution names the command; the function may be called anything."""
        provider = EntryPointProvider()
        with _with_entry_points(
            _FakeEntryPoint("backup", f"{_REAL_MODULE}:{_REAL_ATTR}")
        ):
            (job,) = provider.list_jobs()

        assert job.name == "backup"
        assert job.python_name == _REAL_ATTR

    def test_underscores_normalize_to_hyphens(self) -> None:
        provider = EntryPointProvider()
        with _with_entry_points(
            _FakeEntryPoint("build_wheel", f"{_REAL_MODULE}:{_REAL_ATTR}")
        ):
            (job,) = provider.list_jobs()
        assert job.name == "build-wheel"

    def test_bare_module_value_uses_the_entry_point_name(self) -> None:
        provider = EntryPointProvider()
        with _with_entry_points(_FakeEntryPoint("job_path", _REAL_MODULE)):
            (job,) = provider.list_jobs()
        assert job.attribute_name == "job-path" or job.attribute_name == "job_path"


class TestFailuresAreContained:
    def test_a_malformed_entry_point_is_skipped_not_fatal(self) -> None:
        provider = EntryPointProvider()
        with _with_entry_points(
            _FakeEntryPoint("broken", ""),
            _FakeEntryPoint("good", f"{_REAL_MODULE}:{_REAL_ATTR}"),
        ):
            names = [j.name for j in provider.list_jobs()]
        assert names == ["good"]

    def test_an_unimportable_module_keeps_the_name_visible(self) -> None:
        """A broken distribution must not hide itself; the user needs to see it."""
        provider = EntryPointProvider()
        with _with_entry_points(_FakeEntryPoint("backup", "no_such_module_xyz:fn")):
            listed = provider.list_jobs()
            resolved = provider.get_job("backup")

        assert [j.name for j in listed] == ["backup"]
        assert resolved is not None
        assert resolved.function is None


class TestNoSecondSourceOfTruth:
    def test_uninstalling_removes_the_job_immediately(self) -> None:
        """AC-E3 — no cache means no ghost job to invalidate."""
        with _with_entry_points(
            _FakeEntryPoint("backup", f"{_REAL_MODULE}:{_REAL_ATTR}")
        ):
            assert [j.name for j in EntryPointProvider().list_jobs()] == ["backup"]

        with _with_entry_points():
            assert EntryPointProvider().list_jobs() == []

    def test_repeated_boots_report_the_same_set(self) -> None:
        """AC-E2 — cold/warm parity, trivially, because there is one source."""
        eps = (_FakeEntryPoint("backup", f"{_REAL_MODULE}:{_REAL_ATTR}"),)
        with _with_entry_points(*eps):
            first = [j.name for j in EntryPointProvider().list_jobs()]
            second = [j.name for j in EntryPointProvider().list_jobs()]
        assert first == second == ["backup"]


class TestWiredIntoBoot:
    """AC-E4 — reachability. This provider was unreachable for its whole life,
    so a test that only constructs it directly would leave it exactly so."""

    def test_a_booted_app_sees_entry_point_jobs(self) -> None:
        from functualize.app import FunctualizeApp
        from functualize.app.config import PluginSources

        with _with_entry_points(
            _FakeEntryPoint("backup", f"{_REAL_MODULE}:{_REAL_ATTR}")
        ):
            app = FunctualizeApp(
                name="t",
                plugin_sources=PluginSources(
                    entry_point_group="functualize.plugins.__none__"
                ),
            )
            names = {j.name for j in app.get_jobs()}

        assert "backup" in names, (
            "a booted app does not see entry-point jobs — the provider is not "
            "wired into functualize._app.boot"
        )

    def test_the_job_is_in_the_command_tree(self) -> None:
        """And therefore in the TUI browser, completion, and info schema."""
        from functualize.app import FunctualizeApp
        from functualize.app.commands import build_command_tree
        from functualize.app.config import PluginSources

        with _with_entry_points(
            _FakeEntryPoint("backup", f"{_REAL_MODULE}:{_REAL_ATTR}")
        ):
            app = FunctualizeApp(
                name="t",
                plugin_sources=PluginSources(
                    entry_point_group="functualize.plugins.__none__"
                ),
            )
            assert "backup" in {n.name for n in build_command_tree(app)}


@pytest.mark.parametrize("group", ["functualize.jobs"])
def test_the_default_group_is_the_documented_one(group: str) -> None:
    assert EntryPointProvider()._group == group
