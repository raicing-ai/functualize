"""Tests for the runtime state store format (S3/T15, Part F + schema.md §1).

The store is derived state: a missing, corrupt, or stale-version document must
degrade to an empty envelope, never crash a run.

**Asserted through `FreshStore`, not through a format function.**
`store-substrate` split reading in two — the substrate turns bytes into a
mapping, `normalize_fresh` coerces that mapping — so neither half alone is the
rule this file is about. The store is where they meet, and it is what every
caller uses. `scopes.json`'s opposite rule is pinned the same way in
`test_scope_format.py`.
"""

from __future__ import annotations

import json

import pytest

from functualize._primitives.fresh_format import (
    FRESH_FILENAME,
    FRESH_KEY,
    FRESH_VERSION,
    empty_fresh,
    file_lock,
    normalize_fresh,
    resolve_fresh_path,
    stamp_fresh,
)
from functualize._primitives.fresh_store import FreshStore
from functualize._primitives.substrate import JsonFileSubstrate


def _sub(tmp_path) -> JsonFileSubstrate:
    return JsonFileSubstrate(tmp_path)


def _file(sub: JsonFileSubstrate):
    """The document's file, for the assertions that are about bytes."""
    path = sub.path_for(FRESH_KEY)
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def _save(sub: JsonFileSubstrate, state: dict) -> None:
    sub.write(FRESH_KEY, stamp_fresh(state))


def _load(sub: JsonFileSubstrate) -> dict:
    """What a reader gets — the two halves of the read, joined as callers see them."""
    return FreshStore(sub)._read()


def _update(sub: JsonFileSubstrate, mutate) -> dict:
    store = FreshStore(sub)
    store._mutate(mutate)
    return store._read()


class TestEnvelope:
    def test_envelope_carries_no_scopes(self) -> None:
        """Scopes live in scopes.json. The discard-on-version-bump rule this
        file relies on is only safe because everything left here is derived."""
        assert "scopes" not in empty_fresh()

    def test_empty_state_has_every_section(self) -> None:
        state = empty_fresh()
        assert state["format_version"] == FRESH_VERSION
        assert state["fingerprints"] == {}
        assert state["session"] == {"preconditions": {}}

    def test_history_is_gone(self) -> None:
        """`durable-run-layer`/T3b — this file holds freshness verdicts only.

        Job history is derived from the run log, which recorded the same runs
        plus the nested ones plus who invoked them; shell history moved to its
        own file, because a typed command was never a run. What is left is what
        the file is actually for, which is what lets it be named for that.
        """
        assert "history" not in empty_fresh()


class TestPathResolution:
    def test_declared_project_mode_uses_functualize_dir(self, tmp_path) -> None:
        (tmp_path / ".functualize").mkdir()
        path = resolve_fresh_path(tmp_path)
        assert path == tmp_path / ".functualize" / FRESH_FILENAME

    def test_found_upward_from_subdirectory(self, tmp_path) -> None:
        (tmp_path / ".functualize").mkdir()
        deep = tmp_path / "a" / "b"
        deep.mkdir(parents=True)
        assert resolve_fresh_path(deep) == tmp_path / ".functualize" / FRESH_FILENAME

    @pytest.mark.real_state_root
    def test_standalone_mode_uses_xdg(self, tmp_path) -> None:
        # No .functualize/ anywhere under tmp_path → XDG cache path.
        #
        # Opted out of `_isolate_state_root` because this test's subject *is*
        # the resolution: that fixture sandboxes the suite by putting a
        # `.functualize/` under `tmp_path`, which is precisely the condition
        # standalone mode is defined by the absence of.
        path = resolve_fresh_path(tmp_path)
        assert path.name == FRESH_FILENAME
        assert ".functualize" not in str(path)

    def test_lands_beside_the_discovery_cache(self, tmp_path) -> None:
        from functualize._primitives.cache_format import resolve_cache_path

        (tmp_path / ".functualize").mkdir()
        assert (
            resolve_fresh_path(tmp_path).parent == resolve_cache_path(tmp_path).parent
        )


