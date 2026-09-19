"""Durable state: a run counter that survives process restarts.

Run twice and watch the count keep climbing::

    func persistent_counter.py bump
    func persistent_counter.py bump

**Rewritten by `plugin-taxonomy`/T8.** It used to import `SQLiteStateBackend`,
a `StateBackend`/`ExecutionStore` class ADR-022 retired — and which had been
**defined nowhere in the repository** for some time. Nothing noticed, because
`testpaths = ["tests"]` means the root test run never collects this directory
and CI runs one plugin's examples out of twelve. So the example a reader is
pointed at could not have run.

What the package actually offers is `SQLiteSubstrate`: `read` and `write` over
whole documents, with a revision for compare-and-swap. The counter is written
against that, which is also a better demonstration — the point of a substrate is
that a *document* survives the process, and the compare-and-swap is what makes
two runs at once safe.
"""

from pathlib import Path

from functualize_substrate_sqlite import SQLiteSubstrate

from functualize.job import RunContext

DB_PATH = Path(__file__).parent / "counter.db"

#: The document the count lives in. A key, not a path — the substrate decides
#: where it physically goes, which here is a row in `counter.db`.
KEY = "example-counter"


def bump(rc: RunContext) -> int:
    """Increment a counter stored durably in SQLite.

    Read, modify, write back with ``expect=`` — a losing write means somebody
    else counted between our read and our write, so we read again rather than
    overwriting them. That is the whole shape of a safe update on a substrate,
    in six lines.
    """
    substrate = SQLiteSubstrate(DB_PATH)
    for _ in range(8):
        stored = substrate.read(KEY)
        count = (stored.data.get("runs", 0) if stored else 0) + 1
        revision = stored.revision if stored else None
        if substrate.write(
            KEY,
            {"runs": count, "last_run_note": f"run #{count}"},
            expect=revision,
        ):
            rc.log(f"Persistent run count: {count}")
            return count
    raise RuntimeError("could not record the count; another writer kept winning")
