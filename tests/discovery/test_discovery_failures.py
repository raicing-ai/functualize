"""Discovery failures are retained, not just logged.

The defect this closes: a job module that fails to load contributes no jobs
and writes one line to stderr. Nothing keeps it, so `builtin info` shows a
short list with no explanation and the operator has to reproduce the boot with
the logger turned up to find out why a job is missing.

**Two stages, one list.** As first specified this covered the *import* path
alone, which never sees a `SyntaxError`: a module with a plain typo is
rejected earlier, in the AST/pre-filter stage, at nine sites that catch
`(OSError, SyntaxError)` and return a default. That is the *more likely*
failure, and it is STATUS follow-up #12. Import-only would have published
`discovery_failures: []` for a syntactically broken tree — a report that
actively says "nothing is wrong", which is worse than the current silence.

**The nine sites keep swallowing.** A broken module must stay non-fatal to the
scan; it just stops being invisible.
"""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from functualize._discovery.cached_provider import CachedDirectoryScanProvider
from functualize._discovery.providers import DirectoryScanProvider
from functualize._primitives.pre_filter import (
    ASTModulePreFilter,
    DecoratorModulePreFilter,
    DisplayClassPreFilter,
    GroupOptionsPreFilter,
    ImportModulePreFilter,
    MarkerModulePreFilter,
    extract_function_decorators,
)
from functualize._types.discovery_report import (
    collecting_discovery_failures,
    record_discovery_failure,
)

GOOD = '''
from functualize.job import job


@job
def healthy(x: int = 1) -> None:
    """Healthy."""
'''

SYNTAX_ERROR = '''
from functualize.job import job


@job
def broken(x: int = 1) -> None
    """Missing the colon."""
'''

IMPORT_ERROR = '''
import nonexistent_module_xyz

from functualize.job import job


@job
def unreachable(x: int = 1) -> None:
    """Never registered."""
'''


def _tree(tmp_path: Path, **modules: str) -> Path:
    jobs = tmp_path / "jobs"
    jobs.mkdir()
    for name, source in modules.items():
        (jobs / f"{name}.py").write_text(textwrap.dedent(source))
    return jobs


class TestTheCollectorItself:
    """`_types/discovery_report.py`, in isolation."""

    def test_recording_outside_a_scope_is_a_no_op(self) -> None:
        """Every catch site calls this unconditionally, so it must be safe
        when nobody is scanning."""
        record_discovery_failure("/tmp/whatever.py", ValueError("boom"))

    def test_a_scope_collects_what_is_recorded_inside_it(self) -> None:
        with collecting_discovery_failures() as failures:
            record_discovery_failure(Path("/tmp/jobs/thing.py"), SyntaxError("bad"))
        assert len(failures) == 1
        assert failures[0].module == "thing"
        assert failures[0].path == "/tmp/jobs/thing.py"
        assert failures[0].error_type == "SyntaxError"

    def test_scopes_do_not_leak_into_each_other(self) -> None:
        with collecting_discovery_failures() as outer:
            with collecting_discovery_failures() as inner:
                record_discovery_failure("/tmp/a.py", OSError("x"))
            record_discovery_failure("/tmp/b.py", OSError("y"))
        assert [f.module for f in inner] == ["a"]
        assert [f.module for f in outer] == ["b"]

    def test_the_scope_closes_even_when_the_body_raises(self) -> None:
        try:
            with collecting_discovery_failures():
                raise RuntimeError("scan blew up")
        except RuntimeError:
            pass
        # No scope is active, so this must not land anywhere.
        record_discovery_failure("/tmp/after.py", OSError("z"))
        with collecting_discovery_failures() as fresh:
            pass
        assert fresh == []

    def test_an_identical_record_collapses(self) -> None:
        """A composite pre-filter is several filters, each of which parses the
        file itself, so one broken module is genuinely rejected three or four
        times per scan. Reporting it once per filter would tell an operator
        there are four problems where there is one -- and the count would
        track the filter configuration rather than the tree."""
        with collecting_discovery_failures() as failures:
            for _ in range(4):
                record_discovery_failure("/tmp/broken.py", SyntaxError("bad colon"))
        assert len(failures) == 1

    def test_a_different_failure_for_the_same_path_is_kept(self) -> None:
        """Deduplication must not swallow a second, distinct fact."""
        with collecting_discovery_failures() as failures:
            record_discovery_failure("/tmp/x.py", SyntaxError("bad colon"))
            record_discovery_failure("/tmp/x.py", OSError("gone"))
        assert [f.error_type for f in failures] == ["SyntaxError", "OSError"]

    def test_the_payload_shape_is_the_four_documented_keys(self) -> None:
        with collecting_discovery_failures() as failures:
            record_discovery_failure("/tmp/x.py", ImportError("no module"))
        assert set(failures[0].as_dict()) == {
            "module",
            "path",
            "error_type",
            "message",
        }


