# FUN-25 — Contracts

**Status:** complete (Factory Designer, 2026-09-22). Measured against `68fa1a1`.

## What this ticket changes at a boundary

**Nothing.** That is the contract, and it is the one a reviewer should check first.

This is a spike. Its output is measurements and one markdown reference. It adds no public
symbol, removes none, changes no signature, and touches no declared surface.

```console
$ git diff --name-only origin/master..HEAD -- src/ plugins/
# must be empty for the whole life of this branch
```

| Surface | Change |
|---|---|
| `src/functualize/**` | **none** |
| `plugins/**/src/**` | **none** |
| Public `__all__` in any public folder | **none** |
| `StoreSubstrate` port members | **none** — still `read`, `write`, `lock` (`_types/protocols.py:791-860`) |
| `Stored` / `Revision` | **none** — FUN-24 already made `Revision` opaque; see below |
| Entry points | **none** |
| CLI surface | **none** |

## Public API surface

`tests/test_public_api_surface.py` enforces the exported surface. **This ticket must not
move that test**, and its greenness is task 1.1's precondition and 6.1's postcondition:

```console
$ uv run pytest -q --no-header tests/test_public_api_surface.py
# 43 passed  (baseline measured on 68fa1a1, 2026-09-22)
```

The scaffold's note about deprecating `ScopeStore`/`RunStore` and exporting
`StoreSubstrate` and `Stored` from `functualize.plugin` describes
`runtime-persistence-engine-owned/07-what-changes.md:63` — **FUN-17's work, not this
ticket's.** It is left here as a pointer, explicitly out of scope. Verified today:

```console
$ rg -n "StoreSubstrate" src/functualize/plugin/__init__.py
# no matches — StoreSubstrate is public nowhere, and stays that way in this ticket
```

## The one contract this ticket *does* author

An internal boundary rule for the new directory, checkable in one command
(`plan.md` §4):

> Only `tests/substrate_probe/tier_a.py` may import from `functualize`.

```console
$ rg -n "^(from|import) functualize" tests/substrate_probe/ \
    | rg -v "^tests/substrate_probe/tier_a.py"
# must be empty
```

Rationale: a probe that measures through our adapter measures the adapter. `tier_a.py` is
the deliberate exception because for the filesystem and local SQLite the shipping
substrate *is* the backend under test.

## Import-linter contracts

Seven contracts in `pyproject.toml` decide whether an AFTER shape is legal. The probe adds
no layer and lives entirely under `tests/`, which no contract governs, so they pass
unchanged:

```console
$ uv run lint-imports
```

**If this ever needs a contract edited, that is a finding to raise before editing it** —
and in this ticket it would mean probe code had drifted into `src/`, which
`contracts.md`'s first command already forbids.

## External interfaces this ticket consumes (not publishes)

None is a functualize contract; all are vendor surfaces, listed so the reviewer can tell
measurement from assumption.

| Backend | Reached via | Credential source | Absent ⇒ |
|---|---|---|---|
| JSON filesystem | `functualize._primitives.substrate.JsonFileSubstrate` | none | always runs |
| local SQLite | `functualize_substrate_sqlite.substrate.SQLiteSubstrate` | none | always runs |
| floci emulator | `boto3` + `AWS_ENDPOINT_URL` | none (emulator accepts anything) | module skip |
| AWS S3 / R2 | `boto3` (`AWS_ENDPOINT_URL` swaps the endpoint for R2) | `AWS_*`, `FUNCTUALIZE_PROBE_S3_BUCKET` | module skip |
| AWS DynamoDB | `boto3` | `AWS_*`, `FUNCTUALIZE_PROBE_DDB_TABLE` | module skip |
| Cloudflare D1 | stdlib `urllib.request` — **not `httpx`**, which no first-party package declares (`plan.md` §6) | `CLOUDFLARE_*` | module skip |
| Turso / libSQL | `libsql-client` if present | `TURSO_*` | module skip |
| Supabase Postgres | `psycopg` if present | `SUPABASE_DB_URL` | module skip |

The credential names are already declared in `.env.example` (committed in `68fa1a1`);
this ticket adds `FUNCTUALIZE_PROBE_R2_*` beside them and changes nothing else there.

**Skip, never fail** (AC5) is one idiom, lifted from
`plugins/credentials/functualize-aws/tests/test_integration_floci.py:41-64`:
`pytest.importorskip(...)` for the client, a TCP/`_reachable()` check or an env-var
presence check for the service, then `pytest.skip(..., allow_module_level=True)`. That
file's own rule governs this ticket too —

> "It does *not* fall back to a fake: a green run that silently tested nothing is worse
> than a skip that says so." — `test_integration_floci.py:17-19`

— which is the same rule the issue states as **never invent a cell**.

## Backward compatibility

**Nothing breaks, and here is the command that would falsify it.** The probe is additive:
new files under `tests/substrate_probe/`, one new marker in `pyproject.toml`, ~25 lines
appended to `tests/primitives/test_substrate.py`, one new file under
`contributor/reference/`.

```console
$ uv run ruff check src/ tests/ plugins/ examples/
$ uv run ruff format --check src/ tests/ plugins/ examples/
$ uv run mypy src/
$ uv run lint-imports
$ uv run pytest            # the whole root suite, with no credentials present
```

The last one is the real claim: `testpaths = ["tests"]`, so `tests/substrate_probe/` **is
collected by the default run and by CI's `test-fast`/`test-full` jobs**. A contributor
with no AWS account must see skips, not failures, and not errors at collection time —
which is why every remote module gates at *module* level, before any client is built.
