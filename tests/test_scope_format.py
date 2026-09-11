"""Scope file format: the fail-closed half of the runtime state store.

The table in `scope_format`'s docstring, executable. Every row where
`state_format` degrades to empty, this module refuses — and the refusal must
leave the document where it is, or the next run starts the workflow over.

**Asserted through `ScopeStore`, not through a format function.** `store-substrate`
split reading in two: the substrate turns bytes into a mapping, and
`normalize_scopes` decides whether that mapping can be honoured. Neither half
alone is the rule — "missing reads as no scopes" lives in the store, and
"unreadable refuses" lives in the format — so a test of either half would pin
half the table. The store is where the two meet, and it is what every caller
actually uses.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from functualize._primitives.fresh_format import (
    FRESH_FILENAME,
    resolve_fresh_path,
)
from functualize._primitives.scope_format import (
    SCOPES_FILENAME,
    SCOPES_KEY,
    SCOPES_VERSION,
    empty_scopes,
    stamp_scopes,
)
from functualize._primitives.scope_store import ScopeStore
from functualize._primitives.substrate import JsonFileSubstrate
from functualize._types.errors import ScopeStoreUnreadableError


def _sub(tmp_path) -> JsonFileSubstrate:
    return JsonFileSubstrate(tmp_path)


def _file(sub: JsonFileSubstrate):
    """The document's file, for the assertions that are about bytes."""
    path = sub.path_for(SCOPES_KEY)
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def _save(sub: JsonFileSubstrate, envelope: dict) -> None:
    sub.write(SCOPES_KEY, stamp_scopes(envelope))


def _load(sub: JsonFileSubstrate) -> dict:
    """What a reader gets — the two halves of the read, joined as callers see them."""
    return ScopeStore(sub)._read()


def _update(sub: JsonFileSubstrate, mutate) -> dict:
    store = ScopeStore(sub)
    with store.batch():
        mutate(store._read())
    return store._read()


class TestEnvelope:
    def test_empty_envelope_is_two_keys(self) -> None:
        assert empty_scopes() == {"format_version": SCOPES_VERSION, "scopes": {}}

    def test_round_trip(self, tmp_path) -> None:
        sub = _sub(tmp_path)
        envelope = empty_scopes()
        envelope["scopes"]["s1"] = {"status": "blocked", "position": "approve"}
        _save(sub, envelope)
        assert _load(sub)["scopes"]["s1"]["position"] == "approve"

    def test_save_stamps_the_current_version(self, tmp_path) -> None:
        sub = _sub(tmp_path)
        path = _file(sub)
        _save(sub, {"format_version": 99, "scopes": {}})
        assert json.loads(path.read_text())["format_version"] == SCOPES_VERSION

    def test_save_leaves_no_temp_files(self, tmp_path) -> None:
        sub = _sub(tmp_path)
        _save(sub, empty_scopes())
        assert [p.name for p in tmp_path.iterdir()] == [SCOPES_FILENAME]


class TestLocation:
    def test_scopes_file_is_the_state_file_sibling(self, tmp_path) -> None:
        """One upward walk, one answer — the two files can never land in
        different directories or different modes."""
        (tmp_path / ".functualize").mkdir()
        state = resolve_fresh_path(tmp_path)
        scopes = JsonFileSubstrate.for_project(tmp_path).path_for(SCOPES_KEY)
        assert scopes.parent == state.parent
        assert state.name == FRESH_FILENAME
        assert scopes.name == SCOPES_FILENAME

    def test_sibling_rule_holds_in_standalone_mode(self, tmp_path) -> None:
        """No .functualize/ — both fall back to the XDG cache, together."""
        assert (
            JsonFileSubstrate.for_project(tmp_path).path_for(SCOPES_KEY).parent
            == resolve_fresh_path(tmp_path).parent
        )


class TestFailClosed:
    """Where `state_format` degrades to empty, this refuses (AC-4, AC-6)."""

    def test_missing_file_reads_as_no_scopes(self, tmp_path) -> None:
        assert _load(_sub(tmp_path)) == empty_scopes()

    def test_corrupt_json_refuses(self, tmp_path) -> None:
        sub = _sub(tmp_path)
        path = _file(sub)
        path.write_text("{not valid json")
        with pytest.raises(ScopeStoreUnreadableError):
            _load(sub)

    def test_truncated_write_refuses(self, tmp_path) -> None:
        sub = _sub(tmp_path)
        path = _file(sub)
        path.write_text('{"format_version": 1, "scopes": {"a"')
        with pytest.raises(ScopeStoreUnreadableError):
            _load(sub)

    def test_non_dict_refuses(self, tmp_path) -> None:
        sub = _sub(tmp_path)
        path = _file(sub)
        path.write_text("[1, 2, 3]")
        with pytest.raises(ScopeStoreUnreadableError):
            _load(sub)

    def test_version_mismatch_refuses_and_reports_both_versions(self, tmp_path) -> None:
        sub = _sub(tmp_path)
        path = _file(sub)
        path.write_text(
            json.dumps({"format_version": SCOPES_VERSION + 1, "scopes": {"a": {}}})
        )
        with pytest.raises(ScopeStoreUnreadableError) as excinfo:
            _load(sub)
        assert excinfo.value.found_version == SCOPES_VERSION + 1
        assert excinfo.value.expected_version == SCOPES_VERSION

    def test_scopes_section_not_a_dict_refuses(self, tmp_path) -> None:
        sub = _sub(tmp_path)
        path = _file(sub)
        path.write_text(json.dumps({"format_version": SCOPES_VERSION, "scopes": []}))
        with pytest.raises(ScopeStoreUnreadableError):
            _load(sub)

    def test_missing_version_refuses_rather_than_assuming_current(
        self, tmp_path
    ) -> None:
        sub = _sub(tmp_path)
        path = _file(sub)
        path.write_text(json.dumps({"scopes": {"a": {}}}))
        with pytest.raises(ScopeStoreUnreadableError) as excinfo:
            _load(sub)
        assert excinfo.value.found_version is None


