# plugin-taxonomy — tasks (PR-1)

**2026-09-17 · base `feat/plugin-host-protocol` @ `80ec5f0`.** PR-1 only
(`spec.md` §B D1′). PR-2 and PR-3 are planned and atomized when cut.

Every file list below is the **hit set of the query that found it**, shown with
the task. Every acceptance gate is a command with a `before:` measured today and
an `after:` required value — `before:` values were produced by running the
command, not by reading.

**Prior-art note carried from `plugin-host-protocol`:** *every* reachability
gate that feature wrote during Plan was false when run — six for six — because
they named a test that ought to cover a seam rather than one that did. Each gate
below therefore names the sabotage and the expected failure **count**, and the
rule is: run the sabotage first; if the suite stays green, write the coverage
before writing the fix.

---

## Wave 0 — the enforcement must survive the move

### [x] T1 · `spec_gate.py` stops assuming one directory level

`plan.md` §1.1, `research.md` R1. **Nothing may move before this lands**: the
gate fails open by design, so a move-first sequence leaves `plugins/**/src/**`
unguarded with no error, no failing test and no log line.

**Files** — `git grep -n 'plugins/\*/src\|rel\[1\] == "src"\|GATED_GLOB_PARTS' -- .claude/`:
- `.claude/hooks/spec_gate.py` (25, 87)
- `.claude/hooks/agent_contract.py` (30)
- `.claude/hooks/plan_context.py` (42)
- `.claude/rules/spec-workflow.md` (32)

**Do:** replace the fixed-index predicate `len(rel) >= 3 and rel[1] == "src"`
with one that accepts a `src` segment at any depth below `plugins/` while still
excluding `plugins/<...>/tests/` and `plugins/conftest.py`. Update
`GATED_GLOB_PARTS` and the three prose copies.

**Acceptance gate** — import and **call** the predicate:
```python
from spec_gate import is_gated            # loaded by path
is_gated("plugins/functualize-http/src/functualize_http/x.py", cwd)
is_gated("plugins/adapters/functualize-http/src/functualize_http/x.py", cwd)
is_gated("plugins/substrates/functualize-substrate-sqlite/src/pkg/x.py", cwd)
is_gated("plugins/functualize-http/tests/test_x.py", cwd)
is_gated("src/functualize/_app/boot.py", cwd)
```
`before: True, False, False, False, True` (measured 2026-09-17)
`after:  True, True,  True,  False, True`

**Reachability:** the gate is a `PreToolUse` hook, so its production call path is
the harness, not the test suite. Verified by T2, which is why T2 is not optional.

**DONE** (`1251ef7`). Gate run: the five cases returned
`True, False, False, False, True` before and `True, True, True, False, True`
after — the predicate now answers *is any component `src`* rather than indexing
`rel[1]`. `GATED_GLOB_PARTS` was **deleted, not updated**: `git grep` found only
its own definition, so it was an unused second statement of the layout.

**Two corrections to this task as planned.**

1. **The prose sites were four, not three.** The hit set of
   `git grep -n 'plugins/\*/src'` also found
   `contributor/adr/010-spec-workflow-enforcement-point.md:50` and
   `.spec/STATUS.md:2381`, both stating the gate's scope as current fact, and
   `.claude/rules/spec-workflow.md`'s *not gated* list said `plugins/*/tests/`.
   All updated.
2. **A blocker the task did not predict.** `has_wave_graph` requires every wave
   to carry an `"id"` key; this file shaped them with `"wave"`, so the graph did
   not parse and the gate **denied every write to shipped code**. Fixed in the
   same commit. The Plan-phase check that "confirmed" the graph only counted the
   list's length — a vacuous check of exactly the kind this feature is about.

---

### [x] T2 · A test that fails when the gate stops guarding

The mitigation for `plan.md` §5 surviving smell 1 — shotgun surgery is tolerable
once it is not silent.

**Files:** `tests/hooks/test_spec_gate_depth.py` (new). `tests/` is ungated, so
this task needs no gate of its own to be written.

**Do:** load `.claude/hooks/spec_gate.py` by path and assert the five cases
above, parametrized, with the two-level cases named for the directory groups
`plan.md` §3 introduces.

**Acceptance gate:** `uv run pytest tests/hooks/test_spec_gate_depth.py -q`
`before: file does not exist` · `after: 5 passed`

**Reachability — run the sabotage first.** Revert T1's predicate to
`rel[1] == "src"`. Planned expectation: **2 failed**.

**DONE** (`1251ef7`). Measured: **6 failed, 13 passed** — the planned number was
an undercount written before the case list was finalised. The six name all five
grouped-layout paths (`adapters/`, `substrates/`, `credentials/`, `domains/`) plus
`test_the_predicate_indexes_no_fixed_position`. Restored with
`git checkout --`; 19 passed. The test is not vacuous.

Landed at `tests/spec/` rather than `tests/hooks/`, which holds the framework's
own `HookRegistry` tests and is a different subject. **19 tests**, not the 5 the
task described: 16 parametrized path cases plus three that guard the
over-correction (a file named `src`), depth independence, and the hook's
always-exit-0 invariant driven end to end through `subprocess`.

---

## Wave 1 — the move, and nothing else in the commit

### [x] T3 · `git mv` twelve directories; update every path consumer

`plan.md` §3, `contracts.md` §2.1. **A move-only commit.** Git detects renames
only for unchanged content, and T8 rewrites the sqlite plugin — so the move must
not share a commit with an edit.

