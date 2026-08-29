# Status — Active Work and Contribution Guide

Functualize is pre-release (Alpha). Breaking changes are free until v1.0.0.

## Next Cut — 0.1.1

A patch cut. Scope is one correctness bug found while reviewing an examples
defect, plus the two guards that would have caught the examples defect itself.
Everything here is verified by execution against `0.1.0`, and the reproductions
are written out in full so nobody has to take this on trust.

### The finding: the job metadata cache is not filter-aware

`exclude_patterns` and `--exclude` are **silently ignored against a warm cache**,
and the failure runs in both directions. Minimal reproduction — a directory
containing exactly `alpha.py` (job `alpha`) and `test_beta.py` (job `beta`), no
config unless stated, `func builtin cache clear` before each sequence:

| | Sequence | `func builtin info` lists | |
|---|---|---|---|
| **X1** | cold cache → `--exclude 'test_*.py'` | `alpha` | correct |
| **X2** | one plain run → `--exclude 'test_*.py'` | `alpha`, `beta` | **exclusion ignored** |
| **X3** | plain run → add `[discovery] exclude_patterns` to `.functualize.toml` | `alpha`, `beta` | **ignored until `cache clear`** |
| **X4** | `--exclude 'test_*.py'` once → then **no flag at all** | `alpha` | **`beta` gone for good** |

**X4 is the one that matters.** A single `--exclude` invocation removes a job
from the CLI permanently — no flag set, no config entry, no diagnostic — until
the user knows to run `func builtin cache clear`. The job is not shadowed or
deprioritised; `func beta` answers `Unknown command 'beta'`. X3 is the milder
half of the same bug and is the likelier one to be hit, because it is the
ordinary path: use the tool, then add a filter to the config.

**The filter machinery is not at fault.** Probing
`GlobExcludePreFilter.should_import` (`_primitives/pre_filter.py:472`) on a cold
run shows it firing correctly — `alpha.py -> True`, `test_beta.py -> False` —
and `func builtin config show` resolves the setting correctly
(`exclude_patterns = ["test_*.py"]  # source: project`). The defect is entirely
at the cache boundary.

**The mechanism is visible in the cache file.** Its header
(`_primitives/cache_format.py:271` resolves the path;
`~/.cache/functualize/<project_id>/cache.json`) fingerprints four things and not
the fifth that matters:

```json
{"version": 15, "functualize_version": "0.1.0", "python_version": "3.13.13",
 "deps_hash": "sha256:...", "generated_at": "...",
 "pre_filter_decisions": {".../test_beta.py": {"eligible": false, "source_mtime": ...}}}
```

Format version, package version, Python version and dependencies are all
fingerprinted. **The effective discovery configuration is not.** And
`PreFilterDecision` (`_primitives/cache_format.py:99-114`) persists negative
pre-filter decisions — by design, per its own docstring: *"Only negative
decisions (eligible=False) are persisted"* — with no record of which filter
produced them. The next run replays that `eligible: false` regardless of what
the caller asked for. That is X4. X3 is the same gap from the other side: a file
already cached as a positive descriptor entry is returned without the pre-filter
being consulted again.

The filters are built once at boot from `_discovery_config`
(`_app/boot.py:470`) and handed to the provider, so a single header field is
enough to invalidate correctly — there is no per-directory or per-filter
partition to reconcile.

### How it was found, and why nothing caught it

Review of an examples defect: `examples/plugins/file_based_plugin` shipped no
`.functualize.toml`, so `func greet` — the one command its README publishes —
failed with `Unknown command 'greet'` while the three functions in its own
`test_file_plugin.py` registered as jobs and were invocable. Fixed by `7f09be4`
(the anchor file, now tracked); the earlier `055310b` had restored the plugin
file git had never tracked. Both were `git ls-files` defects, not code defects.

The cache bug surfaced because the natural completion of that fix —
`exclude_patterns = ["test_*.py"]`, to keep the example's test suite out of the
user's command namespace — did not work.

Two guards were missing, and either would have caught the examples defect at
`055310b`:

- **No doc-verify scenario for the example.** `examples/docs/scenarios/` has 16
  scenarios covering 13 doc pages; none covers this example.
- **`uv run pytest examples/` never invokes the CLI here.**
  `test_file_plugin.py` tests the plugin object and the loader in-process. No
  test asserts the README's `func greet` runs.

### Ship-blocking — **DONE 2026-08-29**

Items 1-6 and 9 are landed on `release/0.1.1`; item 7 is deferred to
[`shape-intents/remote-config-source.md`](shape-intents/remote-config-source.md);
item 8 was already fixed. The decision and its reasoning are in
[ADR-010](../contributor/adr/010-discovery-cache-filter-awareness.md).

| # | Item | Commit |
|---|---|---|
| 1 | `discovery_hash` in the cache header | `8c42743`, `ddfd18f` |
| 2 | `CACHE_VERSION` 15 -> 16 | `8c42743` |
| 3 | X2/X3/X4 warm-cache regressions | `0785866`, `b992d14` |
| 4 | `file_based_plugin` publishes only `greet` | `384b946` |
| 5 | doc-verify scenario for that example | `6941aa4` |
| 6 | clean-clone CI guard | `2b941e2` |
| 9 | doc-verify's own `--timeout` docs | `688f8e2` |

Gates: full suite under `HYPOTHESIS_PROFILE=ci --run-slow -n auto`; `pytest
examples/` 139 passed; doc-verify shell tier; `lint-imports` 5 kept 0 broken;
mypy 0 errors over 295 files; ruff clean including `examples/`.

**One claim did not survive.** The first implementation also taught the pre-boot
routing read (`read_routing_names_from_cache`) the fingerprint, on the reasoning
that routing resolves job names before the app boots. Sabotage refuted it:
removing the argument left every assertion green, including a bare-listing pair
added specifically to catch it, because a routing miss falls through to a path
that boots anyway. Reverted in `b5f918e` rather than shipped — it cost a
`resolve_cli_config()` call inside a read documented at a ~3ms budget for
behaviour no test could observe.

#### New follow-ups this work produced

- **`func builtin cache rebuild` rebuilds unfiltered.** It is unfiltered today and
  this change did not widen to fix it. Under the new semantics it writes no
  fingerprint and the next boot invalidates and rebuilds correctly, so it
  self-heals rather than poisons — but its own "Cache rebuilt with N entries"
  line reports an unfiltered count.
- **Child-project providers (`_app/boot.py:888`) receive no discovery config**, so
  they skip the fingerprint check. Unchanged by this work; they have none plumbed.
- **`read_group_options_from_cache` cannot honour the fingerprint.** No call site
  can supply it (`_dispatch_group` has no config in scope), so a group's declared
  flags can be served from a cache written under a different filter set for one
  invocation. Milder than the job case and self-healing on the next boot.

### The original findings, as recorded

1. **Fingerprint the discovery config into the cache header.** Add
   `discovery_hash` beside `deps_hash` in `_primitives/cache_format.py` —
   sha256 over the normalized effective filter fields (`exclude_patterns`,
   `require_file_*`, `require_job_*`, `extra_directories`). Treat a mismatch as
   a full invalidation, the same path a `CACHE_VERSION` mismatch already takes.
   Whole-file invalidation is what makes this sufficient rather than partial: it
   discards `pre_filter_decisions` along with `entries`, closing X4 and X3 with
   one field.

2. **Bump `CACHE_VERSION` to 16** (`_primitives/cache_format.py:93`). Not
   cosmetic — anyone who ran `--exclude` on 0.1.0 has a poisoned cache on disk
   right now, and without the bump the fix does not reach them until something
   else forces a rebuild.

