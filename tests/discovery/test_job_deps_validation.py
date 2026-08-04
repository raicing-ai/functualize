"""Dependency reference resolution and cycle rejection (§A.4).

These used to drive `validate_job_deps` against a hand-built `SimpleNamespace`
app. That function is now a thin delegation: resolution, construction and
validation all live in `JobGraph`, which the executor consults too — so a graph
that validates cannot fail differently at run time.

That consolidation is the point. There were previously three resolvers for
"what job does this reference mean": the validator's (registry-aware, raising),
the executor's (registry-aware, silent — and dead by the time it was found),
and a third that was not registry-aware at all and was the one actually
running. They disagreed, and the disagreement shipped: a callable reference to
a *grouped* job validated as `build.compile_it` and executed as bare
`compile_it`, so boot passed and the run failed with `dependencies failed`.

So these tests exercise the resolver where it now lives, and the last class
drives a real `FunctualizeApp` end to end — because a fake registry is exactly
what let the old divergence hide.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from functualize._engine.job_graph import JobGraph
from functualize._types.errors import JobDependencyError


def _job(deps: tuple = (), function: object = None) -> SimpleNamespace:
    return SimpleNamespace(deps=deps, function=function)


def _registry(**jobs: SimpleNamespace) -> dict[str, object]:
    """``{name: entry}`` mirroring what registration produces.

    `RegisteredJob.dependencies` holds the *declared* names; `JobGraph`
    resolves them against the registry.
    """
    return {
        name: SimpleNamespace(
            name=name, function=spec.function, dependencies=tuple(spec.deps or ())
        )
        for name, spec in jobs.items()
    }


class TestResolution:
    def test_string_refs_resolve(self) -> None:
        graph = JobGraph(
            _registry(lint=_job(), test=_job(), deploy=_job(("lint", "test")))
        )
        assert sorted(graph.deps_of("deploy")) == ["lint", "test"]

    def test_an_unknown_ref_is_rejected(self) -> None:
        graph = JobGraph(_registry(deploy=_job(("nonexistent",))))
        with pytest.raises(JobDependencyError, match="unknown job 'nonexistent'"):
            graph.validate()

    def test_a_callable_ref_resolves_by_identity(self) -> None:
        def lint() -> None: ...

        graph = JobGraph(_registry(lint=_job(function=lint), deploy=_job((lint,))))
        assert graph.deps_of("deploy") == ["lint"]

    def test_a_bare_name_resolves_to_a_grouped_job(self) -> None:
        """The divergence that shipped: registered as `build.compile_it`,
        referenced by its leaf name. One policy now answers both callers."""
        registry = _registry(**{"build.compile_it": _job(), "ship": _job()})
        registry["ship"].dependencies = ("compile_it",)

        assert JobGraph(registry).deps_of("ship") == ["build.compile_it"]

    def test_an_ambiguous_leaf_name_is_rejected(self) -> None:
        """Two groups, same leaf: guessing would silently pick one."""
        registry = _registry(
            **{"a.build": _job(), "b.build": _job(), "ship": _job(("build",))}
        )
        with pytest.raises(JobDependencyError, match="ambiguous"):
            JobGraph(registry).validate()

    def test_a_non_reference_is_rejected(self) -> None:
        graph = JobGraph(_registry(deploy=_job((42,))))
        with pytest.raises(JobDependencyError, match="invalid dependency reference"):
            graph.validate()


class TestCycles:
    def test_a_cycle_is_rejected(self) -> None:
        graph = JobGraph(_registry(a=_job(("b",)), b=_job(("c",)), c=_job(("a",))))
        with pytest.raises(JobDependencyError, match="cycle"):
            graph.validate()

    def test_a_self_cycle_is_rejected(self) -> None:
        graph = JobGraph(_registry(a=_job(("a",))))
        with pytest.raises(JobDependencyError, match="cycle"):
            graph.validate()

    def test_a_diamond_is_valid_and_ordered(self) -> None:
        graph = JobGraph(
            _registry(
                base=_job(),
                left=_job(("base",)),
                right=_job(("base",)),
                top=_job(("left", "right")),
            )
        )
        graph.validate()
        order = graph.order_for("top")

        assert order.index("base") < order.index("left")
        assert order.count("base") == 1, "a shared upstream must appear once"
        assert "top" not in order, "the root runs after its plan, not inside it"

    def test_no_deps_yields_no_plan(self) -> None:
        graph = JobGraph(_registry(solo=_job()))
        graph.validate()
        assert graph.order_for("solo") == []


class TestValidationCoversEveryRegistrationPath:
    """The "second door": three registration paths, one of which was checked.

    Validation now happens when the graph is *built*, and nothing can run a
    dependency without building it — so a dynamically registered job is
    checked by construction rather than by remembering to call a validator.
    """

    def test_a_dynamically_registered_job_is_validated(self) -> None:
        from functualize._app.state import AppState
        from functualize.app.core import FunctualizeApp
        from functualize.job import Deps, job

        AppState.reset()
        try:
            app = FunctualizeApp(name="doors")

            @job(deps=Deps("does_not_exist"))
            def broken() -> None: ...

            app.register_dynamic_job("broken", broken)

            with pytest.raises(
                JobDependencyError, match="unknown job 'does_not_exist'"
            ):
                app.execute("broken")
        finally:
            AppState.reset()

    def test_registering_a_job_invalidates_a_built_graph(self) -> None:
        """A graph built before a registration must not answer from a stale
        picture — a reference it could not resolve may now resolve."""
        from functualize._app.state import AppState
        from functualize.app.core import FunctualizeApp
        from functualize.job import Deps, job

        AppState.reset()
        try:
            app = FunctualizeApp(name="doors")

            @job
            def upstream() -> None: ...

            @job(deps=Deps("upstream"))
            def downstream() -> None: ...

            app.register_dynamic_job("downstream", downstream)
            app.register_dynamic_job("upstream", upstream)

            assert app.execution_engine.job_graph.deps_of("downstream") == ["upstream"]
        finally:
            AppState.reset()