class TestTheParseStage:
    """A5b — the assertion that closes STATUS #12."""

    def test_a_syntax_error_is_retained_by_the_pre_filter(self, tmp_path: Path) -> None:
        broken = tmp_path / "broken.py"
        broken.write_text(textwrap.dedent(SYNTAX_ERROR))
        with collecting_discovery_failures() as failures:
            admitted = ASTModulePreFilter().should_import(broken)
        assert admitted is False, "the site must still swallow"
        assert [f.error_type for f in failures] == ["SyntaxError"]
        assert failures[0].path == str(broken)

    def test_a_syntax_error_is_retained_by_the_decorator_extractor(
        self, tmp_path: Path
    ) -> None:
        """`extract_function_decorators` is the one parse site that returns a
        mapping rather than a bool, so it is patched separately and can drift
        separately."""
        broken = tmp_path / "broken.py"
        broken.write_text(textwrap.dedent(SYNTAX_ERROR))
        with collecting_discovery_failures() as failures:
            assert extract_function_decorators(broken) == {}
        assert [f.error_type for f in failures] == ["SyntaxError"]

    def test_a_syntax_error_reaches_a_full_directory_scan(self, tmp_path: Path) -> None:
        """End to end: the stage that rejects a typo is reached through the
        provider, not only by calling a filter directly."""
        provider = DirectoryScanProvider(
            [str(_tree(tmp_path, good=GOOD, broken=SYNTAX_ERROR))]
        )
        names = [d.name for d in provider.list_jobs()]
        assert "healthy" in names, "a broken module must stay non-fatal"
        assert "broken" not in names

        failures = provider.discovery_failures
        assert [f.module for f in failures] == ["broken"]
        assert failures[0].error_type == "SyntaxError"


class TestEverySwallowSite:
    """The site count, executable rather than asserted in prose.

    `tasks.md` says "nine sites"; the eight it *lists* are the real number --
    seven in `_primitives/pre_filter.py` (six `should_import` methods plus
    `extract_function_decorators`) and one in `_discovery/ast_extractor.py`.
    All six filter classes below carry byte-identical `except` blocks, so a
    patch applied to five of them would pass every other test in this file.

    Each site must do **both** things: record, and still swallow.
    """

    FILTERS = [
        ASTModulePreFilter(),
        DisplayClassPreFilter(),
        GroupOptionsPreFilter(),
        ImportModulePreFilter("functualize"),
        MarkerModulePreFilter(),
        DecoratorModulePreFilter(("job",)),
    ]

    @pytest.mark.parametrize("pre_filter", FILTERS, ids=lambda f: type(f).__name__)
    def test_it_records_and_still_swallows(
        self, pre_filter: object, tmp_path: Path
    ) -> None:
        broken = tmp_path / f"{type(pre_filter).__name__}.py"
        broken.write_text(textwrap.dedent(SYNTAX_ERROR))
        with collecting_discovery_failures() as failures:
            admitted = pre_filter.should_import(broken)  # type: ignore[attr-defined]
        assert admitted is False, "a broken module must not be admitted"
        assert [f.error_type for f in failures] == ["SyntaxError"]

    @pytest.mark.parametrize("pre_filter", FILTERS, ids=lambda f: type(f).__name__)
    def test_an_unreadable_file_records_an_oserror(
        self, pre_filter: object, tmp_path: Path
    ) -> None:
        """The other half of `except (OSError, SyntaxError)`. A path that is
        not a file exercises the OSError branch without needing a permission
        change that a root CI user would not honour."""
        missing = tmp_path / "no_such_dir" / "gone.py"
        with collecting_discovery_failures() as failures:
            assert pre_filter.should_import(missing) is False  # type: ignore[attr-defined]
        assert len(failures) == 1
        assert failures[0].error_type in {"FileNotFoundError", "NotADirectoryError"}

    def test_the_ast_extractor_site_records_too(self, tmp_path: Path) -> None:
        """`_discovery/ast_extractor.py` -- the eighth site, and the only one
        outside `_primitives`."""
        from functualize._discovery.ast_extractor import (
            extract_first_level_dependencies,
        )

        broken = tmp_path / "broken.py"
        broken.write_text(textwrap.dedent(SYNTAX_ERROR))
        with collecting_discovery_failures() as failures:
            assert extract_first_level_dependencies(broken, tmp_path) == {}
        assert [f.error_type for f in failures] == ["SyntaxError"]