3. **Regression tests for the warm-cache transitions.** X2, X3 and X4
   specifically: warm-then-filter, config-added-after-warm, and
   filtered-then-unfiltered. The existing filter tests all run cold, which is
   exactly why this survived to 0.1.0.

4. **Decide the example's test-function question.** Once (1) lands,
   `exclude_patterns = ["test_*.py"]` in
   `examples/plugins/file_based_plugin/.functualize.toml` will work; re-add it.
   If the example should not depend on the fix, move `test_file_plugin.py` into
   a `tests/` subdirectory instead — no config, no filter, and it matches the
   layout every other example already uses. Either way the example currently
   publishes four commands, three of which are its own test suite.

### Worth doing, cheap

5. **A doc-verify scenario for `file_based_plugin`.** Five shell lines: `cd`,
   `func greet`, assert `stdout_contains = "[run-notifier] greet succeeded."`.

6. **A clean-clone guard.** Both `055310b` and `7f09be4` were files that existed
   locally and not in git. A CI step that clones into a temp directory and runs
   each example's README command closes the class, not the two instances.

### Done while scoping this cut

- **Silent skips in `doc-verify` — fixed.** `--engine` marked non-matching steps
  `skip`, a scenario whose steps all skipped rolled up to `skip`, and the exit
  gate only looked for `fail`. So the per-PR job reported green while 10 of 16
  scenarios and 38 of 81 steps ran nothing — installation, scaffold, quickstart,
  discovery, MCP and the whole TUI surface among them.

  `run-scenario` now exits **3** when any scenario executes zero steps, prints a
  **NOT VERIFIED** table naming each unverified scenario, its doc page, and the
  tier that owes it, and repeats that list on stderr. `--allow-skips` accepts the
  narrowing deliberately; `ci.yml` passes it with a comment saying exactly what
  is being given up, so the gap is declared in the workflow file instead of
  hiding in a skip count. `SKILL.md` gains it as hard rule 5, with the tier
  table: `shell` = per-PR CI, `docker` = nightly/release-tag + release gate,
  `pty` = local only (`CLAUDE.md:11`).

  Verified: docker-scenario-under-`--engine shell` exits 3; the same plus
  `--allow-skips` exits 0; an all-shell scenario is unaffected.

- **The docker tier works.** `examples/docs/scenarios/installation.toml` — three
  steps in a clean `python:3.11-slim` — passed **3/3 in 43.7s** on first run
  here. The expectation that it would fail on harness problems before reaching
  real drift was wrong; it needed no fixing at all.

  Two facts worth keeping. The runner prefers **podman** over docker
  (`run-scenario:212-216` tries `podman` first), so `docker images` is the wrong
  place to look for evidence of past runs — check `podman images`. And the image
  was already in the local podman store from 2026-07-25, so the docker tier has
  been exercised on a developer machine before, just never in CI.

### Sequencing

`7f09be4` is on `fix/docs-example-parity`; the cache fix touches
`_primitives/cache_format.py` and the provider read path — a different blast
radius than an examples-only branch. Cut the cache fix as its own branch off
`master` and land it first, then rebase the example config change on top, so
item (4) can go in the same commit that makes it work.

### Not claimed

An earlier pass of this review read the `require_*` filters as also broken
against a warm cache. **That reading was a shell-quoting artifact** — a loop
variable passed unsplit, so `func` received `"--require-job-prefix al"` as a
single argument and printed no table. Re-run with correct quoting,
`--require-job-prefix al` returns `alpha` on a warm cache, correctly. Only
`exclude_patterns` / `--exclude` is proven defective; whether the other filter
families share the gap is untested, and the fix in (1) covers them regardless
because it invalidates on the whole config.


### From the adversarial review of `fix/docs-example-parity` (2026-08-29)

An independent review of `73f811a..8739ddd` run against the tree, not read off
it. Numbering continues from (6) so the items can be merged into the lists
above without renumbering. Each carries the command that demonstrates it — a
claim with no command is not a finding.

The review reproduced two of the five recorded sabotage checks and both matched
their recorded counts exactly, so the sabotage discipline on this branch is
sound and does not need re-auditing. What follows is what it did **not** cover.

#### Ship-blocking

7. **DEFERRED to a shape intent (2026-08-29).** Taken out of the 0.1.1 cut by
   decision; the full evidence and the two coherent end states now live in
   [`.spec/shape-intents/remote-config-source.md`](shape-intents/remote-config-source.md),
   which is committed and self-contained. The finding as originally written
   follows, unchanged.

   **The `remote_first` gate is scope-blind; the stale promise survives in the
   public docstring.** The recorded gate,
   `grep -rn "→ Remote\|Remote →" --include="*.md" .` → 0 hits, is true. The
   `--include="*.md"` scoping is what makes it true. Dropping it:

   ```
   src/functualize/app/presets.py:97:    """CLI → Remote → Env → Files → Defaults.
   src/functualize/_cli/tui/panels/config_table.py:50:    CONFIG: ... (CLI → Env → File → Remote → Default).
   ```

   `grep -rn "RemoteSource(" src/` returns **zero construction sites**, and
   `presets.py:99-101` still tells the reader the boot path "can wire up
   RemoteSource and FileSource". That is the docstring of the very function the
   feature declared dead, reachable from `help(remote_first)` and every IDE
   hover. Six markdown copies were removed and the authoritative one was left.

   **Fix**: correct the docstring to say the preset resolves as `classic()`, or
   delete `RemoteSource`. Then re-run the gate **without** the `--include`
   filter — the scoping is the defect, the markdown copies were the symptom.

8. **`ENGINE_TIER` names a nightly job that does not exist.** The new tier table
   in `run-scenario` and the `ci.yml` comment both assign the docker tier to a
   "nightly + release-tag job". There is no such workflow:

   ```
   $ grep -ln "schedule:\|cron" .github/workflows/*.yml
   .github/workflows/security.yml
   ```

   The docker tier's only real owner today is the manual release gate
   (`release/SKILL.md` Phase 4b). Shipping a table that points at a job nobody
   has written is the same drift class this feature was built to kill, and it
   would be introduced by the fix for it.

   **Fix**: add the nightly workflow, or name the release gate as docker's sole
   owner. Do not leave the forward reference standing.

9. **`--timeout` is documented as an override it no longer is.** `4b9d429`
   changed the semantic to `timeout = int(step.get("timeout", timeout))`, which
   is correct and fixed a real bug — 64 declared per-step timeouts were dead.
   The argparse help and the docstring were updated.
   `.agents/skills/doc-verify/SKILL.md:264` was not, and still reads
   "*global timeout override (seconds, default 120)*". It is now only a default:
   any step declaring its own ignores the flag, so a run can no longer be
   shortened from the command line.

   Adjacent and pre-existing, missed by the parity pass:
   `references/format-spec.md:67` claims per-engine defaults of "60 for shell,
   120 for docker, 30 for pty". The actual default is `args.timeout` = 120 for
   all three engines.

   **Fix**: one line each. Both files are the harness's own documentation, which
   is the one corpus a documentation-parity feature cannot afford to leave stale.

#### Worth doing, cheap

10. **`h-workflow` step 7 asserts global state through a fixed `/tmp` path.**
    The final step runs `func builtin workflow list` with
    `stdout_not_contains = "blocked"`, **unfiltered by scope** — unlike steps 3
    and 4, which correctly `grep` the minted id. Any other blocked scope in the
    shared state store fails it for a reason that has nothing to do with the doc
    it cites. Separately, `/tmp/doc-verify-h-workflow-scope` is a fixed path, so
    two concurrent runs clobber each other's id.

    Latent, not active: the scenario passed **3/3 consecutive runs**, so the
    single-use-scope design works. **Fix**: scope the last assertion to the run's
    own id, and mint the file with `mktemp`.

