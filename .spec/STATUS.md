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

### Ship-blocking — landed, but the cut is **HELD**

Items 1-6 and 9 are landed on `release/0.1.1`; item 7 is deferred to
[`shape-intents/remote-config-source.md`](shape-intents/remote-config-source.md);
item 8 was already fixed. The decision and its reasoning are in
[ADR-010](../contributor/adr/010-discovery-cache-filter-awareness.md).

**Both tranches have landed. 0.1.1 is ready to tag.** An adversarial review of
`c1b6c26..c9d47e4` confirmed the headline fix — X1-X4 are closed, reproduced
against `c1b6c26`, full suite 8820 passed / 9 skipped — and found nine things,
three of which are behavioural defects the fix left open or introduced. Work is
split across two feature directories:

- [`features/0-1-1-review-followups/`](features/0-1-1-review-followups/) —
  **Tranche A**, docs / dead code / disclosure. No behaviour change.
- [`features/discovery-fingerprint-completeness/`](features/discovery-fingerprint-completeness/)
  — **Tranche B**, the three behavioural defects. Blocks the tag.

| F | Finding | Verdict | Where |
|---|---|---|---|
| F1 | `jobs_directories[0]` (`base_dir`) decides what `exclude_patterns` matches and is **not fingerprinted** — two orders give mirror-image correct contents under an identical digest, so the warm transition serves the stale one | confirmed, **blocks tag** | Tranche B / B1 |
| F2 | `cache rebuild` unlinks the file then builds a bare provider, so it writes `discovery_hash: null` and the next command discards its work with a WARNING — in every project. New at HEAD | confirmed, **blocks tag** | Tranche B / B2 |
| F3 | `find_functualize_dir` walks upward, so a child writes into the **parent's** cache file and the parent invalidates on every boot forever. Warning new at HEAD; the mutual clobbering pre-dates it | confirmed, **blocks tag** | Tranche B / B3 |
| F4 | The `None`-fingerprint *adoption* branch is dead code — full suite byte-identical without it, and its one would-be caller deletes the file before reading | confirmed | Tranche A / A1 |
| F5 | Two example READMEs still publish the retracted `cache clear` workaround (`discovery_lab`, `config_lab`) | confirmed | Tranche A / A3, A4 |
| F6 | `TestPreBootRoutingReadHonoursTheFingerprint` names wiring `b5f918e` removed, and claims bare `func` renders without booting — it boots | confirmed | Tranche A / A2 |
| F7 | `docs/cli/discovery.md` (`c9d47e4`) was outside every `[F]` list in `release-0-1-1-blockers/tasks.md` — the one undisclosed scope slip, and where the incomplete doc sweep lived | confirmed, disclosed here | — |
| F8 | `discovery_lab` step 6 names a decorator (`job_metadata`) that exists nowhere in the example; the real one is `@job`. Broken at `c1b6c26` too | confirmed | Tranche A / A3 |
| F9 | `docs/cli/discovery.md:114` documents matching "relative to the scanned directory"; the code matches relative to `jobs_directories[0]` | confirmed | Tranche B / B1 |
| F10 | `test_get_plugin_raises_key_error_for_unregistered` assumed only against the names *it* registered, so Hypothesis could propose an auto-registered entry-point plugin (`mcp`) as "unregistered" and the lookup rightly did not raise. Latent since before this branch; surfaced by a full-suite run and then persisted in `.hypothesis/`, so it would have failed CI deterministically | confirmed, fixed | Tranche A |
| F11 | `tests/test_packaging.py` hardcoded `0.1.0` in two assertions, so the version had a **fourteenth** declaration site that no release checklist named — bumping the documented thirteen and running the suite landed red. Now derives the expected value from `pyproject.toml` | confirmed, fixed | Tranche A |

Two review claims did **not** survive testing, and are recorded so they are not
re-litigated:

- **No non-booting surface serves stale names.** Every surface swept against a
  poisoned cache — `--help`, `builtin info`, `cache show`, `cache check`,
  `shell-init`, `mcp`, `mcp tools`, `func <job>`, `func <group>`,
  `func <group> <job>`, bare `func`, standalone and declared-project — served the
  correct listing and repaired the cache, asserting on **stdout only**. Every
  `func builtin` command boots a full app in the `cli_app` callback. `b5f918e`'s
  revert was right.
- **The `None`-*skip* guard is load-bearing**, unlike the adoption branch beside
  it: forcing `None` to compare makes
  `test_cache_show_leaves_a_matching_cache_byte_identical` fail. The mid-execution
  re-scope from "filtered cache" to "matching cache" was the correct call.

#### Final gates (2026-08-29, both tranches landed)

| Gate | Result |
|---|---|
| Full suite `HYPOTHESIS_PROFILE=ci --run-slow -n auto` | **8832 passed, 9 skipped, 0 failed** (baseline 8820 + 12 new) |
| `pytest examples/` | 139 passed |
| All 11 plugin suites | 245 passed |
| `ruff check` (src, tests, examples, plugins) + `format --check` | clean, 1096 files |
| `mypy src/` | 0 errors, 295 files |
| `lint-imports` | 5 kept, 0 broken |
| doc-verify shell tier | 7 passed, 0 failed, 10 skipped (docker/pty, as CI) |
| clean-clone CI job, simulated end to end at HEAD | both example commands PASS |
| Review repros X1-X4, F1, F2, F3 | all produce the correct answer |
| Version | 13/13 sites at `0.1.1`; `func --version` -> `functualize 0.1.1` |

**Not tagged.** The tag is pushed after this lands on `master` and CI is green on
the merge commit: `verify-ci` looks for the run that commit got when it landed,
and `ci.yml` never runs on tags.

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

7. **CLOSED (2026-09-06) — the shape intent was resolved the "wire it" way.**
   See follow-up **16** below and ADR-016. Both docstrings this entry names are
   corrected: `presets.py` states the real chain, and
   `_cli/tui/panels/config_table.py:50` said `CLI -> Env -> File -> Remote ->
   Default`, which was never the order and is now `CLI -> Env -> File ->
   Default` with the vault noted between CLI and Env. Re-running the gate
   **without** `--include="*.md"` is what found the second one. The deferral
   and the finding as originally written follow, unchanged.

   **DEFERRED to a shape intent (2026-08-29).** Taken out of the 0.1.1 cut by
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
| [`remote-config-source.md`](shape-intents/remote-config-source.md) — **RESOLVED 2026-09-06, wired; see ADR-016** | `RemoteSource` is defined, exported and documented with **zero construction sites in `src/`**, and the `remote_first` preset's docstring promises a chain the boot path does not build. Wire it or remove it — correcting only the docstrings is explicitly not an option. Carries the finding that the original gate passed *because of* its `--include="*.md"` scoping. |
| [`eager-boot-uses-the-provider-it-builds.md`](shape-intents/eager-boot-uses-the-provider-it-builds.md) — **RESOLVED 2026-09-08 by `eager-boot-provider`** | `JobSources(lazy=False)` registers jobs through a second directory scanner instead of the filtered provider `boot_standard` already built and added to the pipeline. Four defects follow: every job module **imported twice** whenever a second provider exists (measured 2 modules → 4 imports, and a regression introduced by wiring `JobSources.functions`), `_registered_commands` keyed by the Python name so `refresh()` leaves phantom entries, discovery filters ignored, and filters half-applied. None reachable from `func`. Read STATUS #32 first — its fix unblocks this one. |
| [`workflow-run-parameters.md`](shape-intents/workflow-run-parameters.md) | **The silent-drop half shipped 2026-09-03** (`feat/workflow-run-params`): a `@workflow` job now refuses a launch argument its signature cannot accept before the graph walks, so the approval is no longer spent on a run that was never going to succeed. **What remains is the run-scoped parameter layer**, and it is a correctness defect on its own: no per-run channel exists, so a value set for a walk does **not survive a gate** — re-measured 2026-09-08, `LAB__STRICT=true` walks to the gate with `strict=True` and the resume in a shell without it runs `check.signoff`, the step whose whole purpose is to apply strict mode, with `strict=False`. One `scope_id`, two answers, selected by the resuming shell. The three trigger plugins can parameterize a single job and not a walk. Implement a run-scoped layer or declare walks unparameterizable and enforce it. |

## Open Features

Full specifications and atomized task lists for these features exist in the maintainer's working branch. Contact a maintainer to get the detailed breakdowns before starting work.

| Feature | Scope | Description |
|---------|-------|-------------|
| TUI Shell Completion Types | 5 phases | Shell mode in the inline TUI gets four upgrades: (A) type-aware tokenizer distinguishing executables (green), directories (blue), flags (dim), and pipes (boundary); (B) a coloured token highlight bar below the input; (C) a preflight mirror row showing the resolved command with description; (D) background `--help` caching for command descriptions. ~8 new files in `_cli/completions/` and `_cli/tui/`. |
| Interactive Gate Prompt | Draft | Three coordinated CLI flags for workflow gates: `--prompt-gates` (prompt inline on TTY, complete walk in one invocation), `--scope-id` (resume existing blocked scope from the CLI), and `Gate(strategy=...)` (declare preferred resolution strategy per gate, overridable by flags). Touches: `_cli/` dispatch, `_engine/`, `_workflow/`. |

## Deferred

Specified work that is not being picked up yet, and what it is waiting on.

### #40 · Aliases resolve on `func` and not on an app's own entry point

Found by `surface-request-parity`/T6, whose brief says a row of the surface
matrix that resists being expressed as a test is **recorded, not dropped**. This
is the one row that resisted and was not already declared deliberate somewhere.

```
# .functualize.toml
[aliases]
g = "greet"

$ func g                 # GREETED
$ python main.py g       # Error: Unknown command 'g'.  Did you mean: greet
```

**Why.** Aliases are resolved in `_cli/dispatch.detect_mode`, the bare CLI's
*pre-boot* routing: it reads `[aliases]` from the merged config and rewrites the
first positional before anything is built. An embedded `main.py` never runs that
routing — click resolves its own command tree — so the alias is an unknown
command with a suggestion.

**Why this is a finding rather than a boundary.** The neighbouring divergence
(row 15, `--exclude` and `[discovery]`) *is* deliberate and says so in two
places: `test_cache_filter_awareness.py` records it, and reading a project file
behind an app author's back would override what they wrote in code. Aliases have
no such argument — a short name for a job is a convenience the app author
configured in the same file, and nothing in the code or in
`docs/cli/aliases.md` states that it stops at `func`. It reads as an accident of
where the resolution happens.

