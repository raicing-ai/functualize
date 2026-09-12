"""Sabotage sweep for `workflow-graph-semantics`/T4.

Run from the worktree root, on a **clean tree**. Every entry asserts its edit
applied before the result is read.

An entry is one or more (old, new) pairs — some properties can only be removed
at two sites at once, which T2 learned the hard way.
"""

import os
import pathlib
import signal
import subprocess

F = pathlib.Path("src/functualize/_engine/frontier.py")
W = pathlib.Path("src/functualize/_engine/workflow_walker.py")
D = pathlib.Path("src/functualize/_engine/dependency_runner.py")

TESTS = [
    "tests/workflow/test_typed_step_outcomes.py",
    "tests/workflow/test_failure_routing.py",
    "tests/workflow/test_abandoned_and_reclaim.py",
    "tests/engine/test_timeout_is_lease_expiry.py",
]

SABOTAGES = [
    # AC-9 — each consumer spells the outcome itself again.
    ("frontier compares the literal", F,
     '        return bool(record and record.get("status") in TERMINAL_SUCCESS)',
     '        return bool(record and record.get("status") == "success")'),

    ("the walker compares the literal", W,
     '        if record is not None and record.get("status") in TERMINAL_SUCCESS:',
     '        if record is not None and record.get("status") == "success":'),

    ("the dependency runner compares the literal", D,
     '                return bool(record.get("status") in TERMINAL_SUCCESS)',
     '                return bool(record.get("status") == "success")'),

    # AC-9 — the set stops meaning anything.
    ("every outcome is terminal-success", F,
     'TERMINAL_SUCCESS: frozenset[str] = frozenset({StepStatus.SUCCESS})',
     'TERMINAL_SUCCESS: frozenset[str] = frozenset(\n'
     '    {StepStatus.SUCCESS, StepStatus.FAILED, StepStatus.TIMED_OUT,\n'
     '     StepStatus.CANCELLED}\n)'),

    # AC-8 — the timeout is never noticed.
    ("nothing notes the step that went silent", F,
     '        silent = self._step_that_went_silent()',
     '        silent = None'),

    ("the scope is read after the claim, not before", F,
     '        silent = self._step_that_went_silent()\n'
     '        lease = self._store.claim_scope(',
     '        lease = self._store.claim_scope('),

    # The load-bearing half of "abandoned": a released lease is expired too.
    ("abandoned is the lease alone", F,
     '        if not scope or scope.get("status") != WalkState.RUNNING:\n'
     '            return None',
     '        if not scope:\n            return None'),

    # A step that reported must keep its reason.
    ("a reported step is overwritten", F,
     '        if self._store.get_step(self._scope_id, step_key(position, "")) is not None:\n'
     '            return None',
     '        if False:\n            return None'),

    ("taking over stamps the scope", F,
     '        self._store.record_step(\n'
     '            self._scope_id,\n'
     '            step_key(node, ""),\n'
     '            {\n'
     '                "status": StepStatus.TIMED_OUT,',
     '        self._store.set_scope_status(self._scope_id, "failed")\n'
     '        self._store.record_step(\n'
     '            self._scope_id,\n'
     '            step_key(node, ""),\n'
     '            {\n'
     '                "status": StepStatus.TIMED_OUT,'),

    # AC-8 — a cancellation collapses back into a failure.
    ("a cancellation is recorded as a failure", W,
     '        return self._fail(node, str(stopped), status=StepStatus.CANCELLED)',
     '        return self._fail(node, str(stopped), status=StepStatus.FAILED)'),

    ("the cancellation arm is gone, so OnFailure sees it", W,
     '        except ScopeCancelledError as stopped:\n'
     '            # **Before** the broad arm, which is what keeps a cancellation out\n'
     '            # of `OnFailure`\'s reach. A declared route recovers from a failure;\n'
     '            # a human stopping a workflow is not a failure to recover from, and\n'
     '            # routing past it would let a graph walk on through the stop.\n'
     '            return self._cancelled(name, stopped)\n',
     ''),

    ("the scope status table collapses the two", W,
     '    StepStatus.CANCELLED: "cancelled",',
     '    StepStatus.CANCELLED: "failed",'),
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
        # pytest is its grandchild and survives, and three sweeps left hung
        # runs eating the machine for half an hour each.
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
