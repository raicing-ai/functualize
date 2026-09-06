"""`JobSources.job_providers` is honoured on both boot paths.

The defect this closes: the field was declared, typed `list[Any]`, documented
in the dataclass docstring -- and read by nothing. `grep -rn "job_providers"
src/` returned exactly two hits, both inside `app/config.py` itself. A caller
who declared a provider there got an empty job list and no diagnostic, which
is the worst of the three possible outcomes: worse than honouring it, and
worse than refusing it.

B1 was decided as *wire it* rather than *delete it* (maintainer, 2026-09-05),
so the field must now honour everything its docstring promises: both boot
paths, and the `(provider, [transforms])` pair form.
"""

from __future__ import annotations

import textwrap
from pathlib import Path
from typing import Any

import pytest

from functualize._config import ResolutionChain
from functualize._discovery.providers import StaticProvider
from functualize._discovery.transforms import NamespaceTransform
from functualize.app import ConfigSources, FunctualizeApp, JobSources, PluginSources
from functualize.job import job


@job
def alpha(x: int = 1) -> None:
    """Alpha."""


@job
def beta(y: str = "b") -> None:
    """Beta."""


def _explicit_app(job_providers: list[Any] | None = None) -> FunctualizeApp:
    """An app that satisfies `is_fully_explicit()`, so it takes `boot_static`.

    Every condition matters: no directories, no children, an explicit
    resolution chain, and explicit plugins with an empty entry-point group.
    Relax any one of them and the app silently takes `boot_standard` instead,
    which is what makes a per-boot-path test worth writing at all.

    Note `functions=[]` rather than `None`. `is_fully_explicit()` reads
    `functions is not None`, so declaring *only* `job_providers` is not by
    itself explicit wiring -- the app falls to `boot_standard`. Whether that
    is right is a question about `is_fully_explicit()`, which this feature
    puts out of scope; here it is simply what the static path requires.
    """
    return FunctualizeApp(
        "a",
        job_sources=JobSources(
            directories=[],
            functions=[],
            job_providers=job_providers,
            lazy=False,
        ),
        config_sources=ConfigSources(config_resolution_chain=ResolutionChain([])),
        plugin_sources=PluginSources(entry_point_group="", explicit_plugins=[]),
    )


def _names(app: FunctualizeApp) -> set[str]:
    return {d.name for d in app.get_jobs()}


class TestBothBootPaths:
    """One test per path, because the two build their pipelines separately."""

    def test_the_static_path_honours_a_declared_provider(self) -> None:
        app = _explicit_app(job_providers=[StaticProvider([alpha])])
        assert app._static_wiring is True
        assert "alpha" in _names(app)

    def test_the_standard_path_honours_a_declared_provider(self) -> None:
        app = FunctualizeApp(
            "a", job_sources=JobSources(job_providers=[StaticProvider([alpha])])
        )
        assert app._static_wiring is False
        assert "alpha" in _names(app)

    def test_neither_path_invents_jobs_when_the_field_is_unset(self) -> None:
        """The control. An empty `job_providers` must stay empty, so the two
        tests above are measuring the field and not some other source."""
        assert _names(_explicit_app()) == set()
        assert "alpha" not in _names(FunctualizeApp("a", job_sources=JobSources()))


class TestTheTupleForm:
    """`(provider, [transforms])` -- the shape the docstring has promised all
    along, and the half of the contract easiest to wire and forget."""

    def test_transforms_in_the_pair_are_applied(self) -> None:
        app = FunctualizeApp(
            "a",
            job_sources=JobSources(
                job_providers=[(StaticProvider([alpha]), [NamespaceTransform("child")])]
            ),
        )
        assert "child.alpha" in _names(app)
        assert "alpha" not in _names(app)

    def test_the_pair_form_works_on_the_static_path_too(self) -> None:
        app = _explicit_app(
            job_providers=[(StaticProvider([alpha]), [NamespaceTransform("child")])]
        )
        assert app._static_wiring is True
        assert "child.alpha" in _names(app)

    def test_a_bare_provider_and_a_pair_may_be_mixed(self) -> None:
        app = FunctualizeApp(
            "a",
            job_sources=JobSources(
                job_providers=[
                    StaticProvider([alpha]),
                    (StaticProvider([beta]), [NamespaceTransform("child")]),
                ]
            ),
        )
        assert {"alpha", "child.beta"} <= _names(app)

    def test_an_empty_transform_list_is_the_bare_form(self) -> None:
        app = FunctualizeApp(
            "a", job_sources=JobSources(job_providers=[(StaticProvider([alpha]), [])])
        )
        assert "alpha" in _names(app)


