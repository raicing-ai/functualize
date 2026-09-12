"""Sabotage sweep for `workflow-graph-semantics`/T2.

Run from the worktree root, on a **clean tree** — each sabotage is restored in
a `finally`, but `git checkout --` would revert uncommitted work in the same
file, and this branch has paid for that twice.

Every entry asserts its edit **applied** before the result is read. A sabotage
that silently fails to apply reads as "the tests do not catch this", which
happened once on this branch and nearly produced a false conclusion.
"""

import pathlib
import subprocess

W = pathlib.Path("src/functualize/_engine/workflow_walker.py")
L = pathlib.Path("src/functualize/_engine/loop_state.py")
V = pathlib.Path("src/functualize/workflow/_validation.py")

SABOTAGES = [
    ("visited keyed by node alone", W,
     "            if (name, iteration) in visited:",
     "            if any(n == name for n, _ in visited):"),
    # Prunes on the iteration and ignores the node, which is the other half of
    # the keying. Written as a membership test over the iterations rather than
    # by corrupting what is added, because that version never matches anything,
    # nothing is ever pruned, and the deferral loop spins — a hang is a break
    # but it is a useless signal, and it cost a 600s timeout to learn.
    ("visited keyed by iteration alone", W,
     "            if (name, iteration) in visited:",
     "            if any(i == iteration for _, i in visited):"),
    # The bug this design removed: the iteration as a **cursor** the loop
    # advances, so a node dequeued afterwards reads the advanced value rather
    # than the one it was queued with. A diamond join is queued once per
    # branch, so its two arrivals get different iterations and the second is
    # not pruned — the join runs twice in one pass.
    #
    # **Two sites, because one is not enough.** Two single-site attempts were
    # inert: mutating `self._iteration` at the back-edge is overwritten by the
    # very next dequeue, and taking `max(cursor, queued)` at the dequeue is
    # saved by FIFO ordering. The property is "the iteration travels with the
    # work", and removing it means the dequeue must ignore what was queued
    # *and* the back-edge must advance the cursor.
    ("the iteration is a cursor, not queued work", W, [
        ("            name, iteration = pending.popleft()\n"
         "            self._iteration = iteration",
         "            name, _queued = pending.popleft()\n"
         "            iteration = self._iteration"),
        ("                pending.append((back, iteration + 1))",
         "                pending.append((back, iteration + 1))\n"
         "                self._iteration = iteration + 1"),
    ]),
    ("the record key ignores the iteration", L,
     '    return str(step_key(name, "" if iteration == 0 else f"loop{iteration}"))',
     '    return str(step_key(name, ""))'),
    ("resume always restarts at iteration 0", W,
     "        start = self._resume_iteration()",
     "        start = 0"),
    ("the bound is not enforced", W,
     "            if iteration + 1 >= loop.max_iterations:",
     "            if False:"),
    ("Loop edges count as cycle edges again", V,
     "    if isinstance(edge, Loop):\n"
     "        # **Not a cycle edge.**",
     "    if False:\n"
     "        # **Not a cycle edge.**"),
]

for label, path, *edits in SABOTAGES:
    # An entry is one or more (old, new) pairs. Some properties can only be
    # removed at two sites at once — the iteration travelling with the queued
    # work is one, and a single-site version of it was inert because the
    # design had already made that unreachable.
    pairs = edits[0] if isinstance(edits[0], list) else [tuple(edits)]
    original = path.read_text()
    body = original
    for old, new in pairs:
        assert body.count(old) == 1, (
            f"{label}: sabotage did not apply ({body.count(old)} matches for "
            f"{old[:60]!r})"
        )
        body = body.replace(old, new, 1)
    path.write_text(body)
    try:
        try:
            r = subprocess.run(
                ["uv", "run", "pytest", "tests/workflow/test_loops.py",
                 "tests/test_workflow_walker.py", "-q", "-p", "no:randomly",
                 "-x"],
                capture_output=True, text=True, timeout=180)
        except subprocess.TimeoutExpired:
            # A hang is a break — the walk no longer terminates — but it is a
            # weak signal, so it is reported as one rather than crashing the
            # sweep and losing every sabotage after it.
            print(f"{label:44s} -> HUNG (>180s): the walk stopped terminating",
                  flush=True)
            continue
        tail = [line for line in r.stdout.strip().splitlines()
                if "passed" in line or "failed" in line or "error" in line]
        print(f"{label:44s} -> {tail[-1] if tail else r.stdout.strip()[-140:]}",
              flush=True)
    finally:
        path.write_text(original)
