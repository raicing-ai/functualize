"""Sabotage sweep for `workflow-graph-semantics`/T6.

Run from the worktree root, on a **clean tree**. Every entry asserts its edit
applied before the result is read.

An entry is one or more (old, new) pairs — some properties can only be removed
at two sites at once, which T2 learned the hard way.
"""

import os
import pathlib
import signal
import subprocess

W = pathlib.Path("src/functualize/_engine/workflow_walker.py")
N = pathlib.Path("src/functualize/_engine/notify.py")
T = pathlib.Path("src/functualize/_types/workflow.py")
R = pathlib.Path("src/functualize/_engine/workflow_runner.py")
O = pathlib.Path("src/functualize/_engine/workflow_orchestrator.py")

TESTS = [
    "tests/workflow/test_notify.py",
    "tests/integration/test_notify_exactly_once.py",
    "--run-slow",
]

SABOTAGES = [
    # AC-13, the outbox rule: the mark must commit *before* the delivery.
    ("the record is written after the delivery", W,
     '            self._store.record_branch(self._scope_id, key, "sent")\n'
     "            self._notifiers.deliver(",
     "            self._notifiers.deliver("),

    ("nothing checks whether it already fired", W,
     "            if self._store.get_branch(self._scope_id, key) is not None:\n"
     "                continue",
     "            if False:\n                continue"),

    ("the key is the state alone, so two targets collide", T,
     '        return f"{self.on}\\x00{self.provider or \'\'}\\x00{self.to}"',
     '        return self.on'),

    # AC-13: a notification is about the scope's status, not the walk outcome.
    ("the status comes from the report", W,
     '        status = str(scope.get("status") or "")',
     '        status = "failed" if report.failed_node else report.outcome.value'),

    ("every declaration fires, whatever the state", W,
     "        for declared in self._declaration.notifications_for(status):",
     "        for declared in self._declaration.notify:"),

    # The refusal: nothing may be guessed, and the check must be run.
    ("the runner does not check the declaration", R,
     "        if self._notifiers is not None:\n"
     "            self._notifiers.check(declaration)",
     "        pass"),

    ("a notifier is picked when several are registered", N,
     "            if len(self._notifiers) == 1:\n"
     "                return next(iter(self._notifiers.values()))",
     "            if self._notifiers:\n"
     "                return next(iter(self._notifiers.values()))"),

    ("anything can be registered as a notifier", N,
     "        if not isinstance(notifier, Notifier):",
     "        if False:"),

    ("a second registration replaces the first", N,
     "        if name in self._notifiers:",
     "        if False:"),

    # A notification is an account of what happened, never a cause of it.
    ("a failed delivery fails the walk", N,
     "        except Exception:  # noqa: BLE001 - an account never changes the outcome",
     "        except Exception as exc:\n            raise exc  # noqa: TRY201\n"
     "        except BaseException:"),

    # N8: `to` is opaque.
    ("`to` is split into several targets", W,
     "                    to=declared.to,",
     '                    to=declared.to.split(",")[0],'),

    # The wiring, which every unit test here would pass without.
    ("the engine never hands over the registry", O,
     "            notifiers=self._engine._notifier_registry,",
     "            notifiers=None,"),
]

for label, path, *edits in SABOTAGES:
    pairs = edits[0] if isinstance(edits[0], list) else [tuple(edits)]
    original = path.read_text()
    body = original
    for old, new in pairs:
        assert body.count(old) >= 1, (
            f"{label}: sabotage did not apply (0 matches for {old[:60]!r})"
        )
        body = body.replace(old, new)
    path.write_text(body)
    try:
        # Its own process group, so a timeout can kill the **whole** tree.
        # `subprocess.run`'s timeout kills the direct child, which is `uv`;
        # pytest is its grandchild and survives.
        proc = subprocess.Popen(
            ["uv", "run", "pytest", *TESTS, "-q", "-p", "no:randomly", "-x"],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
            start_new_session=True,
        )
        try:
            out, _ = proc.communicate(timeout=180)
        except subprocess.TimeoutExpired:
            os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
            proc.communicate()
            print(f"{label:44s} -> HUNG (>180s, killed)", flush=True)
            continue
        tail = [line for line in out.strip().splitlines()
                if "passed" in line or "failed" in line or "error" in line]
        print(f"{label:44s} -> {tail[-1] if tail else out.strip()[-140:]}",
              flush=True)
    finally:
        path.write_text(original)