**Not fixed here.** Closing it means either teaching `CliAdapter` to read
`[aliases]` and register the fallbacks, or moving alias resolution to something
both doors run — the second is the `RunRequest`-shaped answer and is bigger than
this feature. Either way it is a behaviour change on the app surface that nobody
has asked for, and `surface-request-parity` is scoped to *request* parity.

Today's behaviour is pinned by
`test_surface_feature_matrix.py::TestRowsThatNeededTheirOwnDoor::test_an_alias_is_not_resolved_on_an_apps_own_entry_point`,
so closing the gap fails that test and points back here — which is how a
recorded gap should be retired.

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

The 2026-08-27 revision of that document resolved its half by **removing** the
`func self daemon *` subcommands rather than carrying them as contingent lines,
and the work shipped without them (see Completed, and
[ADR-015](../contributor/adr/015-standalone-distribution-and-self-management.md)).
So standalone distribution never depended on a daemon, and its shipping did not
unblock `func watch` either.


## Dropped

Decisions recorded so they are not re-proposed. Removing an item from the plan is not
the same as removing it from the code — where a declaration surface still exists, that
is called out.

| Item | Why |
|------|-----|
| **Fix Engine Group Resolution Leak** | **The defect no longer exists.** `JobExecutionEngine.execute()` (`_engine/executor.py:140`) has no `job_group` parameter, there is no `_resolve_job_group` method anywhere in `src/`, and `executor.py` never references `job_registry`. `job_group` does not appear in `_engine/` at all — the group-options kernel work replaced it with `group_option_values`. The spec also names `execution/engine.py`, `context/runcontext.py`, `core/app.py` and `standalone/cli.py`, none of which exist; it predates the current layout. |
| **`@job(matrix=...)` expansion** | Dropped by decision, not obsolescence. It expands one job into N descriptors, which forces fan-in semantics onto the dependency graph: the ratified proposal's §D.4 has plain `Deps(deploy)` fanning in over every instance while `Deps("deploy[env=dev]")` selects one. That is a real widening of the DAG's contract for a feature nothing currently needs. |
| **Dry-run end-to-end wiring** | Dropped with the matrix work it was bundled with. The engine seam and `--dry-run`/`--explain` plumbing stay as they are (`_engine/scheduler.py`, `_cli/dispatch.py`); nothing is removed. |

### Live code surface left by the matrix decision — REMOVED

Resolved on `fix/pipeline-readiness`. The surface described here — the `matrix=`
parameter, the `JobDeclaration` field and its validation, both serializer keys,
and `NodeKind.MATRIX` — is gone, and `@job(matrix=...)` now raises `TypeError`.
`CACHE_VERSION` went 17 → 18 because `from_dict` reads keys by name, so an
unbumped cache would have raised `KeyError` rather than degrading. `README.md`
no longer advertises matrix parameterization.

The **decision** above is unchanged: matrix expansion stays dropped. What was
removed is the declaration surface it left behind, which was accepted and
validated and read by nothing — the worst of the three states, because a user
who wrote it got neither an error nor an expansion.

## Completed

### Discovery correctness and job parameter types (2026-09-08, `feat/discovery-and-parameter-fixes`)

Five features, one branch. The `.spec/features/` artifacts are cleared; the
durable half is here and in
[ADR-018](../contributor/adr/018-unsatisfiable-jobs-are-reported-not-fatal.md).

Closes **#30**, **#32**, the
[`eager-boot-uses-the-provider-it-builds`](shape-intents/eager-boot-uses-the-provider-it-builds.md)
shape intent, and the remainder of **#18**.

| Feature | What it closed |
|---|---|
| `job-name-collisions` | #32, plus a same-name-in-two-files half and a **non-deterministic winner** |
| `eager-boot-provider` | #30's four defects, plus three found while fixing them |
| `parameter-type-support` | a `Path`/`UUID`/`date`/`Decimal` parameter was unusable and took the CLI down |
| `public-provider-seam` | `StaticProvider` is public; the Subjects guide landed |
| `discovery-failure-surfaces` | a missing job now says why, on every surface a user looks at |

#### The root cause worth remembering

**Six separate classifiers of a job signature, each with its own answer.** A
`Path` parameter was a CLI value to one, a dependency to inject to another, and
`str` to a third. The consolidation is `_primitives/parameter_types.py`
(`is_cli_value_type`, `has_explicit_cli_marker`) and
`_discovery/collisions.py` (`resolve_name_collisions`), and both are imported
by every path that used to decide for itself. `tests/cli/test_parameter_types.py`
drives the outcome through the real CLI so a seventh cannot appear quietly.

#### Four defects found that nothing had recorded

1. **A newly added job module could be invisible to discovery.** `pkgutil` reads
   directories through `FileFinder`, which re-reads only when the directory
   mtime changes, so a file added in the same tick was absent from the scan
   while importing it directly worked — the exact case `refresh()` exists for.
   Fixed with `importlib.invalidate_caches()` in `_discover_module_files`.
2. **The collision winner was never deterministic.** Two files claiming one job
   name gave `b b a b b a a a` over eight cold boots of unmodified 0.2.3 — the
   *surviving* job's behaviour changed with nothing changing on disk. The
   acceptance criterion "preserve today's winner" was therefore unsatisfiable as
   written; the entry key is now sorted, which makes it well-defined and
   preserves the case that was deterministic.
3. **`exclude_patterns` was silently ignored for a relative scan root**, on both
   paths. `Path.relative_to` is textual, so a relative root can never contain an
   absolute candidate; `func --exclude` was unaffected only because the CLI
   resolves its roots first. This is the remaining half of #18.
4. **The two providers disagreed on a grouped job's name** — bare `provision`
   vs `infra.provision` — because each carried its own extraction pass.

#### Behaviour changes

**DI failures no longer raise at boot** — see ADR-018. A library host catching
`DIValidationError` around `FunctualizeApp(...)` now meets it at first use.

**`CACHE_VERSION` 19 -> 20.** The cached entry key became
`source_file::python_name`; an unbumped cache would have kept collapsing
collisions by name.

**Log output carries no logger prefix on either surface.** Both `_cli/main.py`
and `app/adapters/cli.py` set `format="%(message)s"`, so a job's `log()` reads
as the program talking. The app surface was fixed second, after the first pass
left `func` bare and a project's own `main.py` printing
`INFO:functualize.job.lab.report:...` for the same call.

#### Two things worth knowing about the gates

**A relaxed assertion can pass vacuously.** The unknown-command tests were
relaxed enough to run on both surfaces and passed on the app surface by
matching the *discovery warning line* instead of the explanation. They are
`surfaces("func")` now, with the gap recorded as #37 rather than papered over.

**The discovery warning never proved the log format.** It is emitted during app
construction, before either entry point configures logging, so
`logging.lastResort` prints it bare on both surfaces regardless. Only a job's
own `log()` goes through the configured handler, which is what the two-surface
test asserts on now.

### Standalone distribution and self-management (2026-09-04, `feat/standalone-distribution`)

The `standalone-distribution` shape intent is **implemented**, and its artifacts
have been cleared from `.spec/`. The durable
design decisions are in
[ADR-015](../contributor/adr/015-standalone-distribution-and-self-management.md);
this entry records what shipped and what the work turned up.

**What shipped.** A pre-baked standalone binary for seven targets, built in
`release.yml` with checksums attached to the release, plus `install.sh` /
`install.ps1`. Five new `_cli/` modules — `runtime.py` (detection),
`manifest.py` (the voluntary registry), `package_ops.py` (command planning,
reconciliation, the uv receipt merge, and the single execution seam),
`self_cmd.py`, `plugin_cmd.py` — giving `func builtin self
doctor|update|install|python|uv` and `func builtin plugin
list|install|uninstall`. `builtin info` gained install mode and owner. Suite
7893 → **8298 passed**.

**Seven defects the tests found, none of which code review had.**

1. **Atomic writes do not prevent lost updates.** Twelve concurrent
   registrations produced a file containing three. `os.replace` prevents a
   *torn* file, not a lost one, and verify-and-retry does not close it either —
   the verification is itself racy. Serialised with an `os.mkdir` lock
   directory, chosen over `flock` because the binary targets Windows.
2. **`sys.argv[0]` is not a stable identity.** `uv run func` gives the bare
   name, a direct call gives an absolute path; one installation registered
   twice, and the bare-name copy then reported as stale.
3. **The first-run hint corrupted `--perf-report json`** on stderr. Now
   TTY-gated.
4. **`self doctor`'s own boot probe registered a phantom installation**, so the
   registry grew every time doctor reported on it.
5. **Doctor's boot probe answered a question nobody asked.** It built a bare
   `FunctualizeApp`, which boots with none of the CLI's discovery config, and
   so reported "the app starts" in a project where `func builtin version` in
   fact died. It now drives the real entry point.
6. **`owned_python()` followed the venv symlink** out to the base interpreter,
   handing back a Python that sees none of the environment's packages. Found by
   running the command, not by a test. The symlink *is* the environment.
7. **The uv receipt merge refused every path install.** `uv tool install
   "/src[cli]"` writes a `directory` key nothing in the unit tests had. Found by
   running `plugin install` in a real container. The refusal was correct
   behaviour — which is why it surfaced as a clear message rather than a silent
   reinstall from the index — but `directory` is renderable and was not being
   rendered. Fixing it exposed a second latent bug: the owning distribution was
   matched against the *rendered* string, so a path install would never have
   been recognised as the owner.

**Four vacuous tests, all found by sabotage rather than by review.** Two
asserted a name was *absent* from a list, which holds trivially when nothing is
recorded at all — deleting the entire bookkeeping call left them green. One
asserted terminal ownership against the root command object, which is not the
production path (`app/commands.py` resolves per family). One asserted a
handoff by the *absence* of a success line, which a command running on the
worker also produces.

**Two tests could not fail against the live environment**, and were fixed by
making the code take its input as an argument — the same constraint `detect()`
already carried. Nothing in this checkout publishes under `functualize.jobs`, so
the test asserting that group is filtered out passed with the filter deleted.

**Process note, recorded because it happened three times.** `git checkout --`
during a sabotage cycle discarded uncommitted work — twice in task 6.1, once in
7.1. The rule that actually works is *commit, then sabotage, then restore*,
after every change to the file rather than before the first.

