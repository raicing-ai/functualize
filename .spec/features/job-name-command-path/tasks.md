# Execution waves

Status: task review approved by the maintainer on 2026-10-19 (graph and both surviving smells accepted). T9 was then moved from wave 4 into its own wave because it shares `tests/cli/test_command_path_surface.py` with T8; same-wave tasks must touch disjoint files. Ordering only; no task content changed. All tasks use the fixed context anchor: `spec.md`, `contracts.md`, `research.md`, `plan.md`, `tasks.md`, and `.spec/STATE.md` (absent means no work in flight). The branch base is `91947bb4f90c611d588de9907f84e61edf2c1514`.

`[F]` is the allowed file set. Each task names its production call path and a wire that must be broken after a clean commit to prove the test reaches it. If retrieval reveals another file, amend this graph before editing it. Wave N+1 starts only when every task in wave N is checked.

## Wave 0 — lock the failing behavior

### T0 — Red acceptance fixtures

Status: [x] Complete. The base run failed eight named acceptance tests for the
measured shell, TUI, collision and root-help behavior; the separate literal-dot
leaf and explicit-group guard passed. The CLI path is `cli_run -> main ->
dispatch/help/info`, and the TUI path is `SmartBarAutoComplete -> group context`.

- Inputs: `spec.md` E1–E8 and the measured commands in `research.md`.
- [F] `tests/cli/test_command_path_surface.py` (new), `tests/tui/test_command_path_surface.py` (new), `tests/cli/test_collision_surfaces.py` (new).
- Invariants: isolated HOME and all XDG roots for subprocesses; keep the current deterministic winner and machine-readable identity assertions. Test the same fixture cold and warm. The printed suggestion is copied into a subprocess, not merely string-checked.
- Gate: run these tests on the base before a source edit; E1, E3, E4, E5 and E7 must fail for the measured reason. Record E2 and E6 as separate assertions so a later accidental dot ban cannot pass E3 by breaking E6. No task is marked done because an unrelated error made a test red.
- Dependency: none. Completion evidence: failing test names, expected/actual excerpts, and fixture paths.

## Wave 1 — establish shared data, with no delivery edit

### T1 — One path value and public descriptor property

Status: [x] Complete. `CommandPath.of` supplies both trie insertion and the
public descriptor property; focused trie and serialization tests pass. A
post-commit break of each call made 38 tests fail, then both files were restored.
Correction (whole-suite census before T10): the new export failed
`tests/test_public_api_surface.py`, which pins every public name; it now
expects `CommandPath`. File scope widened to that test.

- Inputs: `plan.md` chosen shape; `_job_segments` caller census from Serena and `rg -n '_job_segments' src tests plugins`.
- [F] `src/functualize/_types/naming.py`, `src/functualize/_types/descriptors.py`, `src/functualize/types/__init__.py`, `tests/discovery/test_group_trie.py`, `tests/core/test_command_path.py` (new).
- Invariants: `CommandPath.of(group, name)` is immutable, owns the existing segment derivation, and is the trie's insertion rule; `str(path)` joins segments with spaces but leaves a literal dot inside a leaf. `JobDescriptor.name`, `to_dict` and `from_dict` stay identity-shaped.
- Gate: unit cases for `suite.inventory`, `deploy.web.run`, ungrouped `tools.lint`, and `pack` in `ci`; existing trie and descriptor serialization tests pass. Wire: `GroupTrie.from_cache -> CommandPath.of` and `JobDescriptor.command_path -> CommandPath.of`; after commit, break each call and see its test fail.
- Dependency: T0. Completion evidence: unit output, import from `functualize.types`, and unchanged descriptor JSON keys.

### T2 — Structured collision finding without a payload change

Status: [x] Complete. Cold/warm cached, pipeline, and registry fallback tests
retain both claimant paths, names and legacy four-key payload. Post-commit
breaks of the three producer calls made their respective tests fail, then all
three files were restored.

