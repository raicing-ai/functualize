"""Tests for up-to-date checking (S3/T17, §D.3 + companion R4).

The two correctness fixes get first-class tests: Fix 1 (config-hash in the key)
and Fix 2 (fingerprints survive a discovery-cache rebuild), plus the R4 stat
short-circuit.
"""

from __future__ import annotations

import dataclasses

import pytest

from functualize._primitives.fingerprint import (
    FINGERPRINT_METHODS,
    build_source_map,
    canonical_json,
    classify_return_value,
    compute_args_hash,
    compute_declaration_hash,
    evaluate,
    expand_sources,
    fingerprint_key,
    hash_file,
    make_record,
    reusable_return_value,
    why_return_value_unreusable,
)


@pytest.fixture
def project(tmp_path):
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "a.py").write_text("a")
    (tmp_path / "src" / "b.py").write_text("b")
    return tmp_path


def _fresh_map(root, patterns=("src/**/*.py",), previous=None):
    return build_source_map(root, expand_sources(root, patterns), previous)


class TestCanonicalHashing:
    def test_key_order_does_not_matter(self) -> None:
        assert canonical_json({"a": 1, "b": 2}) == canonical_json({"b": 2, "a": 1})

    def test_unserializable_falls_back_to_repr(self) -> None:
        assert canonical_json({"x": object()})  # must not raise

    def test_args_hash_is_stable(self) -> None:
        assert compute_args_hash({"env": "dev"}) == compute_args_hash({"env": "dev"})

    def test_declaration_hash_changes_with_declaration(self) -> None:
        a = compute_declaration_hash({"sources": ["src/**"]})
        b = compute_declaration_hash({"sources": ["lib/**"]})
        assert a != b


class TestFingerprintKey:
    def test_shape(self) -> None:
        assert fingerprint_key("build", "abc", "checksum") == "build::abc::checksum"

    def test_fix1_config_change_changes_the_key(self) -> None:
        # `func build --env prod` right after `--env dev` must NOT be skipped.
        dev = fingerprint_key("build", compute_args_hash({"env": "dev"}), "checksum")
        prod = fingerprint_key("build", compute_args_hash({"env": "prod"}), "checksum")
        assert dev != prod

    def test_key_has_no_absolute_paths(self) -> None:
        key = fingerprint_key(
            "build", compute_args_hash({"p": "/abs/path"}), "checksum"
        )
        assert "/abs/path" not in key

    def test_methods_enumerated(self) -> None:
        assert set(FINGERPRINT_METHODS) == {"checksum", "timestamp", "none"}


class TestExpandSources:
    def test_globs_expand_sorted_and_relative(self, project) -> None:
        assert expand_sources(project, ["src/**/*.py"]) == ["src/a.py", "src/b.py"]

    def test_directories_are_not_sources(self, project) -> None:
        assert "src" not in expand_sources(project, ["src"])

    def test_missing_pattern_yields_nothing(self, project) -> None:
        assert expand_sources(project, ["nope/**/*.py"]) == []

    def test_patterns_are_deduplicated(self, project) -> None:
        both = expand_sources(project, ["src/**/*.py", "src/a.py"])
        assert both.count("src/a.py") == 1


class TestSourceMapAndR4:
    def test_entries_carry_mtime_size_sha256(self, project) -> None:
        entry = _fresh_map(project)["src/a.py"]
        assert set(entry) == {"mtime", "size", "sha256"}
        assert entry["sha256"] == hash_file(project / "src" / "a.py")

    def test_r4_reuses_hash_when_stat_matches(self, project) -> None:
        previous = _fresh_map(project)
        # Poison the recorded hash: if it is reused, the stat short-circuit
        # fired; if it is recomputed, the poison would be overwritten.
        previous["src/a.py"]["sha256"] = "POISONED"
        current = _fresh_map(project, previous=previous)
        assert current["src/a.py"]["sha256"] == "POISONED"

    def test_r4_rehashes_when_size_differs(self, project) -> None:
        previous = _fresh_map(project)
        previous["src/a.py"]["sha256"] = "POISONED"
        previous["src/a.py"]["size"] = 999  # stat no longer matches
        current = _fresh_map(project, previous=previous)
        assert current["src/a.py"]["sha256"] != "POISONED"

    def test_r4_rehashes_when_mtime_differs(self, project) -> None:
        previous = _fresh_map(project)
        previous["src/a.py"]["sha256"] = "POISONED"
        previous["src/a.py"]["mtime"] = 1.0
        current = _fresh_map(project, previous=previous)
        assert current["src/a.py"]["sha256"] != "POISONED"

    def test_vanished_file_is_skipped(self, project) -> None:
        relpaths = ["src/a.py", "src/gone.py"]
        assert "src/gone.py" not in build_source_map(project, relpaths)


