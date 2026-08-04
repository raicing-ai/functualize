# Wiring discipline — against built-but-unreachable code

## The failure this prevents

On 2026-07-20/21 three capabilities were found that had been **built, unit-tested,
and never connected to anything**:

| capability | built | unit-tested | reachable in production |
|---|---|---|---|
| `WorkflowToolProvider` (5 MCP tools) | yes | 25 tests | **no** — no server registered it |
| `Gate.tools` enforcement | yes | yes | **no** — `run_job` was a second, unlocked door |
| `DepScheduler` + guards + fingerprints + `func why` | yes | 4 test files | **no** — `grep -c` in `executor.py` returned 0 |

The third is the clearest. 944 lines across four modules, all green, referencing
only each other:

```
fingerprint.evaluate  <- guards.py  <- explain.py  <- (nothing)
scheduler.py                                        <- (nothing)
```

So `@job(deps=...)`, `@job(guards=...)` and `@job(cache=...)` were accepted,
validated, serialized into the cache — and did nothing. `func why` printed
`Unknown command`. The renderer had been committed *at the stage gate that
claimed to deliver it*.

## Why every existing gate passed

This is the important part. Nothing was broken by the usual definitions:

- **Unit tests passed** — each constructs its subject directly. `DepScheduler(graph).run(runner)`
  proves the scheduler works. It says nothing about whether *anything constructs a
  DepScheduler*. **The test was the only caller.**
- **The full suite was green**, 5800+ tests.
- **ruff, mypy, lint-imports** were clean. Unreachable code is still well-typed.
- **The stage gate** was "tests + lint green at the stage boundary" — satisfied.

No gate asked *"what production call path reaches this?"* So the answer was
allowed to be "none" three times.

Note the shared shape with a fourth defect: `tests/plugins/test_mcp_workflow_tools.py`
passed unchanged through a breaking change to the `Step` vocabulary, because its
`FakeStep` fixture had no relationship to the real `Step`. **A test that supplies
its own collaborators cannot detect that production supplies none.**

## The rules

### 1. Capability tests, not component tests

Every capability a user can *declare* must have at least one test that declares
it the way a user would and observes the consequence through the public entry
point.

```python
# Proves the component. Does not prove it is reached.
verdict = Preflight(store).check("build", declaration)
assert verdict.should_run is False

# Proves the capability.
@job(cache=Fingerprint(sources=["input.txt"]))
def build() -> None: ran.append("build")
app.execute("build"); app.execute("build")
assert ran == ["build"]          # second run skipped
```

Both are worth having. Only the second fails when the wiring is missing.
`tests/integration/test_declared_capabilities_e2e.py` is the worked example.

### 2. Name the call path before closing a task

Before marking any task done, answer: **"what production call path reaches this
code?"** — and name it concretely (`execute() → _preflight_check → Preflight.check`).

If the honest answer is "a test calls it", the task is not done. Write it in the
commit message; it is cheap, and it is the moment the gap becomes visible.

### 3. Sabotage the wire, not only the logic

Breaking a component's internals and watching a test fail proves the test covers
the logic. It does **not** prove anything covers the integration. After wiring,
break the *wire* — comment out the call, `if False:` the branch — and confirm a
test fails.

Every wiring commit in this codebase since 2026-07-20 records this result. If no
test fails when the call is removed, the call is undefended.

**Commit before you sabotage.** Sabotage means deliberately corrupting source
you are about to restore, and the restore is where it goes wrong: `git checkout
-- <file>` reverts *everything uncommitted in that file*, not just the damage
you did. On 2026-07-21 that silently threw away a finished `topological_order`
rewrite twice — the sabotage was caught, the tests went green again, and the
work was gone. It was noticed only because a follow-up grep found the new code
missing.

So the loop is:

```
1. finish the change
2. run the suite, gates green
3. git commit          <-- the restore point
4. sabotage
5. confirm the right tests fail
6. git checkout -- <file>   (now provably safe)
7. amend the commit with the sabotage result
```

If committing first is genuinely wrong — the change is not yet coherent — copy
the file to the scratchpad and restore with `cp -f` instead. Plain `cp` prompts
interactively and will hang a non-interactive shell, which is its own failure
mode: a hung restore leaves sabotaged source in the tree.

Sabotage is also how you find out a *test* is vacuous, not just a wire. Two
tests written on 2026-07-21 passed under the exact regression they claimed to
cover — a dispatch corpus whose "group beats job" case used a name that was
only a group, and a normalization test whose graph was flat enough that a
wrong traversal still produced the right answer. Neither would have been found
by running them.

### 4. Enumerate every door before shipping a guard

When adding an enforcement, permission, or check, list **every** entry point to
the operation being guarded, and lock each one.

`Gate.tools` was enforced in `_execute_job` — the per-job MCP path — while
`run_job` and `run_job_async` called `app.execute()` directly. An agent refused
`deploy` typed `run_job("deploy")` and got it. A permission with a second door is
not a permission.

### 5. Exercise the *cached* path, not just the live one

A discovery cache is a second production path, and the cheap test harness only
reaches the first. `register_dynamic_job` always hands the engine a live,
materialized function; a warm boot hands it a deferred-import stand-in with no
declaration attached. Code that reads anything off the function therefore works
in every test and fails in every second real run.

This shipped: dependency names were read from the job function, so a cold run
executed `a → b → c` and a warm run executed only `c`. Silently, because the
cache existed. The capability tests could not catch it — they were dynamic
registrations, which is a side door.

**For anything that reads from a job's function or annotations, add a test that
boots twice**: once cold, once against the cache it just wrote, and assert the
two runs agree. `TestWarmBootParity` in
`tests/integration/test_declared_capabilities_e2e.py` is the pattern.

Corollary for discovery: a fact the engine needs at run time and cannot
re-derive without importing must be *recorded on the descriptor* and carried
through the cache — with a `CACHE_VERSION` bump. `FromJob` edges live in the
signature, so they are recorded; `Deps` survives in the cached declaration and
is not.

### 6. Orphan scan at stage gates

Mechanically list symbols defined in `src/` that only tests reference:

```bash
# see the sweep script in this file's history; roughly:
# for each top-level def/class in src/, count references in src+plugins
# (excluding its own file) vs tests/ — report those with 0 production refs
```

This is a **review item, not a hard gate** — it has real false positives (public
API meant for users, plugin extension points, and symbols called from within
their own defining module). Treat a hit as a question to answer, not a failure.

### 7. A stage is done when its declared surface is walked

Green tests are necessary, not sufficient. At a stage boundary, walk that stage's
section of `contracts.md` line by line and, for each item, name the test that
exercises it end-to-end. Items with no such test are the stage's real remaining
work.

Had this been done at the S3 gate, `func why` — listed in that stage's own
deliverables — would have been caught immediately, because there is no test that
runs `func why` and reads output.

## The one-line version

> Code that only tests call is not shipped, however green it is. Before closing
> anything, name *every* production path that reaches it — the cold one and the
> cached one — and break each once to prove something notices.