**Layout** — Q4 **settled** (maintainer, 2026-09-17), four groups not five:
```
plugins/
  adapters/    functualize-http, functualize-lambda, functualize-mcp,
               functualize-flow-viz, functualize-inline
  substrates/  functualize-substrate-sqlite
  credentials/ functualize-aws, functualize-bitwarden
  domains/     functualize-ai, functualize-ai-pydantic,
               functualize-tasks, functualize-tasks-local
  conftest.py  PUBLISHING.md                    (stay at the plugins/ root)
```
An implementation is a **sibling** of its domain, not a child: every plugin stays
at exactly two levels, which is the one depth `members = ["plugins/*/*"]` and
T1's gate are taught. `functualize-inline` goes to `adapters/` because T5 moves
it to `functualize.plugins`, the adapters' group.

**Files** — the hit set of
`git grep -n 'plugins/\*\|plugins/functualize' -- pyproject.toml evals/ tests/ .github/ contributor/ plugins/PUBLISHING.md`:
- `pyproject.toml` (133) — `members = ["plugins/*"]` → `["plugins/*/*"]`
- `evals/providers/_harness.py` (172)
- `tests/conftest.py` (356)
- `tests/integration/test_substrate_durability.py` (149, 231, 279)
- `.github/workflows/ci.yml` (232, 235)
- `contributor/guides/plugin-development.md` (78-89) — *"already a glob"* becomes false
- `plugins/PUBLISHING.md` — its `plugins/<name>/…` verification commands

**File list corrected during T1** — the Plan-phase query
(`git grep -n 'plugins/\*'` over `pyproject.toml evals/ tests/ .github/`) was
too narrow. Widening it to the whole tree found two more, and one of them fails
the same silent way R1 does:

| File | Line | What | Fails how |
|---|---|---|---|
| `tests/primitives/test_entry_point_cache.py` | 46 | `sorted((_ROOT / "plugins").glob("*/src"))` — a **runtime glob** | **SILENTLY.** After the move it returns `[]`, so the test walks zero plugin files, asserts nothing about them, and **stays green**. A vacuous test, which is the failure mode `plan.md` §5 entry 1 exists to make loud. Its docstrings at 11, 22, 75 also name the old layout |
| `contributor/guides/plugin-development.md` | 192 | `rg 'app[.]event_bus' plugins/*/src` — an instruction a contributor runs | Silently — returns nothing, reads as "no clients" |
| `src/functualize/_types/host.py` | 30, 33 | a documented census command in the port's docstring | Silently — same shape |
| `examples/standalone/plugin_host/README.md` | 46 | "measured client count across `plugins/*/src`" | Prose |
| `tests/spec/fixtures/adapters_against_the_port.py` | 29 | an `rg` command in a comment | Prose |
| `.graphifyignore` | 1 | comment says the graph is scoped to `plugins/*/src/` | Prose only — the file is **exclude-only**, so the move does not change what it ingests |
| `.agents/skills/code-intel/SKILL.md` | 144 | describes `.graphifyignore`'s scope | Prose |

**Deliberately NOT changed** — dated measurement records, which would become
false if updated: `contributor/architecture/audit-engine-encapsulation.md:26`,
`audit-entrypoint-coverage.md:4`,
`contributor/architecture/run-model/evidence/verified.md:45`,
`.agents/skills/code-intel/SKILL.md:208`. Each states what a command returned on
a given day against the layout of that day.

**Acceptance gates:**
| Gate | before | after |
|---|---|---|
| `uv sync --all-packages` | resolves, 12 members | resolves, 12 members |
| `uv build --all-packages`; `echo $?` | 0 | 0 |
| `uv run pytest tests/ -q` | 10,681 passed | 10,681 passed (+5 from T2) |
| `ls -d plugins/*/functualize-*/ \| wc -l` | 0 | 12 |

**Reachability — run the sabotage first.** Leave `members = ["plugins/*"]` after
moving. Expected: `uv sync --all-packages` finds **0** workspace packages.

**DONE** (`c232656`). Two sabotages, because the task turned out to carry two
different failure modes:

- **A — the silent one.** Revert `tests/primitives/test_entry_point_cache.py`'s
  runtime glob to `glob("*/src")`. Before the fix that returned `[]` and the
  scan **passed while walking zero files**. With the added non-empty assertion
  it now errors at *collection*: `AssertionError: no plugin src/ directories
  found`. Restored; 9 passed.
- **B — the loud one.** `members = ["plugins/*"]` → **0** workspace packages;
  `["plugins/*/*"]` → **12**.

**Measured results:** root suite **10,697 passed / 0 failed**; examples **212**;
twelve plugin suites run one at a time (a shared invocation collides on
`tests.conftest`, which is why `CONTRIBUTING.md` says one at a time) —
**436 passed**; `uv sync --all-packages --all-extras` and
`uv build --all-packages` exit 0; mypy clean on 356 files; lint-imports 7/0.

**Three root tests failed on the first full run** and were fixed here, all the
same shape — a path built as `plugins/<distribution>/…`:
`tests/cli/test_plugin_catalog.py::test_every_distribution_exists` (now globs
`plugins/*/<distribution>`, so the group stops being its business),
`tests/types/test_every_surface_declares_its_family.py` and
`tests/types/test_run_request.py` (both hard-code three adapter paths).