class TestRefusalIsRepeatable:
    """The property the whole design rests on. If the read moved the file
    aside, the *second* run would find nothing, read it as 'no scopes', and
    start the workflow over — silently."""

    def test_refusing_does_not_move_or_change_the_file(self, tmp_path) -> None:
        sub = _sub(tmp_path)
        path = _file(sub)
        payload = json.dumps({"format_version": 99, "scopes": {"a": {}, "b": {}}})
        path.write_text(payload)

        for _ in range(3):
            with pytest.raises(ScopeStoreUnreadableError):
                _load(sub)

        assert path.exists()
        assert path.read_text() == payload
        assert [p.name for p in tmp_path.iterdir()] == [SCOPES_FILENAME]

    def test_a_writer_cannot_overwrite_a_file_it_could_not_read(self, tmp_path) -> None:
        sub = _sub(tmp_path)
        path = _file(sub)
        payload = json.dumps({"format_version": 99, "scopes": {"a": {}}})
        path.write_text(payload)
        with pytest.raises(ScopeStoreUnreadableError):
            _update(sub, lambda e: e["scopes"].update({"new": {}}))
        assert path.read_text() == payload


class TestRefusalLeaksNothing:
    """Scope records hold gate payloads and step return values, which may be
    secrets. The message reports a count, never content."""

    def test_message_reports_the_count_not_the_payload(self, tmp_path) -> None:
        sub = _sub(tmp_path)
        path = _file(sub)
        path.write_text(
            json.dumps(
                {
                    "format_version": 99,
                    "scopes": {
                        "s1": {"gates": {"approve": {"payload": "hunter2-SECRET"}}},
                        "s2": {},
                    },
                }
            )
        )
        with pytest.raises(ScopeStoreUnreadableError) as excinfo:
            _load(sub)

        message = str(excinfo.value)
        assert "hunter2-SECRET" not in message
        assert excinfo.value.scope_count == 2
        assert "2 workflow scopes" in message
        assert "func builtin data clear --scopes" in message

    def test_unparseable_file_reports_no_count_rather_than_guessing(
        self, tmp_path
    ) -> None:
        sub = _sub(tmp_path)
        path = _file(sub)
        path.write_text("{broken")
        with pytest.raises(ScopeStoreUnreadableError) as excinfo:
            _load(sub)
        assert excinfo.value.scope_count is None


class TestUpdate:
    def test_update_starts_from_empty_when_file_absent(self, tmp_path) -> None:
        sub = _sub(tmp_path)
        envelope = _update(sub, lambda e: e["scopes"].update({"s1": {}}))
        assert envelope["scopes"] == {"s1": {}}
        assert _load(sub)["scopes"] == {"s1": {}}

    def test_concurrent_writers_to_different_scopes_merge(self, tmp_path) -> None:
        """Last-writer-wins per scope, not per file (AC-16)."""
        sub = _sub(tmp_path)
        _update(sub, lambda e: e["scopes"].update({"a": {"n": 1}}))
        _update(sub, lambda e: e["scopes"].update({"b": {"n": 2}}))
        assert _load(sub)["scopes"] == {"a": {"n": 1}, "b": {"n": 2}}


class TestClear:
    """The escape hatch. It is the only thing that moves the file, and it must
    work on exactly the content `load_scopes` refuses."""

    def test_clear_moves_a_readable_file_aside(self, tmp_path) -> None:
        sub = _sub(tmp_path)
        path = _file(sub)
        _save(sub, empty_scopes())
        backup = sub.clear(SCOPES_KEY)
        assert backup is not None and Path(backup).exists()
        assert not path.exists()

    def test_clear_works_on_a_file_that_cannot_be_read(self, tmp_path) -> None:
        sub = _sub(tmp_path)
        path = _file(sub)
        path.write_text("{not valid json")
        backup = sub.clear(SCOPES_KEY)
        assert backup is not None
        assert Path(backup).read_text() == "{not valid json"
        assert _load(sub) == empty_scopes()

    def test_clear_is_a_no_op_when_absent(self, tmp_path) -> None:
        assert _sub(tmp_path).clear(SCOPES_KEY) is None

    def test_clear_twice_does_not_clobber_the_first_backup(self, tmp_path) -> None:
        sub = _sub(tmp_path)
        path = _file(sub)
        path.write_text("first")
        first = sub.clear(SCOPES_KEY)
        path.write_text("second")
        second = sub.clear(SCOPES_KEY)
        assert first is not None and second is not None
        assert first != second
        assert Path(first).read_text() == "first"
        assert Path(second).read_text() == "second"
