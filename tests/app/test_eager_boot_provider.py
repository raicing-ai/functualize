"""`JobSources(lazy=False)` registers the provider boot already built.

The escape hatch for a host that needs its job modules imported at boot — for
import-time side effects, and so a binding error surfaces at construction
rather than at first use. It used to reach past the provider `boot_standard`
had built and added to the pipeline, and scan the directories a second time
through a scanner that took no discovery filter.

Four defects came out of that one substitution. Measured on 0.2.3, with a
module-level side-effect counter rather than a job list — a job list cannot
tell one import from two:

| second provider | imports, lazy=False | imports, lazy=True |
|---|---|---|
| none | 2 — correct | 2 — correct |
| `functions=[...]` | **4** | 2 |
| a child project | **4** | 2 |

Plus: `_registered_commands` keyed by the Python name where every consumer
expects the canonical one; discovery filters ignored; and half-applied when a
second provider happened to exist, so the symptom depended on unrelated
configuration.

Reach, stated plainly: no `func` invocation gets here. All three
`JobSources(...)` constructions in `_cli` hardcode `lazy=True` and there is no
flag, config key or environment variable for it. This is a library-mode defect.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from functualize import FunctualizeApp
from functualize.app.config import DiscoveryConfig, JobSources

COUNTING_JOB = '''
import pathlib

pathlib.Path(__file__).parent.joinpath("imports.log").open("a").write("{name}\\n")


def {name}() -> None:
    """A job whose module records that it was imported."""
'''

PLAIN_JOB = '''
def {name}() -> None:
    """A job."""
'''

GROUPED_JOB = '''
JOB_GROUP = "infra"


def {name}() -> None:
    """A job in a group."""
'''

EXCLUDED_WITH_SIDE_EFFECT = '''
import pathlib

pathlib.Path(__file__).parent.joinpath("excluded-ran.log").write_text("ran")


def skipped_job() -> None:
    """Lives in a file the configuration excludes."""
'''

UNSATISFIABLE_DEPENDENCY = '''
class Unprovided:
    """Nothing registers a provider for this."""


def needs_it(dep: Unprovided) -> None:
    """A job whose dependency cannot be resolved."""
'''


def _jobs(tmp_path: Path, **modules: str) -> Path:
    directory = tmp_path / "jobs"
    directory.mkdir(parents=True, exist_ok=True)
    for stem, source in modules.items():
        (directory / f"{stem}.py").write_text(source)
    return directory


def _import_count(jobs_dir: Path) -> int:
    log = jobs_dir / "imports.log"
    return len(log.read_text().splitlines()) if log.exists() else 0


def _count_imports_in_subprocess(tmp_path: Path, *, extra_source: str) -> int:
    """Boot in a fresh interpreter and count module-level side effects.

    A subprocess rather than an in-process boot because `sys.modules` persists
    across apps within one interpreter: a module already imported by an earlier
    test would not re-run its side effect, and the count would depend on test
    order rather than on the boot path.
    """
    jobs_dir = _jobs(
        tmp_path,
        alpha=COUNTING_JOB.format(name="alpha"),
        beta=COUNTING_JOB.format(name="beta"),
    )
    (tmp_path / "extra.py").write_text(PLAIN_JOB.format(name="extra_job"))
    script = f"""