class TestRoundTrip:
    def test_save_then_load(self, tmp_path) -> None:
        sub = _sub(tmp_path)
        state = empty_fresh()
        state["fingerprints"]["job::abc::checksum"] = {"generates": ["dist/x"]}
        _save(sub, state)
        assert _load(sub)["fingerprints"]["job::abc::checksum"] == {
            "generates": ["dist/x"]
        }

    def test_save_creates_parent_directory(self, tmp_path) -> None:
        sub = _sub(tmp_path / "nested" / "deeper")
        path = _file(sub)
        _save(sub, empty_fresh())
        assert path.exists()

    def test_save_always_stamps_current_version(self, tmp_path) -> None:
        sub = _sub(tmp_path)
        path = _file(sub)
        _save(sub, {"format_version": 999, "fingerprints": {}})
        assert json.loads(path.read_text())["format_version"] == FRESH_VERSION

    def test_save_leaves_no_temp_files(self, tmp_path) -> None:
        sub = _sub(tmp_path)
        _save(sub, empty_fresh())
        assert [p.name for p in tmp_path.iterdir()] == [FRESH_FILENAME]


class TestTolerantLoad:
    def test_missing_file_is_empty_state(self, tmp_path) -> None:
        assert _load(_sub(tmp_path)) == empty_fresh()

    def test_corrupt_json_is_empty_state(self, tmp_path) -> None:
        sub = _sub(tmp_path)
        path = _file(sub)
        path.write_text("{not valid json")
        assert _load(sub) == empty_fresh()

    def test_truncated_write_is_empty_state(self, tmp_path) -> None:
        sub = _sub(tmp_path)
        path = _file(sub)
        path.write_text('{"format_version": 1, "fingerprints": {"a"')
        assert _load(sub) == empty_fresh()

    def test_version_mismatch_discards(self, tmp_path) -> None:
        sub = _sub(tmp_path)
        path = _file(sub)
        path.write_text(
            json.dumps({"format_version": FRESH_VERSION + 1, "fingerprints": {"a": 1}})
        )
        assert _load(sub)["fingerprints"] == {}

    def test_non_dict_is_empty_state(self, tmp_path) -> None:
        sub = _sub(tmp_path)
        path = _file(sub)
        path.write_text("[1, 2, 3]")
        assert _load(sub) == empty_fresh()

    def test_normalize_fills_missing_sections(self) -> None:
        state = normalize_fresh({"format_version": FRESH_VERSION})
        assert state == empty_fresh()

    def test_normalize_rejects_wrong_section_types(self) -> None:
        state = normalize_fresh(
            {"format_version": FRESH_VERSION, "fingerprints": "not-a-dict"}
        )
        assert state["fingerprints"] == {}

    def test_normalize_repairs_session_shape(self) -> None:
        state = normalize_fresh({"format_version": FRESH_VERSION, "session": {}})
        assert state["session"]["preconditions"] == {}


class TestLockedUpdate:
    def test_update_state_persists(self, tmp_path) -> None:
        sub = _sub(tmp_path)

        def add(state):
            state["fingerprints"]["build"] = {"n": 1}

        result = _update(sub, add)
        assert result["fingerprints"] == {"build": {"n": 1}}
        assert _load(sub)["fingerprints"] == {"build": {"n": 1}}

    def test_sequential_updates_of_different_keys_both_survive(self, tmp_path) -> None:
        # Part F: concurrent runs touching *different* job keys must merge,
        # not clobber — update_fresh re-reads inside the lock.
        sub = _sub(tmp_path)
        _update(sub, lambda s: s["fingerprints"].update({"job-a": {"n": 1}}))
        _update(sub, lambda s: s["fingerprints"].update({"job-b": {"n": 2}}))
        fingerprints = _load(sub)["fingerprints"]
        assert fingerprints == {"job-a": {"n": 1}, "job-b": {"n": 2}}

    def test_update_starts_from_empty_when_file_absent(self, tmp_path) -> None:
        sub = _sub(tmp_path)
        state = _update(sub, lambda s: s["fingerprints"].update({"s1": {}}))
        assert state["format_version"] == FRESH_VERSION
        assert state["fingerprints"] == {"s1": {}}

    def test_lock_is_released_after_block(self, tmp_path) -> None:
        sub = _sub(tmp_path)
        path = _file(sub)
        with file_lock(path):
            pass
        # A second acquisition must not hang or fail.
        with file_lock(path):
            pass

    def test_lock_does_not_corrupt_state_file(self, tmp_path) -> None:
        sub = _sub(tmp_path)
        path = _file(sub)
        _save(sub, empty_fresh())
        with file_lock(path):
            pass
        assert _load(sub) == empty_fresh()

    def test_no_absolute_paths_in_keys(self, tmp_path) -> None:
        # Part G: content-addressable-friendly — keys stay project-relative.
        sub = _sub(tmp_path)
        _update(
            sub,
            lambda s: s["fingerprints"].update(
                {"build::deadbeef::checksum": {"sources": {"src/a.py": {}}}}
            ),
        )
        for key in _load(sub)["fingerprints"]:
            assert not key.startswith("/")
