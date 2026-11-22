"""Diff `report.proposed()` against the declaration table `tests/_support/parameter_matrix.py`.

Run from the repository root:
    python3 .spec/features/parameter-contract/matrix/table_diff.py

Prints every row whose table `expected_verdict` (or `proposed` text) differs from the corrected
`proposed()`, and the verdict counts. Exit 1 when any row differs. After task 1.1 corrects the
table, this prints no rows and exits 0.
"""

from __future__ import annotations

import importlib.util
import re
import sys
import types
from collections import Counter
from pathlib import Path

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))
# report.py imports the analyzer, which needs out.json; proposed() does not.
sys.modules.setdefault("analyze", types.SimpleNamespace(clean=None, facts=None, load=None, verdict=None))
import report  # noqa: E402

spec = importlib.util.spec_from_file_location("pm", "tests/_support/parameter_matrix.py")
table = importlib.util.module_from_spec(spec)
spec.loader.exec_module(table)

#: Why each corrected row's verdict is intent: the spec clause (and page cell) it follows.
WHY = {
    "C081": "B-5: INVOCATION_ONLY for fixed tuple[A, B, ...] (D5 = B')",
    "C082": "B-5: INVOCATION_ONLY for dict[str, T] (D5 = B')",
    "C083": "B-5: INVOCATION_ONLY for dict[str, T]; has a default, so not required",
    "C084": "B-5: INVOCATION_ONLY for set[T] (D5 = B')",
    "D105": "B-8: 'a CLI marker on a type nothing converts'; Widget is not a B-3 scalar (D104 is the same clause)",
    "E138": "B-2 availability: declared INJECTED; no provider for (Widget, 'w') -> B-8 provider item",
    "E139": "B-2 availability: declared INJECTED; no provider for (str, 's') -> B-8 provider item",
    "F150": "B-8: 'config fields of an unsupported type (dict, nested model; F-29)'; AC-4",
    "F151": "B-8: 'config fields of an unsupported type (dict, nested model; F-29)'; AC-4",
    "H165": "B-2 availability: no (str, 's2') provider in the matrix registry (only with PC_STR_PROVIDER=1) -> B-8 provider item",
}

counts: Counter[str] = Counter()
diffs = []
for row in table._RAW_ROWS:
    want = report.proposed(row["id"], row["declaration"])
    base = re.match(r"[A-Z_]+", want).group(0)
    counts[base] += 1
    if base != row["expected_verdict"] or want != row["proposed"]:
        diffs.append(f"{row['id']}  {row['declaration']!r:48}  table: {row['expected_verdict']} / {row['proposed']!r}  ->  {want}"
                     f"\n      because {WHY.get(row['id'], 'NO JUSTIFICATION RECORDED')}")
print("\n".join(diffs))
print(f"{len(diffs)} rows differ; verdicts: {dict(sorted(counts.items()))}; total {sum(counts.values())}")
sys.exit(1 if diffs else 0)
