"""The three stores under real concurrency — threads and processes.

None of them had a concurrency test, which is how the `ScopeStore.batch()` lost
write survived (an external review found it by writing one). The stores are
shared per project: two `func` invocations in one directory use the same three
files, and `invoke_parallel` gives 32 worker threads the same objects.

What is asserted here is the property the locking exists for: **two writers
touching different records merge, rather than one clobbering the other.** Not
"writes are atomic" — `update_*` re-reads inside the lock precisely so they are
not, they merge.
"""

from __future__ import annotations

import json
import subprocess
import sys
import textwrap
import threading
from pathlib import Path
from typing import Any

import pytest

from functualize._primitives.run_store import RunStore
from functualize._primitives.scope_store import ScopeStore
from functualize._primitives.state_store import StateStore

WRITERS = 8


class TestThreadsMerge:
    """N threads writing distinct keys, and every key survives."""

    def test_scope_store_keeps_every_thread_s_scope(self, tmp_path: Path) -> None:
        store = ScopeStore(tmp_path / "scopes.json")
        errors: list[BaseException] = []

        def writer(n: int) -> None:
            try:
                store.ensure_scope(f"scope-{n}", workflow=f"w{n}")
                store.set_state(f"scope-{n}", "value", n)
            except BaseException as exc:  # noqa: BLE001 - reported, not swallowed
                errors.append(exc)

        threads = [threading.Thread(target=writer, args=(n,)) for n in range(WRITERS)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(10)

        assert not errors, errors
        fresh = ScopeStore(tmp_path / "scopes.json")
        for n in range(WRITERS):
            assert fresh.get_state(f"scope-{n}", "value") == n, (
                f"scope-{n} lost its write; {WRITERS} threads, distinct keys"
            )

    def test_run_store_keeps_every_thread_s_run(self, tmp_path: Path) -> None:
        store = RunStore(tmp_path / "runs.json")
        ids: list[str] = []
        lock = threading.Lock()

        def writer(n: int) -> None:
            run_id = store.open_run({"job": f"j{n}", "surface": "app.execute"})
            with lock:
                ids.append(run_id)

        threads = [threading.Thread(target=writer, args=(n,)) for n in range(WRITERS)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(10)

        assert len(set(ids)) == WRITERS, "two runs were given the same id"
        fresh = RunStore(tmp_path / "runs.json")
        recorded = set(fresh.run_ids())
        assert set(ids) <= recorded, (
            f"{len(set(ids) - recorded)} run(s) opened successfully and are not "
            "in the file"
        )

    def test_state_store_keeps_every_thread_s_fingerprint(self, tmp_path: Path) -> None:
        store = StateStore(tmp_path / "state.json")

        def writer(n: int) -> None:
            store.put_fingerprint(f"job-{n}", {"hash": str(n)})

        threads = [threading.Thread(target=writer, args=(n,)) for n in range(WRITERS)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(10)

        fresh = StateStore(tmp_path / "state.json")
        keys = set(fresh.fingerprint_keys())
        missing = {f"job-{n}" for n in range(WRITERS)} - keys
        assert not missing, f"{missing} lost their fingerprint"


class TestProcessesMerge:
    """The boundary `flock` actually exists for.

    Threads share a file description in some implementations; separate
    processes never do. This is the case two `func` invocations in one project
    directory hit.
    """

    @pytest.mark.slow
    def test_separate_processes_do_not_clobber_each_other(self, tmp_path: Path) -> None:
        program = tmp_path / "writer.py"
        program.write_text(
            textwrap.dedent("""
                import sys
                from functualize._primitives.scope_store import ScopeStore

                n = sys.argv[1]
                store = ScopeStore(sys.argv[2])
                store.ensure_scope("scope-" + n, workflow="w" + n)
                store.set_state("scope-" + n, "value", int(n))
            """)
        )
        target = str(tmp_path / "scopes.json")
        procs = [
            subprocess.Popen(  # noqa: S603 - fixed argv, no shell
                [sys.executable, str(program), str(n), target],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            for n in range(WRITERS)
        ]
        for p in procs:
            out, err = p.communicate(timeout=120)
            assert p.returncode == 0, err.decode()[-500:]

        data = json.loads(Path(target).read_text())
        found = sorted(data["scopes"])
        assert found == sorted(f"scope-{n}" for n in range(WRITERS)), (
            f"{WRITERS} processes wrote distinct scopes; the file has {found}"
        )


class TestTheTimeoutIsAudible:
    """Giving up on the lock says so.

    It proceeds without the lock after the timeout — correct, a stuck lock must
    not wedge a build — and that is the one path where two writers can lose
    each other's updates. It used to happen in silence, so the only evidence
    was the missing data.
    """

    def test_a_timeout_warns(self, tmp_path: Path, caplog: Any) -> None:
        import logging

        from functualize._primitives.state_format import state_lock

        target = tmp_path / "state.json"
        target.write_text("{}")

        holder_ready = threading.Event()
        release = threading.Event()

        def hold() -> None:
            with state_lock(target, timeout=30):
                holder_ready.set()
                release.wait(20)

        holder = threading.Thread(target=hold)
        holder.start()
        assert holder_ready.wait(10)

        try:
            with (
                caplog.at_level(logging.WARNING),
                state_lock(target, timeout=0.05),
            ):
                pass
        finally:
            release.set()
            holder.join(20)

        assert any("without it" in r.message for r in caplog.records), (
            "the lock was given up on silently; the records were "
            f"{[r.message for r in caplog.records]}"
        )