- Inputs: `contracts.md` JSON object; current `DiscoveryFailure` and `job_name_collision` callers from Serena.
- [F] `src/functualize/_types/discovery_report.py`, `src/functualize/_discovery/collisions.py`, `src/functualize/_discovery/pipeline.py`, `src/functualize/_discovery/registry.py`, `tests/discovery/test_job_name_collisions.py`.
- Invariants: keep `DiscoveryFailure.as_dict()`'s four keys and deterministic winner. Attach typed claimant names and file paths only in memory. Re-derive findings on warm boot. A three-claimant chain is reportable against its final winner.
- Gate: one-file, two-file, provider/pipeline and warm-cache tests prove both paths and claimant names; full-info failure payload is unchanged. Wire: each of the three production collision producers calls the shared finding factory; sabotage each producer after commit.
- Dependency: T0. Completion evidence: assertions over typed details and exact legacy payload.

## Wave 2 — resolve shell paths

### T3 — Shell path acceptance and refusal

Status: [x] Complete. Both doors reject dotted tokens crossing group edges with
the spaces hint; spaced calls, dotted alias targets, literal-dot leaves and
mid-path group flags pass. Cold/warm shell refusal passed. After the clean code
commit, disabling either door's guard failed its targeted assertion; both
guards were restored and the targeted tests passed again.

- Inputs: T1; `walk_group_path` references from Serena; `TrieNode.path` and current `Mode.JOB` fast path.
- [F] `src/functualize/_cli/dispatch.py`, `src/functualize/_cli/main.py`, `src/functualize/app/adapters/cli.py`, `tests/cli/test_group_dispatch_trie.py`, `tests/group_options/test_adapter_entry_point_parity.py`.
- Invariants: reject a single token that traverses multiple group edges; accept a literal-dot leaf that traverses one edge. `func` and app Click door emit the spaces hint. Alias targets remain dotted identities, and `func deploy --env prod web run` keeps its flag position.
- Gate: E3 and E6 plus cold/warm and mid-path flag parity. Rewrite dotted-invocation tests to assert refusal while retaining their jobs' spaced success. Wire: `main -> walk_group_path -> trie.step` and app Click group resolution; sabotage both doors after commit.
- Dependency: T1. Completion evidence: exact error/exit and literal-dot success.

## Wave 3 — render paths and build TUI navigation

### T4 — Hints, usages and non-TTY listing

Status: [x] Complete. Shell and app suggestions emit copyable paths, grouped
leaf help names the full program/path, and bare non-TTY output uses paths.
The focused shell/app suite passed with only the later root-help fixture red.
After a clean commit, restoring dotted identity and leaf-only usage at two
renderers failed their end-to-end assertions; both wires were restored.
Correction (census): the app door printed "Did you mean:" and then raised
on a row its unit test's app could not render, leaving the list empty.
Rows are now rendered before the header; `tests/cli/test_fallbacks.py`
uses real descriptors and asserts `app deploy`. Printing the bare identity
again after the commit failed that assertion. File scope widened to that test.

- Inputs: T1/T3; source census in `research.md`.
- [F] `src/functualize/_cli/main.py`, `src/functualize/app/commands.py`, `src/functualize/app/adapters/cli.py`, `tests/cli/test_command_path_surface.py`.
- Invariants: fuzzy ranking and candidate set remain identity-based; render a matched descriptor's path only at output. Plugin and group suggestions remain valid. Click `prog_name` includes program plus full path on both doors. Bare non-TTY `func` prints paths; JSON stays identity.
- Gate: E1/E2 and copied-line execution on both doors, including a retired name and nested group. Verify leaf help on both direct and group routes. Wire: revert a renderer to `descriptor.name` or leaf `func_name` after commit and watch its end-to-end assertion fail.
- Dependency: T3. Completion evidence: before/after output and sabotage result.

### T5 — Always build the TUI's navigation trie

