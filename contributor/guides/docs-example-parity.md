# Executable docs & examples parity

The documentation and the `examples/` tree are a second product surface. Nothing
ran either of them until 2026-08-29: `testpaths = ["tests"]`, no CI job touched
`examples/`, and `doc-verify` was agent-invoked. Two core changes —
ADR-007/008 (secrets and config) and ADR-009 (group options) — altered behaviour
that roughly 50 doc pages and 20 example projects assert **in prose**, and
nothing failed.

This guide is the procedure for catching that, written after the pass that found
it rather than before.

## Run it when

- Cutting a release, or bumping the version.
- An ADR lands that changes behaviour a user can observe.
- `/sync-docs` runs — that is the other moment someone reconciles docs with code.

## The pass

```bash
# One environment, all three flags: they prune each other.
uv sync --all-packages --all-extras --group docs

uv run pytest examples/ -v

PATH="$PWD/.venv/bin:$PATH" python \
    .agents/skills/doc-verify/scripts/run-scenario examples/docs/scenarios/

uv run mkdocs build --strict
```

Then walk each `examples/**/README.md` verification checklist the harness does
not cover, and each index list for directories missing from it.

## Why the release audit does not catch this

`.agents/skills/release/SKILL.md` Phase 1 already reads the whole documentation
corpus — but **statically**. It verifies that referenced paths exist, that
symbols exist with the stated signature, and that fenced blocks parse.

Every finding in the 2026-08-29 pass passes all three checks.

> *"`api_key` → masked in field detail"*

That sentence names no symbol and no path, and contains no code to parse. It is
a claim about runtime behaviour, falsifiable only by running the command. It was
false for months. That is the hole this guide fills, and it is why the parity
pass **runs** things where the audit **reads** them.

## The drift classes, each with the method that detects it

| Drift class | Instance found | Caught by |
|---|---|---|
| A behavioural claim silently falsified by a core change | `showcase` printed `api_key`, `db_password` and `output_token` in cleartext while three doc layers claimed masking — one crediting a `"token"` keyword heuristic ADR-008 had deleted | Running the command: `func builtin env release` |
| An example file never committed, because `.gitignore` was too broad | `run_notifier.py` — a blanket `.functualize/` swallowed the plugin the example is *about*; its 3 tests failed on every clean clone | `uv run pytest examples/` from a clean clone |
| A scenario that fails open, or asserts nothing | `h-workflow` asserted a sentinel (`WORKFLOW_SETUP_OK`) its own command never printed, so it had never passed — and its body declared no `@workflow`, reached no gate and resumed nothing, despite its description | Reading the scenario against its own description |
| Index drift — a new example invisible to readers | 4 examples missing from 3 indexes; one README said "Five directories" above a six-row table | Count the directories, count the rows |
| The same stale fact copied into N files | The boot provider row ("TOML + INI") in 3 files; `remote_first()`'s promise in 6 | `grep` the *claim*, never the file |
| A dead capability the docs present as working | `remote_first()` — `RemoteSource` is constructed nowhere, so the preset resolves as `classic()` while the docs recommended it for Vault | Read the call path, not the symbol: a symbol that exists proves nothing about it being reached |
| Harness environment noise read as documentation drift | `exit 127` on every step, with no `.venv/bin` on `PATH` | Run a known-good scenario **first** |
| A doc that publishes a red command | `docs/examples/index.md:48` published `uv run pytest examples/ -v`, which was red | Run the command the doc tells the reader to run |
| A test that pins a claim nothing satisfies | `test_file_plugin.py` requires subscriptions to `job.execute.success` / `.failure`; the engine emits one terminal `job.execute.end` carrying the outcome as a field | Grep the event names the product actually emits |

## Hard rule: prove the harness before believing a failure

**Before believing any doc-verify failure, run `a-core-builtins`.** It exercises
the plumbing and nothing else.

This pass's first run reported **twelve** documentation failures that were one
missing `PATH` entry. A run that reports many failures at once is far more
likely to be one broken precondition than a documentation set that went stale at
the same moment.

Two preconditions produce that outcome, and neither announces itself:

1. **`.venv/bin` on `PATH`** — shell steps invoke `func` as a plain command;
   without it every step exits 127.
2. **The working directory at the repository root** — a shell step's `cwd` is
   process-relative (`run-scenario` does `Path(step["cwd"])` with no `ROOT`
   join, unlike the pty engine).

A third, for local runs: `uv sync --all-packages`, `--all-extras` and
`--group docs` each prune what the others install. Each CI job has its own
environment, so each flag is correct there; a local pass needs all three at
once. Running one alone produced two phantom TUI test failures and six phantom
mypy errors in this pass, both of which vanished once the venv was complete.

## Writing a scenario that cannot pass vacuously

The `h-workflow` failure mode is the one to design against: a scenario whose
description promises far more than its assertions require.

- **Assert the state, not the exit code.** A workflow scenario that checks only
  "the command ran" passes when the gate never engages. Assert `blocked`, and
  the gate by name.
- **A must-error case asserts a non-zero exit *and* the message.** "It failed"
  passes when the command fails for an unrelated reason — a typo in the fixture,
  a missing venv, a job that no longer exists.
- **Assert a decoy.** A masking scenario that never checks a *non*-secret cannot
  tell "detection works" from "everything is masked". `secrets_lab`'s `sort_key`
  exists for exactly this.
- **Prove it is not vacuous by breaking the thing it covers.** Delete the
  `Gate(...)`, the `Secret[str]`, the `_options.py` — the scenario must go red.
  Then restore.

## Commit before sabotaging

`git checkout -- <file>` reverts **everything** uncommitted in that file, not
just the damage. Commit the finished change first, sabotage second, restore
third. Skipping this has silently discarded completed work more than once
(`wiring-discipline.md` §3).

## Related

- [`wiring-discipline.md`](wiring-discipline.md) — a capability that is built,
  unit-tested and unreachable. `remote_first()` is a worked instance.
- [`tui-panels.md`](tui-panels.md) §14 — the `secret=` contract every panel must
  carry.
- `.agents/skills/doc-verify/SKILL.md` — the harness itself.