11. **The `doc-verify` job syncs `--all-extras` alone.** The skill's own
    precondition section states a run needs all three flags
    (`--all-packages --all-extras --group docs`), because they prune each other.
    The job uses one. Green today only because the six shell scenarios import no
    workspace package — but `j-dev-contrib` runs the test suite, and the first
    shell scenario to touch an AI or plugin example will fail on a missing
    package **and be reported as documentation drift**, which is precisely the
    failure mode that precondition exists to prevent.

    **Fix**: add `--all-packages` to that job's sync. One word.

    **Fixed (2026-08-29).** The job now syncs `--all-packages --all-extras`.
    `--group docs` is deliberately not part of it: the one step that needed
    mkdocs was `j-dev-contrib`'s `mkdocs build --strict`, and that step has
    been removed — it cited `docs/contributing.md:370-494`, a range whose file
    never mentions mkdocs at all, so it asserted a command no documented line
    contains. `docs-build` owns that command with the right group synced. The
    third flag remains necessary for a *local* run of the whole suite, as the
    skill's precondition says.

#### Judgment call, not a blocker

12. **`test_a_closed_pipe_exits_zero_and_quietly` flakes under load.**
    `tests/pipeline/test_exit_codes.py:131` asserts `result.stderr.strip() == ""`
    while `_plugins/loader.py:448-452` hardcodes a 50 ms plugin-load budget and
    writes the advisory to **stderr**. On a contended runner the budget is
    exceeded and a performance advisory fails a correctness test:

    ```
    E  AssertionError: WARNING:functualize._plugins.loader:Plugin 'functualize-http'
       took 55ms to load (budget: 50ms).
    ```

    Measured here: `HYPOTHESIS_PROFILE=ci uv run pytest --run-slow -n auto -q`
    → **1 failed / 8788 passed** when run against competing load, and
    **8789 passed / 0 failed** on a quiet machine. Serially,
    `tests/pipeline/test_exit_codes.py --run-slow` → 12 passed. So the
    8789-passed figure recorded for this branch is correct and reproducible, and
    the "load-induced" diagnosis is right.

    It is still worth closing: GitHub runners are more contended than a
    developer machine, and the documented CI command is `-n auto`. Pre-existing,
    unrelated to this branch. **Fix**: log the advisory at `DEBUG`, or route it
    off stderr. Two lines, removes a class of CI flake permanently.

#### Deferred past 0.1.1

13. **`executor.py:1018` passes a dead argument.** `config_class=entry.config_class`
    at the workflow `run_step` seam has no observable effect: setting it to
    `None` left all 276 `-k workflow` tests and all 61 combination-matrix tests
    green, because `execute()` re-derives it at `executor.py:290`
    (`entry.config_class or detected_config`). `src/` cleanup with no user
    impact; wants its own change with the workflow suite as the gate.

#### From the docker tier's first full run (2026-08-29)

Prompted by the skip fix: with skips no longer invisible, the docker tier was
run end to end for the first time. **688s wall, 3 scenarios passed, 3 failed.**
Re-running each failure alone splits them:

| Scenario | In the batch | Alone | Verdict |
|---|---|---|---|
| `i-mcp` | FAIL | pass (3/3) | interference |
| `g-discovery` | FAIL | pass (45s) | interference |
| `c-scaffold-project` | FAIL | **FAIL** (277s) | **real** |

14. **`docs/cli/scaffold.md:197` documents a filename the scaffolder does not
    write.** The doc states that in a project context `scaffold add tui-screen`
    produces `src/<package>/screens/<name>_screen.py`. `generator.py:341-342`
    writes `f"{file_name}.py"` with no suffix. Reproduced directly:

    ```
    $ podman run --rm -v "$PWD:/src:ro" python:3.11-slim bash -c \
        "pip install '/src[cli]' && functualize builtin scaffold init my-app3 \
         --template simple && cd my-app3 && \
         functualize builtin scaffold add tui-screen dashboard && find src -type f"
    src/my_app3/screens/dashboard.py      # not dashboard_screen.py
    src/my_app3/screens/dashboard.tcss    # matches
    ```

    The command exits 0 and the `.tcss` name matches; only the `.py` name does
    not. `_screen` appears nowhere in `src/`. **The doc is the wrong one**:
    `tests/scaffold/test_cli.py:198,215` and `tests/test_integration.py:369` all
    assert the unsuffixed name. The doc most likely generalised from the *class*
    name, which does carry the suffix (`generator.py:350-355` → `DashboardScreen`).

    Worth noting what could not have caught this: pytest asserts what the code
    does, so it agrees with the code and stays green; the shell tier never runs
    the scenario; CI has never run the docker tier. Only a scenario encoding the
    *doc's* claim fails — which is the design working.

    **FIXED.** `docs/cli/scaffold.md:197` now documents `screens/<name>.py`, and
    `c-scaffold-project.toml:104` follows it. The doc was corrected rather than
    the code because the tests, which are the only other executable statement of
    the contract, already agreed with the code.

15. **Doc-verify scenarios collide across concurrent runs.** `i-mcp` and
    `g-discovery` failed in the batch and passed alone. The batch ran beside a
    second session's `--run-slow -n auto`, so **CPU starvation and shared fixed
    paths are both live hypotheses and this run cannot separate them.** The
    shared-path one is concrete and already half-recorded as item (10):
    `h-workflow` steps 1-3 read and write `/tmp/doc-verify-h-workflow-scope`, a
    **fixed** path. Two runs overlapping between step 1 and step 2 give step 2 a
    scope id the other run already consumed — and step 1's own description is
    "a used one can never block again". That is very likely what turned
    `h-workflow` red in one shell-tier run here while three consecutive runs
    elsewhere were 7/7.

    **FIXED for the shared-path half.** `run-scenario` now creates one scratch
    directory per invocation and exports `$DOC_VERIFY_SCRATCH` and
    `$DOC_VERIFY_RUN_ID` into every step's environment, on all three engines;
    `h-workflow` and `j-dev-contrib` address it instead of fixed `/tmp` names.
    The directory is removed on a clean run and **kept, with its path printed to
    stderr, when anything failed** — a scenario that hands a value between steps
    leaves it there, and that value is the first thing wanted when the step that
    read it failed.

    Step 7 was scoped at the same time (this is item (10)): it asserted
    `stdout_not_contains = "blocked"` over the whole global `workflow list`, so
    any unrelated blocked scope failed it. It now greps for this run's scope id
    and asserts the scope has left the listing.

    Proof, same machine, same moment, only the scenario file differing — three
    concurrent runs each way:

    | Version | Result |
    |---|---|
    | `HEAD` (fixed `/tmp` path) | **3 of 3 runs FAIL** (exit 1) |
    | with scratch | **3 of 3 runs pass** (7/7 steps, exit 0) |

    **Still open: the CPU-starvation half.** The batch that produced the original
    `i-mcp` and `g-discovery` failures ran at load 25.8 on 12 cores. Those two are
    docker scenarios whose `/tmp` writes are container-internal and whose port
    9090 is never published to the host, so the shared-path fix does not touch
    them. Re-measure the tier on a quiet machine before wiring any job.

16. **Only `installation` is CI-ready today.** It passed in three separate runs
    and costs ~95s, so it fits as a second step in the existing `doc-verify`
    job — no new runner slot, and no `needs:` serialising the `test-full`
    matrix behind it. The rest of the tier waits on (15).

