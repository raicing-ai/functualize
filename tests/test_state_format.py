"""Tests for the runtime state store format (S3/T15, Part F + schema.md §1).

The store is derived state: a missing, corrupt, or stale-version file must
degrade to an empty envelope, never crash a run.
"""

from __future__ import annotations

import json

from functualize._primitives.state_format import (
    HISTORY_LIMIT,
    STATE_FILENAME,
    STATE_VERSION,
    empty_state,
    load_state,
    normalize_state,
    resolve_state_path,
    save_state,
    state_lock,
    update_state,
)


class TestEnvelope:
    def test_empty_state_has_every_section(self) -> None:
        state = empty_state()
        assert state["format_version"] == STATE_VERSION
        assert state["fingerprints"] == {}
        assert state["scopes"] == {}
        assert state["history"] == []
        assert state["session"] == {"preconditions": {}}

    def test_history_limit_is_positive(self) -> None:
        assert HISTORY_LIMIT > 0


class TestPathResolution:
    def test_declared_project_mode_uses_functualize_dir(self, tmp_path) -> None:
        (tmp_path / ".functualize").mkdir()
        path = resolve_state_path(tmp_path)
        assert path == tmp_path / ".functualize" / STATE_FILENAME

    def test_found_upward_from_subdirectory(self, tmp_path) -> None:
        (tmp_path / ".functualize").mkdir()
        deep = tmp_path / "a" / "b"
        deep.mkdir(parents=True)
        assert resolve_state_path(deep) == tmp_path / ".functualize" / STATE_FILENAME

    def test_standalone_mode_uses_xdg(self, tmp_path) -> None:
        # No .functualize/ anywhere under tmp_path → XDG cache path.
        path = resolve_state_path(tmp_path)
        assert path.name == STATE_FILENAME
        assert ".functualize" not in str(path)

    def test_lands_beside_the_discovery_cache(self, tmp_path) -> None:
        from functualize._primitives.cache_format import resolve_cache_path

        (tmp_path / ".functualize").mkdir()
        assert (
            resolve_state_path(tmp_path).parent == resolve_cache_path(tmp_path).parent
        )


class TestRoundTrip:
    def test_save_then_load(self, tmp_path) -> None:
        path = tmp_path / STATE_FILENAME
        state = empty_state()
        state["fingerprints"]["job::abc::checksum"] = {"generates": ["dist/x"]}
        save_state(path, state)
        assert load_state(path)["fingerprints"]["job::abc::checksum"] == {
            "generates": ["dist/x"]
        }

    def test_save_creates_parent_directory(self, tmp_path) -> None:
        path = tmp_path / "nested" / "deeper" / STATE_FILENAME
        save_state(path, empty_state())
        assert path.exists()

    def test_save_always_stamps_current_version(self, tmp_path) -> None:
        path = tmp_path / STATE_FILENAME
        save_state(path, {"format_version": 999, "fingerprints": {}})
        assert json.loads(path.read_text())["format_version"] == STATE_VERSION

    def test_save_leaves_no_temp_files(self, tmp_path) -> None:
        path = tmp_path / STATE_FILENAME
        save_state(path, empty_state())
        assert [p.name for p in tmp_path.iterdir()] == [STATE_FILENAME]


class TestTolerantLoad:
    def test_missing_file_is_empty_state(self, tmp_path) -> None:
        assert load_state(tmp_path / "nope.json") == empty_state()

    def test_corrupt_json_is_empty_state(self, tmp_path) -> None:
        path = tmp_path / STATE_FILENAME
        path.write_text("{not valid json")
        assert load_state(path) == empty_state()

    def test_truncated_write_is_empty_state(self, tmp_path) -> None:
        path = tmp_path / STATE_FILENAME
        path.write_text('{"format_version": 1, "fingerprints": {"a"')
        assert load_state(path) == empty_state()

    def test_version_mismatch_discards(self, tmp_path) -> None:
        path = tmp_path / STATE_FILENAME
        path.write_text(
            json.dumps({"format_version": STATE_VERSION + 1, "fingerprints": {"a": 1}})
        )
        assert load_state(path)["fingerprints"] == {}

    def test_non_dict_is_empty_state(self, tmp_path) -> None:
        path = tmp_path / STATE_FILENAME
        path.write_text("[1, 2, 3]")
        assert load_state(path) == empty_state()

    def test_normalize_fills_missing_sections(self) -> None:
        state = normalize_state({"format_version": STATE_VERSION})
        assert state == empty_state()

    def test_normalize_rejects_wrong_section_types(self) -> None:
        state = normalize_state(
            {"format_version": STATE_VERSION, "fingerprints": "not-a-dict"}
        )
        assert state["fingerprints"] == {}

    def test_normalize_repairs_session_shape(self) -> None:
        state = normalize_state({"format_version": STATE_VERSION, "session": {}})
        assert state["session"]["preconditions"] == {}


class TestLockedUpdate:
    def test_update_state_persists(self, tmp_path) -> None:
        path = tmp_path / STATE_FILENAME

        def add(state):
            state["history"].append({"job": "build"})

        result = update_state(path, add)
        assert result["history"] == [{"job": "build"}]
        assert load_state(path)["history"] == [{"job": "build"}]

    def test_sequential_updates_of_different_keys_both_survive(self, tmp_path) -> None:
        # Part F: concurrent runs touching *different* job keys must merge,
        # not clobber — update_state re-reads inside the lock.
        path = tmp_path / STATE_FILENAME
        update_state(path, lambda s: s["fingerprints"].update({"job-a": {"n": 1}}))
        update_state(path, lambda s: s["fingerprints"].update({"job-b": {"n": 2}}))
        fingerprints = load_state(path)["fingerprints"]
        assert fingerprints == {"job-a": {"n": 1}, "job-b": {"n": 2}}

    def test_update_starts_from_empty_when_file_absent(self, tmp_path) -> None:
        path = tmp_path / STATE_FILENAME
        state = update_state(path, lambda s: s["scopes"].update({"s1": {}}))
        assert state["format_version"] == STATE_VERSION
        assert state["scopes"] == {"s1": {}}

    def test_lock_is_released_after_block(self, tmp_path) -> None:
        path = tmp_path / STATE_FILENAME
        with state_lock(path):
            pass
        # A second acquisition must not hang or fail.
        with state_lock(path):
            pass

    def test_lock_does_not_corrupt_state_file(self, tmp_path) -> None:
        path = tmp_path / STATE_FILENAME
        save_state(path, empty_state())
        with state_lock(path):
            pass
        assert load_state(path) == empty_state()

    def test_no_absolute_paths_in_keys(self, tmp_path) -> None:
        # Part G: content-addressable-friendly — keys stay project-relative.
        path = tmp_path / STATE_FILENAME
        update_state(
            path,
            lambda s: s["fingerprints"].update(
                {"build::deadbeef::checksum": {"sources": {"src/a.py": {}}}}
            ),
        )
        for key in load_state(path)["fingerprints"]:
            assert not key.startswith("/")