import sys
sys.path.insert(0, {str(tmp_path)!r})
from functualize import FunctualizeApp
from functualize.app.config import DiscoveryConfig, JobSources
{extra_source}
app = FunctualizeApp("t", job_sources=sources, **kwargs)
print(sorted(d.name for d in app.get_jobs()))
"""
    result = subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True,
        text=True,
        cwd=tmp_path,
    )
    assert result.returncode == 0, result.stderr
    return _import_count(jobs_dir)


class TestEachAdmittedModuleIsImportedOnce:
    """D1. The promise `lazy=False` exists to make."""

    def test_with_a_second_provider_from_declared_functions(
        self, tmp_path: Path
    ) -> None:
        """A1. Was 4 for two modules: adding *any* other job source opened a
        guard that ran the whole directory scan again on top of the one that
        had already happened."""
        count = _count_imports_in_subprocess(
            tmp_path,
            extra_source=(
                "import extra\n"
                "sources = JobSources(directories=['jobs'], "
                "functions=[extra.extra_job], lazy=False)\n"
                "kwargs = {}\n"
            ),
        )

        assert count == 2

    def test_with_no_second_provider(self, tmp_path: Path) -> None:
        """A4. The control: this was already correct, so it fails if the fix
        works by disabling the eager scan wholesale rather than by routing
        it through the provider."""
        count = _count_imports_in_subprocess(
            tmp_path,
            extra_source=(
                "sources = JobSources(directories=['jobs'], lazy=False)\nkwargs = {}\n"
            ),
        )

        assert count == 2

    def test_the_lazy_path_is_unchanged(self, tmp_path: Path) -> None:
        """The invariant the eager column had to meet. Out of scope to change,
        in scope to keep."""
        count = _count_imports_in_subprocess(
            tmp_path,
            extra_source=(
                "import extra\n"
                "sources = JobSources(directories=['jobs'], "
                "functions=[extra.extra_job], lazy=True)\n"
                "kwargs = {}\n"
            ),
        )

        assert count == 2


class TestTheCommandKeySpelling:
    """D2. Every consumer of this map expects the canonical name."""

    def test_the_key_is_canonical_on_the_eager_path(self, tmp_path: Path) -> None:
        """A5. Was `__top__::deploy_thing` for the descriptor `deploy-thing`,
        so `refresh()` eviction and `_show_job_config` — both of which compare
        against the canonical name — could not match it."""
        jobs_dir = _jobs(tmp_path, deployer=PLAIN_JOB.format(name="deploy_thing"))

        app = FunctualizeApp(
            "e", job_sources=JobSources(directories=[str(jobs_dir)], lazy=False)
        )

        assert list(app.job_registry._registered_commands) == ["__top__::deploy-thing"]

    def test_both_paths_use_the_same_spelling(self, tmp_path: Path) -> None:
        eager_dir = _jobs(
            tmp_path / "e", deployer=PLAIN_JOB.format(name="deploy_thing")
        )
        lazy_dir = _jobs(tmp_path / "l", deployer=PLAIN_JOB.format(name="deploy_thing"))

        eager = FunctualizeApp(
            "e", job_sources=JobSources(directories=[str(eager_dir)], lazy=False)
        )
        lazy = FunctualizeApp(
            "l", job_sources=JobSources(directories=[str(lazy_dir)], lazy=True)
        )

        assert sorted(eager.job_registry._registered_commands) == sorted(
            lazy.job_registry._registered_commands
        )

    def test_refresh_leaves_no_phantom_behind_a_deleted_file(
        self, tmp_path: Path
    ) -> None:
        """A6. `refresh()` exists for exactly the long-lived consumers — a TUI,
        an MCP server — that would observe a job whose file is gone."""
        jobs_dir = _jobs(tmp_path, deployer=PLAIN_JOB.format(name="deploy_thing"))
        app = FunctualizeApp(
            "e", job_sources=JobSources(directories=[str(jobs_dir)], lazy=False)
        )

        (jobs_dir / "deployer.py").unlink()
        app.refresh()

        assert app.get_jobs() == []
        assert list(app.job_registry._registered_commands) == []


class TestFiltersAreHonoured:
    """D3 and D4. The provider carries the filters; the second scanner did not
    take one, and when both ran the provider's descriptors were discarded by a
    dedupe — so a filter changed which modules were *imported* without changing
    which jobs existed."""

    def test_exclude_patterns_takes_effect(self, tmp_path: Path) -> None:
        """A7."""
        jobs_dir = _jobs(
            tmp_path,
            kept=PLAIN_JOB.format(name="kept"),
            skipme=PLAIN_JOB.format(name="skipped_job"),
        )

        app = FunctualizeApp(
            "e",
            job_sources=JobSources(directories=[str(jobs_dir)], lazy=False),
            discovery_config=DiscoveryConfig(exclude_patterns=("skipme.py",)),
        )

        assert [d.name for d in app.get_jobs()] == ["kept"]

    def test_require_file_prefix_takes_effect(self, tmp_path: Path) -> None:
        jobs_dir = _jobs(
            tmp_path,
            job_kept=PLAIN_JOB.format(name="kept"),
            other=PLAIN_JOB.format(name="other"),
        )

        app = FunctualizeApp(
            "e",
            job_sources=JobSources(directories=[str(jobs_dir)], lazy=False),
            discovery_config=DiscoveryConfig(require_file_prefix="job_"),
        )

        assert [d.name for d in app.get_jobs()] == ["kept"]

    @pytest.mark.parametrize(
        "config",
        [
            DiscoveryConfig(),
            DiscoveryConfig(exclude_patterns=("skipme.py",)),
            DiscoveryConfig(require_file_prefix="job_"),
        ],
    )
    def test_both_paths_admit_the_same_names(
        self, tmp_path: Path, config: DiscoveryConfig
    ) -> None:
        """A8. Not "both filter" — two independent filter applications that
        agree today and drift tomorrow is what produced this.

        The grouped module is load-bearing. Without it this criterion passed
        while the two paths disagreed about a grouped job's *name*: the
        uncached provider carried its own extraction pass and produced the
        bare `provision` where the cached one produced `infra.provision`, so
        `func infra provision` could not find it. Two suites of plugin
        dispatch tests caught it; this one had not.
        """
        modules = {
            "job_kept": PLAIN_JOB.format(name="kept"),
            "skipme": PLAIN_JOB.format(name="skipped_job"),
            "job_grouped": GROUPED_JOB.format(name="provision"),
        }
        eager_dir = _jobs(tmp_path / "e", **modules)
        lazy_dir = _jobs(tmp_path / "l", **modules)

        eager = FunctualizeApp(
            "e",
            job_sources=JobSources(directories=[str(eager_dir)], lazy=False),
            discovery_config=config,
        )
        lazy = FunctualizeApp(
            "l",
            job_sources=JobSources(directories=[str(lazy_dir)], lazy=True),
            discovery_config=config,
        )

        assert sorted(d.name for d in eager.get_jobs()) == sorted(
            d.name for d in lazy.get_jobs()
        )

    def test_an_excluded_module_is_not_imported(self, tmp_path: Path) -> None:
        """A9, asserted by side effect rather than by the job list — the old
        behaviour imported the module and then dropped its jobs, which a job
        list cannot distinguish from not importing it.

        This is the feature's one deliberate behavioural break: a host relying
        on a side effect inside an excluded module would see it stop running.
        """
        jobs_dir = _jobs(
            tmp_path,
            kept=PLAIN_JOB.format(name="kept"),
            skipme=EXCLUDED_WITH_SIDE_EFFECT,
        )

        FunctualizeApp(
            "e",
            job_sources=JobSources(directories=[str(jobs_dir)], lazy=False),
            discovery_config=DiscoveryConfig(exclude_patterns=("skipme.py",)),
        )

        assert not (jobs_dir / "excluded-ran.log").exists()


class TestTheBootTimePromisesSurvive:
    """What `lazy=False` is *for*. These are "must keep holding", not new."""

    def test_a_di_error_still_raises_at_construction(self, tmp_path: Path) -> None:
        """A10. If eager descriptors took the lazy-proxy branch in
        `register_descriptors`, this would move to first use and the escape
        hatch would lose the guarantee it exists for."""
        jobs_dir = _jobs(tmp_path, bad=UNSATISFIABLE_DEPENDENCY)

        with pytest.raises(Exception, match="No provider for Unprovided"):
            FunctualizeApp(
                "e", job_sources=JobSources(directories=[str(jobs_dir)], lazy=False)
            )

    def test_descriptors_carry_a_live_function(self, tmp_path: Path) -> None:
        """The mechanism behind the criterion above, asserted directly so a
        later change cannot satisfy the job list while losing eager DI."""
        jobs_dir = _jobs(tmp_path, kept=PLAIN_JOB.format(name="kept"))

        app = FunctualizeApp(
            "e", job_sources=JobSources(directories=[str(jobs_dir)], lazy=False)
        )

        (descriptor,) = app.get_jobs()
        assert callable(descriptor.function)

    def test_the_eager_path_has_no_warm_variant(self, tmp_path: Path) -> None:
        """Stated as a test so a later change cannot quietly give it one: the
        eager provider is uncached by construction, which is what makes "every
        admitted module is imported at boot" true on the second run as well."""
        jobs_dir = _jobs(tmp_path, kept=PLAIN_JOB.format(name="kept"))

        app = FunctualizeApp(
            "e", job_sources=JobSources(directories=[str(jobs_dir)], lazy=False)
        )

        assert getattr(app, "_cached_provider", None) is None
        assert app._eager_provider is not None
