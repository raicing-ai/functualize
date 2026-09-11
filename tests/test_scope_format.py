"""Scope file format: the fail-closed half of the runtime state store.

The table in `scope_format`'s docstring, executable. Every row where
`state_format` degrades to empty, this module refuses — and the refusal must
leave the file where it is, or the next run starts the workflow over.
"""

from __future__ import annotations

import json

import pytest

from functualize._primitives.fresh_format import (
    FRESH_FILENAME,
    resolve_fresh_path,
)
from functualize._primitives.scope_format import (
    SCOPES_FILENAME,
    SCOPES_VERSION,
    clear_scopes,
    empty_scopes,
    load_scopes,
    resolve_scopes_path,
    save_scopes,
    update_scopes,
)
from functualize._types.errors import ScopeStoreUnreadableError


class TestEnvelope:
    def test_empty_envelope_is_two_keys(self) -> None:
        assert empty_scopes() == {"format_version": SCOPES_VERSION, "scopes": {}}

    def test_round_trip(self, tmp_path) -> None:
        path = tmp_path / SCOPES_FILENAME
        envelope = empty_scopes()
        envelope["scopes"]["s1"] = {"status": "blocked", "position": "approve"}
        save_scopes(path, envelope)
        assert load_scopes(path)["scopes"]["s1"]["position"] == "approve"

    def test_save_stamps_the_current_version(self, tmp_path) -> None:
        path = tmp_path / SCOPES_FILENAME
        save_scopes(path, {"format_version": 99, "scopes": {}})
        assert json.loads(path.read_text())["format_version"] == SCOPES_VERSION

    def test_save_leaves_no_temp_files(self, tmp_path) -> None:
        path = tmp_path / SCOPES_FILENAME
        save_scopes(path, empty_scopes())
        assert [p.name for p in tmp_path.iterdir()] == [SCOPES_FILENAME]


class TestLocation:
    def test_scopes_file_is_the_state_file_sibling(self, tmp_path) -> None:
        """One upward walk, one answer — the two files can never land in
        different directories or different modes."""
        (tmp_path / ".functualize").mkdir()
        state = resolve_fresh_path(tmp_path)
        scopes = resolve_scopes_path(tmp_path)
        assert scopes.parent == state.parent
        assert state.name == FRESH_FILENAME
        assert scopes.name == SCOPES_FILENAME

    def test_sibling_rule_holds_in_standalone_mode(self, tmp_path) -> None:
        """No .functualize/ — both fall back to the XDG cache, together."""
        assert (
            resolve_scopes_path(tmp_path).parent == resolve_fresh_path(tmp_path).parent
        )


class TestFailClosed:
    """Where `state_format` degrades to empty, this refuses (AC-4, AC-6)."""

    def test_missing_file_reads_as_no_scopes(self, tmp_path) -> None:
        assert load_scopes(tmp_path / "nope.json") == empty_scopes()

    def test_corrupt_json_refuses(self, tmp_path) -> None:
        path = tmp_path / SCOPES_FILENAME
        path.write_text("{not valid json")
        with pytest.raises(ScopeStoreUnreadableError):
            load_scopes(path)

    def test_truncated_write_refuses(self, tmp_path) -> None:
        path = tmp_path / SCOPES_FILENAME
        path.write_text('{"format_version": 1, "scopes": {"a"')
        with pytest.raises(ScopeStoreUnreadableError):
            load_scopes(path)

    def test_non_dict_refuses(self, tmp_path) -> None:
        path = tmp_path / SCOPES_FILENAME
        path.write_text("[1, 2, 3]")
        with pytest.raises(ScopeStoreUnreadableError):
            load_scopes(path)

    def test_version_mismatch_refuses_and_reports_both_versions(self, tmp_path) -> None:
        path = tmp_path / SCOPES_FILENAME
        path.write_text(
            json.dumps({"format_version": SCOPES_VERSION + 1, "scopes": {"a": {}}})
        )
        with pytest.raises(ScopeStoreUnreadableError) as excinfo:
            load_scopes(path)
        assert excinfo.value.found_version == SCOPES_VERSION + 1
        assert excinfo.value.expected_version == SCOPES_VERSION

    def test_scopes_section_not_a_dict_refuses(self, tmp_path) -> None:
        path = tmp_path / SCOPES_FILENAME
        path.write_text(json.dumps({"format_version": SCOPES_VERSION, "scopes": []}))
        with pytest.raises(ScopeStoreUnreadableError):
            load_scopes(path)

    def test_missing_version_refuses_rather_than_assuming_current(
        self, tmp_path
    ) -> None:
        path = tmp_path / SCOPES_FILENAME
        path.write_text(json.dumps({"scopes": {"a": {}}}))
        with pytest.raises(ScopeStoreUnreadableError) as excinfo:
            load_scopes(path)
        assert excinfo.value.found_version is None