class TestTheImportStage:
    """A5 — the original scope."""

    def test_a_missing_dependency_is_retained(self, tmp_path: Path) -> None:
        provider = DirectoryScanProvider(
            [str(_tree(tmp_path, good=GOOD, importer=IMPORT_ERROR))]
        )
        assert [d.name for d in provider.list_jobs()] == ["healthy"]

        failures = provider.discovery_failures
        assert len(failures) == 1
        assert failures[0].module == "importer"
        assert failures[0].error_type == "ModuleNotFoundError"
        assert "nonexistent_module_xyz" in failures[0].message
        assert failures[0].path.endswith("importer.py")

    def test_both_stages_land_in_one_list(self, tmp_path: Path) -> None:
        """The point of one key rather than two: a consumer never has to know
        which stage rejected what."""
        provider = DirectoryScanProvider(
            [
                str(
                    _tree(
                        tmp_path, good=GOOD, broken=SYNTAX_ERROR, importer=IMPORT_ERROR
                    )
                )
            ]
        )
        assert [d.name for d in provider.list_jobs()] == ["healthy"]
        kinds = {f.error_type for f in provider.discovery_failures}
        assert kinds == {"SyntaxError", "ModuleNotFoundError"}


class TestACleanTreeReportsNothing:
    def test_no_failures_when_everything_reads(self, tmp_path: Path) -> None:
        provider = DirectoryScanProvider([str(_tree(tmp_path, good=GOOD))])
        provider.list_jobs()
        assert provider.discovery_failures == []

    def test_empty_before_the_first_scan(self, tmp_path: Path) -> None:
        provider = DirectoryScanProvider([str(_tree(tmp_path, broken=SYNTAX_ERROR))])
        assert provider.discovery_failures == []


class TestTheListIsPerScan:
    """A cached or lazy boot that imported nothing reports no failures. Stated
    as an assertion so a stale report cannot appear — and so the limitation is
    visible rather than discovered in production."""

    def test_the_cached_provider_records_on_a_cold_pass(self, tmp_path: Path) -> None:
        from functualize._primitives.locator import ResourceLocator

        jobs = _tree(tmp_path, good=GOOD, importer=IMPORT_ERROR)
        provider = CachedDirectoryScanProvider(
            [str(jobs)], ResourceLocator(), project_root=tmp_path
        )
        assert [d.name for d in provider.list_jobs()] == ["healthy"]
        assert [f.module for f in provider.discovery_failures] == ["importer"]

    def test_an_import_failure_is_reported_on_every_pass(self, tmp_path: Path) -> None:
        """Better than the task anticipated, and worth pinning as behaviour.

        A module that fails to import writes **no cache entry**, so it stays in
        the "new files" set on every pass and is retried — and therefore
        reported — every time. The warm-boot blind spot the task warned about
        does not apply to this half.
        """
        from functualize._primitives.locator import ResourceLocator

        jobs = _tree(tmp_path, good=GOOD, importer=IMPORT_ERROR)
        provider = CachedDirectoryScanProvider(
            [str(jobs)], ResourceLocator(), project_root=tmp_path
        )
        provider.list_jobs()
        assert [f.module for f in provider.discovery_failures] == ["importer"]

        provider.list_jobs()
        assert [f.module for f in provider.discovery_failures] == ["importer"]

    def test_a_cached_pre_filter_decision_reports_nothing_on_the_second_pass(
        self, tmp_path: Path
    ) -> None:
        """The blind spot, stated rather than discovered in production.

        `_should_import_with_cache` persists **negative** decisions keyed by
        mtime, so a file rejected at the parse stage is judged once and skipped
        thereafter — and a skipped file records nothing. The list answers "what
        did *this* pass fail to read", and a pass that re-read nothing failed
        at nothing.

        A standing inventory of broken files would be a different feature: it
        would have to survive the cache, which means writing the failure into
        the cache entry. That is deliberately not what this is.
        """
        from functualize._discovery.cached_provider import CachedDirectoryScanProvider
        from functualize._primitives.locator import ResourceLocator
        from functualize._primitives.pre_filter import ASTModulePreFilter

        jobs = _tree(tmp_path, good=GOOD, broken=SYNTAX_ERROR)
        provider = CachedDirectoryScanProvider(
            [str(jobs)],
            ResourceLocator(),
            pre_filter=ASTModulePreFilter(),
            project_root=tmp_path,
        )
        provider.list_jobs()
        assert [f.error_type for f in provider.discovery_failures] == ["SyntaxError"]

        provider.list_jobs()
        assert provider.discovery_failures == []

    def test_a_repeat_scan_replaces_rather_than_appends(self, tmp_path: Path) -> None:
        """`DirectoryScanProvider` memoizes, so this asserts the list does not
        double up if the memo is cleared."""
        provider = DirectoryScanProvider([str(_tree(tmp_path, broken=SYNTAX_ERROR))])
        provider.list_jobs()
        first = provider.discovery_failures
        provider._cache = None
        provider.list_jobs()
        assert provider.discovery_failures == first
        assert len(provider.discovery_failures) == 1