**Verified in containers**, not only in pytest: every install mode detected
against a real install of that kind (settling the `tool_pipx` signal no earlier
audit host could check), a second plugin install leaving the first present, and
the install script picking musl and refusing a tampered archive before
unpacking it.
### Boolean flag negation (2026-09-03, `feat/workflow-run-params`)

`shape-intents/boolean-flag-negation.md` is **implemented**. A boolean set
`true` in a config file can now be turned off from the command line, on both
surfaces. The config ladder promised CLI > env > file; for booleans it was
three-quarters true and nothing said so.

**Four decisions were taken by the maintainer before specifying**, which is why
the shape intent sat unimplemented:

| | Question | Decision |
|---|---|---|
| D1 | Do config booleans gain a negative form? | **Yes** — `--x/--no-x` |
| D2 | What wins when `--no-foo` is ambiguous? | **The literal field `no_foo`.** `foo` then renders with no negative form |
| D3 | May the frozen typer snapshot change? | **Yes**, recorded as deliberate |
| D4 | `--flag=value` for a boolean? | **Refused on both surfaces** |

**One rule, two surfaces.** `negative_flag_for` (`_types/naming.py`, re-exported
through `app.utils`) decides the spelling for both the click builders and
`func`'s pre-boot parser. If they decided independently, `--no-cache` would mean
different things depending on how the program was invoked — the divergence class
that already produced three disagreeing dependency resolvers here.

D2's guarantee is **determinism, not detection**: click raises nothing for a
`cache`/`no_cache` collision and binds by declaration order, so the same two
fields gave opposite results depending on which was written first. Asserted with
the fields declared in **both orders**.

Before / after, on a project whose config sets both booleans `true`:

