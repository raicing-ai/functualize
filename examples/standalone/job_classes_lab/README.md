# job_classes_lab

Three job classes, one collision.

A job class is a `pydantic.BaseModel` with `@job` on it. Each public method is
one job, and the class's typed fields are the configuration **all** of its
methods read. Nothing here is registered by hand: `jobs/` is scanned like any
other job directory.

```bash
cd examples/standalone/job_classes_lab
```

## Layout

| File | Why it looks like this |
|---|---|
| `jobs/pg.py` | `@job(group="pg")` on `Postgres(Database)`. `Database` has **no** `@job` of its own — the opt-in is never inherited — but its fields (`host`, `port`) and its `JOB_TAGS` still reach the concrete class. `start`, `stop` and `backup` are the three methods, so three names. |
| `jobs/legacy.py` | A plain function with `JOB_GROUP = "pg"`, whose name normalizes to `pg.start` — the same name as `Postgres.start`. This is the collision. |
| `jobs/reports.py` | Bare `@job` on `Reports`, so the class name becomes the group; `JOB_GROUP = "data"` stays the namespace above it. Its job is `data.reports.generate`, two words deep on the command line. |
| `config.base.toml` | `[pg]` sets `host` and `port`; `[data.reports]` sets `month`. One section per class, read by every method of that class. |
| `pyproject.toml` | `[tool.functualize] jobs_directories = ["jobs"]` — the standard project-config location, so `func` works here without an install. |

## Run → Expect

Run each command in order and compare against **Expect**. `.functualize/cache/`
is written on the first run; nothing else changes on disk.

| # | Run | Expect |
|---|-----|--------|
| 1 | `func builtin info jobs` | Four rows: `data.reports.generate`, `pg.backup`, `pg.stop`, and `pg.start` reading `Name collision: neither definition is registered.` with the full message indented beneath it |
| 2 | `func pg` | Only `backup` and `stop`. `start` is **absent** — a collided name is not a command |
| 3 | `func pg start` | Exit code `2`, stderr names both definitions and both files, stdout empty |
| 4 | `func pg stop --force` | `stopped db.internal:6543 (force=True)` — `host` and `port` came from `[pg]`, `force` from the flag |
| 5 | `func pg backup` | `backed up db.internal:6543 to s3://backups` — the method's own `@job(tags=…)` plus the class's tags |
| 6 | `func data` | `Sub-groups: reports` |
| 7 | `func data reports generate --kind csv` | `generated 2026-09 report as csv` — `month` came from `[data.reports]` |
| 8 | `func data.reports generate` | Exit code `2`, refused: a dotted name crosses a group. Two levels are spelled with two words. (On a *cold* scan the same line answers `Unknown command 'data.reports'` plus a "Did you mean" — the group is learned from the first walk, which step 6 already did) |
| 9 | `func builtin info --json` | `pg.backup` has `["method-tag", "class-tag", "database"]`; `pg.stop` has `["class-tag", "database"]` (no method tags of its own); `data.reports.generate` has `["nightly"]` |

Step 9 is the tag merge in one line: the method's own declaration first, then
the class's `@job(tags=…)`, then `JOB_TAGS` outward along the MRO. `Database`'s
`("database",)` is last because it is the furthest base.

Two refusals are worth reading rather than just observing:

- **The collision is strict because a class is involved.** `legacy.start` and
  `Postgres.start` both claim `pg.start`, and *neither* runs. The other three
  jobs keep working — the project boots, discovery reports one failure.
- **`JOB_TAGS` must be `ClassVar`.** Drop the annotation in `jobs/pg.py` and the
  tuple becomes a pydantic field instead: it stops contributing tags and starts
  asking for configuration, silently, because the annotation is legal Python.

## Tests

```bash
uv run pytest examples/ -v
```

`tests/test_job_classes_lab.py` runs the real `func` binary against a copy of
this directory — the class job's output, the tag merge, the two collision
surfaces, and the absence of `start` from `func pg`.
