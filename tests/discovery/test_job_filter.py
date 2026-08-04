"""Job-level (function-level) discovery filters — the require_job_* family.

These settings judge each discovered *function*, unlike the require_file_*
family which judges each file. The distinction is the point: a file holding one
decorated job and nine undecorated helpers must contribute exactly one job.
"""

from __future__ import annotations

import textwrap
from pathlib import Path

from functualize._discovery.filter_factory import build_job_filter_from_config
from functualize._discovery.providers import DirectoryScanProvider
from functualize._primitives.job_filter import (
    AllJobFilters,
    JobDecoratorFilter,
    JobPostfixFilter,
    JobPrefixFilter,
    RawJobCandidate,
)
from functualize._primitives.pre_filter import extract_function_decorators
from functualize.app.config import DiscoveryConfig

# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------


class TestBuildJobFilterFromConfig:
    def test_no_job_level_settings_returns_none(self) -> None:
        """No require_job_* setting → no filter, so callers skip the pass."""
        assert build_job_filter_from_config(DiscoveryConfig()) is None

    def test_file_level_settings_alone_return_none(self) -> None:
        """require_file_* is the other level and must not build a job filter."""
        config = DiscoveryConfig(
            require_file_prefix="job_", require_file_import="functualize"
        )
        assert build_job_filter_from_config(config) is None

    def test_each_setting_builds_its_filter(self) -> None:
        config = DiscoveryConfig(
            require_job_prefix="run_",
            require_job_postfix="_job",
            require_job_decorators=("job",),
        )
        result = build_job_filter_from_config(config)
        assert isinstance(result, AllJobFilters)

        assert [type(f) for f in result._filters] == [
            JobPrefixFilter,
            JobPostfixFilter,
            JobDecoratorFilter,
        ]

    def test_filters_are_anded(self) -> None:
        """Multiple job-level settings must all be satisfied."""
        config = DiscoveryConfig(require_job_prefix="run_", require_job_postfix="_job")
        result = build_job_filter_from_config(config)
        assert result is not None

        assert result.should_register(RawJobCandidate("run_deploy_job"))
        assert not result.should_register(RawJobCandidate("run_deploy"))
        assert not result.should_register(RawJobCandidate("deploy_job"))


# ---------------------------------------------------------------------------
# Individual filters
# ---------------------------------------------------------------------------


class TestJobPrefixFilter:
    def test_matches_prefix(self) -> None:
        f = JobPrefixFilter("run_")
        assert f.should_register(RawJobCandidate("run_deploy"))
        assert not f.should_register(RawJobCandidate("deploy"))

    def test_judges_function_name_not_group_path(self) -> None:
        """A grouped job is judged by its function name, not "group.func"."""
        f = JobPrefixFilter("run_")
        assert f.should_register(RawJobCandidate("infra.run_deploy"))
        assert not f.should_register(RawJobCandidate("run_infra.deploy"))


class TestJobPostfixFilter:
    def test_matches_postfix(self) -> None:
        f = JobPostfixFilter("_job")
        assert f.should_register(RawJobCandidate("deploy_job"))
        assert not f.should_register(RawJobCandidate("deploy"))


class TestJobDecoratorFilter:
    def test_admits_only_decorated_functions(self) -> None:
        f = JobDecoratorFilter(("job",))
        assert f.should_register(RawJobCandidate("deploy", decorators=("job",)))
        assert not f.should_register(RawJobCandidate("helper"))

    def test_any_configured_decorator_admits(self) -> None:
        f = JobDecoratorFilter(("job", "workflow"))
        assert f.should_register(RawJobCandidate("deploy", decorators=("workflow",)))

    def test_unrelated_decorator_is_rejected(self) -> None:
        """A decorated function still needs a *configured* decorator."""
        f = JobDecoratorFilter(("job",))
        assert not f.should_register(RawJobCandidate("deploy", decorators=("cache",)))


# ---------------------------------------------------------------------------
# Decorator name extraction (the AST source of truth)
# ---------------------------------------------------------------------------


