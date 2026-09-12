import pathlib, subprocess

W = pathlib.Path("src/functualize/_engine/workflow_walker.py")
L = pathlib.Path("src/functualize/_engine/loop_state.py")
V = pathlib.Path("src/functualize/workflow/_validation.py")

SABOTAGES = [
    ("visited keyed by node alone", W,
     "            if (name, iteration) in visited:",
     "            if any(n == name for n, _ in visited):"),
    ("visited keyed by iteration alone", W,
     "            visited.add((name, iteration))",
     "            visited.add((iteration, iteration))"),
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
        r = subprocess.run(
            ["uv", "run", "pytest", "tests/workflow/test_loops.py",
             "tests/test_workflow_walker.py", "-q", "-p", "no:randomly"],
            capture_output=True, text=True, timeout=600)
        tail = [l for l in r.stdout.strip().splitlines()
                if "passed" in l or "failed" in l or "error" in l]
        print(f"{label:44s} -> {tail[-1] if tail else r.stdout.strip()[-140:]}")
    finally:
        path.write_text(original)
