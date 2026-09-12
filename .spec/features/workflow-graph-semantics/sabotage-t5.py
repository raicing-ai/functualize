"""Sabotage sweep for `workflow-graph-semantics`/T5.

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
O = pathlib.Path("src/functualize/_engine/workflow_orchestrator.py")
L = pathlib.Path("src/functualize/_events/walk_log.py")
B = pathlib.Path("src/functualize/_app/boot.py")
S = pathlib.Path("src/functualize/_primitives/scope_store.py")
V = pathlib.Path("src/functualize/app/_workflow_view.py")

TESTS = [
    "tests/workflow/test_watch_stream.py",
    "tests/workflow/test_workflow_surface_parity.py",
]

SABOTAGES = [
    # R-e itself: the renderer falls back to describing the record.
    ("watch describes the record when quiet", V,
     "        scope = store.get_scope(scope_id)\n"
     "        if not walk_is_live(scope):\n"
     "            return",
     "        scope = store.get_scope(scope_id)\n"
     "        if not walk_is_live(scope):\n"
     "            if scope:\n"
     "                yield {'seq': seen + 1, 'event': 'workflow.walk.end',\n"
     "                       'payload': {'node': scope.get('position') or ''}}\n"
     "            return"),

    # AC-11: the walker is silent.
    ("the walker emits nothing", W,
     "        if self._emit is None:\n            return",
     "        if True:\n            return"),

    ("the engine never wires the bus", O,
     "            emit=self._engine._event_bus.emit,",
     "            emit=None,"),

    ("the runner drops it on the floor", W,
     "        self._emit = emit",
     "        self._emit = None"),

    ("nothing subscribes at boot", B,
     "    _install_walk_log(app._event_bus, _scope_store_for_project)",
     "    pass"),

    # The subscriber files by the wrong key.
    ("events are filed by workflow name", L,
     '        scope_id = event.payload.get("scope_id")',
     '        scope_id = event.resource'),

    ("an event with no scope is filed anyway", L,
     '        if not isinstance(scope_id, str) or not scope_id:\n            return',
     '        if False:\n            return'),

    # The sequence is what makes following resumable.
    ("the sequence restarts", S,
     '            seq = (\n                max(\n                    (e.get("seq", 0) for e in entries if isinstance(e, dict)), default=0\n                )\n                + 1\n            )\n            seq_box[0] = seq',
     "            seq = 1\n            seq_box[0] = seq"),

    ("`after` is ignored, so a watch cannot resume", S,
     "                if isinstance(e, dict) and int(e.get(\"seq\", 0)) > after",
     "                if isinstance(e, dict)"),

    # What only an event can say.
    ("a replayed step is reported as executed", W,
     '                outcome="replayed" if run.replayed else "executed",',
     '                outcome="executed",'),

    ("the loop pass is not carried", W,
     '            self._say("step.start", node=name, iteration=iteration)',
     '            self._say("step.start", node=name)'),

    # AC-12.
    ("an unheld scope counts as live", V,
     "    return lease is not None and not is_expired(lease, datetime.now(UTC))",
     "    return True"),
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
