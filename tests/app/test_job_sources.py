"""`JobSources.functions` is honoured on both boot paths, not just the static one.

The defect this closes: `functions` reached `StaticProvider` only inside
`boot_static`. `boot_static` runs only when `is_fully_explicit()` holds, which
additionally requires no directories, no children, an explicit
`config_resolution_chain`, and explicit plugins with `entry_point_group == ""`.

So the obvious thing to write --

    FunctualizeApp("a", job_sources=JobSources(functions=[alpha]))

-- discovered **zero jobs** and said nothing. Four conditions the caller never
mentioned decided whether their explicit list of functions was read at all.

`spec.md` allowed either outcome: honour it on `boot_standard` too, or refuse
construction with a message naming the other conditions. Honouring it is what
shipped, because nothing about `functions` needs the rest of explicitness --
`StaticProvider` does no I/O either way.
"""

from __future__ import annotations

import textwrap
from pathlib import Path
from typing import Any

from functualize._config import ResolutionChain
from functualize._discovery.providers import DirectoryScanProvider, StaticProvider
from functualize.app import ConfigSources, FunctualizeApp, JobSources, PluginSources
from functualize.job import job


@job
def alpha(x: int = 1) -> None:
    """Alpha."""


@job
def beta(y: str = "b") -> None:
    """Beta."""


def _names(app: FunctualizeApp) -> set[str]:
    return {d.name for d in app.get_jobs()}


def _write_jobs_dir(tmp_path: Path, *, name: str = "gamma") -> Path:
    jobs_dir = tmp_path / "jobs"
    jobs_dir.mkdir()
    (jobs_dir / "from_disk.py").write_text(
        textwrap.dedent(
            f"""
            from functualize.job import job

            @job
            def {name}(z: int = 3) -> None:
                \"\"\"From disk.\"\"\"
            """
        )
    )
    return jobs_dir


class TestTheStandardPathReadsFunctions:
    """The defect, directly. Each of these was `set()` before."""

    def test_functions_alone_yields_the_function(self) -> None:
        app = FunctualizeApp("a", job_sources=JobSources(functions=[alpha]))
        assert app._static_wiring is False, "must be the *standard* path"
        assert "alpha" in _names(app)

    def test_several_functions_all_arrive(self) -> None:
        app = FunctualizeApp("a", job_sources=JobSources(functions=[alpha, beta]))
        assert {"alpha", "beta"} <= _names(app)

    def test_functions_survive_a_lazy_boot(self) -> None:
        """`lazy=True` is the default, and it is the setting a real caller
        will have. The static path never sees it -- `boot_static` is not lazy
        -- so a fix tested only with `lazy=False` would miss the common case."""
        app = FunctualizeApp("a", job_sources=JobSources(functions=[alpha], lazy=True))
        assert "alpha" in _names(app)

    def test_the_static_path_still_reads_functions(self) -> None:
        """Regression guard: the step was *moved* out of `boot_static`, and a
        move is the kind of change that fixes one path by breaking the other."""
        app = FunctualizeApp(
            "a",
            job_sources=JobSources(directories=[], functions=[alpha], lazy=False),
            config_sources=ConfigSources(config_resolution_chain=ResolutionChain([])),
            plugin_sources=PluginSources(entry_point_group="", explicit_plugins=[]),
        )
        assert app._static_wiring is True
        assert "alpha" in _names(app)

    def test_an_empty_list_yields_nothing(self) -> None:
        """The control, and the shape `is_fully_explicit()` cares about:
        `functions=[]` is explicit *and* empty, which must stay empty."""
        app = FunctualizeApp("a", job_sources=JobSources(functions=[]))
        assert "alpha" not in _names(app)


class TestOrderingAgainstDirectories:
    """`StaticProvider` keys by bare name, and a duplicate name loses *every*
    job in the collision. So where the static provider sits relative to the
    directory provider is load-bearing, not cosmetic."""

    def test_directory_jobs_and_declared_functions_coexist(
        self, tmp_path: Path
    ) -> None:
        app = FunctualizeApp(
            "a",
            job_sources=JobSources(
                directories=[str(_write_jobs_dir(tmp_path))],
                functions=[alpha],
                lazy=False,
            ),
        )
        assert {"gamma", "alpha"} <= _names(app)

    def test_the_static_provider_sits_after_the_directory_provider(
        self, tmp_path: Path
    ) -> None:
        app = FunctualizeApp(
            "a",
            job_sources=JobSources(
                directories=[str(_write_jobs_dir(tmp_path))],
                functions=[alpha],
                lazy=False,
            ),
        )
        kinds = [
            type(getattr(entry, "provider", entry)).__name__
            for entry in app._resolution_pipeline._providers
        ]
        assert kinds == [DirectoryScanProvider.__name__, StaticProvider.__name__]

    def test_functions_then_job_providers(self) -> None:
        """The full declared order, with no directories: functions first,
        `job_providers` after -- matching the field order in `JobSources`."""
        app = FunctualizeApp(
            "a",
            job_sources=JobSources(
                functions=[alpha], job_providers=[StaticProvider([beta])]
            ),
        )
        providers: list[Any] = [
            getattr(entry, "provider", entry)
            for entry in app._resolution_pipeline._providers
        ]
        assert len(providers) == 2
        assert [d.name for d in providers[0].list_jobs()] == ["alpha"]
        assert [d.name for d in providers[1].list_jobs()] == ["beta"]


class TestParityWithTheStaticPath:
    """Whichever path booted it, the same declaration must produce the same
    descriptor -- otherwise `functions` means two different things."""

    def test_both_paths_produce_the_same_parameters(self) -> None:
        standard = FunctualizeApp("a", job_sources=JobSources(functions=[alpha]))
        static = FunctualizeApp(
            "a",
            job_sources=JobSources(directories=[], functions=[alpha], lazy=False),
            config_sources=ConfigSources(config_resolution_chain=ResolutionChain([])),
            plugin_sources=PluginSources(entry_point_group="", explicit_plugins=[]),
        )
        assert standard._static_wiring is False
        assert static._static_wiring is True

        from_standard = standard.get_job("alpha")
        from_static = static.get_job("alpha")
        assert from_standard is not None and from_static is not None
        assert [f.name for f in from_standard.parameters] == ["x"]
        assert [f.name for f in from_standard.parameters] == [
            f.name for f in from_static.parameters
        ]
        assert from_standard.source == from_static.source