#### Verified clean — do not re-audit

Re-running these is wasted effort unless the code under them moves.

| Claim | Command | Result |
|---|---|---|
| No `src/` behaviour change | `git diff 73f811a --stat -- src/` | empty |
| Sabotage 4.2 (workflow seam) | direct call at `executor.py:1012` | **13 failed**, as recorded; restore clean, 185 passed |
| Sabotage 5.2/5.3 (showcase) | `Secret[str]` → `str` on `api_key` | **3 failed**, same three by name; restore clean, 33 passed |
| Matrix reaches the real seam | the above | confirmed — it is not bypassed |
| Masking tests order-independent | `pytest examples/ -q`; `pytest group_options_lab showcase -q` | 139 passed; 48 passed |
| `h-workflow` determinism | 3 consecutive runs | 7/7 steps each time |
| Import contracts | `uv run lint-imports` | 5 kept, 0 broken |
| Shell tier | CI's exact invocation | 6 passed, 0 failed, exit 0 |
| Docs build | `uv run mkdocs build --strict` | exit 0 |
| Phase 4b's "134 blocks, 16 scenarios" | `run-scenario --audit` | 134 and 16 |
| Index parity | 6 dirs in `examples/standalone/`, 6 table rows | matches |
| `7f09be4`'s cold/warm claim | `func greet` in `file_based_plugin`, twice | both exit 0, plugin announces |
| Undisclosed scope creep | `git diff 73f811a --stat` vs the union of `[F]` lists | none found |

`k-group-options` and `l-secrets` were read for vacuity and are not vacuous:
`k` asserts both must-error **messages** rather than merely a non-zero exit, and
`l` asserts the `sort_key` decoy, which is the one assertion that separates
"detection works" from "everything is masked".

#### Corrections this review owes

- It first reported the recorded 8789-passed figure as unreproducible and the
  "load-induced" explanation as not honest. **Both were wrong**, and the
  retraction is item (12): a clean re-run produced exactly 8789 passed, 0
  failed. The first run had been launched alongside `lint-imports` and a
  repo-wide `grep`.
- A first probe of the workflow seam set `config_class=None` and found nothing
  red. That proved nothing about the tests — it is item (13), a property of
  `src/`. The recorded sabotage, run afterwards, turned 13 red.

#### One process note

The `[F]`-list discipline held: no undisclosed scope creep was found, which is
unusual. The gap is that findings carried to `STATE.md` as follow-ups get fixed
in commits no task gate covers — `7f09be4` is correct, but correct by the
author's care rather than by a gate. Both files it added sit outside every
task's `[F]`, and outside the "34/34 tasks, 16/16 acceptance criteria" claim.


## Shape Intents (Specified, Not Yet Implemented)

Committed design documents with per-assertion PASS/GAP verification against the current codebase. Fully self-contained — no external files needed to start work.

| Shape intent | Scope |
|---|---|
| [`remote-config-source.md`](shape-intents/remote-config-source.md) | `RemoteSource` is defined, exported and documented with **zero construction sites in `src/`**, and the `remote_first` preset's docstring promises a chain the boot path does not build. Wire it or remove it — correcting only the docstrings is explicitly not an option. Carries the finding that the original gate passed *because of* its `--include="*.md"` scoping. |

## Open Features

Full specifications and atomized task lists for these features exist in the maintainer's working branch. Contact a maintainer to get the detailed breakdowns before starting work.

| Feature | Scope | Description |
|---------|-------|-------------|
| TUI Shell Completion Types | 5 phases | Shell mode in the inline TUI gets four upgrades: (A) type-aware tokenizer distinguishing executables (green), directories (blue), flags (dim), and pipes (boundary); (B) a coloured token highlight bar below the input; (C) a preflight mirror row showing the resolved command with description; (D) background `--help` caching for command descriptions. ~8 new files in `_cli/completions/` and `_cli/tui/`. |
| Interactive Gate Prompt | Draft | Three coordinated CLI flags for workflow gates: `--prompt-gates` (prompt inline on TTY, complete walk in one invocation), `--scope-id` (resume existing blocked scope from the CLI), and `Gate(strategy=...)` (declare preferred resolution strategy per gate, overridable by flags). Touches: `_cli/` dispatch, `_engine/`, `_workflow/`. |

## Deferred

Specified work that is not being picked up yet, and what it is waiting on.

| Item | Waiting on | Notes |
|------|-----------|-------|
| **`func watch`** | The daemon feature | Deferred by decision. Two things about this are worth knowing before it is picked up again, because both cut against the deferral as written. |

**`func watch` does not, as specified, need a daemon.** Its own proposal lists
"the daemon watcher stays external (polling fallback only)" as an explicit
*non-goal* (`matrix-watch-dryrun/proposal.md:70`), and the spec says the same
(`spec.md:43`): the scoped feature is `watchfiles` plus a debounce setting, in
the invoking process. So deferring it on a daemon either means a **different,
richer watch** than the one specified — one backed by a persistent process — or
the two were conflated. If the former, the existing spec does not describe the
feature that is wanted and needs revisiting rather than resuming.

**The daemon has no spec.** `persistent-process.md` and
`kernel-persistent-process-api.md` no longer exist anywhere in the repo. The
only surviving trace is `scrutiny-reports/standalone-distribution-2026-07-18.md`
(C5), which found `func self daemon *` to be "contingent on an undecided
proposal" and recommended marking those lines contingent — that adjudication
never happened. Until a daemon spec exists, this deferral has no unblocking
event: nothing can be observed to land.


## Dropped

Decisions recorded so they are not re-proposed. Removing an item from the plan is not
the same as removing it from the code — where a declaration surface still exists, that
is called out.

| Item | Why |
|------|-----|
| **Fix Engine Group Resolution Leak** | **The defect no longer exists.** `JobExecutionEngine.execute()` (`_engine/executor.py:140`) has no `job_group` parameter, there is no `_resolve_job_group` method anywhere in `src/`, and `executor.py` never references `job_registry`. `job_group` does not appear in `_engine/` at all — the group-options kernel work replaced it with `group_option_values`. The spec also names `execution/engine.py`, `context/runcontext.py`, `core/app.py` and `standalone/cli.py`, none of which exist; it predates the current layout. |
| **`@job(matrix=...)` expansion** | Dropped by decision, not obsolescence. It expands one job into N descriptors, which forces fan-in semantics onto the dependency graph: the ratified proposal's §D.4 has plain `Deps(deploy)` fanning in over every instance while `Deps("deploy[env=dev]")` selects one. That is a real widening of the DAG's contract for a feature nothing currently needs. |
| **Dry-run end-to-end wiring** | Dropped with the matrix work it was bundled with. The engine seam and `--dry-run`/`--explain` plumbing stay as they are (`_engine/scheduler.py`, `_cli/dispatch.py`); nothing is removed. |

### Live code surface left by the matrix decision

`@job(matrix=...)` is still **accepted and validated** and then does nothing — the worst
of the three states, because a user who writes it gets neither an error nor an
expansion. Deciding what to do about that is its own change, not covered here:

- `job/decorators.py:60` — the `matrix=` parameter on the public decorator.
- `_types/job_declaration.py:460,488-494` — the field plus validation that raises
  `ValueError` on a malformed matrix. Also serialized in `to_dict`/`from_dict`
  (`:510,527`), so removing the field needs a cache-format bump.