class TestExtractFunctionDecorators:
    def test_records_names_per_function(self, tmp_path: Path) -> None:
        module = tmp_path / "jobs.py"
        module.write_text(
            textwrap.dedent(
                """
                @job
                def decorated(): ...

                @job(retries=3)
                def called(): ...

                @registry.job
                def attribute(): ...

                @registry.job(retries=3)
                def called_attribute(): ...

                def plain(): ...
                """
            )
        )

        result = extract_function_decorators(module)

        assert result == {
            "decorated": ("job",),
            "called": ("job",),
            # Attribute chains collapse to their leftmost name, matching
            # DecoratorModulePreFilter's root-name rule.
            "attribute": ("registry",),
            "called_attribute": ("registry",),
            "plain": (),
        }

    def test_unparseable_file_yields_empty_mapping(self, tmp_path: Path) -> None:
        """No decorators known → a decorator filter rejects, never admits."""
        module = tmp_path / "broken.py"
        module.write_text("def oops(:\n")

        assert extract_function_decorators(module) == {}


# ---------------------------------------------------------------------------
# End-to-end through the scan provider
# ---------------------------------------------------------------------------


def _write_mixed_module(directory: Path) -> None:
    """A module whose decorated and undecorated functions must be separated."""
    (directory / "tasks.py").write_text(
        textwrap.dedent(
            """
            def job(fn):
                # A transparent decorator: nothing survives on the function
                # object, so filtering must read the source AST.
                return fn

            @job
            def deploy() -> str:
                return "deployed"

            def rollback() -> str:
                return "rolled back"
            """
        )
    )


class TestDirectoryScanProviderJobFiltering:
    def test_decorator_filter_is_function_level(self, tmp_path: Path) -> None:
        """The decorated function is registered; its undecorated sibling is not.

        This is the whole point of the job level: a file-level decorator filter
        admits the module and every public function in it.
        """
        _write_mixed_module(tmp_path)
        config = DiscoveryConfig(require_job_decorators=("job",))

        provider = DirectoryScanProvider(
            [str(tmp_path)],
            job_filter=build_job_filter_from_config(config),
        )

        assert sorted(d.name for d in provider.list_jobs()) == ["deploy"]

    def test_no_filter_registers_every_public_function(self, tmp_path: Path) -> None:
        """Unfiltered discovery takes everything public — the decorator too."""
        _write_mixed_module(tmp_path)
        provider = DirectoryScanProvider([str(tmp_path)])

        assert sorted(d.name for d in provider.list_jobs()) == [
            "deploy",
            "job",
            "rollback",
        ]

    def test_decorators_are_recorded_on_descriptors(self, tmp_path: Path) -> None:
        _write_mixed_module(tmp_path)
        provider = DirectoryScanProvider([str(tmp_path)])

        by_name = {d.name: d for d in provider.list_jobs()}
        assert by_name["deploy"].decorators == ("job",)
        assert by_name["rollback"].decorators == ()

    def test_prefix_filter_selects_functions_within_a_file(
        self, tmp_path: Path
    ) -> None:
        (tmp_path / "tasks.py").write_text(
            textwrap.dedent(
                """
                def run_deploy() -> str:
                    return "deployed"

                def helper() -> str:
                    return "helped"
                """
            )
        )
        config = DiscoveryConfig(require_job_prefix="run_")

        provider = DirectoryScanProvider(
            [str(tmp_path)],
            job_filter=build_job_filter_from_config(config),
        )

        # The filter judges the Python name (`run_deploy` matches `run_`);
        # the descriptor carries the canonical address.
        assert sorted(d.name for d in provider.list_jobs()) == ["run-deploy"]

    def test_cli_flags_reach_the_job_filter(self) -> None:
        """Each require_job_* flag survives argv parsing into the built filter.

        The flags are parsed twice — once by the argv pre-scanner for routing,
        once by Typer — so a flag missing from the pre-scanner's tables would
        silently not filter the listing.
        """
        from functualize._cli.dispatch import _extract_global_options

        argv = [
            "func",
            "--require-job-prefix",
            "run_",
            "--require-job-postfix",
            "_job",
            "--require-job-decorators",
            "job",
            "--require-file-marker",
            "__functualize__",
        ]
        _opts, cli_flags = _extract_global_options(argv)

        assert cli_flags["require_job_prefix"] == "run_"
        assert cli_flags["require_job_postfix"] == "_job"
        assert cli_flags["require_job_decorators"] == ["job"]
        assert cli_flags["require_file_marker"] == "__functualize__"

    def test_filtered_job_is_unreachable_by_name(self, tmp_path: Path) -> None:
        """A hidden job must not stay runnable — listing and lookup agree."""
        _write_mixed_module(tmp_path)
        config = DiscoveryConfig(require_job_decorators=("job",))

        provider = DirectoryScanProvider(
            [str(tmp_path)],
            job_filter=build_job_filter_from_config(config),
        )

        assert provider.get_job("deploy") is not None
        assert provider.get_job("rollback") is None