| | Before | After |
|---|---|---|
| `func deploy run --no-verbose` | `No such option` | `verbose=False` |
| `func deploy --no-strict run` | `unknown option` | `strict=False` |
| `func deploy --strict=false run` | **worked** (only here) | error naming `--no-strict` |
| `python main.py deploy --strict=false run` | error | error (click's own) |
| neither flag | from the file | **unchanged** |

The third row is the only invocation that stops working. It worked on exactly
one of four combinations and was the parity defect, not a feature: `func`'s
parser never asked whether the flag was a boolean, while click always refuses an
inline value on a flag.

#### Five findings, all from running rather than reading

1. **There are five flag-rendering sites, not the four the plan named.**
   `_option_from_marker` was missed: a bool declaring a short form routed down
   it and silently lost its pair. Found by the test.
2. **The TUI readiness evaluator had the same bug shape** — `bar.py` added
   `no_<name>` only for a bool *without* a short flag, mirroring the builder
   defect. `TestReadinessAgreesWithClick` caught it immediately because it
   derives its expected set from the param builder rather than a table. That is
   the design from ADR-009 working exactly as intended.
3. **The surface-parity harness read `--no-dry-run` as an extra *field***. It
   now folds a negative onto its positive only when the positive is also
   present — precisely right under D2, since a field literally named `no_cache`
   appears alone and must survive as itself.
4. **`_group_flag_tokens` had no sibling list**, so the emitter could not reach
   the verdict dispatch would on the way back in. Threaded through, or
   `emit(resolve(text)) == text` breaks in the one case D2 exists for.
5. **A wave gate was weaker than CI's.** `tests/group_options/` was run without
   `--run-slow`, so a second pinned test sat in the skip count and only
   surfaced in the full suite. **`--run-slow` belongs in any gate that claims a
   directory is green** — the same lesson `Potential Follow-ups` #7 records
   ("green at `default` is not green at `ci`"), reached from a different angle.

#### Two tripwires fired, and both were inverted rather than deleted

- `test_a_groups_negative_boolean_spelling_is_not` ended with *"Whether group
  booleans should gain the pair is a dispatch-level question this feature does
  not answer. **If they ever do, this test is the one that will say so.**"* It
  was the single failure across the group-options and TUI suites when dispatch
  learned the spelling.
- `test_the_group_listing_documents_its_options` has now moved **twice, in
  opposite directions, for the same reason each time**: the listing must say
  what the parser accepts. #13 inverted it to the positive form only, because
  the builder advertised a negative the parser never recognised — and recorded
  the gap it could not close. This feature closed that gap, so the listing
  advertises the pair again, and this time it is true. Its docstring now names
  the invariant that survived both moves rather than the spelling.

#### Gates

| Gate | Result |
|---|---|
| Full suite `HYPOTHESIS_PROFILE=ci --run-slow -n auto` | **9351 passed, 102 skipped, 1 failed** |
| That one failure | `test_a_closed_pipe_exits_zero_and_quietly` — the known load flake, *Potential Follow-ups* **#12**. **12 passed serially**; a doc-verify run was concurrent |
| `pytest examples/` | 187 passed |
| All 11 plugin suites | 245 passed |
| doc-verify shell tier | 9 passed, 0 failed, 10 skipped (docker/pty, as CI) — 95 steps |
| `ruff check` + `format --check` | clean, 1226 files |
| `mypy src/` | 0 errors, 305 files |
| `lint-imports` | 5 kept, 0 broken |

#### Known cost, accepted

Help output changed for every boolean config field (`--dry-run` becomes
`--dry-run / --no-dry-run`). Eleven such fields ship in `examples/`. Measured
rather than estimated: of 74 `-k help` candidates and 23 tests naming a boolean
flag, **three** actually moved, and all three were pinned tests that moved
deliberately.

### Workflow launch validation (2026-09-03, `feat/workflow-run-params`)

The first acceptance item of
[`shape-intents/workflow-run-parameters.md`](shape-intents/workflow-run-parameters.md)
is **implemented**. A `@workflow` job now refuses a launch argument its
signature cannot accept **before the graph walks**, instead of running every
step, blocking at a gate, waiting for a person to approve, and failing at the
epilogue — spending the approval on a run that was never going to succeed.

The shape intent's Assertion 3 called this "not an option: leaving it as it
stands", and its fix is the same under either design option, so it lands ahead
of the run-scoped parameter decision rather than waiting on it. **No run-scoped
parameter layer was built**: no `Param` marker, no `RunParamSource`, no
`scope["params"]`, and `step_key`'s empty `args_hash` is untouched.

**The rule is Python's.** `Signature.bind_partial` already splits exactly the
right way — it rejects a keyword the signature cannot accept, tolerates the
parameters DI has yet to fill, and honours `**kwargs`. `unexpected_keyword_error`
(`_engine/validation.py`) adds only the `fn()` prefix `bind_partial` omits, so
the message is byte-identical to a real call's. The parity test compares against
an actual call rather than a frozen literal.

**Reproductions**, from `tests/workflow/test_launch_validation.py`:

| | Before | After |
|---|---|---|
| `execute('walk', zzz=1)` | `BLOCKED`; 4 step records + a published gate | `FAILURE`; state store untouched |
| the same on an approved, blocked scope | advanced the run | scope record byte-identical, still resumable to `SUCCESS` |
| `execute('lab.parse', zzz=1)` (plain job) | `FAILURE` | unchanged |

A1 asserts the **state store**, not the status: both behaviours return a status,
so a status assertion would pass against an implementation that walked the whole
graph and failed afterwards.

#### Four defects this work found in its own gates

Worth recording because three of the four were invisible to gates written during
the Plan phase, and all four are the same class: **a gate derived from prose
rather than run at authoring time is not a gate** (`CONSTITUTION.md` →
*Acceptance Gates*).

1. **A gate that did not observe the line its task changed.** The context-move
   task's gate (`-k workflow` + the combination matrix) stayed **70 passed**
   under sabotage. Widening to `tests/engine/ tests/config/ tests/execution/`
   turned 7 red — one being `test_lifecycle_order.py`, which was **already red
   against the unsabotaged change**: moving `ExecutionContext` above the
   `@workflow` prelude reorders steps 2 and 3 of a pinned twenty-step contract.
   The move is correct and stands; `contributor/reference/execution-lifecycle.md`
   and the test's `_DOCUMENTED_ORDER` moved with it, as that test's own failure
   message demands. **Step 2's constraint column was `—` and now states one.**

2. **A task whose `[F]` named no test file** while its acceptance criteria could
   not be met without one.

3. **Two test files with the same basename** (`test_launch_validation.py`) in
   `tests/engine/` and `tests/workflow/`, neither carrying an `__init__.py`, so
   pytest refused to collect both. The first task's isolated run could not see
   it; renamed to `tests/engine/test_unexpected_keyword.py`.

4. **Config-model fields were refused as unknown launch arguments** — caught by
   the full suite, not by the feature's own tests. `func trip-planner --city
   Tokyo` failed with `trip_planner() got an unexpected keyword argument
   'city'`, because `city` is a field of the job's config model and
   `_resolve_config_model` pops those names out of `call_kwargs` *later*.

   The research note asserting "membership in the signature is the whole
   question" was **wrong**, and is corrected in the feature's `research.md`
   rather than left standing. The acceptable set is the signature **plus what
   later stages consume**; `also_accepts` carries it and both sides read
   `model_fields`, so it stays one decision. Group options are genuinely not in
   that set — `_resolve_group_options` reads the dedicated `group_option_values`
   parameter, never `call_kwargs` — and that was checked after the failure
   rather than assumed before it.

   **The reasoning error is the reusable part:** the note correctly ruled out
   reusing the engine's own `ResolutionPlan` classifier, then read that as "no
   other stage matters". Ruling one candidate out is not an enumeration.

   Every A1–A5 fixture declared a DI-only workflow with no config model, so the
   one shape that mattered was the one shape absent.

#### One design departure, and one risk that did not materialise

- **`_failure_before_execution` is extracted and shared** by the launch refusal
  and the existing `ValidationError` handler. The plan said only "return through
  the established refusal shape"; copying ~28 lines to do that would have made a
  second implementation of an invariant that matters — the exception is
  *returned*, never raised, which is what lets the CLI render a failure panel
  instead of a traceback.
- **RK1-B was not needed.** The fallback (refuse without firing `AFTER_FAILURE`,
  avoiding the context move) stayed unused: the move landed, and hook parity
  with a plain job's `TypeError` — which reaches `AFTER_FAILURE` through
  `_execute_with_lifecycle` — is intact.

#### Gates

| Gate | Result |
|---|---|
| Full suite `HYPOTHESIS_PROFILE=ci --run-slow -n auto` | **9326 passed, 101 skipped, 0 failed** |
| `pytest examples/` | 187 passed |
| All 11 plugin suites | 245 passed |
| `ruff check` + `format --check` (src, tests, examples, plugins) | clean, 1222 files |
| `mypy src/` | 0 errors, 305 files |
| `lint-imports` | 5 kept, 0 broken |

Still open from the shape intent, and untouched here: Assertion 2 (a value set
for a walk does not survive a gate), Assertion 5 (no per-run channel that is not
process-global), Assertion 6 (the trigger plugins cannot parameterize a walk),
and Assertion 7 (step replay identity). The design question — a run-scoped
parameter layer, or declaring walks unparameterizable — is still open.

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

37. **The unknown-command explanation does not reach a project's own
    `main.py`.** `explain_missing_job` (`_cli/info.py`) is called from both
    reporters — `func`'s unknown-command path and the CLI adapter's
    `_show_command_not_found` — but a project's own entry point invokes click
    in standalone mode, so an unrecognized name is rendered by click's
    `UsageError` before either runs. `func` users get "needs_dep.py failed to
    load, so the job it defines is missing"; an app user gets click's "No such
    command".

    Per `contributor/architecture/surface-boundary.md` this is a *program*
    concern rather than a *how you reach the program* concern, so the two
    should align. The fix is an error boundary around the adapter's click
    invocation, which is a wider change than the surface it would fix.
    `tests/cli/test_discovery_failure_surfaces.py` marks the affected tests
    `surfaces("func")` rather than relaxing them — a relaxed assertion passed
    vacuously on the app surface by matching the discovery warning line
    instead of the explanation.

38. **An `Enum` job parameter arrives as its member's `str` value, not the
    member.** `_click_type_for` renders `click.Choice` of member values and
    nothing converts back, so `def paint(c: Color)` invoked as `func paint
    red` receives `"red"` rather than `Color.RED`. Pre-existing, and left
    alone by `parameter-type-support` deliberately: a job comparing against
    the string works today and would break. The choice validation is correct,
    so the surface is right and only the conversion is missing.

39. **`tests/_cli/test_self_doctor.py::test_a_recognised_installation_reports_ok`
    fails on any machine whose global install manifest holds stale records.**
    It reads the real `~/.config/functualize/install.json`, so a developer with
    deleted worktrees registered there sees a failure unrelated to their
    change. Verified failing on `master` at `78d9ff4`, independent of any
    branch. The test's own docstring says it pins `argv[0]` precisely to avoid
    environment dependence; the manifest is a second source of it.



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

12. **CLOSED (2026-09-06) by `discovery-and-gate-defects`/4.1 and /4.2.**
    A job module with a `SyntaxError` no longer vanishes silently.

    `func builtin info --json` carries `discovery_failures` — always present,
    `[]` when there are none — with `{module, path, error_type, message}` per
    entry, and the plain rendering prints them above the job list. Both stages
    that can reject a module now record: the AST/pre-filter pass (where a
    `SyntaxError` actually lands) and the import pass.

    The original framing was half the problem. Covering imports alone would
    have published `discovery_failures: []` for a syntactically broken tree — a
    report that actively says "nothing is wrong", which is worse than the
    silence it replaced. A `SyntaxError` never reaches the import path; it was
    swallowed earlier, at eight sites (seven in `_primitives/pre_filter.py`,
    one in `_discovery/ast_extractor.py`). All eight still swallow — a broken
    module must stay non-fatal to the scan — they just stop being invisible.

    Verified against the shipped `func` on a real tree: one healthy job
    discovered, one `SyntaxError` and one `ModuleNotFoundError` reported. See
    #27 for the one case that is still invisible.

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

16. **CLOSED (2026-09-06) by ADR-016 / `remote-source-activation`.**
    `remote_first()` now builds CLI -> Vault -> Env -> Files -> Defaults, and
    **raises** at construction when no remote provider is registered rather
    than degrading to `classic()`. `parse_annotation` has a production caller
    (`_config/annotations.py`), the encrypted per-project vault and its key
    seam exist, `func builtin vault sync|list|status|clear|keygen` fill and
    inspect it, and `functualize-aws` / `functualize-bitwarden` provide
    `aws-sm`, `aws-ssm` and `bws`. The decision the entry asked for was made
    the "wire it" way; see `contributor/adr/016-remote-source-activation.md`.

    Two contracts found on the way and **not** closed, carried forward as
    follow-up **26** below. The finding as originally written follows,
    unchanged.

    **`remote_first()` is a public preset that resolves nothing remotely.** The
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

18. **RESOLVED — `exclude_patterns` cannot reach any scan root but the first.**
    Closed in two halves: [ADR-011](../contributor/adr/011-discovery-fingerprint-completeness.md)
    gave `GlobExcludePreFilter` every scan root (deepest containing root wins),
    and `job-name-collisions`/`eager-boot-provider` resolved both sides of the
    comparison, without which a relative root such as `directories=["jobs"]`
    matched nothing and every pattern was ignored. One construction site
    (`_discovery/filter_factory.py:96`), and it passes the roots.

    The original finding, as recorded. Surfaced while
    giving `examples/plugins/file_based_plugin` the config file its README assumed.
    The setting is documented as "exclude files matching glob patterns before any
    other filter runs" (`docs/cli/discovery.md:101-114`), with the qualifier that
    patterns match "the file's path relative to the scanned directory" — singular,
    and that is the bug: there is more than one scanned directory, and the filter
    only ever knows about one of them.
19. **The workflow hooks have no committed tests** — `.claude/hooks/{spec_gate,agent_contract,plan_context,bash_audit}.py` were verified exhaustively at authoring time (deny/pass/exemption/staleness/dedup/symlink-containment/fail-open, against real captured harness payloads), but those matrices were throwaway scripts. `grep -rn '.claude/hooks' tests/` returns **0**. Nothing catches a regression if someone edits a validator. This is the repo's own reachability rule pointed at itself: the declared surfaces in the feature's `contracts.md` are exercised by no committed test. Fix: a `tests/harness/` tier feeding recorded payloads to each script and asserting on stdout and exit code — never calling internals, since the hook's public entry point *is* stdin/stdout.
20. **User-scope `~/.claude/commands/agentic-*.md` shadow the project copies** — all five diverge, and two still name `ROADMAP.md` / `PROJECT.md`, files this repo removed. A maintainer with those personal copies gets the stale command; a fresh clone gets the correct one. Hooks hot-reload mid-session, but command definitions resolved this way do not. Fix: delete the user-scope copies so the project versions apply, or keep them deliberately and accept that project-level command fixes will not reach you.

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

21. **CLOSED (2026-09-06) by `remote-source-activation`/4.2.** Both trigger
    plugins now read the one `RunStatus` -> HTTP table
    (`functualize.types.http_status_for_status`, declared in
    `_types/http_status.py`), parameterized over every enum member so a tenth
    status fails rather than defaulting. `functualize-http` had the same defect
    in a subtler form — its JSON body said `"status": "failure"` while the
    status *line* said `200 OK`, so anything reading only the line saw success.
    Its reason-phrase map knew four codes and would have emitted
    `HTTP/1.1 202 Unknown`; it now covers every code the table can produce.

    Four `FakeJobResult`s typed `status` as a `str` is why this could hide, and
    one test asserted `response["status"] == "success"` when the real value is
    `"Success"` — documenting the fake rather than the wire. The finding as
    originally written follows, unchanged.

    **`functualize-lambda` reports every failure as HTTP 200 with a null body.**
    The generated handler
    (`plugins/functualize-lambda/src/functualize_lambda/__init__.py:126`) does

    ```python
    result = app.execute(job_name, **job_kwargs)
    return {"statusCode": 200, "body": result.return_value}
    ```

    `result.status` is never read. A job that fails validation, fails its guards,
    or raises — anything that comes back as a `JobResult` rather than an escaping
    exception — returns `{"statusCode": 200, "body": None}`, which is
    indistinguishable from a job that succeeded and returned nothing. Only an
    exception that escapes `execute()` reaches the `except` branch and becomes a
    500, and the engine's whole design is that failures *do not* escape: they are
    returned so the CLI can render them instead of a traceback. So the branch that
    reports failure is the one the engine tries hardest never to take.

    Contrast `functualize-http`, which surfaces `result.status` in its response
    body (`__init__.py:175-181`) and is correct today. Two trigger plugins,
    one `JobResult`, two answers.

    Surfaced 2026-09-02 while writing contracts for
    `.spec/features/workflow-launch-validation/` — a refused workflow launch is a
    `FAILURE` result, and tracing where each surface would show it found this. It
    is **pre-existing and unrelated to that feature**, which is why it was
    recorded rather than folded in; the launch-validation contracts note it so a
    reviewer comparing surfaces does not read it as newly introduced.

    **Fix**: map `RunStatus` to a status code the way the HTTP plugin does, or at
    minimum carry `status` in the body. Wants a decision on what a Lambda caller
    should see for `BLOCKED` — a gated workflow reached through Lambda is neither
    a success nor an error, and that is the case the mapping has to name rather
    than round off.

22. **AMENDED (2026-09-06) — the cause is a product defect, and it is proven.**
    `tui.default_surface` is **not** in `_BASE_SETTINGS`; the shell registers it
    as an import side effect of `_cli/tui/__init__.py:88`, and a direct
    `func <job>` run under true-lazy boot never imports that package. So
    neither `FUNCTUALIZE_TUI_DEFAULT_SURFACE` nor a `tui.default_surface` line
    in a config file reaches the gate that exists to serve the direct-run path,
    and `_explicit_stdout_preference`'s broad `except Exception` hides the
    difference. Verified directly: with the env var set, the gate returns False
    in a clean process and True immediately after
    `register_settings(*tui_settings())`. Under `-n auto` xdist balances
    dynamically, so whether the worker had already imported the shell varied
    run to run — the sharding was the symptom, not the cause.

    `remote-source-activation`/4.2 made both tests state which catalog they
    mean and added
    `test_the_setting_is_inert_until_the_shell_registers_it`, which asserts
    against `_BASE_SETTINGS` so that **closing the gap fails the test** and
    prompts its deletion. A `strict=True` xfail was tried and rejected: it
    XPASSes once the shell has been imported, swapping one order-dependent
    outcome for another. The fix belongs to the surface/settings owner. The
    finding as originally written follows, unchanged.

    **`test_env_override_opens_the_gate` passes only under xdist sharding.**
    `tests/adapters/test_surface_gate.py::TestWantsStdoutSurface::test_env_override_opens_the_gate`
    **fails when `tests/adapters/` is run on its own** and passes in the full
    suite under `-n auto`. Verified against `f9fe1ba` in a throwaway worktree,
    so it predates the workflow-launch-validation and boolean-flag-negation
    work; found while chasing an unrelated red.

    It sets `FUNCTUALIZE_TUI_DEFAULT_SURFACE=stdout` with `monkeypatch` and
    asserts `wants_stdout_surface(...)` is true, so the likely cause is
    settings-store state that another test in the wider run happens to
    establish — meaning the test passes for a reason it does not state.

    Same family as #10 and as the F10 finding in the 0.1.1 review: a test whose
    result depends on something outside its own body. **Consequence:** anyone
    running `pytest tests/adapters/` while working on the adapters sees a red
    that is not theirs, which is exactly how a real regression gets waved
    through. **Fix:** make the fixture establish whatever the wider run
    supplies, or assert against an explicitly constructed settings store.

23. **`test_reentry_guard_ignores_second_trigger_while_running` flakes on
    Python 3.11.** `tests/_cli/test_job_execution_thread_worker.py:121` triggers
    `action_execute()` twice with an `await pilot.pause()` between them and
    asserts the re-entry guard swallowed the second
    (`_snapshot_store.record.call_count == 1`). It failed once on CI with
    `assert 2 == 1` on the **3.11** matrix leg while 3.12 and 3.13 passed in the
    same run; a rerun of the identical commit passed in 14m44s.

    Same family as #10 and #12: **the assertion times the machine, not the
    code.** If the first worker finishes before the second trigger lands, the
    guard legitimately never fires and `record` is called twice — a correct
    system failing a test that assumed a scheduling order. Python 3.11's asyncio
    differs enough from 3.12/3.13 for the race to land differently there.

    Ruled out as a cause, during PR #17: the test predates that branch
    (`84ed555`), the only change to `job_execution.py` was inside the
    `bad_flag is not None` early-return branch, which a bare `slowjob` never
    enters; the `bar.py` readiness change only alters the `known` flag-set for
    boolean fields, and its loop does not run for input with no `-` tokens; and
    the function-local `app.utils` import is a `sys.modules` hit, since
    `display_affinity.py` already imports that module at module scope. Locally
    on 3.13 it passed 3x serially and 6x under concurrent load.

    **Fix:** assert the guard's *state* rather than a post-hoc call count — hold
    the first worker open until the second trigger has been observed, instead of
    racing it. Lowering nothing and rerunning is what makes a flake permanent.

24. **An exemption used to silence the shell-write auditor instead of being
    recorded by it — FIXED.** `bash_audit.py` folded two questions into one
    predicate (*is there a task list?* / *is there an exemption?*) and returned
    early on either. So a shell write to gated code under an active
    `.spec/EXEMPT` was recorded **nowhere**: the `PreToolUse` gate never fires
    for a shell write, and the auditor stayed quiet because the exemption
    existed.

    **Declaring an exemption made a write less audited than not declaring one.**
    Reproduced before fixing — 0 ledger lines with an exemption, 1 without.
    `CONSTITUTION.md` calls that ledger "the entire mitigation for the fact that
    an agent can exempt itself"; a mitigation that skips the case it was built
    for is not one.

    Found during the 0.1.3 release prep: the bump to
    `src/functualize/__init__.py` went in by script under an exemption and left
    no trace, while the 0.1.2 release — which used the `Edit` tool — has its
    ledger entry. That asymmetry between two releases is what exposed it.

    `tests/harness/test_bash_audit_ledger.py` is the fix's gate and the **first
    committed test for `.claude/hooks/`**, so #19 is now partly discharged: one
    of the four validators has a test. The other three still have none.

25. **The release version count in this file is stale, and the release skill now
    says so.** Item #148 above records "13/13 sites at `0.1.1`" — true then, and
    it predates the four `skills/*/SKILL.md` frontmatter versions that ship
    inside the wheel. The real count at 0.1.3 is **seventeen**.

    The historical line is left as written rather than back-dated. The durable
    fix is in `.agents/skills/release/SKILL.md` Phase 0, which now enumerates
    the sites, gives the verification grep, and says plainly not to trust a
    count written in prose — including this file's.

26. **`RemoteProvider`'s docstring names two exceptions that do not exist, and
    a 12-factor clause one shipped provider cannot honour.** Found while
    building the two provider plugins (`remote-source-activation` 5.1/5.2) and
    deliberately not fixed there — both are core contracts, and a plugin task
    changing the protocol its own plugins implement is the wrong direction.

    - The docstring tells an implementor to raise `RemoteKeyNotFoundError` and
      `RemoteConnectionError`. **Neither exists.** Only `RemoteTimeoutError`
      does, and none of the three is publicly exported, so `functualize-aws`
      and `functualize-bitwarden` each define their own `SecretNotFoundError`.
      Two plugins, two private hierarchies, and a caller cannot catch "not
      found" generically. Either export the family or delete the promise.
    - *"Credentials MUST be resolved from environment variables only, following
      12-Factor App principles."* `functualize-bitwarden` honours it;
      `functualize-aws` cannot, because the maintainer's per-value override
      requirement (`?profile=`, `?role=`, `?account=`, `?region=`) is
      something environment variables cannot express — different secrets in one
      config file may need different accounts. The clause is now half-false by
      design and should say what it actually means: the *ambient credential
      chain* comes from the environment; an annotation may redirect which
      identity is used, and never carries a credential itself.

27. **A parse failure disappears on the second run.** The remaining half of
    #12, left open deliberately rather than missed.

    `discovery_failures` is **per scan**: it answers "what did this pass fail
    to read". The two stages behave differently under the cache, and only one
    of them keeps reporting:

    - **Import failures repeat.** A module that fails to import writes no cache
      entry, so it stays in the "new files" set and is retried — and reported —
      on every run.
    - **Parse failures do not.** `_should_import_with_cache` persists a
      *negative* pre-filter decision keyed by mtime, so a file rejected for a
      `SyntaxError` is judged once and skipped thereafter. A skipped file
      records nothing.

    Verified against the shipped `func` with a warm cache: run one reports both
    the `SyntaxError` and the `ModuleNotFoundError`; run two reports only the
    `ModuleNotFoundError`. So the operator most likely to be confused — someone
    who has run the tool before, fixes nothing, and runs it again — sees the
    typo reported once and then never again.

    Both behaviours are asserted in `tests/discovery/test_discovery_failures.py`
    so neither can change silently. Making the parse failure survive means
    writing it into the cache entry, which turns a per-scan report into a
    standing inventory of broken files — a different feature with its own
    invalidation question (when does a recorded failure stop being true?), and
    not one to fold into a defect fix.

28. **`l-standalone-binary` cannot pass: its own recipe has a broken `xargs`.**
    **FIXED 2026-09-07.** The recipe now resolves the interpreter in two
    statements — `python_bin=$(uv python find 3.12)` then
    `src_root=$("$python_bin" -c 'import sys; print(sys.prefix)')` — with an
    explicit non-empty check, so a future resolution failure says so instead of
    producing an empty `cp -a "$src_root"/.`.

    Verified in a real `rust:1-slim-bookworm` container up to the resolution
    step: `src_root` comes back as
    `/root/.local/share/uv/python/cpython-3.12.14-linux-x86_64-gnu` with an
    executable `bin/python`. The ten-minute `cargo install pyapp` beyond it is
    unchanged and still runs only on demand. Note the resolved prefix is the
    *patch-versioned* directory, which is why the next line copies
    `"$src_root"/.` rather than the symlink.

    The original finding follows.

    Found at the `discovery-and-gate-defects`/6.1 checkpoint, where the full
    scenario suite was run. 15 of 16 doc pages verified; this is the one that
    did not, and it fails for a reason inside the scenario rather than in the
    documentation it is supposed to check.

    `examples/docs/scenarios/l-standalone-binary.toml:56`:

    ```sh
    src_root=$(uv python find 3.12 | xargs -I{} {} -c 'import sys; print(sys.prefix)')
    ```

    In the `rust:1-slim-bookworm` container this prints
    `xargs: {}: No such file or directory` — the `-I` replacement is not applied
    to `argv[0]`, so xargs tries to exec the literal string `{}`. Under
    `set -e` the step exits **127** at ~21s, long before the ten-minute
    `cargo install pyapp` it exists to run.

    Reproduced directly: `uv python find 3.12` prints a valid path
    (`/root/.local/share/uv/python/cpython-3.12-linux-x86_64-gnu/bin/python3.12`)
    and exits 0, and uv installs correctly — so neither the network, the
    image, nor `docs/getting-started/installation.md` is at fault. The string
    `xargs` appears **only** in the scenario; the documented commands do not
    use it.

    Consequence: `docs/getting-started/installation.md:52-155` is **not
    verified**, and has not been since this recipe was written. That is the
    same class of failure STATUS already records for this scenario — *"a
    verification step that has not been run is not evidence"* — recurring one
    layer down, in a step that now runs and fails fast rather than never
    running at all.

    Fix is one line: `src_root=$("$(uv python find 3.12)" -c 'import sys;
    print(sys.prefix)')`. ~~Left undone deliberately — it belongs to the
    standalone-distribution work, and verifying it costs a full ten-minute
    container build.~~ Done as above; verifying the *resolution* turned out to
    cost about a minute, not ten — only the `cargo` build beyond it is
    expensive, and the fix does not reach it.

29. **`[tool.functualize] skill` is accepted, validated, and read by nothing.**
    Shipped knowingly by `third-party-host-seams`/1.2, and recorded here
    because that task required it to be — this is the fourth member of a class
    this file already calls *"the worst of the three states"*.

    `_KNOWN_TOOL_KEYS` now holds `{"job", "skill"}`, so a single-file script
    declaring the skill it belongs to no longer earns a warning on every run.
    `ScriptMetadata.skill` is parsed and exposed. **Nothing consumes it**, and
    `spec.md` puts consuming it out of scope.

    Shipping the key ahead of a consumer is deliberate: the file format should
    settle before anything depends on it, and a host package can start writing
    the field now. But the pattern has a track record here — `omit_defaults`
    (#14) and `remote_first()` (#16) are the same shape, and the second of
    those resolved silently as `classic()` for its entire shipped life. The
    difference is that this one is counted from the day it landed.

    The site is marked `# TRANSITIONAL(third-party-host-seams/1.2)`. Close this
    by wiring the value to whatever reads it, or by removing the key if no
    consumer arrives.

30. **RESOLVED 2026-09-08 by `eager-boot-provider`.** The eager boot path
    bypasses the provider it just built — four defects, one root cause.
    Supersedes the original narrower note. Audited 2026-09-07;
    every number below was measured, not inferred. The verified analysis lives
    in
    [`.spec/shape-intents/eager-boot-uses-the-provider-it-builds.md`](shape-intents/eager-boot-uses-the-provider-it-builds.md)
    (spec + contracts, no tasks — the work is **parked**, see the end of this
    entry). It lived under `.spec/features/` until that directory was cleared
    for the PR #29 merge, and was migrated rather than deleted: the 13
    acceptance criteria carry authoring-time measurements that would be
    expensive to re-derive.

    `_app/boot.py` `boot_standard` builds a `DirectoryScanProvider` from the
    resolved `DiscoveryConfig` — with `pre_filter` and `job_filter` — and adds it
    to the pipeline (`boot.py:499`). `resolve_and_register_jobs` (`:1140`) then
    registers the eager path by a different route entirely,
    `JobRegistry.scan_and_register_headless`, which enumerates with
    `pkgutil.iter_modules` and takes no discovery filter. One provider is built
    and bypassed; a second scanner runs instead.

    **D1 — every job module is imported twice.** Whenever `provider_count > 1`
    the guard at `:1149` opens and `resolve_all()` calls `list_jobs()` on every
    provider, including the directory provider whose work has already been done.
    Measured with a module-level side-effect counter, two job modules, no
    `DiscoveryConfig`:

    | Second provider | `lazy=False` | `lazy=True` |
    |---|---|---|
    | none | 2 — correct | 2 — correct |
    | `functions=[...]` | **4** | 2 — correct |
    | a child project | **4** | 2 — correct |

    Import-time side effects therefore run **twice**, on the one path
    `contributor/architecture/developer-modes.md:48` documents as *"the escape
    hatch for users who need import-time side effects"*. It also doubles a path
    whose measured budget is already ~2000 ms against ~125 ms.

    **This regressed in this branch.** Before `1f24356`, `boot_standard` added
    exactly one provider (verified: no other `add_provider` call in that
    function), so the guard could never open without a child project.
    `wire_declared_job_sources` fixed `JobSources.functions` being silently
    ignored and, in doing so, gave `boot_standard` a second provider. The fix
    was right; this consequence was not noticed at the time.

    **D2 — `_registered_commands` is keyed by the Python name, and goes stale.**
    The eager path writes `f"{job_group or '__top__'}::{attr_name}"`. Every
    consumer expects the canonical descriptor name — `app/core.py:496`
    (`refresh()` eviction) and `app/adapters/cli.py:1262-1265`
    (`_show_job_config`). Measured for `deploy_thing` (canonical
    `deploy-thing`):

    ```
    lazy=False   descriptor: deploy-thing   key: __top__::deploy_thing
    lazy=True    descriptor: deploy-thing   key: __top__::deploy-thing
    ```

    Not unbounded growth — the write is idempotent — but staleness: after the
    job file is deleted and `refresh()` runs, `lazy=False` still reports
    `__top__::deploy_thing` while `get_jobs()` returns nothing. `refresh()`
    exists for exactly the long-lived consumers (TUI, MCP) that would see it.

    **D3 — discovery filters are ignored.** `exclude_patterns`, every
    `require_*`, and `DiscoveryConfig.pre_filter` have no effect.

    **D4 — …except partially.** With the guard open *and* a filter set, the
    provider half does filter (3 imports rather than 4, against `lazy=True`'s 1)
    but its descriptors are discarded by the `already_registered` dedupe. The
    filter changes which modules are imported and not which jobs exist — so the
    symptom depends on whether an unrelated second provider happens to exist.

    **Reach — narrower than first recorded.** `lazy` is a `JobSources` field and
    nothing else. All three `JobSources(...)` in `_cli` hardcode `lazy=True`
    (`main.py:509`, `:1210`, `:1330`); there is no flag, config key or env var,
    so the CLI's eight discovery flags only ever reach the *correct* path. And
    `app/core.py:169` is the sole assignment of `_discovery_config` in the tree
    — nothing merges `[tool.functualize.discovery]` into a library app. So
    D1/D2 need `lazy=False` alone; D3/D4 need `lazy=False` **and** a hand-passed
    `DiscoveryConfig`. **No `func` invocation can reach any of them.**

    **Why it is parked rather than fixed.** The obvious fix — route the eager
    branch through the provider — would delete the only place #32 below is
    caught, trading a CLI-invisible bug for the loss of a real diagnostic. It
    also has a second edge: `resolve_all()` raises on duplicate names across
    providers and the caller catches it and `return`s, so making eager purely
    pipeline-driven turns a name collision from "partial registration" into "no
    jobs at all". Both are solvable; neither is solved. Decide #32 first.


31. **`ModulePreFilter` ships as `should_import`, not `accepts` — RESOLVED
    2026-09-07, see [ADR-017](../contributor/adr/017-module-pre-filter-signature.md).**
    Decision: keep `should_import(source_file)`, reject `accepts(path, source)`.

    The sketch bundled a rename with a signature change, and they have opposite
    answers. `source` eliminates the redundant *reads* (0.6–7% of the measured
    cost) and leaves the redundant *parses* (27–91%) untouched, and an eager
    `source` would force every candidate to be read before any filter runs —
    inverting the cheapest-first ordering and making a filename rejection
    20–200× more expensive. The name keeps the `should_register` /
    `should_import` symmetry and names the consequence that matters: returning
    `True` runs a module's import-time side effects.

    The original finding follows.

    **`ModulePreFilter` ships as `should_import`, not `accepts`.** `third-party-host-seams`/`contracts.md` §S1
    sketches the promoted Protocol as `accepts(self, path: Path, source: str)
    -> bool`. What shipped is `should_import(self, source_file: Path) -> bool`.

    The implementation followed the code rather than the contract, deliberately
    and on the contract's own reasoning: §S1 says this seam *"promotes the
    existing shape rather than inventing one"*, and the existing shape is
    `should_import(source_file)` — the method all thirteen built-in filters in
    `_primitives/pre_filter.py` implement and every call site in discovery
    invokes. Shipping `accepts` would have meant either renaming thirteen
    filters and their call sites, or publishing a public method name that
    disagrees with every internal one.

    The `source` parameter is also absent: filters read the file themselves
    (and the AST ones parse it), so a caller-supplied `source` string would be
    a second, possibly-stale copy of what the filter is about to read.

    This is now the public surface, exported from `functualize.plugin` and
    documented in `docs/guides/jobs-discovery.md`. Renaming it later is a
    breaking change, so it is flagged here rather than left as an unremarked
    difference between the spec and the code. **No action needed if the shipped
    name is right; this exists so the choice is visible.**

32. **RESOLVED 2026-09-08 by `job-name-collisions`.** A job silently disappears
    when two functions normalize to the same name — on the *default* path.
    Found 2026-09-07 while auditing #30, and it is the only defect in that
    audit a `func` user can hit.

    Canonical identity lowercases and hyphenates, so `build_wheel` and
    `buildWheel` in one module both become `build-wheel`. The eager registry
    path detects that and raises. The provider path — which `lazy=True` uses,
    and `lazy=True` is what all three `JobSources(...)` in `_cli` hardcode —
    does not:

    ```
    build_wheel() + buildWheel() in one module

    lazy=False  ->  ValueError: Two jobs normalize to the same name 'build-wheel'
    lazy=True   ->  ['build-wheel']        # one job vanished, no diagnostic
    ```

    Measured on a cold boot in a fresh directory, so it is not a cache artifact.

    `_discovery/registry.py` carries the check and says exactly why it exists:
    *"Normalization can map two distinct functions onto one name … Without this
    the second silently replaces the first and one job vanishes with no
    diagnostic anywhere. Two functions cannot share an address, so this is an
    authoring error and says so."* That reasoning applies verbatim to the path
    that lacks it, and the path that lacks it is the one everybody runs.

    Note the *other* two registry-only behaviours turned out not to be losses,
    which is why this is the only entry: invalid `JOB_GROUP` warns and skips on
    **both** paths (verified by probe — a grep count suggested otherwise and was
    wrong), and `_config_validator` is dead code, never assigned anywhere in the
    tree.

    **Where the fix belongs.** `register_descriptors` (`_app/boot.py:1218`) is
    called by both boot paths, so putting the check there fixes `lazy=True` and
    simultaneously preserves the diagnostic the eager path already has — which
    is what unblocks #30, since routing eager through the provider would
    otherwise delete it. One change, two entries closed.

    Not done: the maintainer paused this work on 2026-09-07 to reassess
    priorities across all five defects rather than fix them in discovery order.

33. **`test_ui_stays_responsive_while_job_executes` was flaky on a loaded CI
    runner — FIXED 2026-09-07.** Two failures in three runs on PR #29, on
    Python 3.11: once with `got 0 polls`, once with `got 3 polls`, both against
    an idle ceiling of 20 and a floor of 6, with a clean pass in between on an
    unchanged tree.

    **Two causes, both measurement bugs rather than flakiness in the code
    under test.**

    *The window was not guaranteed to contain the job.* The test polled while
    `tui_app.workers` was non-empty, starting immediately after
    `action_execute()`. If the worker had not started, the loop never iterated
    and reported zero — the same observation a genuinely frozen loop produces,
    so the failure was indistinguishable from the defect the test exists to
    catch.

    The first repair waited for `_job_worker_running`, copying the pattern its
    neighbour `test_reentry_guard_ignores_second_trigger_while_running` uses.
    **That failed in CI too**, with *"the job worker never reached RUNNING"* —
    because the deadline for reaching RUNNING was `BLOCK_SECONDS`, i.e. a guess
    about how fast the machine starts a thread. That is precisely the class of
    assertion `tests/_responsiveness.py` was written to get away from, and
    swapping one arbitrary constant for another would have repeated it.

    The fix that held takes the signal from the job itself: `slow_job` sets a
    `threading.Event` as its first statement, and the test waits on that with a
    deliberately generous 10s startup budget. Worker state is never consulted.
    A job that never begins fails loudly; a job that begins late costs only
    startup time and does not distort the measurement, because the window is
    timed from the event.

    *The floor was compared against the wrong denominator.* `idle_polls` is
    measured over the full `BLOCK_SECONDS`, but the window actually polled
    starts when the worker is running and ends when it finishes — shorter, by a
    margin that varies with how quickly the machine got the thread going.
    Comparing a short window's count against a full window's ceiling asks the
    loop for more work in less time, which is how a responsive run reported 3
    polls against a floor of 6. The ceiling is now scaled by the observed
    elapsed time before `responsive_floor` is applied, so the comparison is
    between rates.

    **Verified not to be a weakening**, at both iterations. With the real defect
    reintroduced — the sync job called inline instead of through
    `run_worker(..., thread=True)` — the old and both new versions fail. The
    final one fails on the responsiveness assertion: the job body runs, so the
    start event is set, but the polling window is then empty and the scaled
    floor is not met. 5/5 clean runs locally.

    An earlier sabotage attempt (freezing the loop at dispatch while the thread
    also ran) passed against **both** versions — worth recording, because it
    means neither the old nor the new test covers a dispatch-time freeze that
    overlaps the job's own duration. That gap predates this fix and is not
    closed by it.

    Two sibling tests share the un-scaled comparison —
    `tests/_cli/test_display_refresh_thread_worker.py` and
    `tests/tui_audit/test_blocking_worker.py`. Neither is currently failing, so
    both were left alone; if either starts flaking, this is the reason.

    The original finding follows.

    Observed 2026-09-07 on PR #29: `test-fast` failed on Python 3.11
    with `got 0 polls ... against an idle ceiling of 20 (floor 6)`, then
    **passed on a re-run of the same commit**, with no code change between.
    The previous CI run had passed on a tree differing only in two unrelated
    test files, and it passes 3/3 locally.

    `tests/_cli/test_job_execution_thread_worker.py:87`. The test blocks a job
    for `BLOCK_SECONDS = 0.4` and polls the event loop every
    `TICK_INTERVAL = 0.02`, requiring a floor derived from an idle measurement
    taken on the same machine moments earlier — so it is already
    self-calibrating, and calibration is not what fails.

    **The failure mode is not the one the message names.** `ticks == 0` means
    the `while tui_app.workers and ...` loop never iterated *even once*, i.e.
    `tui_app.workers` was already falsy when the poll loop was reached. That is
    a race between the worker starting and the polling beginning, not the
    "sync call is still blocking the event loop" the assertion reports. A
    genuinely blocked loop would still tick at least once before the deadline.

    Not "fixed" by widening the tolerance: the property it guards is real and
    load-bearing (a sync job must not freeze the TUI, the defect the
    thread-worker migration exists to close), and a weakened assertion would
    stop catching it. The right repair is to make the test wait until the
    worker is observably running before it starts counting, so the measurement
    cannot begin after the work has finished. **Done, plus the rate scaling the
    second failure mode needed — see the head of this entry.**

34. **The pre-filter stack parses each candidate file three to four times.**
    Measured while deciding ADR-017; recorded because the cost is real even
    though the protocol change proposed for it was the wrong fix.

    Seven of the thirteen built-in filters each do their own `read_text()` +
    `ast.parse()`, and the baseline stack — `AnyOf(AST, DisplayClass,
    GroupOptions)` at position 5 plus `AnyOf(Default, GroupOptions)` at
    position 2 — reaches the same file three or four times with no filter
    configured at all.

    | | small job file (905 B) | `_cli/builtins.py` (85 KB) |
    |---|---|---|
    | three filters, as shipped | 568.6 µs | 52,347 µs |
    | of which redundant reads | 39.7 µs — 7.0% | 303 µs — 0.6% |
    | of which redundant parses | 151 µs — **26.6%** | 47,473 µs — **90.7%** |

    **The fix is a parse memoized per `(path, mtime)`, not a protocol change.**
    Keyed that way it is correct across a `refresh()` (the file changes, the key
    changes) and needs no signature change, so it costs nothing at the public
    seam ADR-017 just settled. `mtime` alone is the same validity tier the
    discovery cache already trusts for its negative decisions, so it introduces
    no new staleness assumption.

    Deliberately not done, for two reasons worth stating rather than leaving
    implicit:

    - **It is a cold-boot cost only.** `CachedDirectoryScanProvider._list_jobs`
      runs the filter only for `on_disk - cached_files`, and rejections persist
      as decisions keyed by mtime. A warm boot over an unchanged tree parses
      nothing. The 90.7% figure is the worst case on the largest file in the
      repository, on the one path that already accepts a multi-second budget.
    - **The memo needs an owner and a lifetime.** A module-level cache would
      outlive a `refresh()` and leak across `FunctualizeApp` instances in a
      long-lived process (TUI, MCP server) — the same shape as #30's phantom
      entries. Doing it properly means threading a per-scan cache through
      `build_pre_filter_from_config`, which is a design change rather than an
      optimization.

    Close this by adding that per-scan memo, or by deciding the cold-boot cost
    is acceptable and saying so.

## Recently Completed (2026-09)

| Feature | Description |
|---------|-------------|
| mcp-server-fixes | `fix/mcp-server-fixes`: `func mcp serve` crashed on grouped jobs with parameters — the plugin compiled `async def {dotted_job_name}(...)` via `exec`, a SyntaxError that killed registration (found live by the NOOA integration probe; verified against 0.2.3 and still present on master). Fix: codegen under a sanitized identifier, dotted name restored on the function object; descriptions attach as `__doc__` instead of being interpolated into source (a `'''` in a docstring broke compilation the same way). Server boots no longer run FastMCP's PyPI update check or print its banner unless `FASTMCP_*` env vars opt back in. `fastmcp` dependency bounded to `<5`. Regression net: unit + registration tests, a live subprocess stdio capability test, and a `grouped_tools` example with its own serve harness. Full plugin + examples suites green; ruff clean. See `.spec/features/mcp-server-fixes/` on the branch (cleared before merge). |

### workflow-continuation

Roadmap items 1–6 of the pi-workflows parity study, landed as `0.3.0`. The verbs
that drive a workflow now exist on every surface, and `--scope-id` is gone.

**The decision worth keeping.** *`answer` records. `resume` advances.* One
meaning each. Until this split, **every** verb called *resume* on every surface
was a deposit, and nothing anywhere advanced a blocked walk except re-invoking
the job process — which an agent driving the workflow over MCP cannot do. A
workflow could be inspected and answered by an agent and finished only by a
human at a terminal.

**Rules that outlive the feature:**

- **A capability that is "about the program" gets one spelling, reachable
  identically from every surface.** Which spelling can change — this feature
  deleted the fix that an earlier application of the same rule produced — but
  that there is exactly one does not. `contributor/architecture/surface-boundary.md`
  now carries the three-revision history as its worked example.
- **A verb that runs a job goes through the funnel, whatever surface it is on.**
  MCP enforced its gate-tool policy at `_execute_job`, "the one place a
  job-executing call cannot get past". Making the CLI's `resume` advance created
  a second such door, so the funnel and the policy moved into `app/`.
  A check a caller can skip by not calling it is not a permission.
- **…and the funnel's exemptions are as load-bearing as the funnel.** Passing
  the gate-tool policy to `resume` made every gate that declared `tools=[…]`
  refuse its own workflow — the walk that is the only way out of the block. The
  rule was already written down for the read tools; `resume` is the third member
  of that set.
- **One projection, plus a test that checks the callers against it.** Two
  projections of the same store existed in the same process and the poorer one
  faced humans. Lifting them into one function removes the drift; the test is
  what keeps it removed (`pitfalls.md` §6 — a registry nothing verifies is just
  another copy).
- **A parity test enumerates; it does not sample.** Both sets are derived from
  the live surfaces, so neither can grow a verb the other lacks without failing,
  and nobody has to remember to edit the test (`pitfalls.md` §19).
- **Ambiguity is listed, never guessed.** Zero candidates names the survey verb,
  one is used, several are listed and the call fails. Never "newest wins" —
  `blocked_at` resets on every re-block, so recency is not computable anyway.
- **A flag that may *create* state and one that may only *address* it are two
  flags.** `--scope-id` did both, so a typo silently became a blocked run under
  the typo. `--wf-run-id` may mint; `--wf-resume` may not.

**What writing the tests found that reading did not:**

1. The gate-policy-refuses-its-own-resume bug above.
2. `--reopen` could not address its own target: `resolve_gate` searched only
   *pending* gates, and an answered gate is by definition not pending.
3. The consumed-gate guard read a completed walk as "hasn't passed the gate",
   because a finished walk sets `position` back to `None`.
4. The parity test's own helper filtered parameters by *name* to skip variadics,
   and `call_gate_tool` has a real parameter named `args` — a false gap. A test
   that cries wolf is how a real gap later gets waved through.

**One roadmap item was withdrawn as false.** `04-mcp.md` §3 asked for per-job
tool descriptions to stop repeating examples "the schema already carries". The
schema carries no examples at all — `field_property` emits type, description,
default and enum, and `FieldDescriptor` has no `examples` attribute. Removing
them would have deleted the only copy and made tool selection worse.

**Known limitation, shipped deliberately:** concurrent `resume` is not fenced.
Two invocations against one scope both walk it; the file lock serializes writes
so nothing corrupts, but the second overwrites the first's step records. Making
`resume` easy makes the race easy. The fix is a lease with a fencing token,
which belongs with the durable run layer (roadmap item 8) rather than being
half-built here.

**Still outstanding from the roadmap:** Tier 2 — item 7 (agent-step port as a
Protocol with capability flags, gated on this feature), item 8 (durable run
layer: events, lifecycle verbs, leases, per-step timeouts, effects outbox), and
item 9 (loops, failure routing, watch, notify). The study lives at
`~/code/raicing-ai/pi-workflow-parity/`; its `CHANGELOG.md` §3 is the
do-not-re-litigate table.

### workflow-state-durability

Workflow scopes moved out of `.functualize/state.json` into
`.functualize/scopes.json`, with an independent format version and a
**fail-closed** read.

**The decision worth keeping.** Runtime persistence is two files, and the line
between them is the discard rule, not the subject matter:

| | `state.json` | `scopes.json` |
|---|---|---|
| holds | fingerprints, history, session cache | workflow scope records |
| is | **derived** — recomputable from the source tree | a **record** — recomputable from nothing |
| bad version / corrupt | degrades to empty | **refuses**, file left in place |

A `STATE_VERSION` bump — an ordinary release action — used to erase every
in-flight run, gate payloads and all, and so did `func builtin state clear`,
under help text naming only "fingerprints, history".

**Rules that outlive the feature:**

- **When adding a section to either file, pick the file first.** If losing it
  would upset someone it is not derived, and does not belong in `state.json`.
- **The scope file is the state file's sibling**, derived via `with_name`, never
  a second upward walk — two walks can disagree (`pitfalls.md` §22).
- **A fail-closed read must not move the file.** Refusing has to be repeatable;
  renaming aside makes the *next* run find nothing, read it as "no scopes", and
  start over silently — the failure the split exists to remove.
- **A refusal reports a count, never content.** Scope records hold gate payloads
  and step return values.
- **Both dispatch paths, or neither** (`pitfalls.md` §23). A sabotage check found
  the warm path (`lazy_command`) uncovered *after* the task, the code and the
  tests had all been written to prevent exactly that. A green suite never
  detects this; only breaking the call does.

**No migration**: scopes in the old envelope are lost once, on upgrade. Pre-1.0,
and a permanent read-time shim for a one-time transition is the two-store shape
the change exists to remove. Recorded in `CHANGELOG.md`, which is the only
warning anyone gets.

Reference: `contributor/reference/state-store.md` — marked "shipped", cited by
nothing, and already drifted before this feature touched it.

**Still open, deliberately out of scope:** the `--scope-id` removal and the
`--wf-*` verb surface (see `~/code/raicing-ai/pi-workflow-parity/`, docs 05 and
12); `WorkflowWalker._key(name)` hashing args to the empty string; and the walk
rewriting a replayed step's `completed_at` without re-executing it.

## Recently Completed (2026-08)

| Feature | Description |
|---------|-------------|
| Spec-workflow enforcement | The spec-driven workflow is now mechanically enforced, not advisory. Four harness hooks in `.claude/hooks/`: a `PreToolUse` gate on `Edit`/`Write`/`NotebookEdit` that denies changes to `src/functualize/**` and `plugins/*/src/**` without a `tasks.md` carrying a wave graph; a `PreToolUse` rewrite that gives the built-in `Plan` agent the contract it cannot load; a `PostToolUse` injection of the execution contract at plan approval; and a `PostToolUse` `Bash` auditor that records shell bypasses. All fail open and resolve paths from the hook's `cwd`, so they validate the worktree rather than the session origin. Escape hatch is `.spec/EXEMPT`, logged to the committed `.spec/exemptions.log`. See [ADR-010](../contributor/adr/010-spec-workflow-enforcement-point.md) for why the gate fires on writes rather than at plan approval. |
| Spec-workflow document repair | The workflow documents referenced four files that never existed and were gitignored — `PROJECT.md`, `REQUIREMENTS.md`, `ROADMAP.md`, and the `.agentic-coding` marker — across 16 sites. `AGENTS.md` now supplies the project context anchor, Phase 0 keys on the committed `CONSTITUTION.md`, and Phase 5 targets `STATUS.md`. The `spec-driven-developer` tool list gained `Edit`, `Skill`, and `Agent`, without which three of its own instructions could not run. |
| `.spec/features/` lifecycle | Feature artifacts are tracked on the branch so the spec, contracts, plan and task ledger are reviewable, then cleared before merge by the required `spec-artifacts-cleared` check, so master carries none. Recoverable afterwards via `git fetch origin refs/pull/<N>/head`. |

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

## standalone-self-management — completed 2026-09-04

A standalone binary can manage itself. The design record is
`contributor/adr/015-standalone-distribution-and-self-management.md`, whose
**Correction** section supersedes the original decision; the analysis of why
PyApp's own updater cannot be used is kept in
`.spec/shape-intents/standalone-self-management.md`.

What building a real binary found that no gate had:

1. **A venv is not a distribution.** The bake produced `uv venv --relocatable`,
   whose `bin/python` is a symlink to the interpreter it was made from and
   whose stdlib lives in that interpreter's prefix. Unpacked elsewhere it
   contains no Python. Killed all seven v0.2.1 binaries.
2. **uv installs a workspace root as editable by default**, leaving a `.pth`
   pointing at the build machine and no package in site-packages — a binary
   that starts and then imports nothing. `--no-editable`, asserted in the bake.
3. **`uv python install` offers only the host libc's distributions**, so a musl
   target baked on a glibc runner embeds a glibc interpreter.
4. **`pyapp update` does not exist** on a pre-baked build: hidden without
   `PYAPP_EXPOSE_UPDATE=1`, refuses under `PYAPP_SKIP_INSTALL=1`, and would
   pip-install from an index if it ran.
5. **`argv[0]` is `-c`** inside a PyApp binary, which made every mutating
   command read as a degraded install and made the registry record
   `<prefix>/bin/-c` — a path that never existed and was reported stale on the
   run that created it.
6. **The size-measurement step failed six working builds.** `ls a b` exits
   non-zero when one of the two is absent, and `set -o pipefail` turned that
   into a failed job after a successful ten-minute build.

Process notes:

- **A verification step that has not been run is not evidence.**
  `l-standalone-binary.toml` was written to catch defects 1 and 2 and carried
  the same wrong recipe, because its build step is expensive and was never
  executed. Two releases were burned before it was.
- **A test that asserts on host state passes locally and fails in CI.** The
  missing-manager test patched `resolve_uv` while the mode used `resolve_pipx`,
  so it was really asserting "this machine has no pipx" — true on a laptop,
  false on a GitHub runner.
- **One new test was vacuous on first run**: it computed the expected checksum
  from the tampered archive, so it verified a checksum of the tampering.

---

## plugin-visibility-and-catalog — completed 2026-09-08

Reported as one bug: an installed `functualize-mcp`'s commands were missing
from the `func` TUI. The audit found the same omission repeating on four
surfaces, a precedence rule with three different answers, and a whole
entry-point group that nothing read.

### What was wrong

`build_command_tree()` — its own docstring calls it "the shell's **one**
command tree" — composed only job nodes and the reserved `builtin` subtree. No
file under `_cli/tui/` called `get_plugin_commands()` at all. Every surface
reading the tree inherited the hole, and the user-visible result was worse than
a missing list row: typing `mcp serve` into the SmartBar produced no
pre-flight, no error and no output whatsoever.

The other three were independent:

| Surface | Symptom |
|---|---|
| `builtin info schema` | 67 entries, 0 plugin commands — the surface every `--help` epilog advertises to agents as "all commands" |
| shell completion | `shell-init bash` emitted `deploy` 9×, `builtin` 14×, `mcp` 0× |
| `functualize.jobs` | `EntryPointProvider` was never instantiated in `src/` |

And precedence, for one job colliding with one plugin command:

- `func collide` → job won, plugin dropped, `logger.debug` only
- `app.cli_command` → **plugin won, silently** (click's `add_command`
  overwrites, and `__call__` registers jobs first)
- `CliAdapter.run()` → `ValueError`

`check_name_conflicts` also inspected only `namespace is None`, so a namespaced
collision went unchecked there while `_dispatch_group` checked exactly that
case.

### Decisions worth not re-litigating

**`func --help` stays a global-flags page listing only `builtin`.** Chosen
deliberately when the alternatives were offered. The command index lives in
bare `func`, `builtin info schema`, and `func <namespace>`. Pinned by
`tests/cli/test_help_surface_pinned.py`; a change that adds a row there is
contradicting a decision, not fixing an oversight.

**Plugin kinds are derived from the entry-point group, never enumerated.**
`functualize.plugins` → adapter, `functualize.domains` → domain,
`functualize.*_providers` → implementation. Domains declare new provider groups
at runtime, so a name list would be stale on arrival. Lives in
`_primitives/plugin_kinds.py`, reached from `_cli` through `app.utils` — a
direct `_cli` → `_primitives` import breaks the contract, which was verified by
trying it.

**`functualize.jobs` is wired, and deliberately has no cache.** Enumeration
reads `EntryPoint.name`/`.value` — metadata — so it imports nothing and the
warm-boot-zero-imports guarantee survives. Re-reading the table each boot makes
cold/warm parity and no-ghost-after-uninstall true *by construction* rather
than by invalidation logic. `CACHE_VERSION` stayed at 19; the plan had called
for 20.

**`PluginCommand.needs_terminal` was not optional.** `func mcp serve` calls
`start_stdio()`, where stdout *is* the MCP protocol channel. Exposing plugin
commands in the TUI without a terminal declaration would have handed users a
way to hang their shell — the fix introducing the worse bug. Both transports
block in the foreground, so the flag selects the transport rather than whether
the command returns, and `CommandNode`'s plain bool survives.

### Deferred

**Plugin namespaces are absent from the discovery cache**
(`_cli/main.py:779-782`), so `func mcp serve` still classifies as
`Mode.UNKNOWN`, boots, and only then recovers inside `_dispatch_group`. The
observable behaviour is correct, so this is a startup-cost and architecture
concern rather than a defect. Caching plugin namespaces alongside job groups
would remove the detour and is the prerequisite for ever showing plugin
commands pre-boot.

**Entry-point job metadata is resolved on demand, not persisted.**
`JobNode._resolved_descriptor()` imports a `<entry_point>` job's module when
something asks it to *describe* itself, so `info schema` and the pre-flight
panel show real parameters. A bulk listing of many entry-point jobs therefore
imports each one. Persisting those descriptors, keyed on the installed
`(distribution, version)` set, would remove that — at the cost of owning
invalidation.

### Process notes

- **Two surfaces disagreeing was caught by nothing, because the parity harness
  compared the wrong thing.** `test_schema_surface_parity.py` exists because
  two renderings of a command's *fields* drifted. Nothing compared the
  *inventory* — which commands exist — so four surfaces could disagree with
  full green CI. `test_command_inventory_parity.py` closes that.
- **`git checkout -- <file>` cost finished work twice in one session**, both
  times by sabotaging a change that had not been committed yet. The rule in
  `wiring-discipline.md` §3 is not a formality; the failure mode is silent and
  the file simply reverts.
- **A test fixture that builds a plain `FunctualizeApp` loads every plugin on
  the machine.** `make_tui_app` did, so the panel-ring snapshot depended on
  which optional packages a developer had synced. It is now plugin-free by
  default.
- **Wiring a new provider into `boot_static` broke its zero-I/O promise.**
  Reading the entry-point table walks `sys.path`. Static wiring is the "I told
  you where my jobs are" path; discovery belongs to the discovering boot. The
  opposite mistake — wiring only `boot_static`, where a default app never looks
  — was made first and caught by the reachability test.
- **A source-text assertion is not a behavioural one.** A test grepping
  `inspect.getsource(_dispatch_group)` for a function name passed for the wrong
  reason and failed for the wrong reason too: editing the module mid-run made
  `linecache` return a neighbouring function's source.
