"""``functualize-sqlite-import`` — the legacy import as an offline command.

It does **not** boot the app: boot is what refuses with
``LegacyImportRequired`` while un-imported runtime documents sit in the
database, so the command that clears the refusal must not depend on it
(`contracts.md` §6, Q-4).

    functualize-sqlite-import [--project PATH] [--db PATH] [--dry-run] [--resume | --rollback]

Exit codes: 0 imported and verified (or nothing to do), 2 usage, 3 refused
records — nothing imported, 4 verification failed — rolled back, 5 another
import holds the lock.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

from functualize_substrate_sqlite._factory import IMPORT_COMMAND, default_database_path
from functualize_substrate_sqlite._legacy_import import Mode, import_legacy

__all__ = ["main"]


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog=IMPORT_COMMAND,
        description=(
            "Import this project's legacy runtime documents into the relational "
            "SQLite schema: offline, backed up, verified, and refused whole if any "
            "record is illegal. The documents stay authoritative until it succeeds."
        ),
    )
    parser.add_argument(
        "--project",
        type=Path,
        default=Path.cwd(),
        help="the project whose state.db to import (default: the current directory)",
    )
    parser.add_argument(
        "--db", type=Path, help="the database file, instead of the project's state.db"
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="read, check and report; write nothing"
    )
    which = parser.add_mutually_exclusive_group()
    which.add_argument(
        "--resume", action="store_true", help="finish an import whose marker exists"
    )
    which.add_argument(
        "--rollback",
        action="store_true",
        help="undo a recorded import; the documents become authoritative",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    db = args.db or default_database_path(args.project.resolve())
    mode = (
        Mode.ROLLBACK if args.rollback else Mode.RESUME if args.resume else Mode.IMPORT
    )
    report = import_legacy(Path(db), dry_run=args.dry_run, mode=mode)
    stream = sys.stdout if report.outcome == 0 else sys.stderr
    print(report.text(), file=stream)
    return int(report.outcome)


if __name__ == "__main__":  # pragma: no cover - the console script is the entry point
    raise SystemExit(main())