Status: [x] Complete. Jobs build the trie with or without GroupOptions; the
same path walk handles flags, dotted traversal refusal and literal-dot leaves.
No-options candidates include scoped children and provenance, and a selected
candidate runs. Focused TUI/group-flag suite passed (27 tests before the final
literal-dot case). After a clean commit, restoring the no-spec guard made E4
fail three assertions; the guard was removed again.
Correction (found during T8's wave run): the always-built trie swallowed
`builtin config ` completion, failing two pre-existing SmartBar subcommand
tests from this task's commit on. A walk inside the reserved `builtin`
subtree now returns to the registry's subcommand chain; disabling that
guard after its commit failed both tests again.
Census: two more stub fixtures (`tests/cli/test_cross_panel_sync.py`,
`tests/cli/test_diff_view_wiring.py`) gave the app no jobs while the bar
named one; they now carry the job they resolve. Test-only; scope widened.

- Inputs: T1/T3; Serena reference set for `build_group_option_trie`.
- [F] `src/functualize/_cli/tui/cli_arg_parser.py`, `src/functualize/_cli/tui/smart_bar_autocomplete.py`, `tests/group_options/test_tui_completion_context.py`, `tests/group_options/test_tui_group_flags.py` (its synthetic trie must contain its asserted shallow job), `tests/tui/test_command_path_surface.py`.
- Invariants: jobs produce the trie even with no `GroupOptions`; options only decorate it. The root offers group names, under `audit ` only that node's children, with provenance. Group flags still scope by position; a dotted group token is not offered as a runnable path.
- Gate: E4 plus with/without-options comparison, typed candidate execution, and no `builtin` under `audit `. Wire: restore the `if not specs: return None` guard after commit; E4 must fail.
- Dependency: T3. Completion evidence: candidate lists and sabotage result.

### T6 — Collision projection for human and JSON output

Status: [x] Complete. Typed findings are joined to the final descriptor by
identity. Clean catalog/detail key sets remain exact; affected rows add only
the five-field `collisions` array. One-file and two-file cold/warm info, three
claimants, narrow/full text and JSON, and legacy four-key failures passed.
After the clean commit, removing the projection calls made the full-report
test fail on the missing array; the calls were restored.

- Inputs: T2; `job_catalog` and `discovery_failures` reference sets from Serena.
- [F] `src/functualize/_cli/info.py`, `src/functualize/_cli/builtins.py`, `tests/cli/test_info_discovery_failures.py`, `tests/cli/test_job_detail_declaration.py`.
- Invariants: one projection joins typed findings to the final descriptor by identity; no message parsing. Text says path and both files; JSON says identity and adds `collisions` only on affected rows. Full report's `discovery_failures` shape and clean catalog rows remain compatible.
- Gate: E5 narrow and full info, one/two/three claimants, cold/warm. Rewrite exact-key tests to distinguish clean and colliding rows. Wire: remove the projection call after commit and prove text and JSON tests fail.
- Dependency: T2/T1. Completion evidence: output samples and byte-compatible legacy payload keys.

## Wave 4 — finish interactive and help surfaces

### T7 — TUI displayed path, presets and write-back

Status: [x] Complete. Browser rows, pre-flight header, selection into SmartBar,
the one bar emitter and callback-rendered recent presets use actual paths while
history and selection retain dotted identity. Literal-dot leaves and group
flags round-trip. Fifty focused TUI/write-back tests passed. After a clean
commit, restoring the raw browser identity failed its displayed-path test;
the display wire was restored.
Correction (census): browser rows for top-level nodes without a descriptor
(`builtin`, groups, plugin namespaces) had no `command_path`, so opening the
browser raised in every real project and 85 pilot/pre-flight tests failed.
`_cli/tui/job_listing.py` now gives such a row its own name as its path;
removing it after the commit failed seven pilot and snapshot tests. The
pre-flight test stubs gain the field the header reads. Scope widened to
`job_listing.py` and the three `tests/cli/test_preflight_*.py` files.

- Inputs: T1/T5 and ADR-009's one-emitter rule.
- [F] `src/functualize/_cli/tui/app.py`, `src/functualize/_cli/tui/sync.py`, `src/functualize/_cli/tui/panels/job_browser.py`, `src/functualize/_cli/data/invocation_preset.py`, `tests/tui_group_options/test_write_back_contract.py`, `tests/tui_group_options/test_panel_rendering.py` (existing browser expectation passes a bare identity), `tests/tui/test_command_path_surface.py`.
- Invariants: row, header, bar and recent preset show a path that resolves; history keys and selected job payloads remain dotted identity. `build_command_line` remains the sole bar emitter and keeps quoting and group flags mid-path.
- Gate: E6 on each display, preset selection and bar round trip, plus existing TUI write-back contract. Wire: restore one raw-identity or dot-split display after commit; its user-surface assertion fails.
- Dependency: T5. Completion evidence: TUI text, round-trip test and sabotage result.

### T8 — Resume hints, provenance and inline handoff

Status: [x] Complete. The blocked-run resume line is copied from stderr and
run on the app door: a literal-dot leaf prints `tools.release --wf-resume`,
a grouped job `ci ship --wf-resume`, and both finish the run. The deposit
response names the same paths. Both TUI refusals offer the trie's whole path
(`deploy web run` for `deploy web.run`). A mounted child's ungrouped job keeps
child attribution and a local literal-dot leaf stays `local`; E4's `(local)`
labels pass. No dot conversion remains at the six sites. After the clean
commit, restoring each of the four text conversions failed its surface test,
and dropping the child prefix match failed the provenance test; all restored.
Deviation: provenance matches a child namespace by identity prefix, not by
path, because an ungrouped child job is a single literal-dot leaf.

- Inputs: T1/T5; job-name conversion hit set from `rg -n` in `research.md`.
- [F] `src/functualize/app/_workflow_resume.py`, `src/functualize/app/adapters/click_params.py`, `src/functualize/_cli/completions/provenance.py`, `src/functualize/_cli/inline_tui.py`, `tests/cli/test_command_path_surface.py`, `tests/workflow/test_gate_drafts.py` (live deposit response is asserted here), `src/functualize/_cli/tui/cli_arg_parser.py` (the TUI resolution carries the trie's path for a refused dotted token), `src/functualize/_cli/tui/job_execution.py` (the in-panel worker renders the same hint from that resolution), `tests/tui/test_command_path_surface.py` (the in-panel hint is asserted here).
- Invariants: resume lines use path without changing stored workflow identity; provenance derives from group/path rather than splitting identity; inline handoff uses the trie result, not dot substitution.
- Gate: copied resume line executes, literal-dot leaf survives, `(local)`/`(job)` attribution remains; source ratchet has no job-name dot conversion at these sites. Wire: restore each text conversion after commit and see a surface test fail.
- Dependency: T5. Completion evidence: command transcript and provenance assertions.

## Wave 5 — root help (serialized: shares `tests/cli/test_command_path_surface.py` with T8)

### T9 — Root help from the discovered trie

Status: [x] Complete. `func --help` lists `builtin`, `deploy`, `hello` and
`suite` for the E7 project (nested `deploy.web` appears only as `deploy`),
with the global options intact. Rows are the top-level nodes of
`JobCommandProvider`, the trie-built tree the shell and app door walk, from
one boot inside the existing diagnostic scope; cold and warm output are
byte-identical. A module that fails to load keeps the other rows, and a
project whose boot fails on a reserved name still prints the page. The
builtin-only test is rewritten as an inventory/parity test against the bare
listing. After the clean commit, removing the row registration failed E7 and
three inventory tests; restored. Installed plugin namespaces stay out of
root help, which lists the project's jobs and groups.

- Inputs: T1/T3 and N3; the existing pinned decision/test in `tests/cli/test_help_surface_pinned.py`.
- [F] `src/functualize/_cli/main.py`, `tests/cli/test_help_surface_pinned.py`, `tests/cli/test_command_path_surface.py`.
- Invariants: `func --help` retains its global option descriptions and builtin subtree, adds top-level jobs and groups, uses one diagnostic boot and the same path source. A discovery failure must not hide diagnostic help. Cold and warm output agree.
- Gate: E7, group nesting and broken-project help. Rewrite the old “builtin only” test as a positive inventory/parity test; do not delete it. Wire: remove the discovered-row registration after commit and E7 fails.
- Dependency: T4. Completion evidence: root help Commands block, cold/warm comparison, sabotage result.

## Wave 6 — collision notices on every shell surface

### T10 — Collision notice on the command and in TUI

Status: [x] Complete. One function, `_cli/info.py::collision_notices`, renders
each finding with the existing renderer at the job's path. `func tools status`
and `func check` (group and job routes) print exactly one stderr line before
the job's own output, cold and warm, for one-file and two-file pairs; the
two-file line names `status_ (…tools_more.py) runs` and `status (…tools.py)
was dropped`. Group help prints the same line under the row, `info jobs`
carries it, the TUI pre-flight writes it under the header, and the browser
shows `tools ⚠` with that line on the row reaching it. `tools other` and
`hello` get none; rows still post their identity. After the clean commit,
removing each of the five calls failed its test; all restored. Residual: the
application's own CLI door does not print the line (its adapter is outside
this task's scope and cannot import `_cli`).

- Inputs: T6/T7; one text renderer from `src/functualize/_cli/info.py`.
- [F] `src/functualize/_cli/main.py`, `src/functualize/_cli/tui/app.py`, `src/functualize/_cli/tui/panels/job_browser.py`, `tests/cli/test_collision_surfaces.py`, `tests/tui/test_command_path_surface.py`, `src/functualize/_cli/info.py` (the notice lines are rendered at each job's path beside the existing renderer, so every surface reads one function), `src/functualize/_cli/tui/job_listing.py` (it builds the browser panel, which must receive the notices).
- Invariants: invocation writes one warning line to stderr before the final claimant runs; group help, TUI row marker and pre-flight warning agree. A clean command gets none; no duplicate warning under cold/warm discovery. A selected row still invokes identity.
- Gate: E5 all human surfaces and N2. Wire: remove the warning call from each door after commit; the corresponding test fails.
- Dependency: T6/T7. Completion evidence: one/two-file transcripts and TUI assertions.

## Wave 7 — ratchet and documentation

### T11 — Guard future spelling drift and document the contract

Status: [x] Complete. `tests/spec/test_command_path_ratchet.py` walks the AST
of every production source except `_types/naming.py` and rejects
`replace(".", " ")` or `split(".")` on a job-identity receiver; eleven
fixtures prove versions, modules, events, sections, vault targets,
namespaces, groups, typed tokens, query text and `rsplit` stay legal. Of the
sixteen base sites only the cached provider's canonical lookup remained; it
now calls `normalize_name`. The guide documents identity versus path, the
literal-dot leaf and the collision warning (replacing two stale claims), the
lab example calls `CommandPath` and `command_path`, and `CHANGELOG.md` has the
`### Fixed` entry. After the clean commit, reintroducing
`job_name.replace(".", " ")` in `click_params.py` failed the ratchet, and the
same call in a negative fixture failed that fixture; both restored. Not in
E8: six `rsplit(".", 1)` leaf/group derivations (for example
`JobDescriptor.func_name`) predate the feature and still treat a literal dot
as a boundary.

- Inputs: T1–T10; the `rg` source hit set recorded in `research.md`.
- [F] `tests/spec/test_command_path_ratchet.py` (new), `src/functualize/_discovery/cached_provider.py`, `docs/guides/jobs-discovery.md`, `CHANGELOG.md`, `examples/standalone/group_options_lab/tests/test_group_options_lab.py`.
- Invariants: E8 detects job-name dot conversions without rejecting unrelated version, module, vault or configuration dots. Any remaining split of a job identity for non-shell purposes is moved behind the naming boundary or documented as programmatic and proven outside E8. The public API has an example caller. Docs say shell path versus program identity accurately. Changelog adds a `### Fixed — …` entry under Unreleased.
- Gate: E8, example tests, `tests/skills/` if shipped skill prose changes, and a source scan for every former 15-surface site. Wire: reintroduce `job_name.replace(".", " ")` in one test fixture after commit and watch the ratchet fail.
- Dependency: T8/T9/T10. Completion evidence: ratchet failure proof, docs/example parity and changelog line.

## Wave 8 — complete verification and artifact lifecycle

### T12 — Whole-feature gate and artifact lifecycle

Status: [x] Complete. The E1–E8 selection across shell, app, TUI, cold/warm
discovery, group flags, literal-dot leaves, legacy JSON, and the source ratchet
passed (2283 passed, 389 skipped); the standalone group-options example passed
(18 tests). Ruff check and format, mypy, and all seven import contracts passed.
The dead-code delta introduced no new or tests-only findings. PR validation
records the tip-tier and artifact lifecycle evidence at handoff.

- Inputs: all preceding tasks and `contributor/guides/wiring-discipline.md`.
- [F] `.spec/STATUS.md`, this task ledger, then deletion-only last commit under `.spec/features/job-name-command-path/` after the feature-bearing push validates.
- Invariants: no source or test edit in the final artifact-clearing commit. The durable rule and any accepted compromise move to `.spec/STATUS.md` or an ADR. No tracker key, URL, run id or harness name in commit/PR title or body. `master` is reached only by a reviewed squash PR; designer never performs merge, release or deploy.
- Gate: E1–E8 end to end, both doors, TUI, cold/warm, group flags, exact legacy JSON keys; `uv run ruff check --fix src/ tests/ plugins/ examples/` then `ruff format --check`, `mypy src/`, `lint-imports`, relevant pytest (maximum two local invocations per verification), CI tip tier, and `uv run python .github/scripts/dead_code_delta.py <base> <head>`. Price the CI and test load; do not issue a single local suite expected past the 600 s cap. Confirm `contract-diff-carries-task-graph` parses this graph and `spec-artifacts-cleared` turns green after the deletion-only push.
- Dependency: T11. Completion evidence: command outputs, dead-code classification, PR validation, durable entry and artifact-clearing commit.

## Wave 9 — app-door child group path review finding

### T13 — Make a child group hint runnable through the app door

- Inputs: the reviewed app-door child-plus-`JOB_GROUP` finding and the existing E1/E6 command-path contract.
- [F] `tests/cli/test_command_path_surface.py`, `src/functualize/_types/naming.py`, `src/functualize/app/adapters/cli.py`, `src/functualize/_app/boot.py`, `.spec/features/job-name-command-path/contracts.md`, `.spec/STATUS.md`, this ledger.
- Invariants: preserve dotted identity and legacy JSON; do not split a literal-dot leaf; keep normalized child namespaces and group flags; no new dependency. The printed hint includes the app program name and runs when copied.
- Gate: compose `JobSources.children` and `JOB_GROUP` through the real app Click door; prove the regression red at the reviewed head, then green after the fix. Verify the spaced command, dotted refusal, and source ratchet. Run Ruff, format, mypy, import contracts, relevant pytest, and dead-code delta; report PR checks after the push. Break the repaired wire after a clean commit and watch the regression test fail, then restore it.
- Dependency: T12. Completion evidence: the red/green test output, concrete production call path, checks, and a written namespaced `CommandPath` decision.

## Task Dependency Graph

```json
{
  "waves": [
    {"id": 0, "tasks": ["T0"]},
    {"id": 1, "tasks": ["T1", "T2"]},
    {"id": 2, "tasks": ["T3"]},
    {"id": 3, "tasks": ["T4", "T5", "T6"]},
    {"id": 4, "tasks": ["T7", "T8"]},
    {"id": 5, "tasks": ["T9"]},
    {"id": 6, "tasks": ["T10"]},
    {"id": 7, "tasks": ["T11"]},
    {"id": 8, "tasks": ["T12"]},
    {"id": 9, "tasks": ["T13"]}
  ]
}
```
