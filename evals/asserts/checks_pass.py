"""The load-bearing grader: did the code the agent wrote actually run?

Because functualize is ours, "did this work" is an exit code, not an opinion.
No LLM judge is involved, which makes this both the cheapest and the most
trustworthy assertion in the suite.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _common import as_record, result  # noqa: E402


def get_assert(output, context) -> dict:
    record = as_record(output)

    if record.get("error"):
        return result(False, f"Agent run failed: {record['error']}")

    checks = record.get("checks") or []
    if not checks:
        return result(False, "No verification commands configured for this case")

    failed = [c for c in checks if c.get("exit_code") != 0]
    if not failed:
        return result(True, f"All {len(checks)} verification commands exited 0")

    first = failed[0]
    detail = (first.get("stderr") or first.get("stdout") or "").strip()[-600:]
    return result(
        False,
        f"{len(failed)}/{len(checks)} checks failed. "
        f"`{first['command']}` exited {first['exit_code']}: {detail}",
        score=1.0 - len(failed) / len(checks),
    )