class TestChecksumEvaluation:
    def test_no_record_is_stale(self, project) -> None:
        verdict = evaluate(None, root=project, source_map=_fresh_map(project))
        assert verdict.up_to_date is False
        assert "no previous run" in verdict.reason

    def test_unchanged_sources_are_fresh(self, project) -> None:
        source_map = _fresh_map(project)
        record = make_record(source_map)
        assert evaluate(record, root=project, source_map=source_map).up_to_date

    def test_edited_source_is_stale_and_named(self, project) -> None:
        record = make_record(_fresh_map(project))
        (project / "src" / "a.py").write_text("CHANGED")
        verdict = evaluate(record, root=project, source_map=_fresh_map(project))
        assert verdict.up_to_date is False
        assert "src/a.py" in verdict.changed

    def test_new_source_is_stale(self, project) -> None:
        record = make_record(_fresh_map(project))
        (project / "src" / "c.py").write_text("c")
        verdict = evaluate(record, root=project, source_map=_fresh_map(project))
        assert verdict.up_to_date is False
        assert "src/c.py" in verdict.changed

    def test_removed_source_is_stale(self, project) -> None:
        record = make_record(_fresh_map(project))
        (project / "src" / "b.py").unlink()
        verdict = evaluate(record, root=project, source_map=_fresh_map(project))
        assert verdict.up_to_date is False
        assert "src/b.py" in verdict.changed

    def test_declaration_change_invalidates(self, project) -> None:
        source_map = _fresh_map(project)
        record = make_record(source_map, job_version="v1")
        verdict = evaluate(
            record, root=project, source_map=source_map, job_version="v2"
        )
        assert verdict.up_to_date is False
        assert "declaration changed" in verdict.reason


class TestMethodNone:
    def test_never_fresh(self, project) -> None:
        source_map = _fresh_map(project)
        record = make_record(source_map)
        verdict = evaluate(record, root=project, source_map=source_map, method="none")
        assert verdict.up_to_date is False
        assert "disabled" in verdict.reason


class TestTimestampMethod:
    def test_missing_output_forces_a_run(self, project) -> None:
        verdict = evaluate(
            make_record({}),
            root=project,
            source_map=_fresh_map(project),
            generates=["dist/app.whl"],
            method="timestamp",
        )
        assert verdict.up_to_date is False
        assert "output missing" in verdict.reason

    def test_output_newer_than_sources_is_fresh(self, project) -> None:
        import os
        import time

        out = project / "dist"
        out.mkdir()
        (out / "app.whl").write_text("built")
        # Make the output decisively newer than the sources.
        future = time.time() + 10
        os.utime(out / "app.whl", (future, future))
        verdict = evaluate(
            make_record({}),
            root=project,
            source_map=_fresh_map(project),
            generates=["dist/app.whl"],
            method="timestamp",
        )
        assert verdict.up_to_date is True

    def test_source_newer_than_output_is_stale(self, project) -> None:
        import os

        out = project / "dist"
        out.mkdir()
        (out / "app.whl").write_text("built")
        os.utime(out / "app.whl", (1.0, 1.0))  # ancient output
        verdict = evaluate(
            make_record({}),
            root=project,
            source_map=_fresh_map(project),
            generates=["dist/app.whl"],
            method="timestamp",
        )
        assert verdict.up_to_date is False
        assert "newer" in verdict.reason

    def test_timestamp_without_generates_cannot_be_fresh(self, project) -> None:
        verdict = evaluate(
            make_record({}),
            root=project,
            source_map=_fresh_map(project),
            method="timestamp",
        )
        assert verdict.up_to_date is False
        assert "requires generates" in verdict.reason


class TestRecordShape:
    def test_matches_schema_section_1(self, project) -> None:
        record = make_record(
            _fresh_map(project),
            generates=["dist/x"],
            job_version="v1",
            recorded_at="2026-07-20T00:00:00",
        )
        assert set(record) == {
            "sources",
            "generates",
            "return_value",
            # Q19: whether the value may be reused is a property of the value,
            # so it is recorded beside it rather than re-derived by every
            # reader (which is how readers come to disagree).
            "return_value_reusable",
            "return_value_kind",
            "return_value_type",
            "recorded_at",
            "job_version",
        }

    def test_return_value_reserved_as_none(self, project) -> None:
        # Reserved in S3; read in S8 / result-tracking deps without a format change.
        assert make_record({})["return_value"] is None