- `_types/naming.py:200` — `NodeKind.MATRIX`, consumed only by
  `tests/discovery/test_group_trie.py:98`. Bracket-splitting for `deploy[env=dev]`
  is documented in `contributor/architecture/group-trie.md:71`.
- `README.md:31` advertises "matrix parameterization" as a shipped `@job` capability.
  That line is currently false in effect and should go whichever way the decision lands.


## Completed

### TUI panel support for GroupOptions (2026-08-28, `feat/tui-group-options-panels`)

`shape-intents/tui-group-options-panels.md` is **implemented**. Its stale
tally — "30 (4 pass, 26 gaps)" — was wrong twice over: the real split was
12 PASS / 18 GAP, and the feature was not merely unimplemented. The TUI was
**actively broken** for any project declaring a `GroupOptions` subclass.

**One cause, nine defects.** S6b wired the mid-path resolver into the TUI's
*read* paths and left every *write-back* path parsing the bar's first token as
the job. For the canonical text `deploy --env prod web run v1.2`, that token is
the **group**. Editing a field truncated the command to `deploy`; the
pending-sync emitted a dotted spelling its own resolver refuses; group
overrides vanished; a path segment bound to the job's first positional
(`image = "web"` — silent data corruption); Ctrl+S saved a shortcut naming a
group, which is not invocable; panels were built for the group and so never
appeared; readiness was evaluated against the group node, so the bar read READY
regardless of what the job was missing; missing-args detection returned "not a
command"; and completion's argument slice under-cut by two per mid-path flag,
spilling path segments and a deeper group's flags into the job's own.

Nobody had hit any of it, because **no example project declared a
`GroupOptions` subclass** — the trie was always `None` and every defect dormant.
`examples/standalone/group_options_lab/` is the fixture that arms them, and
`tests/tui_group_options/` holds the regressions.

What shipped:

- **One emitter.** `build_command_line` (`_cli/tui/sync.py`) turns "which job,
  which values" back into a line the user could have typed, placing each group
  flag beside the segment of the group that declared it. Every producer — the
  config-table sync, the pending sync, the pre-flight header, Ctrl+S — routes
  through it, so `emit(resolve(text)) == text` holds by construction rather
  than by four implementations agreeing.
- **Two levels declaring one name.** The values dict is flat by design
  (`_engine/executor.py`), so one value means one place to write it: the
  **outermost** declaring level. `PendingExecution.group_option_paths` records
  the attribution the flat dict cannot carry, and the snapshot and diff both
  read it.
- **Group options render as the path's, not the job's.** A dimmed `[deploy]`
  prefix in the Config Table, the pre-flight and the diff; rows after the job's
  own, outermost group first; filterable by group as well as by field name.
  The Job Browser now shows `deploy web run`, and its filter takes dots,
  spaces or hyphens.
- **A group's credential masks.** `FieldDescriptor.secret` reaches a group
  option through the cache for free, and the panel `FieldDef`s carry it —
  sabotage-checked in both renderers, from the `Secret[str]` declared in the
  example rather than from a stub (`wiring-discipline.md` §8).
- **An unknown job flag stops READY.** Position is what separates a group's
  flag from the job's own, so `deploy web run --env prod` is a job flag named
  `env` and there is none. The bar says so instead of sending the user to a
  click error unannounced.
- **A seventh probe in `tests/group_options/test_surface_parity.py`.** The
  harness previously drove the TUI's *resolver*; a field's kind is decided
  again on the way to the screen, which is how two of the five recorded leaks
  got past it. The render surface now partitions like the rest.

**X.3 held throughout**: an ungrouped job renders byte-identically, verified
live against the example's `status` control at every checkpoint.

#### Scrutiny pass (2026-08-28) — eight more defects, and why the suite was green

The work above was reviewed against its own intent and its own ADR. Eight
further defects surfaced, six reproduced against a running app; all are fixed
and pinned. What is worth recording is not the list but the **four shapes** the
suite could not see, because each one recurs:

1. **A test that builds its own fixture stops tracking the builder.**
   `test_d1_editing_a_field_keeps_the_whole_command_path` hand-built a
   two-row `FieldDef` list, deliberately, to isolate D1 from D6. Once D6 was
   fixed and `build_command_panels` began emitting a *second kind* of row, the
   stub could not grow a `group_path` and the test went on passing over a shape
   the panel no longer produces. The live path — edit `[deploy] --env`, write
   the bar back — emitted the flag at the **job's** position, the walk returned
   no group value, the bar read READY, and the job ran on the unedited value.
   This is `wiring-discipline.md` §8 ("start from the real declaration, not a
   stub") applied to a field that is not a secret. The replacement,
   `TestThePanelTheBuilderActuallyProduces`, drives `build_command_panels` and
   walks **every** row it emits.

2. **A rule enforced by prose is not enforced.** ADR-009 claimed the
   `tokens[0]` grep gate made the root-cause class "mechanically detectable";
   it was a bash snippet in a guide and nothing ran it. Meanwhile the same
   branch had three more unenforced rules — one emitter, one tokenizer, every
   `FieldDef` carries its wires — and a defect behind one of them. All four are
   now `tests/tui_group_options/test_write_back_gate.py`, which caught a real
   violation within an hour of being written.

3. **A behaviour gated on a condition needs the *other* feature's tests re-run
   under that condition.** Readiness was rewritten to resolve through the trie.
   Every group-options fixture arms the trie and types a *job*; every
   pre-existing readiness test runs where the trie is `None`. Nothing typed a
   **builtin** with the trie armed — so `builtin env` greyed out in any project
   declaring a `GroupOptions` subclass, and `action_execute` (gated on READY)
   made Enter a silent no-op. The X.3 control proves an ungrouped *job* is
   unaffected and says nothing about a builtin.
   `TestBothSidesOfTheTrieGate` parametrises over both sides.

4. **A one-off manual audit produces no artifact.** Two assertions were closed
   by reading rather than by testing, and both were wrong for a shape the
   reader did not have in front of them:
   - "which flags does this job accept?" was compared by hand against `--help`
     for the jobs that happened to exist, so a **positional** (a click
     `Argument`, no flag spelling) and a **bool with a short flag** (no `--no-`
     half) both slipped through. `TestReadinessAgreesWithClick` now derives the
     answer from `build_click_params_from_fields` itself, over a fixture
     carrying every shape the builder branches on.
   - `CF.1–3` was discharged "by audit only" and was right for one level of
     grouping and wrong for two.

   The same shape covers the two remaining defects: the fixed point was tested
   over a hand-written table of four whitespace-free lines (the emitters quote,
   every reader called `.split()`, and a value with a space resolved to *no
   job*), and "CLI parity" was six probes over one CLI — so nobody noticed that
   an app's **own** entry point answered `No such option '--env'` while `func`
   ran the same line. `tests/group_options/test_adapter_entry_point_parity.py`
   is the seventh CLI probe.

Recorded as ADR-009 decisions 9–11 and amendments to decisions 1 and 7.

**Known gap, left deliberately**: `get_missing_required_args`
(`_cli/tui/missing_args.py`) was fixed and still has **no production call
path**. Kept rather than deleted — see *Potential Follow-ups* item 8 for what
it would take to wire it up.


### Secrets and config unification (2026-08-27, `feat/secrets-and-config`)

ADR-007 and ADR-008 are **accepted and implemented**. A scrutiny pass executed
every claim in both drafts against a running process rather than against the
source, and found that both described a system less wired than they assumed —
17 verified defects, recorded with reproduction commands in
ADR-007 and ADR-008 (see ADR-008's Addendum for what the implementation and
its review amended).

What shipped:

- **One resolver, where one resolver is possible.** Four independent
  implementations of "what value will this field have?" disagreed about values,
  not just formatting. `ResolvedField` / `resolve_job_fields` in
  `_config/resolved_field.py` is the single answer for `info --job` and
  `func builtin env`. The **TUI panels deliberately do not read it**: the seam
  needs a live Pydantic class, so reaching it would import the job module on
  every panel refresh and forfeit true-lazy boot. They share the *detector*
  instead — `secret`/`required`/`default` carried through the discovery cache —
  and read values from the same `ResolutionChain`. See ADR-008 Addendum A1; the
  residual risk is cache drift, guarded by
  `tests/config/test_descriptor_cache_fidelity.py`.
- **One env spelling.** `JOB__FIELD` and a bare, unprefixed `FIELD` are deleted;
  `JOB_FIELD` is the only form. Group options keep `SCOPE__FIELD`, which is a
  different feature with a real disambiguation reason.
- **One secret detector, one mask predicate.** `is_secret_field` decides
  secretness and `display_value` decides rendering, on all five sinks. A
  name-based regex is gone.
- **`Secret[str]` is usable as a config field type** — pydantic core and JSON
  schema, so the declaration marker and the value wrapper are one mechanism.
- **TOML alone by default**, with `func builtin config migrate` and a
  plugin-based escape hatch that is tested end-to-end.

Four pieces of **dead wiring** surfaced, which is the recurring theme:
`preflight_widget.py` had no mount points (deleted), `_collect_job_secrets`
always returned an empty set, `migrate_ini_to_toml` had no callers (the module
is now deleted — see below), and ADR-007's own documented escape hatch did not
work. Guarded now by `tests/config/test_secret_surface_parity.py`, which fails
if any surface drifts from the others.

Not done, and deliberately: `[secrets]` (withdrawn), `--template` (unnecessary —
the default `builtin env` output *is* the skeleton), and `func builtin config
migrate` (built during implementation, then **removed** — a conversion command
exists to carry a user population across a break, and pre-1.0 there is none to
carry, so it was `migrate_ini_to_toml`-with-no-callers one level up. The
warning on an unreadable config file names conversion and the plugin escape
hatch instead, and `tests/config/test_legacy_ini_project.py` proves following
it works).

## Potential Follow-ups

Items identified during development that are worth doing but not yet designed:

1. **Autocomplete placeholder crashes instead of degrading** — a missing `textual-autocomplete` optional dep takes out every Pilot test instead of silently skipping. Fix: make the fallback a real Widget or skip it in `compose()`.
2. **Preset awareness in Config Files panel** — the panel assumes a classic config chain with file sources. If the app uses `env_only()` or `twelve_factor()`, the panel shows an empty file list. Fix: read the active preset and hide/adapt the panel.
3. **Settings with no consumers** — `execution_mode`, `history_retention`, `completion_debounce_ms`, `signature_enabled`, `show_session_stamp`, `default_override_target` all resolve truthfully in the Settings panel but nothing reads them yet. Wire each to its consumer one at a time. (`sensitive_keywords` was on this list and has been **removed** rather than wired — see *Completed* below; masking follows the model, never a name.)
4. **Shell completion model unification** — SmartBar completion and `func builtin shell-init` both consume the same trie and descriptors but compute their partition independently. A shared model (`_cli/completions/shared.py`) would prevent the two from drifting.
5. **`builtin parallel` items missing from history** — parallel batch items run at invoke depth 1 and the history filter only records depth 0. Explicit recording in `parallel` itself would fix this.
6. **`RunContext.log()` bypasses the injected `Log`** — **resolved** (`fix/runcontext-log-di`). `RunContext` now holds the live per-invocation capability map (the `TTY` pattern) and `log()` takes its sink from it, so `rc.log(...)` and a `log: Log` parameter are the same instance. The DI registry is deliberately not consulted — the engine skips it for `Log` too, so reading it would make the two disagree. A job with no `Log` falls back to the `functualize.job.<name>` logger, unchanged. Level validation moved into `log()` (and `CapturingLog`) so an invalid level fails identically on both paths.
7. **~~The slow test tier is red~~ — DONE (2026-08-19, branch `fix/run-slow-tests`).**
   82 failures / 14m36s → green on both Hypothesis profiles (`default` 5m11s, `ci` 9m33s;
   8,407 tests at `-n 10`). All five CI gates verified. The tier found **two real product
   bugs shipped in 0.1.0**, both now fixed:
   - `NamespaceTransform` canonicalized the prefix when *writing* names but matched the raw
     spelling when *reading*, so every namespaced job was unreachable by its only published
     name (`8922756`).
   - Multi-word `JOB_GROUP` failed registration — `qualified_name` validates its group as a
     Python identifier *by design*, so it must see the raw group, but `registry.py` and
     `sync.py` normalized first. `JOB_GROUP = "data_ops"`, this project's own documented
     example, raised `ValueError`. Single-word groups worked, which is why the fixtures
     missed it (`584d04c`).

   Two claims in the original write-up of this item were **wrong** and are corrected here:
   - *"`--run-slow` is not in the release checklist's gates."* It was — gate 6 in
     `.agents/skills/release/SKILL.md` since v0.1.0. The gate existed and still failed,
     for two reasons now fixed: it ran the `default` profile rather than CI's `ci`, and
     with no `-n auto` it could never finish inside the skill's own 300s per-command
     timeout, so it reported BLOCKING on every release and was waived by habit.
   - *"Canonical-identity … may be a product question."* It is not. `normalize_segment`
     strips trailing hyphens deliberately; the tests encoded the pre-normalization world
     and were wrong, the policy was not.

   Lesson worth keeping: **green at `default` is not green at `ci`.** The `ci` profile
   draws 200 examples to `default`'s 100 and found two further failures after the tier had
   already been called green. Verify with `HYPOTHESIS_PROFILE=ci`, never bare `--run-slow`.

   **Carried forward, not done by this work:** the `entry_points()` caching it measured
   (#9), the load-sensitive `test_blocking_worker` assertion it identified (#10), and the
   question of gating `release.yml` on CI (#11). A further ~47 `@given` tests still draw
   only from finite strategies (`sampled_from`/`booleans`/`just`/`none`) and could become
   exhaustive `parametrize` — but that is a search hint, not a work item: the same pass
   established that static counts misclassify property tests in both directions, so never
   bulk-convert on one.

8. **`skip-existing` masks trusted-publisher misconfiguration** — `release.yml` passes
   `skip-existing: true` to `pypa/gh-action-pypi-publish`, which makes twine call
   `Repository.package_is_uploaded()` *before* attempting the upload
   (`twine/commands/upload.py:193`, then `continue`). That check is client-side — it
   reads PyPI's JSON API — so when a version is already on the index **no POST is made
   and no authorization happens**. A green publish job therefore proves only that the
   OIDC mint succeeded, i.e. that *at least one* of the twelve projects trusts
   `(raicing-ai, functualize, release.yml, pypi)`. It proves nothing about the other
   eleven individually.

   This was confirmed empirically during the 0.1.0 release: a `workflow_dispatch` run
   skipped all 24 artifacts, and the log timings show why — the 12 wheels are spaced
   ~40 ms apart (one JSON fetch per project) while all 12 sdists are skipped within
   6 ms of each other, served from twine's `_releases_json_data` cache.

   Consequence: 0.1.0 published its twelve projects by one-time token upload, so its
   own tag run verified nothing. **0.1.1 is the first release that genuinely exercises
   trusted publishing on all twelve**, because it posts files that do not yet exist —
   a project with a missing or wrong publisher will fail there with a 403, not a 400.
   Expect that as a plausible 0.1.1 release failure and check the publishing settings
   first if it happens.

   To verify ahead of a release without spending a version, run twine once per package
   *without* `--skip-existing` and read the status: `400 already exists` means the
   publisher works, `403` means it is missing.

9. **`FunctualizeApp()` calls `entry_points()` seven times** — **RESOLVED**
   (`perf/slow-tier-followups`). Once per entry-point
   group (`plugins`, `domains`, `ai_providers`, `state_providers`, `tasks_providers`,
   `format_providers`, `remote_providers`), and each call rescans every installed
   distribution from disk. Measured over 16 interleaved runs against master on a
   215-distribution environment: median construction **111.9 ms -> 73.3 ms, a 34%
   reduction** (an earlier single instrumented run suggested 60%, but the
   instrumentation inflated the per-call timings; the paired figure is the real
   one). The call sites are
   `_config/registry.py:169,193`, `_plugins/loader.py:326`,
   `_plugins/domain_registry.py:155,245`, `_discovery/providers.py:775`, and
   `_cli/tui/display_provider_discovery.py:79`; none is cached. One scan feeding all
   seven group lookups is the obvious fix. Left alone so far because this is the boot
   hot path and every surface pays it, so it needed its own verification pass rather
   than a drive-by patch. That pass is done: the seven now share one snapshot taken on
   first use, in `_primitives/entry_points.py`.

   The verification that mattered was ordering, since the snapshot is a real behaviour
   change — the stdlib does see a distribution added to `sys.path` mid-process, so a
   later lookup used to pick one up and now would not. Nothing mutates `sys.path`
   inside the 68 ms window the seven lookups span; `--import-lib` paths are applied at
   `_cli/main.py:268`, explicitly *before* app construction; the `_discovery`
   insertions add job-module directories, which do not carry `.dist-info`; and the one
   plugin hit for `sys.path` is inside a `-c` string for a child process. The TUI
   display-provider lookup keeps the stdlib call (it is off the boot path, and `_cli`
   may not import `_primitives`), so it always reads fresh.

10. **`test_blocking_worker` asserts an absolute tick count against wall clock** —
    **RESOLVED** (`perf/slow-tier-followups`).
    `tests/tui_audit/test_blocking_worker.py::test_thread_worker_keeps_event_loop_responsive`
    required `ticks_during_work >= 3` with `BLOCK_SECONDS = 0.4` and
    `TICK_INTERVAL = 0.05`, so the ceiling is ~8 ticks and the margin is thin. It is the
    same class as Hypothesis's `deadline` and the stale `test_config_resolution_budget`
    threshold: **the assertion times the machine, not the code**, and CI runs ~2.5x slower
    than a workstation. Lowering the threshold trades one arbitrary number for another —
    the fix is a *relative* assertion (thread worker vs. the async-blocking control in the
    same file), which is what the test actually means to prove. Untouched since v0.1.0.

    Turned out to be wider than written here: `RESPONSIVE_THRESHOLD = 3` was in **three**
    modules across five assertion sites, not the one test named. `tests/_responsiveness.py`
    now measures the same loop idle, immediately before the real measurement, and requires
    a third of that ceiling. Checked that it still discriminates rather than merely passing:
    the pre-fix pattern scores 0 ticks against an idle ceiling of 8 and a floor of 2. Only
    the `>=` assertions changed — an upper bound is already safe under load, because load
    pushes the count further into passing.

11. **`release.yml` does not require CI green on the tagged commit** —
    **RESOLVED** (`perf/slow-tier-followups`). The job graph was
    `build -> publish -> github-release` with no `workflow_run` or check-suite dependency,
    so a tag pushed at a red commit published to PyPI regardless. Deferred once
    deliberately; revisited because the `v0.1.0` tag turned out to sit at
    `cb94db5`, two commits *after* the source that was actually published on 2026-08-06
    (both CI-only, so nothing shipped wrong — but the tag does not mark the release, and
    it is immutable under the `release tags` ruleset). Two separable changes: gate the
    publish on CI, and tag before publishing rather than after. See also #8, which covers
    the `skip-existing` half of this workflow's problems — still open.

    A `verify-ci` job now finds the run the tagged commit got when it landed on master
    (`ci.yml` never runs on tags) and refuses to publish unless it concluded successfully.
    No run at all fails immediately, an all-completed-without-success set fails immediately
    rather than waiting out the timeout, and an in-flight run is waited on for up to 45
    minutes. CONTRIBUTING carries the two consequences a releaser needs before tagging.

12. **A job module with a `SyntaxError` vanishes silently.** No warning, no
    diagnostic, exit 0 — the job simply is not listed. Cost ~20 minutes on a
    test fixture during the secrets work, and would cost a user far more, since
    they have no reason to suspect the file was even considered. Discovery
    should report a module it failed to parse.

13. **A second, unreachable "what's missing?" implementation** —
    `get_missing_required_args` (`_cli/tui/missing_args.py`) answers "which required
    arguments has the user not supplied yet?" and **nothing calls it**. Its only
    references in `src/` are the import and `__all__` entry in `_cli/tui/__init__.py`;
    its only callers are two test modules. The live answer comes from
    `SmartBar.evaluate` (`_cli/tui/bar.py`), a separate implementation that walks the
    tokens itself.

    Kept rather than deleted (maintainer decision, 2026-08-28), because it returns
    strictly more than `evaluate` does: field **descriptors**, not just names. That is
    enough to render "Missing: `image` (str) — Image tag to deploy" where the bar today
    can only say "Missing: image". Wiring it up is that feature, not a cleanup.

    Both were repaired during the GroupOptions panel work (2026-08-28) — each matched
    the bar's first token against the job list, which under a group is the *group*, so
    `missing_args` returned "not a command" for every grouped job. The two agree today;
    the standing cost is that a reader must work out which one runs.

    To wire it: give `evaluate` the result instead of recomputing it, and delete the
    duplicated token walk — they must not both survive, or they will drift. Note it is
    `async` and `evaluate` is not, so the call has to move to where the app already
    awaits (`on_input_changed`), with the result passed in. One more cost found in the
    2026-08-28 scrutiny pass: its repair calls `build_group_option_trie` on every
    invocation, unmemoized, where the app holds a cached property — harmless while it
    is dead, and a per-keystroke cache read the moment it is not.

14. **`omit_defaults` is API surface ahead of a caller** — `build_command_line`'s
    keyword is specified, documented (ADR-009 decision 3) and tested, and nothing
    passes it `True`. Either find the caller it was designed for — a snapshot restore
    handing the emitter fully *resolved* values, where every field is present and most
    are defaults nobody chose — or delete it. It is cheap to keep and cheap to remove;
    what it must not do is sit unexplained.

15. **The shell has no round-trip fuzz** — the fixed point `emit(resolve(text)) == text`
    is asserted over a hand-written table plus a handful of value shapes. Both defects
    the 2026-08-28 pass found on that property were *outside* the table (a group row
    edited in the panel; a value containing a space). A generator over
    {path depth} × {which levels declare flags} × {value shapes: empty, spaces, quotes,
    leading dash, unicode} would have found both without anyone having to think of them.
    The example project and `collision_tui` already supply the project shapes; what is
    missing is the value axis.

16. **`remote_first()` is a public preset that resolves nothing remotely.** The
    preset is exported, documented and unit-tested, and the boot wiring behind it
    does not exist. `remote_first()` returns `config_resolution_chain=None`, which
    `app/config.py:74-77` documents as boot building the *classic* chain — so it is
    `classic()` with a different file pattern and `dotenv=False`. A reader choosing
    it for Vault or AWS Secrets Manager gets local file and environment resolution,
    silently.

    **Built and unit-tested**: `RemoteSource` (`_config/sources.py:246`),
    `ProviderRegistry.register_remote_provider` / `get_remote_provider` /
    `list_remote_providers` (`_config/registry.py:69,117,147`), the
    `functualize.remote_providers` entry-point group (`:193`), and
    `manifest.parse_annotation` for `provider://reference` (`_config/manifest.py:37`).

    **Missing**: the boot wiring, and only that. `boot.py` constructs no
    `RemoteSource` — `grep -c remote src/functualize/_app/boot.py` returns **0** — and
    `manifest.parse_annotation` has **zero production callers** (the `parse_annotation`
    hits in `src/` are the unrelated `_cli/annotation_utils` function of the same name).

    **The decision to make**: deprecate and remove the preset, or wire it. Either needs
    an ADR, because it is public API surface (`app/__init__.py:29,57`, and
    `tests/test_public_api_surface.py:49` pins it).

    **Why it went unnoticed**: `test_app_presets_properties.py:124` asserts that
    `remote_first()` returns `config_resolution_chain=None` — it tests the stub, and it
    tests it faithfully. Shipped, unit-tested, unreachable; the failure class
    `AGENTS.md:82` names. The docs that promised remote resolution have been corrected
    to say it is not wired, so no user-facing claim now depends on this decision.

    Related to follow-up **2** above: that one is about presets the Config Files panel
    cannot see, this one about a preset that does not do what it says. Both would be
    touched by any work that makes presets legible at runtime.

17. **`rc.invoke` cannot pass group options; `app.execute` can.** Surfaced by the
    `docs-example-parity` combination matrix. The engine's
    `execute(..., group_option_values=...)` is the documented channel for "a surface
    passing on the flags it parsed" (`app/core.py:592-598` names two fillers, the CLI
    and MCP). `app.execute` exposes it. `RunContext.invoke`
    (`_engine/capabilities/runcontext.py:365-374`) and both `Invoke.__call__`
    overloads (`_engine/capabilities/invoke.py:84,282`) do not — their `**kwargs` go
    to the job function's own parameters — so a job invoking a grouped job cannot set
    its group options at all.

    There is **no workaround through the override layer**: group options resolve
    against a view built fresh for the group path (`executor.py:2065`,
    `self._make_config_view(group_path)`), while `rc.config.set()` writes to the
    *job's* view. The only two channels are the group's config section and its
    environment variable.

    **The work is small; the surface is the question.** Threading one keyword through
    four call sites (`runcontext.py:365` and its pass-through at `:374`, both
    `Invoke.__call__`s, and the `self._engine.execute(...)` calls at `invoke.py:399`
    and `:593`) is mechanical. But `Invoke` is a public capability exported from
    `functualize.job` with a shipped double (`testing/doubles.py:71`, `MockInvoke`),
    so widening it changes a published protocol — which is what needs the ADR.

    **Why it is not simply a bug to leave closed**: the boundary that *should* exist
    is against implicit inheritance — a flag typed at `deploy.web` silently steering
    a job under `deploy.worker`. An explicit `group_option_values=` argument is the
    caller naming values deliberately, the same thing `app.execute` already permits,
    so the design reason for the boundary does not argue against it. The concrete
    gap: a job deploying to staging and then production cannot invoke one grouped job
    twice with different `env` without mutating `os.environ` mid-run.

    The boundary as it stands is pinned by
    `tests/group_options/test_combination_matrix.py` and stated in
    `docs/guides/group-options.md`, so the documentation is correct either way — this
    is a capability decision, not a drift fix.

18. **`exclude_patterns` cannot reach any scan root but the first.** Surfaced while
    giving `examples/plugins/file_based_plugin` the config file its README assumed.
    The setting is documented as "exclude files matching glob patterns before any
    other filter runs" (`docs/cli/discovery.md:101-114`), with the qualifier that
    patterns match "the file's path relative to the scanned directory" — singular,
    and that is the bug: there is more than one scanned directory, and the filter
    only ever knows about one of them.

    `boot.py:469` picks `base_dir = Path(app._jobs_directories[0])` and hands it to
    `build_pre_filter_from_config`. `GlobExcludePreFilter.should_import` then
    relativizes each candidate against that single directory and, for anything
    outside it, returns `True` — "File is not under base_dir — cannot match, allow
    through" (`_primitives/pre_filter.py:474-478`). Meanwhile the CLI boots the app
    over *every* scan root and appends the CWD unconditionally
    (`_cli/main.py:476-484`, `:1174-1177`, `:1292`), so a project with
    `jobs_directories = ["jobs"]` scans both `jobs/` and the root while the filter
    can only see `jobs/`.

    **Concretely**: `exclude_patterns = ["**/test_*.py"]` — the exact line
    `docs/cli/config.md:53` and `docs/cli/discovery.md:108` both print as the
    canonical example — silently fails to exclude a `test_*.py` at the project root.
    That is where the pattern is most obviously aimed, and where it does nothing.
    Observed, not inferred: adding it to that example changed no listing.

    **Why it went unnoticed**: `tests/test_pre_filter.py:436`,
    `test_file_outside_base_dir_allowed`, pins the allow-through as deliberate — and
    at the primitive level it is correct, because a filter that cannot relativize a
    path has nothing to match. The defect is one layer up, in choosing a single
    `base_dir` for a scan that spans several roots. Every test of the primitive
    passes and will keep passing after a fix.

    **The decision to make**: whether the filter is per-scan-root (build one
    `GlobExcludePreFilter` per directory, each with its own `base_dir`) or
    anchor-relative (one filter based at `discovery_result.anchor`, so patterns read
    against the project root the way a `.gitignore` does). The second matches what a
    reader writing `**/test_*.py` already assumes and keeps one filter instance; the
    first is closer to the current structure. Either way `docs/cli/discovery.md`'s
    "relative to the scanned directory" needs to become true rather than
    approximately true.

    No user-facing claim is currently *wrong* in a way that misleads about behaviour
    the docs promise elsewhere, so this is a defect to schedule, not a drift fix to
    rush. But it is the failure class `AGENTS.md:82` names: shipped, unit-tested,
    and unreachable on the path that matters.

## Recently Completed (2026-07)

| Feature | Description |
|---------|-------------|
| Shell and task runner | Stdout capability, builtin parallel/history/env/shell-init, group options kernel + TUI navigation, PEP 723 scripts, interactive prompting |
| CLI/Shell convergence | CLI namespace consolidation, shell mode, dynamic input bar |
| TUI source-chain detail | Config Files detail view, Settings panel, TOML edit/save |
| TUI app decomposition | Extracted 2393-line `app.py` business logic into focused modules |
| CLI config discovery consolidation | Unified config discovery, fixed XDG resolution bug |
| Release hardening | Mode D arg fix, dead code removal, interactivity plugin protocol |

## Contribution Entry Points

Good first issues for new contributors (ordered by complexity):

1. **Follow-up #2 (Preset awareness)** — small, self-contained TUI change in one panel (`panels/config_files.py`)
2. **Follow-up #3 (Settings consumers)** — wire resolved settings to their actual behavior, one setting per PR
3. **Follow-up #12 (SyntaxError vanishes silently)** — one diagnostic in discovery; the failure mode is easy to reproduce and the fix is contained
4. **Follow-up #14 (`omit_defaults` has no caller)** — small and self-contained; the parameter is specified and tested but nothing passes it

See `CONSTITUTION.md` for quality gates that apply to all changes.
