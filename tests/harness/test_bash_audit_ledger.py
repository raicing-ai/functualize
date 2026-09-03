"""The shell-write auditor records an exemption instead of being silenced by it.

`CONSTITUTION.md` calls `.spec/exemptions.log` "the entire mitigation for the
fact that an agent can exempt itself". `bash_audit.py` used to fold two
different questions into one predicate — *was a task list present?* and *was an
exemption declared?* — and return early on either.

The consequence: a shell write to gated code while an exemption was active was
recorded **nowhere**. The `PreToolUse` gate never fires for a shell write (it
sees `Edit`/`Write`/`NotebookEdit` only), and this hook returned because the
exemption existed. **Declaring an exemption made a write less audited than not
declaring one**, which is exactly backwards.

Found during the 0.1.3 release prep, where the version bump to
`src/functualize/__init__.py` went in by script under an active exemption and
left no trace, while the 0.1.2 release — which used the `Edit` tool — has its
entry.

These are the first committed tests for `.claude/hooks/` (*Potential
Follow-ups* #19). They drive the script the way the harness does — a JSON
payload on stdin — and never import its internals, because stdin/stdout **is**
the hook's public entry point.
"""

from __future__ import annotations

import json
import subprocess
import sys
import uuid
from pathlib import Path

import pytest

HOOK = Path(__file__).parent.parent.parent / ".claude" / "hooks" / "bash_audit.py"

_TASKS_MD = """## Task Dependency Graph

```json
{"waves": [{"id": 0, "tasks": ["1.1"]}]}
```
"""

_EXEMPT_REASON = "a perfectly valid twenty-plus character reason for this write"


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """A git repo with one committed gated file, then dirtied."""
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    gated = tmp_path / "src" / "functualize"
    gated.mkdir(parents=True)
    (gated / "mod.py").write_text("x = 1\n")
    (tmp_path / ".spec").mkdir()
    subprocess.run(["git", "add", "-A"], cwd=tmp_path, check=True)
    subprocess.run(
        ["git", "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "init"],
        cwd=tmp_path,
        check=True,
    )
    (gated / "mod.py").write_text("x = 2\n")  # the shell write under audit
    return tmp_path


def _run(repo: Path, session: str) -> list[list[str]]:
    """Drive the hook and return the ledger's rows, split on tabs.

    The session id is made unique per call. The hook caches the gated paths it
    has already seen in a file keyed by session id under the system tempdir,
    and `dirty_gated` yields **repo-relative** paths — so a fixed id would let
    one test's run suppress the next one's across `tmp_path` repos, and across
    whole pytest invocations. That is a property of the hook's dedupe, not a
    defect: it is what stops one shell write being logged on every subsequent
    Bash call in a session.
    """
    subprocess.run(
        [sys.executable, str(HOOK)],
        input=json.dumps(
            {"cwd": str(repo), "session_id": f"{session}-{uuid.uuid4().hex}"}
        ),
        text=True,
        capture_output=True,
        check=False,
    )
    ledger = repo / ".spec" / "exemptions.log"
    if not ledger.is_file():
        return []
    return [
        line.split("\t")
        for line in ledger.read_text().splitlines()
        if line and not line.startswith("#")
    ]


def test_a_shell_write_under_an_exemption_is_recorded(repo: Path) -> None:
    """The regression. This produced zero rows before the fix."""
    (repo / ".spec" / "EXEMPT").write_text(f"Spec-exempt: {_EXEMPT_REASON}\n")

    rows = _run(repo, "s-exempt")

    assert len(rows) == 1, f"the exemption silenced the auditor: {rows}"
    assert "src/functualize/mod.py" in rows[0][2]
    assert _EXEMPT_REASON in rows[0][3], (
        "the recorded reason must be the one the exemption gave, not a generic "
        f"placeholder: {rows[0][3]}"
    )


def test_an_uncovered_shell_write_is_still_recorded(repo: Path) -> None:
    """The control that already worked, pinned so the fix did not trade one for
    the other."""
    rows = _run(repo, "s-bare")

    assert len(rows) == 1
    assert "no tasks.md and no .spec/EXEMPT" in rows[0][3]


def test_a_task_list_records_nothing(repo: Path) -> None:
    """The one condition that genuinely means "no record is owed".

    The workflow was followed; there is nothing to disclose. If this ever starts
    logging, every ordinary feature commit would write ledger noise and the
    ledger would stop being read.
    """
    feature = repo / ".spec" / "features" / "f"
    feature.mkdir(parents=True)
    (feature / "tasks.md").write_text(_TASKS_MD)

    assert _run(repo, "s-tasks") == []


def test_the_two_reasons_are_distinguishable(repo: Path) -> None:
    """A reader must be able to tell a declared bypass from an undeclared one.

    They are different events: one is a maintainer taking the escape hatch on
    the record, the other is the workflow being skipped silently. A ledger that
    spelled them the same way would hide the distinction it exists to surface.
    """
    (repo / ".spec" / "EXEMPT").write_text(f"Spec-exempt: {_EXEMPT_REASON}\n")
    declared = _run(repo, "s-a")[0][3]

    (repo / ".spec" / "EXEMPT").unlink()
    (repo / ".spec" / "exemptions.log").unlink()
    undeclared = _run(repo, "s-b")[0][3]

    assert declared != undeclared