class TestFix2CacheIndependence:
    def test_fingerprints_survive_a_discovery_cache_rebuild(self, project) -> None:
        """Fix 2: rebuilding cache.json must not drop fingerprints."""
        from functualize._primitives.cache_format import resolve_cache_path
        from functualize._primitives.state_store import StateStore

        (project / ".functualize").mkdir()
        store = StateStore.for_project(project)
        key = fingerprint_key("build", compute_args_hash({"env": "dev"}), "checksum")
        store.put_fingerprint(key, make_record(_fresh_map(project)))

        # Simulate a cache rebuild: the discovery cache is deleted/rewritten.
        cache_path = resolve_cache_path(project)
        cache_path.write_text('{"format_version": 9}')
        cache_path.unlink()

        assert StateStore.for_project(project).get_fingerprint(key) is not None


class TestReturnValueReuse:
    """Resolved Q19 — a value that cannot be carried must say so, not vanish.

    Serialization is pydantic's, not `json`'s. Classifying with `json.dumps`
    condemned `@dataclass` returns — the most idiomatic way to return
    structured data in Python — because stdlib json has no encoder for the
    *type*, though `dataclasses.asdict` renders the data in one call. The
    unreusable set is meant to be the rare tail (live connections, sockets,
    open files), not ordinary code.
    """

    def test_ordinary_values_are_reusable(self) -> None:
        from datetime import datetime
        from pathlib import Path as PathType

        from pydantic import BaseModel

        @dataclasses.dataclass
        class Report:
            rows: int

        class Model(BaseModel):
            n: int

        for value in (
            "x",
            3,
            {"a": [1, 2]},
            None,
            True,
            Report(1),
            Model(n=1),
            PathType("/tmp/x"),
            datetime(2026, 7, 21),
            {1, 2},
            (1, "a"),
            [Report(1), Report(2)],
        ):
            reusable, _kind, _type, _stored = classify_return_value(value)
            assert reusable, value

    def test_a_dataclass_is_reusable(self) -> None:
        """The case a `json.dumps` classifier got wrong."""

        @dataclasses.dataclass
        class Report:
            rows: int

        reusable, kind, type_name, stored = classify_return_value(Report(42))
        assert (reusable, kind, type_name) == (True, "json", "Report")
        assert stored == {"rows": 42}

    def test_a_path_is_reusable_and_marked(self, project) -> None:
        reusable, kind, _t, stored = classify_return_value(project / "src" / "a.py")
        assert (reusable, kind) == (True, "path")
        assert isinstance(stored, str)

    def test_a_value_with_no_schema_is_not_reusable(self) -> None:
        """The genuine tail: nothing can derive a shape for this."""

        class Conn:
            def __init__(self) -> None:
                self.sock = object()

        reusable, kind, type_name, _s = classify_return_value(Conn())
        assert (reusable, kind, type_name) == (False, "unserializable", "Conn")

    def test_the_record_stays_json(self) -> None:
        """The crash this replaces happened while writing the state file."""
        import json

        class Conn:
            def __init__(self) -> None:
                self.sock = object()

        json.dumps(make_record({}, return_value=Conn()))  # must not raise

    def test_an_unreusable_value_is_not_stored(self) -> None:
        class Conn:
            def __init__(self) -> None:
                self.sock = object()

        record = make_record({}, return_value=Conn())
        assert record["return_value"] is None
        assert record["return_value_reusable"] is False

    def test_the_consumers_type_rebuilds_the_original(self) -> None:
        """The writer stored a dict; the reader's annotation says `Report`."""

        @dataclasses.dataclass
        class Report:
            rows: int

        record = make_record({}, return_value=Report(42))
        value = reusable_return_value(record, job_name="r", expected_type=Report)
        assert isinstance(value, Report) and value.rows == 42

    def test_without_a_type_the_stored_shape_comes_back(self) -> None:
        @dataclasses.dataclass
        class Report:
            rows: int

        record = make_record({}, return_value=Report(42))
        assert reusable_return_value(record, job_name="r") == {"rows": 42}

    def test_an_item_schema_survives_via_the_annotation(self) -> None:
        """`type([Report(1)])` is `list` — the writer cannot know the item
        type, so only the consumer's annotation can restore it."""

        @dataclasses.dataclass
        class Report:
            rows: int

        record = make_record({}, return_value=[Report(1), Report(2)])
        value = reusable_return_value(record, job_name="r", expected_type=list[Report])
        assert value == [Report(1), Report(2)]

    def test_a_drifted_type_is_refused_rather_than_coerced(self) -> None:
        @dataclasses.dataclass
        class Report:
            rows: int

        @dataclasses.dataclass
        class Other:
            name: str

        record = make_record({}, return_value=Report(42))
        assert reusable_return_value(record, job_name="r", expected_type=Other) is None

    def test_reading_back_an_unreusable_value_yields_nothing(self) -> None:
        class Conn:
            def __init__(self) -> None:
                self.sock = object()

        record = make_record({}, return_value=Conn())
        assert reusable_return_value(record, job_name="make-report") is None

    def test_the_warning_fires_once_per_job(self, caplog) -> None:
        """Once per job per process — not once per dependent that missed it."""
        import logging

        from functualize._primitives import fingerprint as fp

        class Conn:
            def __init__(self) -> None:
                self.sock = object()

        fp._WARNED_UNREUSABLE.discard("noisy-job")
        record = make_record({}, return_value=Conn())
        with caplog.at_level(logging.WARNING):
            for _ in range(3):
                reusable_return_value(record, job_name="noisy-job")

        assert sum("noisy-job" in r.message for r in caplog.records) == 1

    def test_the_warning_names_the_type(self, caplog) -> None:
        import logging

        from functualize._primitives import fingerprint as fp

        class Conn:
            def __init__(self) -> None:
                self.sock = object()

        fp._WARNED_UNREUSABLE.discard("typed-job")
        with caplog.at_level(logging.WARNING):
            reusable_return_value(
                make_record({}, return_value=Conn()), job_name="typed-job"
            )
        assert any("Conn" in r.message for r in caplog.records)

    def test_a_live_path_reads_back_as_a_path(self, project) -> None:
        from pathlib import Path

        target = project / "src" / "a.py"
        value = reusable_return_value(
            make_record({}, return_value=target), job_name="p", expected_type=Path
        )
        assert isinstance(value, Path) and value == target

    def test_a_deleted_path_is_refused(self, project) -> None:
        """A cached path to a deleted file is a wrong answer, catchably.

        pydantic cannot see this: existence is a freshness question, not a
        serialization one.
        """
        from pathlib import Path

        target = project / "src" / "a.py"
        record = make_record({}, return_value=target)
        target.unlink()
        assert reusable_return_value(record, job_name="p", expected_type=Path) is None

    def test_why_explains_an_unreusable_value(self) -> None:
        class Conn:
            def __init__(self) -> None:
                self.sock = object()

        reason = why_return_value_unreusable(make_record({}, return_value=Conn()))
        assert "Conn" in reason and "not reusable" in reason

    def test_why_explains_a_vanished_path(self, project) -> None:
        target = project / "src" / "a.py"
        record = make_record({}, return_value=target)
        target.unlink()
        assert "no longer exists" in why_return_value_unreusable(record)

    def test_why_is_silent_when_nothing_is_wrong(self) -> None:
        assert why_return_value_unreusable(make_record({}, return_value="ok")) == ""