class TestRefusalIsRepeatable:
    """The property the whole design rests on. If the read moved the file
    aside, the *second* run would find nothing, read it as 'no scopes', and
    start the workflow over — silently."""

    def test_refusing_does_not_move_or_change_the_file(self, tmp_path) -> None:
        path = tmp_path / SCOPES_FILENAME
        payload = json.dumps({"format_version": 99, "scopes": {"a": {}, "b": {}}})
        path.write_text(payload)

        for _ in range(3):
            with pytest.raises(ScopeStoreUnreadableError):
                load_scopes(path)

        assert path.exists()
        assert path.read_text() == payload
        assert [p.name for p in tmp_path.iterdir()] == [SCOPES_FILENAME]

    def test_a_writer_cannot_overwrite_a_file_it_could_not_read(self, tmp_path) -> None:
        path = tmp_path / SCOPES_FILENAME
        payload = json.dumps({"format_version": 99, "scopes": {"a": {}}})
        path.write_text(payload)
        with pytest.raises(ScopeStoreUnreadableError):
            update_scopes(path, lambda e: e["scopes"].update({"new": {}}))
        assert path.read_text() == payload


class TestRefusalLeaksNothing:
    """Scope records hold gate payloads and step return values, which may be
    secrets. The message reports a count, never content."""

    def test_message_reports_the_count_not_the_payload(self, tmp_path) -> None:
        path = tmp_path / SCOPES_FILENAME
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
            load_scopes(path)

        message = str(excinfo.value)
        assert "hunter2-SECRET" not in message
        assert excinfo.value.scope_count == 2
        assert "2 workflow scopes" in message
        assert "func builtin state clear --scopes" in message

    def test_unparseable_file_reports_no_count_rather_than_guessing(
        self, tmp_path
    ) -> None:
        path = tmp_path / SCOPES_FILENAME
        path.write_text("{broken")
        with pytest.raises(ScopeStoreUnreadableError) as excinfo:
            load_scopes(path)
        assert excinfo.value.scope_count is None


class TestUpdate:
    def test_update_starts_from_empty_when_file_absent(self, tmp_path) -> None:
        path = tmp_path / SCOPES_FILENAME
        envelope = update_scopes(path, lambda e: e["scopes"].update({"s1": {}}))
        assert envelope["scopes"] == {"s1": {}}
        assert load_scopes(path)["scopes"] == {"s1": {}}

    def test_concurrent_writers_to_different_scopes_merge(self, tmp_path) -> None:
        """Last-writer-wins per scope, not per file (AC-16)."""
        path = tmp_path / SCOPES_FILENAME
        update_scopes(path, lambda e: e["scopes"].update({"a": {"n": 1}}))
        update_scopes(path, lambda e: e["scopes"].update({"b": {"n": 2}}))
        assert load_scopes(path)["scopes"] == {"a": {"n": 1}, "b": {"n": 2}}


class TestClear:
    """The escape hatch. It is the only thing that moves the file, and it must
    work on exactly the content `load_scopes` refuses."""

    def test_clear_moves_a_readable_file_aside(self, tmp_path) -> None:
        path = tmp_path / SCOPES_FILENAME
        save_scopes(path, empty_scopes())
        backup = clear_scopes(path)
        assert backup is not None and backup.exists()
        assert not path.exists()

    def test_clear_works_on_a_file_that_cannot_be_read(self, tmp_path) -> None:
        path = tmp_path / SCOPES_FILENAME
        path.write_text("{not valid json")
        backup = clear_scopes(path)
        assert backup is not None
        assert backup.read_text() == "{not valid json"
        assert load_scopes(path) == empty_scopes()

    def test_clear_is_a_no_op_when_absent(self, tmp_path) -> None:
        assert clear_scopes(tmp_path / "nope.json") is None

    def test_clear_twice_does_not_clobber_the_first_backup(self, tmp_path) -> None:
        path = tmp_path / SCOPES_FILENAME
        path.write_text("first")
        first = clear_scopes(path)
        path.write_text("second")
        second = clear_scopes(path)
        assert first is not None and second is not None
        assert first != second
        assert first.read_text() == "first"
        assert second.read_text() == "second"
