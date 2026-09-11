"""Shell history has its own file, and `func builtin history` still merges.

`durable-run-layer`/T3b. One ring in `state.json` held two kinds of record
under a `namespace` tag, and they went to two different places:

* **job** history was a strict subset of the run log, which recorded the same
  runs plus the nested ones plus who invoked them — so it is derived now.
* **shell** history has no counterpart anywhere. `git status` typed into shell
  mode was never a run, and the log has nowhere to put it.

The user-visible contract is that none of that shows: same records, same order,
same `--namespace` flag.
"""

from __future__ import annotations

import json
import threading
from pathlib import Path

from functualize._primitives.shell_history import (
    SHELL_HISTORY_LIMIT,
    ShellHistoryStore,
    resolve_shell_history_path,
)


class TestRoundTrip:
    def test_append_and_read_newest_first(self, tmp_path: Path) -> None:
        store = ShellHistoryStore(tmp_path / "shell-history.json")
        store.append({"command": "a"})
        store.append({"command": "b"})
        assert [e["command"] for e in store.entries()] == ["b", "a"]

    def test_limit(self, tmp_path: Path) -> None:
        store = ShellHistoryStore(tmp_path / "shell-history.json")
        for i in range(5):
            store.append({"command": str(i)})
        assert len(store.entries(limit=2)) == 2

    def test_reads_before_any_write(self, tmp_path: Path) -> None:
        assert ShellHistoryStore(tmp_path / "shell-history.json").entries() == []

    def test_it_survives_a_new_store_object(self, tmp_path: Path) -> None:
        path = tmp_path / "shell-history.json"
        ShellHistoryStore(path).append({"command": "durable"})
        assert ShellHistoryStore(path).entries()[0]["command"] == "durable"

    def test_the_ring_is_bounded(self, tmp_path: Path) -> None:
        """Bounded at the same 200 the shared ring used.

        A migration that silently shortens a user's recall is a migration
        noticed for the wrong reason.
        """
        store = ShellHistoryStore(tmp_path / "shell-history.json")
        for i in range(SHELL_HISTORY_LIMIT + 10):
            store.append({"command": str(i)})
        entries = store.entries()
        assert len(entries) == SHELL_HISTORY_LIMIT
        assert entries[0]["command"] == str(SHELL_HISTORY_LIMIT + 9)


class TestItIsAConvenience:
    """Degrades to empty rather than refusing — unlike `scopes.json`.

    The asymmetry is deliberate and is the one `state_format` and `scope_format`
    already draw: losing this costs a user their command recall, while losing a
    scope record costs an approval spent on a run that no longer exists.
    """

    def test_an_unreadable_file_reads_as_empty(self, tmp_path: Path) -> None:
        path = tmp_path / "shell-history.json"
        path.write_text("{not json")
        assert ShellHistoryStore(path).entries() == []

    def test_a_wrong_shape_reads_as_empty(self, tmp_path: Path) -> None:
        path = tmp_path / "shell-history.json"
        path.write_text(json.dumps({"entries": "not a list"}))
        assert ShellHistoryStore(path).entries() == []

    def test_writing_over_a_broken_file_works(self, tmp_path: Path) -> None:
        """The consequence of degrading: it must be recoverable by use."""
        path = tmp_path / "shell-history.json"
        path.write_text("{not json")
        store = ShellHistoryStore(path)
        store.append({"command": "after"})
        assert [e["command"] for e in store.entries()] == ["after"]


class TestConcurrentShells:
    def test_two_writers_merge(self, tmp_path: Path) -> None:
        """Two shells in one project must interleave, not clobber.

        Read-modify-write under the file's own lock, the same discipline the
        other stores use.
        """
        path = tmp_path / "shell-history.json"

        def write(tag: str) -> None:
            store = ShellHistoryStore(path)
            for i in range(20):
                store.append({"command": f"{tag}-{i}"})

        threads = [threading.Thread(target=write, args=(t,)) for t in ("a", "b")]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=20)

        commands = [e["command"] for e in ShellHistoryStore(path).entries()]
        assert len(commands) == 40, f"writes were lost: {len(commands)} of 40"
        assert len({c for c in commands if c.startswith("a-")}) == 20
        assert len({c for c in commands if c.startswith("b-")}) == 20


class TestItSitsBesideTheOtherStores:
    def test_the_path_is_the_state_files_sibling(self, tmp_path: Path) -> None:
        """Derived from one upward walk, never a second one.

        Two walks can disagree about which project or which mode they are in,
        and a reader must not reconstruct a key the writer computed.
        """
        from functualize._primitives.state_format import resolve_state_path

        (tmp_path / ".functualize").mkdir()
        state = resolve_state_path(tmp_path)
        shell = resolve_shell_history_path(tmp_path)
        assert shell.parent == state.parent
        assert shell.name == "shell-history.json"

    def test_beside_state_agrees_with_for_project(self, tmp_path: Path) -> None:
        from functualize._primitives.state_format import resolve_state_path

        (tmp_path / ".functualize").mkdir()
        assert (
            ShellHistoryStore.beside_state(resolve_state_path(tmp_path)).path
            == ShellHistoryStore.for_project(tmp_path).path
        )


class TestStateJsonNoLongerHoldsHistory:
    """The point of the move: the file can now be named for what it holds."""

    def test_the_envelope_has_no_history_section(self) -> None:
        from functualize._primitives.state_format import _SECTIONS, empty_state

        assert "history" not in empty_state()
        assert "history" not in _SECTIONS
        assert set(_SECTIONS) == {"fingerprints", "session"}, (
            "what is left must be freshness verdicts only — that is what makes "
            "renaming the file to `fresh.json` a definition rather than an "
            "approximation"
        )
