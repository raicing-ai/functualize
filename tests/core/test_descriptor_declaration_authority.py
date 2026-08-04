"""`JobDescriptor.declaration` must reach the executor, not only the graph.

Registration reads `deps` off the **descriptor** (`RegisteredJob.dependencies`,
resolved at registration precisely because a warm boot has no live function to
ask). The executor reads `cache`/`guards`/`exec` off the **function**
(`function.__functualize_job__`, five sites in `_engine/executor.py`).

For a scanned job the two cannot disagree — the provider derives the
declaration from the decorated function and materialization restores the
dunder — so the split stayed invisible until someone built a descriptor by
hand, which in practice means a `JobProvider`. There, `declaration=` with
`deps` worked and `declaration=` with `cache` silently did nothing. Partial
honouring is the worst outcome: the field visibly works, so the ignored half
reads as a runtime bug rather than an unsupported input (finding F4).
"""

from __future__ import annotations

from collections.abc import Generator, Sequence
from pathlib import Path
from typing import Any

import pytest

from functualize._app.state import AppState
from functualize._types.descriptors import JobDescriptor
from functualize._types.job_declaration import Fingerprint, JobDeclaration
from functualize.app import FunctualizeApp
from functualize.app.config import JobSources, PluginSources


@pytest.fixture(autouse=True)
def _reset_state() -> Generator[None]:
    AppState.reset()
    yield
    AppState.reset()


class HandBuiltProvider:
    """A `JobProvider` yielding a descriptor nobody decorated."""

    def __init__(self, descriptor: JobDescriptor) -> None:
        self._descriptor = descriptor

    def list_jobs(self) -> Sequence[JobDescriptor]:
        return [self._descriptor]

    def get_job(self, name: str) -> JobDescriptor | None:
        return self._descriptor if name == self._descriptor.name else None


def _descriptor(function: Any, declaration: JobDeclaration | None) -> JobDescriptor:
    return JobDescriptor(
        name="hand-built",
        group=None,
        function=function,
        docstring="Hand-built.",
        parameters=[],
        source="provider",
        metadata={},
        module_path="tests.core.test_descriptor_declaration_authority",
        declaration=declaration,
    )


class ProviderPlugin:
    """Contributes the provider during boot — the only moment that works.

    `add_job_provider()` after construction adds to the resolution pipeline but
    does not re-run `register_descriptors`, so the job never reaches the
    execution engine. A plugin's `__call__` runs at boot step 4, before job
    resolution, which is how a real `JobProvider` arrives.
    """

    name = "declaration-probe"
    version = "1.0.0"
    description = "Registers a hand-built job descriptor."

    def __init__(self, descriptor: JobDescriptor) -> None:
        self._descriptor = descriptor

    def __call__(self, app: Any) -> None:
        app.add_job_provider(HandBuiltProvider(self._descriptor))


def _app(tmp_path: Path, descriptor: JobDescriptor) -> FunctualizeApp:
    jobs = tmp_path / "jobs"
    jobs.mkdir(exist_ok=True)
    return FunctualizeApp(
        name="testapp",
        job_sources=JobSources(directories=[str(jobs)]),
        plugin_sources=PluginSources(explicit_plugins=[ProviderPlugin(descriptor)]),
    )


class TestCacheOnADescriptor:
    """The measurement from the F4 write-up: 3 invocations, 1 execution."""

    def test_declared_cache_skips_the_second_run(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        monkeypatch.chdir(tmp_path)
        source = tmp_path / "input.txt"
        source.write_text("unchanged")
        runs: list[int] = []

        def hand_built() -> str:
            runs.append(1)
            return "done"

        app = _app(
            tmp_path,
            _descriptor(
                hand_built,
                JobDeclaration(cache=Fingerprint(sources=("input.txt",))),
            ),
        )

        for _ in range(3):
            app.execute("hand-built")

        assert len(runs) == 1, (
            f"declared cache= should have skipped runs 2 and 3, got {len(runs)}"
        )

    def test_changed_source_runs_again(self, tmp_path: Path, monkeypatch) -> None:
        """Skipping is staleness, not memoization — a changed source re-runs."""
        monkeypatch.chdir(tmp_path)
        source = tmp_path / "input.txt"
        source.write_text("first")
        runs: list[str] = []

        def hand_built() -> str:
            runs.append(source.read_text())
            return "done"

        app = _app(
            tmp_path,
            _descriptor(
                hand_built,
                JobDeclaration(cache=Fingerprint(sources=("input.txt",))),
            ),
        )

        app.execute("hand-built")
        source.write_text("second")
        app.execute("hand-built")

        assert runs == ["first", "second"]


class TestNoRegression:
    def test_a_decorated_function_keeps_its_own_declaration(
        self, tmp_path: Path
    ) -> None:
        """Fill-in only: the descriptor never overwrites what @job attached.

        The scanned path derives the descriptor's declaration *from* the
        function, so overwriting would be a no-op at best and a stale-cache
        read at worst if the two ever drift.
        """
        own = JobDeclaration(category="from-the-function")
        other = JobDeclaration(category="from-the-descriptor")

        def hand_built() -> None:
            pass

        hand_built.__functualize_job__ = own  # type: ignore[attr-defined]
        _app(tmp_path, _descriptor(hand_built, other))

        assert hand_built.__functualize_job__ is own  # type: ignore[attr-defined]

    def test_no_declaration_attaches_nothing(self, tmp_path: Path) -> None:
        def hand_built() -> None:
            pass

        _app(tmp_path, _descriptor(hand_built, None))

        assert not hasattr(hand_built, "__functualize_job__")

    def test_an_unattachable_callable_warns(self, tmp_path: Path, caplog) -> None:
        """A callable that takes no attributes must say so, not fall silent.

        Silence is the whole bug: the declaration would be accepted, ignored,
        and indistinguishable from a runtime fault.
        """

        class Slotted:
            __slots__ = ()

            def __call__(self) -> None:
                pass

        _app(tmp_path, _descriptor(Slotted(), JobDeclaration(category="x")))

        assert any("could not be attached" in r.message for r in caplog.records), (
            "expected a warning naming the job whose declaration was dropped"
        )
