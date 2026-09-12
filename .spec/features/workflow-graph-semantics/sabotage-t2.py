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
    ("the iteration is a cursor, not queued work", W,
     "            back = self._loop_back(name, run.value, iteration)\n"
     "            if back is not None:\n"
     "                pending.append((back, iteration + 1))",
     "            back = self._loop_back(name, run.value, iteration)\n"
     "            if back is not None:\n"
     "                pending.append((back, self._iteration + 1))\n"
     "                self._iteration += 1"),
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

for label, path, old, new in SABOTAGES:
    original = path.read_text()
    assert original.count(old) == 1, f"{label}: sabotage did not apply ({original.count(old)})"
    path.write_text(original.replace(old, new, 1))
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