class TestWhyIsActuallyWired:
    """`why_return_value_unreusable` must have a caller (wiring discipline).

    It shipped in T32 with no production caller at all — built, unit-tested,
    and unreachable, which is the exact pattern
    `contributor/guides/wiring-discipline.md` exists to prevent. Caught by the
    S8 stage-gate orphan scan, not by the suite.
    """

    def test_func_why_reports_an_unusable_return_value(self, tmp_path) -> None:
        import threading

        from functualize.app.core import FunctualizeApp
        from functualize.job import Fingerprint, job

        (tmp_path / "a.csv").write_text("x")
        monkey = pytest.MonkeyPatch()
        monkey.chdir(tmp_path)
        try:

            @job(cache=Fingerprint(sources=["*.csv"]))
            def make_handle():  # type: ignore[no-untyped-def]
                return threading.Lock()

            app = FunctualizeApp(name="why-wired")
            app.register_dynamic_job("make_handle", make_handle)
            app.execute("make-handle")

            assert "not reusable" in app.explain("make-handle")
        finally:
            monkey.undo()

    def test_it_stays_quiet_for_an_ordinary_return(self, tmp_path) -> None:
        """A note that always fires is a note nobody reads."""
        from functualize.app.core import FunctualizeApp
        from functualize.job import Fingerprint, job

        (tmp_path / "a.csv").write_text("x")
        monkey = pytest.MonkeyPatch()
        monkey.chdir(tmp_path)
        try:

            @job(cache=Fingerprint(sources=["*.csv"]))
            def make_rows() -> dict:
                return {"rows": 1}

            app = FunctualizeApp(name="why-quiet")
            app.register_dynamic_job("make_rows", make_rows)
            app.execute("make-rows")

            assert "not reusable" not in app.explain("make-rows")
        finally:
            monkey.undo()
