"""Sabotage sweep for `workflow-graph-semantics`/T3.

Run from the worktree root, on a **clean tree**. Every entry asserts its edit
applied before the result is read.

An entry is one or more (old, new) pairs — some properties can only be removed
at two sites at once, which T2 learned the hard way.
"""

import pathlib
import subprocess

W = pathlib.Path("src/functualize/_engine/workflow_walker.py")
V = pathlib.Path("src/functualize/workflow/_validation.py")

SABOTAGES = [
    # AC-6: the undeclared case must be untouched. Routing everything would
    # make every existing workflow continue past a failure it never declared.
    ("every failure routes, declared or not", W,
     "            if edge.when is not None and not edge.when(exc):\n"
     "                continue",
     "            if False:\n                continue"),

    # AC-7: the route must be read on replay, not decided again.
    ("the route is re-evaluated on replay", W,
     "        recorded = self._store.get_branch(self._scope_id, _failure_branch(name))\n"
     "        if recorded is not None:\n"
     "            return str(recorded)",
     "        recorded = None\n        if recorded is not None:\n"
     "            return str(recorded)"),

    ("the route is never recorded", W,
     "            self._store.record_branch(self._scope_id, _failure_branch(name), target)",
     "            pass"),

    # END and "no route" must stay distinguishable.
    ("routed-to-END collapses into no-route", W,
     "            target = _ROUTED_TO_END if _is_end(edge.target) else str(edge.target)",
     "            target = str(edge.target)"),

    # A routed failure must not also advance the frontier.
    ("a routed failure also takes the success path", W,
     "                self._record_routed_failure(name)\n"
     "                if run.failure_route != _ROUTED_TO_END:\n"
     "                    pending.append((run.failure_route, iteration))\n"
     "                continue",
     "                self._record_routed_failure(name)\n"
     "                if run.failure_route != _ROUTED_TO_END:\n"
     "                    pending.append((run.failure_route, iteration))"),

    # A recovered workflow must not be marked failed.
    ("a routed failure still fails the scope", W,
     "    def _record_routed_failure(self, name: str) -> None:",
     "    def _record_routed_failure(self, name: str) -> None:\n"
     "        self._store.set_scope_status(self._scope_id, 'failed')"),

    # The validator must see OnFailure — T2's blind spot, checked here.
    ("the validator ignores an OnFailure target", V,
     "        elif isinstance(edge, OnFailure):\n"
     "            if not _is_end(edge.target) and edge.target not in node_names:",
     "        elif isinstance(edge, OnFailure):\n            if False:"),

    ("a failure route counts as a cycle edge", V,
     "    if isinstance(edge, OnFailure):\n"
     "        # **A failure route is not a cycle edge**",
     "    if False:\n        # **A failure route is not a cycle edge**"),
]

for label, path, *edits in SABOTAGES:
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
                ["uv", "run", "pytest", "tests/workflow/test_failure_routing.py",
                 "tests/workflow/test_loops.py", "-q", "-p", "no:randomly", "-x"],
                capture_output=True, text=True, timeout=180)
        except subprocess.TimeoutExpired:
            print(f"{label:44s} -> HUNG (>180s)", flush=True)
            continue
        tail = [line for line in r.stdout.strip().splitlines()
                if "passed" in line or "failed" in line or "error" in line]
        print(f"{label:44s} -> {tail[-1] if tail else r.stdout.strip()[-140:]}",
              flush=True)
    finally:
        path.write_text(original)
