#!/usr/bin/env python3
"""PostToolUse on Bash: record shell writes to shipped code that skipped the gate.

Contract: .spec/features/spec-workflow-enforcement/contracts.md section C11.
Rationale: research.md section F0.11.

The write gate (spec_gate.py) sees Edit, Write and NotebookEdit. A shell write --
`echo >`, `sed -i`, `tee`, a heredoc, a script -- raises none of those, so it
passes unexamined. Blocking that reliably would mean parsing arbitrary shell,
which is fragile and easy to fool. This observes instead: the bypass stays
possible and stops being invisible.

The command string is deliberately never inspected. Detection is by observed
effect on the working tree.

Never blocks. No decision authority. Exits 0 unconditionally.
"""

import json
import os
import re
import subprocess
import sys
import tempfile
import time

GATED_DIR = "src/functualize"
EXEMPT_FILE = ".spec/EXEMPT"
LEDGER_FILE = ".spec/exemptions.log"
EXEMPT_MAX_AGE_S = 60 * 60
EXEMPT_RE = re.compile(r"^Spec-exempt:\s*(.{20,})$")
REASON = "shell-write: no tasks.md and no .spec/EXEMPT"


def is_gated_rel(rel):
    """rel is a repo-relative POSIX path from `git status --porcelain`."""
    parts = rel.split("/")
    if rel.startswith(GATED_DIR + "/"):
        return True
    return len(parts) >= 4 and parts[0] == "plugins" and parts[2] == "src"


def dirty_gated(cwd):
    try:
        r = subprocess.run(
            ["git", "status", "--porcelain", "--untracked-files=all", "--",
             GATED_DIR, "plugins"],
            cwd=cwd, capture_output=True, text=True, timeout=10,
        )
        if r.returncode != 0:
            return set()
    except (OSError, subprocess.SubprocessError):
        return set()
    out = set()
    for line in r.stdout.splitlines():
        if len(line) < 4:
            continue
        path = line[3:].strip()
        if " -> " in path:  # rename: take the destination
            path = path.split(" -> ", 1)[1]
        path = path.strip('"')
        if is_gated_rel(path):
            out.add(path)
    return out


def has_wave_graph(text):
    _, sep, tail = text.rpartition("## Task Dependency Graph")
    if not sep:
        return False
    m = re.search(r"```json\s*\n(.*?)\n\s*```", tail, re.S)
    if not m:
        return False
    try:
        waves = json.loads(m.group(1)).get("waves")
    except Exception:
        return False
    return isinstance(waves, list) and len(waves) > 0


def workflow_followed(cwd):
    """True when a task list or a fresh exemption already covers this work."""
    root = os.path.join(cwd, ".spec", "features")
    if os.path.isdir(root):
        with os.scandir(root) as entries:
            for e in entries:
                if not e.is_dir():
                    continue
                tasks = os.path.join(e.path, "tasks.md")
                try:
                    if os.path.isfile(tasks):
                        with open(tasks, encoding="utf-8") as fh:
                            if has_wave_graph(fh.read()):
                                return True
                except OSError:
                    continue
    path = os.path.join(cwd, EXEMPT_FILE)
    try:
        if time.time() - os.path.getmtime(path) <= EXEMPT_MAX_AGE_S:
            with open(path, encoding="utf-8") as fh:
                for line in fh:
                    line = line.strip()
                    if line:
                        return bool(EXEMPT_RE.match(line))
    except (OSError, ValueError):
        pass
    return False


def cache_path(session_id):
    safe = re.sub(r"[^A-Za-z0-9_.-]", "_", str(session_id))[:64] or "nosession"
    return os.path.join(tempfile.gettempdir(), f"spec-gate-{safe}.json")


def load_seen(path):
    try:
        with open(path, encoding="utf-8") as fh:
            return set(json.load(fh).get("seen", []))
    except (OSError, ValueError):
        return set()


def save_seen(path, seen):
    try:
        with open(path, "w", encoding="utf-8") as fh:
            json.dump({"seen": sorted(seen)}, fh)
    except OSError:
        pass


def log(cwd, paths):
    ledger = os.path.join(cwd, LEDGER_FILE)
    stamp = time.strftime("%Y-%m-%dT%H:%M:%S%z")
    hour = stamp[:13]
    already = set()
    try:
        if os.path.isfile(ledger):
            with open(ledger, encoding="utf-8") as fh:
                for line in fh:
                    if line.startswith("#"):
                        continue
                    f = line.rstrip("\n").split("\t")
                    if len(f) == 4 and f[0][:13] == hour:
                        already.add(f[2])
        rows = [p for p in sorted(paths) if p not in already]
        if not rows:
            return
        with open(ledger, "a", encoding="utf-8") as fh:
            for p in rows:
                fh.write(f"{stamp}\t{os.path.basename(cwd)}\t{p}\t{REASON}\n")
    except OSError:
        pass


def main():
    payload = json.load(sys.stdin)
    cwd = payload.get("cwd")
    if not isinstance(cwd, str) or not os.path.isdir(cwd):
        return
    cache = cache_path(payload.get("session_id"))
    current = dirty_gated(cwd)
    seen = load_seen(cache)
    new = current - seen
    save_seen(cache, current)
    if not new:
        return
    if workflow_followed(cwd):
        return
    log(cwd, new)


if __name__ == "__main__":
    try:
        main()
    except Exception:
        pass
    sys.exit(0)
