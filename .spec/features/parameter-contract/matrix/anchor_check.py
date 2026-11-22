"""Resolve every task's **Input:** artifacts against the Execute context anchor.

Run from the repository root:  python3 .spec/features/parameter-contract/matrix/anchor_check.py

For each task in tasks.md, the **Input:** block (up to the task's **[F]:** line) is scanned for
backticked names of feature artifacts — `spec.md`, `plan.md`, `schema.md`, `contracts.md`,
`research.md`, `tasks.md`, and any file under the feature's `matrix/` (kit scripts and
`evidence/*.txt`, which are named bare, e.g. `gates-authoring.txt`). Each name is resolved to a
real path under the feature directory (a name that resolves nowhere is reported, not guessed).

Source-code citations (`_types/enums.py:31-50`, …) are not spec documents: the anchor "restricts spec
documents, not the codebase" (agentic-execute.md), so they are not counted. Repository documentation
outside the feature (`data-flow.md`, ADRs) is listed separately so the reader can see it.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

FEATURE = Path(".spec/features/parameter-contract")
SPEC_DOCS = {"spec.md", "plan.md", "schema.md", "contracts.md", "research.md", "tasks.md"}

OLD_ANCHOR = {"tasks.md"}  # of this feature's files, the six-file anchor permitted only tasks.md
NEW_ANCHOR_DOCS = {"tasks.md", "spec.md", "plan.md", "schema.md", "contracts.md"}  # + matrix/**


def resolve(name: str) -> Path | None:
    base = name.split(":")[0].split(" ")[0]
    if base in SPEC_DOCS:
        return FEATURE / base
    if base.startswith("matrix/"):
        p = FEATURE / base
        return p if p.exists() else None
    for cand in (FEATURE / "matrix" / base, FEATURE / "matrix" / "evidence" / base):
        if cand.exists():
            return cand
    return None


def in_anchor(p: Path, *, new: bool) -> bool:
    rel = p.relative_to(FEATURE)
    if rel.parts[0] == "matrix":
        return new
    return rel.name in (NEW_ANCHOR_DOCS if new else OLD_ANCHOR)


def main() -> int:
    text = (FEATURE / "tasks.md").read_text()
    blocks = re.split(r"^### \[[ x]\] ", text, flags=re.M)[1:]
    old_out = new_out = 0
    unresolved: list[str] = []
    docs_outside: set[str] = set()
    for b in blocks:
        tid = b.split()[0]
        if "**Input:**" not in b:
            print(f"{tid:5} no Input line")
            continue
        inp = b.split("**Input:**", 1)[1].split("**[F]:**", 1)[0]
        names = re.findall(r"`([^`]+)`", inp)
        arts: list[Path] = []
        for n in names:
            stem = n.split(":")[0].split(" ")[0]
            if stem.endswith((".md", ".txt")) or stem.startswith("matrix/") or stem in ("rows.py", "report.py"):
                p = resolve(n)
                if p is not None:
                    arts.append(p)
                elif stem.endswith(".md"):
                    docs_outside.add(stem)
                else:
                    unresolved.append(f"{tid}: {n}")
        arts = sorted(set(arts))
        old_bad = [str(a.relative_to(FEATURE)) for a in arts if not in_anchor(a, new=False)]
        new_bad = [str(a.relative_to(FEATURE)) for a in arts if not in_anchor(a, new=True)]
        old_out += bool(old_bad)
        new_out += bool(new_bad)
        print(f"{tid:5} artifacts={[str(a.relative_to(FEATURE)) for a in arts]}  "
              f"outside-old={old_bad or '-'}  outside-new={new_bad or '-'}")
    print()
    print(f"tasks: {len(blocks)}")
    print(f"tasks with an input outside the OLD six-file anchor: {old_out}")
    print(f"tasks with an input outside the NEW anchor:          {new_out}")
    print(f"unresolved feature-artifact names: {unresolved or 'none'}")
    print(f"repository docs named in inputs (codebase, not spec documents): {sorted(docs_outside) or 'none'}")
    return 1 if new_out else 0


if __name__ == "__main__":
    sys.exit(main())