class TestMalformedEntriesAreLoud:
    """The field exists to end silence; it must not start its own."""

    def test_a_one_tuple_names_the_shape_it_wanted(self) -> None:
        with pytest.raises(TypeError, match=r"1-tuple.*exactly two items"):
            FunctualizeApp(
                "a", job_sources=JobSources(job_providers=[(StaticProvider([alpha]),)])
            )

    def test_a_non_list_second_item_is_refused(self) -> None:
        with pytest.raises(TypeError, match="second item is a list"):
            FunctualizeApp(
                "a",
                job_sources=JobSources(
                    job_providers=[(StaticProvider([alpha]), NamespaceTransform("c"))]
                ),
            )

    def test_a_non_provider_is_refused_by_the_protocol_check(self) -> None:
        with pytest.raises(TypeError, match="JobProvider"):
            FunctualizeApp(
                "a", job_sources=JobSources(job_providers=["not a provider"])
            )


class TestOrderingAgainstDirectories:
    """Declared providers are added last, so the pipeline order matches the
    order the fields are declared in: directories, functions, job_providers."""

    def test_directory_jobs_and_declared_jobs_coexist(self, tmp_path: Path) -> None:
        jobs_dir = tmp_path / "jobs"
        jobs_dir.mkdir()
        (jobs_dir / "from_disk.py").write_text(
            textwrap.dedent(
                """
                from functualize.job import job

                @job
                def gamma(z: int = 3) -> None:
                    \"\"\"Gamma.\"\"\"
                """
            )
        )
        app = FunctualizeApp(
            "a",
            job_sources=JobSources(
                directories=[str(jobs_dir)],
                job_providers=[StaticProvider([alpha])],
                lazy=False,
            ),
        )
        assert {"gamma", "alpha"} <= _names(app)

    def test_the_declared_provider_sits_after_the_directory_provider(
        self, tmp_path: Path
    ) -> None:
        jobs_dir = tmp_path / "jobs"
        jobs_dir.mkdir()
        (jobs_dir / "from_disk.py").write_text("")
        app = FunctualizeApp(
            "a",
            job_sources=JobSources(
                directories=[str(jobs_dir)],
                job_providers=[StaticProvider([alpha])],
                lazy=False,
            ),
        )
        providers = [
            entry.provider if hasattr(entry, "provider") else entry[0]
            for entry in app._resolution_pipeline._providers
        ]
        assert isinstance(providers[-1], StaticProvider)
        assert len(providers) == 2


class TestDeclarativeMatchesImperative:
    """`add_job_provider()` is the imperative path. Both reach the same
    `ResolutionPipeline.add_provider`, so both must answer `get_job`.

    They differ in one respect, and it is a property of *when* they run rather
    than of this wiring: boot resolves the pipeline once and registers what it
    finds, so a provider declared in `JobSources` lands in `job_registry` and
    shows up in `get_jobs()`. One added after boot has missed that pass, and is
    reachable only through the pipeline. That asymmetry predates this change
    and is asserted here so a future re-resolution would be noticed rather than
    assumed.
    """

    def test_both_paths_answer_get_job(self) -> None:
        declared = FunctualizeApp(
            "a", job_sources=JobSources(job_providers=[StaticProvider([alpha])])
        )
        imperative = FunctualizeApp("a", job_sources=JobSources())
        imperative.add_job_provider(StaticProvider([alpha]))

        for app in (declared, imperative):
            found = app.get_job("alpha")
            assert found is not None
            assert found.name == "alpha"

    def test_both_paths_agree_on_the_pair_form(self) -> None:
        declared = FunctualizeApp(
            "a",
            job_sources=JobSources(
                job_providers=[(StaticProvider([alpha]), [NamespaceTransform("ns")])]
            ),
        )
        imperative = FunctualizeApp("a", job_sources=JobSources())
        imperative.add_job_provider(StaticProvider([alpha]), [NamespaceTransform("ns")])

        for app in (declared, imperative):
            assert [d.name for d in app._resolution_pipeline.resolve_all()] == [
                "ns.alpha"
            ]
            # Asserted through `resolve_all`, not `get_job`, because
            # `resolve_one("ns.alpha")` answers None on *both* paths: the
            # pipeline's single-name lookup does not reach a namespaced
            # descriptor. That is a defect in `NamespaceTransform.transform_get`
            # or in `resolve_one`, it predates this wiring, and it is equally
            # wrong for a declared and an added provider -- which is exactly the
            # equivalence this test is for. Pinned here so a fix is noticed.
            assert app._resolution_pipeline.resolve_one("ns.alpha") is None

    def test_only_the_declared_provider_reaches_the_registry(self) -> None:
        """The asymmetry, pinned. Declaring is strictly the stronger form."""
        declared = FunctualizeApp(
            "a", job_sources=JobSources(job_providers=[StaticProvider([alpha])])
        )
        imperative = FunctualizeApp("a", job_sources=JobSources())
        imperative.add_job_provider(StaticProvider([alpha]))

        assert "alpha" in _names(declared)
        assert "alpha" not in _names(imperative)