**An environment trap worth recording.** The task's own gate,
`uv sync --all-packages`, **dropped the `[cli]` extra** and mypy then reported 6
errors in `_cli/tui/functualize_autocomplete.py` — a file this task never
touched — because `textual-autocomplete` was uninstalled. `.spec/TESTING.md`
documents exactly this (*"the three sync flags prune each other … running one
alone produces failures that look like real defects"*). The correct gate is
`uv sync --all-packages --all-extras`.

**Also observed:** `functualize-state-sqlite`'s suite is **25 passed / 0
failed**. `.spec/STATE.md` recorded 4 failures there as proven pre-existing
(subprocess tests that SIGKILL and cannot inherit an in-process `monkeypatch`).
They pass once the plugins are really installed, which `--all-packages
--all-extras` does. Nothing was masked — T10 re-checks this against AC-22.

---

## Wave 2 — one rule for entry-point groups

### [x] T4 · `_primitives/entry_point_groups.py`, and nine readers import it

`plan.md` §1.1 and §3. The set of groups core reads is currently implicit —
three inline string literals, three module constants in three layers, two
dynamic. Nothing can compare it against what the ecosystem declares.

**Files** — the hit set of `rg -n 'entry_points\(group=' src/functualize`:
- `src/functualize/_primitives/entry_point_groups.py` (new) — `READ_GROUPS`
- `src/functualize/app/utils.py` (60, 189) — re-export, the seam `_cli` must use
- `src/functualize/_app/boot.py` (206)
- `src/functualize/_plugins/loader.py` (326)
- `src/functualize/_plugins/domain_registry.py` (31, 156)
- `src/functualize/_config/registry.py` (169, 193)
- `src/functualize/_cli/skills.py` (166)
- `src/functualize/_cli/tui/display_provider_discovery.py` (82)

`_discovery/providers.py:790` is **out of scope**: its group is caller-supplied
(a job source's own), not a group core owns.

**Layer constraint, non-negotiable:** `_cli` may not import `_primitives`
(import-linter *"`_cli` uses public API only"*). Both `_cli` readers go through
`functualize.app.utils`, exactly as `classify_group` already does.

**Acceptance gates:**
| Gate | before | after |
|---|---|---|
| `git grep -c 'entry_points(group="functualize' -- src/` | 3 | **0** |
| `uv run lint-imports` | 7 kept / 0 broken | 7 kept / 0 broken |
| `uv run mypy` | green, 364 files | green |

**Reachability — run the sabotage first.** Change one member of `READ_GROUPS`
to a typo (`functualize.pluginz`). Planned expectation: `tests/plugins` goes red.

**DONE** (`15647db`). The planned scope was **the wrong suite, and nearly
produced a false negative.** `tests/plugins` fails **1** — `test_init_default_group`,
which asserts the literal equals the literal. That is a unit test of a constant,
not evidence of a call path, and on its own it would have been indistinguishable
from cosmetic wiring: 687 tests in that directory passed with the group name
typo'd, because they mock `entry_points`.

Widening to `tests/core tests/_cli tests/cli tests/app` gives **11 more, 12 in
total**, and the meaningful ones are behavioural:

- `tests/cli/test_plugin_command_dispatch.py` — **6 failures**. Plugin commands
  stop being dispatched at all: with the group misspelled, no installed plugin
  is discovered, so its CLI commands simply do not exist.
- `tests/cli/test_schema_surface_parity.py` — **3 failures**. CLI/MCP schema
  parity breaks because the MCP plugin never loads.
- `tests/core/test_app.py`, `test_config_objects.py`,
  `tests/cli/test_info_subcommands.py` — 1 each.

**Production call path:** `FunctualizeApp.__init__` → `_app/boot.py` →
`PluginLoader(group=PLUGINS)` → `entry_points(group=self._group)` → the
installed distribution's `plugin.__call__(app)` → the CLI commands it registers.
Restored; 49 passed.

**Gate met:** `git grep -c 'entry_points(group="functualize' -- src/` **3 → 0**.
lint-imports 7/0; mypy clean on **357** files; 3,477 tests green across plugins,
config, core, app, primitives and `_cli`.

**One design decision taken here, not in the plan.** The task said "nine readers
import it"; **six do**. `_discovery/providers.py:790` takes its group from the
caller (a job source's own) and was already out of scope. The other two are
`_cli/skills.py` and `_cli/tui/display_provider_discovery.py`, and the
`_cli uses public API only` contract forbids that layer importing `_primitives`.
Routing the constants through `functualize.app.utils` would widen the **public**
API — and `contributor/reference/public-api-example-coverage.md` makes every
public symbol owe a caller in `examples/` — to buy nothing at runtime. Those two
constants stay where they are and are tied to `READ_GROUPS` **by test**, in T6.

---

### [x] T5 · The three orphan groups move to `functualize.plugins`; `vault_key_providers` is deleted

`spec.md` §I (Q2, Q3, Q5 — settled), `contracts.md` §3.3, §3.4.

**Files** — the hit set of
`git grep -l -E 'functualize\.(state|interactivity)_providers' -- . ':!.spec' ':!CHANGELOG.md'`, plus the two `vault_key_providers` sites:
- `plugins/substrates/functualize-state-sqlite/pyproject.toml` (23)
- `plugins/adapters/functualize-inline/pyproject.toml` (24)
- `examples/plugins/custom_state_backend/pyproject.toml` (10)
- `src/functualize/_cli/data/plugin_catalog.toml` (76, 97)
- `src/functualize/_cli/plugin_cmd.py` (7, 86) — the docstring examples
- `pyproject.toml` (49) — `vault_key_providers`, **deleted**
- `src/functualize/_config/vault_keys.py` (6) — the sentence advertising it, deleted
- `examples/plugins/custom_state_backend/README.md`, `.../_plugin.py` (3, 31)
- `examples/plugins/README.md` (30), `docs/contributing.md` (625)
- `plugins/adapters/functualize-inline/README.md` (36)
- `tests/_cli/test_plugin_cmd.py` (52, 58, 104)
- `tests/cli/test_plugin_catalog.py` (142)
- `tests/primitives/test_plugin_kinds.py` (27, 30)
- `tests/scaffold/test_domain_scaffold.py` (386)
- `tests/standalone/test_domains_command.py` (78)

The last five are **tests asserting the current wiring**; they change meaning,
which is why they are in the file list rather than expected to pass unchanged.
`test_plugin_kinds.py` keeps its cases — `classify_group` is unchanged, and the
point of those rows is that classification is derived. Add a comment there
recording that classifying a group is not the same as loading it.

**Acceptance gates:**
| Gate | before | after |
|---|---|---|
| `git grep -l -E 'functualize\.(state\|interactivity)_providers' -- . ':!.spec' ':!CHANGELOG.md' \| wc -l` | 15 | 0 |
| `git grep -c vault_key_providers -- . ':!.spec'` | 2 files | 0 |
| AC-3: a test boots an app with the substrate plugin installed **via its entry point** and asserts `app.substrate` is the SQLite one | absent | present, green |

**Reachability — run the sabotage first.** Revert
`functualize-state-sqlite/pyproject.toml` to `functualize.state_providers`.

**DONE.** The caveat was right: the entry-point change only takes effect after
`uv sync --all-packages --all-extras` re-installs the distribution's metadata,
so the sabotage is *edit the pyproject, re-sync, run*. Confirmed working in both
directions by probe before the test was written — a plain `FunctualizeApp` in an
empty directory resolved `JsonFileSubstrate` under the old group and
`SQLiteSubstrate` under the new one.

**Gates met.** AC-1: **0 orphan groups** — a script walking every shipped
`pyproject.toml` finds every declared `functualize.*` group either in
`READ_GROUPS` or named by a live `DomainMetadata`. That is the feature's
headline gate. AC-3: `tests/spec/test_a_substrate_plugin_loads_through_its_entry_point.py`,
4 tests, boots a real app with no explicit plugins and asserts the substrate is
the plugin's, that every store holds the *same instance*, and that the database
lands where the filesystem substrate would have put its files.

**AC-2's gate was mis-written and is corrected here.** It asked for **0 files**
naming `state_providers`/`interactivity_providers`. Four remain, and all four
should: `_config/vault_keys.py` and `_primitives/entry_point_groups.py` explain
*why the group was removed*, `tests/_cli/test_plugin_cmd.py` records what its
example used to be, and `tests/primitives/test_plugin_kinds.py` keeps the
classifier cases — `classify_group` is generic over the `<x>_providers` shape
and still maps them to `IMPLEMENTATION`, which is the point worth pinning:
**classifying a group is not loading it.** The honest gate is *0 files that
declare or wire a dead group*, which is met.

---

### Two things this task uncovered that the plan did not predict

**1. The suite's storage backend was about to be decided by the environment.**
Making the plugin load meant `uv sync --all-packages` (what CI runs) silently
switched the whole root suite to SQLite, while a plain `uv sync` left it on the
filesystem. Same suite, different backend, no signal — and it bypassed both
`FUNCTUALIZE_TEST_SUBSTRATE`, which exists to make exactly that choice
deliberately, and the `json_substrate` marker that goes with it.

`tests/conftest.py::_hide_default_changing_plugins` now hides the substrate
plugin from discovery for the root suite, patched at
`_primitives.entry_points.entry_points` — the single choke point every reader in
`src/` goes through. `tests/spec/test_a_substrate_plugin_loads_through_its_entry_point.py`
opts back in with the new `installed_plugins` marker. One file boots the real
thing on purpose instead of ten thousand doing it by accident.

**2. A real product defect, reachable for the first time (maintainer decision to
fix it here, 2026-09-17).** `SQLiteStatePlugin._db_path` returned
`fresh_root / ".functualize" / "state.db"`, so merely having the plugin installed
created a `.functualize/` directory **in whatever directory the app ran in** —
reproduced in an empty temp dir. Creating `.functualize/` is the documented
switch from *standalone* to *project* mode, so the plugin silently promoted
every directory a user ran in, and littered a database beside every loose
script. The repo states the opposite intent in `tests/cli/test_state_mode_report.py`'s
own docstring.

The plugin's comment claimed it followed *"the same rule the filesystem
substrate follows"*. It did not: `JsonFileSubstrate.for_project` goes through
`resolve_fresh_location`, which returns the XDG cache in standalone mode. The
fix routes `_db_path` through that same call — `functualize.app.utils.resolve_fresh_location`
is already public API, so no new surface was needed. Verified in both modes: a
loose directory is left **empty** (db at `~/.cache/functualize/<id>/state.db`),
a declared project gets `<project>/.functualize/state.db`.

**60 tests failed when the plugin first loaded; 57 were this bug.** The other 3
are `tests/cli/test_state_mode_report.py`, whose subject genuinely is a JSON
file's location, and they now pin the filesystem through the product's own
`[plugins] disabled` mechanism — subprocess runs no in-process patch can reach.
That pin exposed a third finding, recorded not fixed: `disabled` matches the
**entry-point** name (`sqlite`, `_plugins/loader.py:335`), not the plugin's
`name` attribute (`sqlite-state`, `:504`), and a `FunctualizeApp` built in user
code does not read `[plugins] disabled` from config at all — only `_cli/main.py`
does. That asymmetry is `contributor/architecture/surface-boundary.md`
territory and is left alone here.

---

### [x] T6 · The gate that stops an orphan group recurring

`plan.md` §3, the rule in `contracts.md` §3.3.

**Files:** `tests/spec/test_every_declared_group_has_a_reader.py` (new).

**Do:** parse every shipped `pyproject.toml` — core, the 12 plugins, the 3
examples — collect every `[project.entry-points."functualize.*"]` group, and
assert each is in `READ_GROUPS` **or** is the `entry_point_group` of an
installed `DomainMetadata`. The file list is discovered by glob, not hard-coded,
so a new plugin is covered without editing the test.

**Acceptance gate:** `uv run pytest tests/spec/test_every_declared_group_has_a_reader.py -q`
`before: file does not exist; the rule it asserts is violated 4 times`
`after: 1 passed`

**Reachability — run the sabotage first.** Re-add
`[project.entry-points."functualize.state_providers"]` to any plugin. Expected:
**1 failed**, naming that file and that group.

**DONE.** Two sabotages, because the gate has two directions and only one was
planned.

- **Declared → read.** Re-declared `functualize.interactivity_providers` on
  `functualize-inline`: **1 failed, 28 passed**, and the failure id is
  `[plugins/adapters/functualize-inline/pyproject.toml]` — the parametrisation
  names the file to fix rather than making a reader go looking.
- **Read → declared.** Typo'd `SKILLS` in `READ_GROUPS`: **2 failed** —
  `test_every_read_group_is_actually_read_somewhere_in_src` and the `_cli`
  link test. A constant whose reader was deleted is the same defect mirrored,
  and the next manifest to declare that group would be silently dead again.

Restored; **29 passed**.

**Three things this task does that the plan did not ask for**, each because the
gate would otherwise be able to pass while checking nothing:

1. **Manifests are found by glob, never listed** — and
   `test_the_manifest_scan_finds_the_shipped_plugins` asserts the glob found at
   least thirteen. T3 moved these directories one level deeper and two globs
   elsewhere started matching nothing *silently*; a gate with that failure mode
   is worse than no gate.
2. **Domain groups come from an AST walk of the shipped sources, not from
   installed metadata.** A plain `uv sync` does not install the workspace
   plugins, so `discover_domains()` returns nothing and the test would report
   `functualize.ai_providers` as an orphan on a clean checkout — a false alarm
   that teaches people to ignore the gate.
3. **The `_cli` link T4 deferred** is asserted here: `functualize.skills` and
   `functualize.displays` are read from a layer that may not import
   `_primitives`, so their constants are tied to `READ_GROUPS` by test.

---

## Wave 3 — the storage seam

### [x] T7 · Remove the middle man; the provider goes lazy and compare-and-swap

`plan.md` §1.3. **One deletion closes AC-4, AC-5, AC-6, AC-7 and AC-8.**

**Files** — the hit set of serena `find_referencing_symbols(TaskDocument)` plus
`git grep -n TaskDocument`:
- `plugins/domains/functualize-tasks-local/src/functualize_tasks_local/_provider.py` — delete `TaskDocument`; rewrite `LocalTaskProvider`
- `plugins/domains/functualize-tasks-local/src/functualize_tasks_local/_plugin.py` (17, 31, 66-67)
- `plugins/domains/functualize-tasks-local/tests/test_local_provider.py` (4, 12, 18-31)
- `tests/plugins/test_tasks_local_prefix_properties.py` (16, 23, 33)
- `plugins/substrates/functualize-state-sqlite/src/functualize_state_sqlite/_plugin.py` (70-73, 75-83) — stop swallowing; the docstring documents the swallow as deliberate, so it changes with the behaviour

**Do:**
1. `LocalTaskProvider.__init__(substrate_source: Callable[[], StoreSubstrate])`.
   Not a port — one consumer, no discovery, no registry (`plan.md` §5 entry 3).
2. `list()` → one `read("tasks")`.
3. Every mutation → read → modify → `write(key, payload, expect=stored.revision)`
   → on `False`, re-read and retry, bounded. `Stored.revision` and
   `write(expect=)` are already in the port (`_types/protocols.py:718-800`);
   **nothing widens**.
4. Tasks stored as nested mappings, not `json.dumps` strings.
5. `_plugin.py` passes `lambda: app.substrate` and does **not** touch the
   substrate at `APP_READY`.
6. `functualize-state-sqlite/_plugin.py` lets the install failure surface.

**Acceptance gates:**
| AC | Gate | before | after |
|---|---|---|---|
| AC-6 | substrate `read` calls during `list()` of 10 tasks, counted with a spy | **11** | **1** |
| AC-5 | two concurrent `update()` on a substrate whose `lock()` is a no-op | one update lost | both land |
| AC-7 | `func builtin data show` on a project with tasks | escaped JSON | task titles |
| AC-4 | install a substrate after the engine resolved one | swallowed into `logger.exception` | surfaces |
| AC-8 | the §1.2 probe, with `LocalTasksPlugin.name` forced to sort **before** the substrate plugin | `JsonFileSubstrate` | `SQLiteSubstrate` |
| — | `git grep -c TaskDocument -- . ':!.spec'` | 5 files | 0 |

**Reachability — run the sabotage first.** Restore the unconditional
`write()` (drop `expect=`). Expected: the AC-5 test fails. Then restore the
eager `app.substrate` read in `_plugin.py`. Expected: the AC-8 test fails.

**DONE** (`c4b6416`). Both landed, and the first one caught a **vacuous test of
my own**:

- **A — drop `expect=`.** First attempt: **0 relevant failures**. The AC-5 test
  as written did two `add` calls *in sequence*, and sequential writers never
  collide, so it passed with compare-and-swap removed. Rewritten to force the
  interleaving — writer B lands between A's read and A's write — after which the
  sabotage fails `test_an_interleaved_update_does_not_erase_the_other`.
- **B — restore the eager read.** Fails
  `test_the_substrate_wins_whichever_hook_runs_first[sorts-before-the-substrate]`,
  the exact case the bug produced, and the run now carries the refusal in the
  log: *"the substrate is already in use by this app's engine"* — which is AC-4
  working.

**Measured:** tasks-local suite **15 passed**; the AC-8 file **5 passed**; the
rewritten property suite **7 passed** under `--run-slow`; mcp **32**, tasks
**15**, root `tests/plugins` **688 passed**. mypy for the package **11 → 9**,
*below* its baseline. Root mypy clean on 357 files.

**AC-4 is met as "reported", not "raised to the user".** The plugin no longer
catches; boot's hook isolation catches and logs a WARNING naming the hook and
the reason. That is the layer that owns hook failures, and the message is the
`install_substrate` refusal in full. Recorded rather than overclaimed.

**AC-7's literal wording does not match the command.** It asked that
`func builtin data show` "renders task titles"; that command renders counts and
store descriptions, never task contents, so no edit to it could satisfy the
sentence. The *substance* — a task is data, not an escaped string — is met and
asserted by `test_a_task_is_stored_as_fields_not_as_a_string`. On disk::

    {"tasks": {"10440f294f08": {"title": "Deploy the service", "status": "pending", ...}}}

where it used to be a JSON string inside a JSON value.

**A port limitation found here, not closed here.** `write(expect=None)` is
unconditional and the port cannot express *expect this key to be absent*, so the
**first** write to a fresh document cannot be compare-and-swapped and two
processes creating the first task on a no-op-lock backend can collide. AC-5 asks
about concurrent `update()`, which operates on an existing document and *is*
safe. Declared as surviving smell 6 in `plan.md`, pinned by a test that asserts
the limitation rather than a false guarantee, and carried to
`sdd/substrate-conformance` as its Q2 — where the decision belongs, because it
is about every substrate rather than about tasks.

---

## Wave 4 — the rename, then truth

### [x] T8 · `functualize-state-sqlite` → `functualize-substrate-sqlite`

`contracts.md` §1.1, §4.1. **After T7**, because `SQLiteStatePlugin.name` is the
sort key `plan.md` §1.2 proved load-bearing; once T7 lands, the name cannot
matter.

**Files** — the hit set of
`git grep -l -E 'functualize-state-sqlite|functualize_state_sqlite' -- . ':!.spec' ':!CHANGELOG.md'` → **54 files**, minus 2 untracked `graphify-out/` artefacts and 3 `uv.lock`s regenerated at the end → **49 edited by hand**. Notable ones:
- `plugins/substrates/functualize-state-sqlite/` → `functualize-substrate-sqlite/`, and `src/functualize_state_sqlite/` → `src/functualize_substrate_sqlite/`
- class `SQLiteStatePlugin` → `SQLiteSubstratePlugin`; `name` `"sqlite-state"` → `"substrate-sqlite"`; config section `plugin.sqlite-state` → `plugin.substrate-sqlite`; `description` reworded
- `pyproject.toml` — `[all]`, `[tool.uv.sources]`
- `src/functualize/_cli/data/plugin_catalog.toml` (74-78)
- `src/functualize/_cli/scaffold/templates/full-interactivity/pyproject.toml.j2` (11, 20), `main.py.j2`, `README.md.j2`; `scaffold/cli.py`, `scaffold/registry.py`
- `tests/conftest.py` (356, 360) — path **and** name, one fixture
- `tests/integration/test_substrate_durability.py` (149, 231, 279)
- `src/functualize/_types/host.py`, `_primitives/fresh_store.py`, `_primitives/scope_store.py` — prose citations
- **deletions:** `SQLiteStateBackend` in `plugins/.../README.md` (16, 19), `examples/persistent_counter/persistent_counter.py` (10, 19), `examples/persistent_counter/test_persistent_counter.py` (10, 22) — it is defined nowhere
- 5 ADR / codemap / guide files keep the **old** name where they narrate history; they gain the new one where they describe the present

**Acceptance gates:**
| Gate | before | after |
|---|---|---|
| `git grep -l -F functualize-state-sqlite -- . ':!CHANGELOG.md' ':!.spec'` | 49 files | 0 |
| `git grep -l -F functualize_state_sqlite -- . ':!CHANGELOG.md' ':!.spec'` | 14 files | 0 |
| `git grep -l -F SQLiteStateBackend -- . ':!.spec'` | 4 files | 0 |
| `python -c "import functualize_substrate_sqlite as m; print(m.__all__)"` | ImportError | `['SQLiteSubstrate', 'SQLiteSubstratePlugin']` |
| AC-16: the `persistent_counter` example imports resolve **and** the directory is collected | broken, uncollected | resolves, collected |
| `uv sync --all-packages && uv build --all-packages` | green | green |

**Reachability — run the sabotage first.** Leave `tests/conftest.py:356`
pointing at the old directory. Expected: every test using that fixture errors at
collection.

**DONE** (`d0af29b`). **The planned sabotage passes, and the caveat was right.**
Pointing the `sys.path` insert at the old directory changes nothing: the
distribution is *installed* in a synced workspace, so the import resolves
regardless. That line is a fallback for an environment where the plugin is not
installed — a plain `uv sync` — and it cannot be exercised in the environment CI
and this session use. Recorded rather than dressed up.

Two sabotages that do bite, on the things the rename actually had to get right:

- **The import name** in the same fixture: `from functualize_state_sqlite…` →
  **205 errors** under `FUNCTUALIZE_TEST_SUBSTRATE=sqlite`.
- **The entry-point target** in the plugin's manifest, after a re-sync:
  **4 failed** in `test_a_substrate_plugin_loads_through_its_entry_point.py`.

**Gates met:** `functualize-state-sqlite` **0 files** outside CHANGELOG, `.spec/`
and the ADRs; `functualize_state_sqlite` **0**; `SQLiteStatePlugin` **0**;
`SQLiteStateBackend` **0** except the docstring recording its removal.
`python -c "import functualize_substrate_sqlite"` → `['SQLiteSubstratePlugin',
'SQLiteSubstrate']`. `uv build --all-packages` 26 artifacts, exit 0.

**Two things in this package were false, not merely misnamed**, and are fixed
rather than renamed:

- The README's API reference listed **five** classes. The package exports
  **two**, and none of the five is either of them. Rewritten against what
  exists, with the schema and why it is a document store.
- `examples/persistent_counter/` imported `SQLiteStateBackend`, defined nowhere
  in the repository. `testpaths = ["tests"]` keeps the root run out of that
  directory and CI runs one plugin's examples out of twelve, so the example a
  reader is pointed at could not have run. Rewritten against `SQLiteSubstrate`;
  3 tests, green (AC-16).

ADR-022 keeps the old name and gains a pointer to the new one. The CHANGELOG and
the other two ADRs keep it outright — a dated decision that renames itself stops
being a record.

---

### [x] T9 · Plugin-surface honesty and documentation truth

`spec.md` §D.5, §D.6, A.5, A.6.

**Files** — four independent hit sets:
- **Q6, `MCPAdapterPlugin`:** `plugins/adapters/functualize-mcp/src/functualize_mcp/_plugin.py` (22-34); `src/functualize/app/adapters/_validation.py` (28) — give `validate_adapter` a production caller
- **the always-False probe:** `plugins/domains/functualize-ai/src/functualize_ai/_provider_discovery.py` (205-227)
- **the mypy-opaque table:** `plugins/domains/functualize-ai/src/functualize_ai/__init__.py` (140)
- **`_state_fallback.py`** (119 LOC, retired protocol, and its advice at line 30)
- **doc truth:** `plugins/PUBLISHING.md` (104, 113-115, 194, 226); `contributor/architecture/codemaps/overview.md` (73), `modules.md` (153), `dependencies.md` (117), `entry-points.md` (14-21 — it lists 3 groups where 7 static ones exist)
- **added during T3**, found while fixing paths and left for this task because
  they are *truth* problems rather than *path* problems:
  `CONTRIBUTING.md` (459) describes `plugins/functualize-fullscreen-tui/` —
  **the directory does not exist** (`ls` → nothing, at either depth) — and says
  it "does not count toward the thirteen"; there are **twelve**. T3 removed the
  one thing in that file that was a broken *command* (an install of the retired
  `functualize-state`, dead since ADR-022) and left the prose here

**Acceptance gates:**
| AC | Gate | before | after |
|---|---|---|---|
| AC-17 | `validate_adapter` production callers; `MCPAdapterPlugin` passes it | 0 callers; 2 of 3 members missing | ≥1 caller; passes |
| AC-18 | `git grep -n 'hasattr(app, "resolve_model")' -- plugins/` | 1 | 0 |
| AC-19 | `uv run mypy plugins/domains/functualize-ai-pydantic` | 47 errors | recorded, **not increased**; the `__getattr__` share removed |
| AC-20 | `git grep -l -F functualize-state -- plugins/PUBLISHING.md contributor/architecture/codemaps/` | 4 files | 0 |
| AC-11 | live `StateBackend`/`ExecutionStore` references (imports and calls) in `docs/ examples/ plugins/`, ADRs excluded | 8 sites / 4 files | 0 |
| AC-11b | prose mentions recording the retirement, same paths | 24 files | **≥16 preserved** — must NOT go to zero |

**Reachability:** AC-18 changes behaviour — a project with an `[ai]` section
starts being honoured.

**DONE** (`97f7518`). Three sabotages, all landing:

- **Restore the always-False probe** (`getattr(app, "resolve_model")`):
  `test_the_ai_section_is_actually_asked_for` fails — the config facade is never
  consulted, which is exactly what shipped.
- **Delete `MCPAdapterPlugin.run`**: `test_exactly_the_marked_adapters_fail_conformance`
  fails. That file's fixture had `MCPAdapterPlugin` marked `# want-error`
  *because* it never conformed; the mark is now removed and its absence is what
  bites.
- **The production check itself** is covered by
  `tests/plugins/test_a_false_adapter_claim_is_reported.py` — a class with the
  label and not the methods is warned about by name, a real adapter and a
  non-adapter are silent, and the shipped MCP plugin no longer trips it.

**Measured gates:**

| Gate | before | after |
|---|---|---|
| AC-17 `MCPAdapterPlugin` satisfies `AdapterPlugin` | False | True |
| AC-17 the claim is checked in production | 0 callers | `_plugins/loader.py::_validate_metadata`, every load path |
| AC-18 live `hasattr(app, "resolve_model")` (AST) | 1 | **0** |
| AC-19 `functualize-ai-pydantic` mypy | 56 | **11** |
| AC-19 `functualize-ai` mypy | 46 | **23** |
| AC-20 `functualize-state` in PUBLISHING/codemaps | 8 sites | 2, both prose recording its removal |
| AC-11 live `StateBackend`/`ExecutionStore` refs | 8 sites / 4 files | **1** — see below |
| AC-11b prose preserved | 24 files | 21, none deleted to satisfy AC-11 |

**Three corrections to the plan's gates.**

1. **`validate_adapter` cannot have a production caller**, and the task assumed
   it could. It is in the public `app/` package; the `Internal never imports
   public` contract forbids `_plugins` from importing it. The **protocol** is
   the shared thing and `_plugins` may import `_types`, so the check is an
   `isinstance` against `AdapterPlugin` in `_validate_metadata`. The intent —
   *the claim is checked on a real boot* — is met; the named function is not the
   mechanism.
2. **AC-11's residual 1 is not a violation.** It is `EphemeralStateBackend()`,
   a class `functualize-ai` **defines itself** in `_state_fallback.py`. The name
   echoes the retired protocol; the object is real and is the honest in-memory
   store. Renaming it is public-API churn for a word, and the module now states
   plainly what it is.
3. **AC-19's baseline was 47 in the spec and 56 when measured.** The spec's
   number came from `plugin-host-protocol`/T11 and had drifted. Recorded as
   measured, not as remembered.

**A test was defending the defect.** `tests/plugins/test_ai_state_fallback.py`
asserted that the ephemeral warning names `functualize-state-sqlite` — the
instruction that could not help, since that plugin provides a `StoreSubstrate`
rather than the `StateBackend` the module uses. It now asserts the warning names
**no package at all**.

**A behaviour change, marked breaking in the commit:** a project with an `[ai]`
section now has it honoured. It never was.

---

## Wave 5 — close

### [x] T10 · Regenerate locks, run every gate, update `.spec/STATE.md`

`uv.lock` and the two `examples/project/*/uv.lock` regenerated **once**, at the
end. Then: root suite, `examples/`, all twelve plugin suites, `lint-imports`,
`mypy`, `ruff`, and AC-22 — the four pre-existing `sqlite` failures
(`.spec/STATE.md` wave 10) unchanged or fixed, **never newly masked**.

**DONE.** Locks regenerated; `git grep -c 'plugins/functualize-'` over all three
is **0**, and the root lock carries 26 references to the grouped layout.

| Gate | Result |
|---|---|
| `uv run ruff check src/ tests/ plugins/` | clean |
| `uv run ruff format --check` | 1,354 files already formatted |
| `uv run mypy src/` | clean, 357 files |
| `uv run lint-imports` | 7 kept / 0 broken |
| `uv build --all-packages` | exit 0, 26 artifacts |
| root suite | **10,744 passed / 0 failed**, 1,602 skipped |
| `examples/` | **212 passed** |
| twelve plugin suites | **447 passed**, 1 skipped |

**AC-22 is satisfied in the strongest form: the four failures are gone, and not
by masking.** `functualize-substrate-sqlite` runs **25 passed / 0 failed**. They
were subprocess tests that SIGKILL a child, which therefore could not inherit
the in-process `monkeypatch` the suite used to swap the substrate; they pass now
because the distribution is genuinely installed by
`uv sync --all-packages --all-extras`. Nothing was skipped, xfailed or deleted
to achieve it.

**The full run found two more instances of the defect this feature is about**,
both invisible until the plugins actually loaded:

1. **`func builtin domains list` advertised a substrate as a domain SDK.** It
   printed `pip install functualize-state-sqlite` — whose old name shared a
   prefix with the `functualize-state` domain ADR-022 removed — so a user
   following it installed a substrate and still had no domains. Fixed in
   `_cli/builtins.py` and `_cli/scaffold/cli.py`; the test now asserts the two
   domain SDKs that exist and that the word "substrate" does **not** appear.
2. **`examples/quickstart/step7_workflow/test_step7.py` resolved its own store.**
   `ScopeStore.for_project(Path.cwd())` reads the filesystem default and ignores
   the app's storage, so with the plugin installed it read an empty
   `scopes.json` while the run wrote to a database. It asks the app now — the
   sixth site of this exact shape found in this feature, after `data show`,
   `data clear`, `run list`, `run show` and `history`, and the second time it has
   been fixed in the repository (`store-substrate`/T7 did `builtin workflow`).

---

## Task Dependency Graph

```json
{
  "waves": [
    {"id": 0, "tasks": ["T1", "T2"], "why": "the spec gate must survive the move before anything moves; it fails open, so its breakage is silent"},
    {"id": 1, "tasks": ["T3"], "why": "a move-only commit, so git records renames and T8's edits stay legible"},
    {"id": 2, "tasks": ["T4", "T5", "T6"], "why": "T4 names the read set; T5 moves the orphans into it; T6 makes the rule mechanical. T5 depends on T4's constant, T6 on both"},
    {"id": 3, "tasks": ["T7"], "why": "removes the middle man and the eager substrate read, closing AC-4 through AC-8; must precede the rename because the plugin name is the sort key that decides the substrate today"},
    {"id": 4, "tasks": ["T8", "T9"], "why": "the rename, once the name is no longer load-bearing; and the surface/doc truth that the rename would otherwise have to carry"},
    {"id": 5, "tasks": ["T10"], "why": "locks regenerated once, every gate run, state recorded"}
  ],
  "edges": [
    {"from": "T1", "to": "T2"},
    {"from": "T2", "to": "T3"},
    {"from": "T3", "to": "T4"},
    {"from": "T4", "to": "T5"},
    {"from": "T5", "to": "T6"},
    {"from": "T6", "to": "T7"},
    {"from": "T7", "to": "T8"},
    {"from": "T8", "to": "T9"},
    {"from": "T9", "to": "T10"}
  ]
}
```
