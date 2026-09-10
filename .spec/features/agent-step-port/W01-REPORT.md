# W01 report — `agent-step-port`, waves 0 and 1 (T1, T2)

Worktree `pi-parity`, shared with three other agents. **No git command was run**
(per the shared rules); every undo was an edit of the file itself.

Both tasks are implemented and their gates are green. `tasks.md` checkboxes are
**not** flipped — that file is not in my scope and the orchestrator was editing it
(18:33) while I worked. Requested at the end of this report.

---

## T1 · `AgentStepExecutor`, `AgentCapability`, and two errors

### What changed

| File | Lines | Change |
|---|---|---|
| `src/functualize/_types/protocols.py` | 330 → **460** (+130) | the port: `AgentCapability` (`StrEnum`, 3 members), `AgentStepContext` (frozen dataclass, 6 fields), `AgentStepResult` (frozen dataclass, 2 fields), `AgentStepExecutor` (`@runtime_checkable Protocol`); module docstring lists it; `__all__` +4; imports `Mapping`/`dataclass`/`StrEnum` and `RunRequest` under `TYPE_CHECKING` |
| `src/functualize/_types/errors.py` | 307 → **408** (+101) | `AgentExecutorUnavailableError`, `AgentCapabilityRefusedError`; `Sequence` added to the `collections.abc` import; `AgentCapability` imported under `TYPE_CHECKING` |
| `src/functualize/plugin/__init__.py` | 116 → **129** | 4 imports + 9 `__all__` lines (comment + the four names) — the door contracts §6 names |
| `tests/test_public_api_surface.py` | +7 | the four names registered in `EXPECTED_EXPORTS["functualize.plugin"]` |

`tests/test_public_api_surface.py` is **shared**: another agent added
`Freshness`/`FreshnessVerdict` to it mid-run (lines 71–72, F9), which is why the
file's total moved further than my 7 lines. Different sections, no conflict — the
brief's warning applied, and did not cost anything.

Choices worth naming:

- **`StrEnum`, not `(str, Enum)`.** Contracts §1 spells it `(str, Enum)`; on this
  interpreter that is the same type with a `UP042` warning attached, and
  `_types/outcome.py:39-45` already records exactly that decision for `Family`. I
  followed the precedent. It also makes `f"{capability}"` render
  `enforces_tool_allowlist` rather than `AgentCapability.ENFORCES_TOOL_ALLOWLIST`,
  which the error messages depend on.
- **`AgentStepContext`/`AgentStepResult` live in `_types/protocols.py`.** Contracts
  §1 groups them with the port and the plan's file list names no `_types` module of
  their own, so a new module would have been out of scope. Consequence, stated
  plainly: `protocols.py` now holds two dataclasses beside its Protocols. The
  module docstring says so rather than pretending they are protocols.
- **All six `AgentStepContext` fields are required** (no defaults), exactly as
  contracts §1 writes them. `tools=()` is a valid *value* meaning "no constraint
  declared"; nothing defaults it silently.
- **`errors.py` does not import `protocols.py` at runtime** — only under
  `TYPE_CHECKING` (import-linter excludes those, and ruff's `TC001` requires it).
  `str(self.capability)` needs no import.

### Gates

**Gate A** — `rg -c 'class AgentStepExecutor' src/functualize/_types/protocols.py`

before (`0`, exit 1):

```
0
exit=1
```

after:

```
1
```

**Gate B (Protocol, not ABC)** —
`rg -n 'class AgentStepExecutor' -B2 src/functualize/_types/protocols.py | rg -c 'runtime_checkable'`

before: `n/a` (no class to look above). after:

```
1
```

**Independent falsifier — behaviour, not another grep:**

```
$ uv run python -c "from functualize._types import protocols; p = protocols.AgentStepExecutor; print(...)"
is_protocol: True
is_runtime_protocol: True
members: ['capabilities', 'execute', 'name']
is ABCMeta-subclass-only (no ABC in mro): ['AgentStepExecutor', 'Protocol', 'Generic', 'object']
```

No `ABC` anywhere in the MRO, `_is_runtime_protocol` true, and the three members
present — AC-1's claim, answered without `rg`.

### Sabotage (T1)

`@runtime_checkable` deleted from above the class (one line), then:

```
=== gate 2 (sabotaged) ===
0
0 — GATE RED
=== isinstance (sabotaged) ===
TypeError: Instance and class checks can only be used with @runtime_checkable protocols
```

Restored by editing the decorator back; gates re-run:

```
=== gate 1 restored ===
1
=== gate 2 restored ===
1
=== isinstance restored ===
True
All checks passed!
42 passed in 0.80s          # tests/test_public_api_surface.py
```

The gate moves 1 → 0 → 1, and the behaviour it stands for breaks visibly rather
than silently.

### Not done

- **No production call path exists yet, by construction.** T1 is declaration only:
  nothing implements the Protocol until T5, and nothing raises the errors until T3.
  The intended path, for whoever wires it: `_validate_workflow_graph` (T3) →
  `missing_executor_hint` → `AgentExecutorUnavailableError`. I claim no
  reachability for this task, and nothing in this wave should pass a
  wiring-discipline check on its own.

---

## T2 · `EXECUTOR_PROVIDERS`, `CORE_EXECUTORS`, and a shared provider-table test

### What changed

| File | Lines | Change |
|---|---|---|
| `src/functualize/_engine/agent_providers.py` | **new, 52** | `EXECUTOR_PROVIDERS`, `CORE_EXECUTORS`, `missing_executor_hint` — copied from `_gate/_strategy.py` including the `CORE_*` empty-hint rule |
| `tests/gate/test_provider_tables.py` | **new, 242** | 16 tests, parametrized over a `_TABLES` list covering both tables, plus a discovery guard |
| `tests/gate/test_registry.py` | 307 → **259** (−48) | `TestTheStrategyProviderTable` (5 tests) relocated; `subprocess`, `Path`, `REPO_ROOT` and the three strategy-table imports dropped |

`tests/gate/` collects 19 → **30** tests.

Shape of the shared test (`pitfalls.md` §6: *"one registry, plus a test that checks
it against the thing it describes"*):

- `ProviderTable` holds the table, the `CORE_*` set and the hint function as
  **module-path + attribute-name strings**, so the same list is what the discovery
  test compares against disk. A third table joins `_TABLES`.
- `TestEveryTableIsListedHere::test_every_provider_table_in_src_is_listed_here`
  walks `src/functualize/**/*.py` for `^[A-Z][A-Z0-9_]*_PROVIDERS\s*[:=]` and
  refuses a table that is not in the list (and a listed table that no longer
  exists). This is the piece that makes "a third table joins a list" true rather
  than aspirational.
- `TestEveryProviderTable` (parametrized, ids = table name): non-empty; a core name
  is registered by core; a core name gets no hint; **every** non-core name names
  its package; unknown name gets no hint; core names the plugins without importing
  them.
- Two tests keep the *absolute* pairings, because the parametrized format check
  derives its expectation from the table and would therefore pass with two packages
  swapped: `ai_inbound → functualize-ai`, `ai_outbound → functualize-mcp` (moved
  from `test_registry.py`, so nothing was weakened) and the new
  `ai → functualize-ai`, `mcp-elicitation → functualize-mcp`.
- The gate-specific staleness test (`set(STRATEGY_PROVIDERS) ==
  set(_VALID_GATE_STRATEGIES)`) moved over unchanged; it stays unparametrized with
  a comment saying why (no executor validator exists).

### Gates

**Gate A** — `rg -n '^[A-Z_]+_PROVIDERS' src/functualize/ | wc -l`

before: `1` (`_gate/_strategy.py:40`). after:

```
2
src/functualize/_engine/agent_providers.py:30:EXECUTOR_PROVIDERS: dict[str, str] = {
src/functualize/_gate/_strategy.py:40:STRATEGY_PROVIDERS: dict[str, str] = {
```

**Gate B** — `grep -rn -E 'import functualize_(ai|mcp)' src/ | wc -l`

before `0`, after `0`. (See finding 3: this spelling is not the whole question, and
my test asks a wider one.)

**Independent falsifier — AST, not regex:**

```
$ uv run python -c "<ast walk over src/functualize for names ending _PROVIDERS>"
2 [('EXECUTOR_PROVIDERS', 'src/functualize/_engine/agent_providers.py'),
   ('STRATEGY_PROVIDERS', 'src/functualize/_gate/_strategy.py')]
```

Two, in the two expected files — the same answer by a different mechanism.

### Sabotage (T2)

Five breaks, each restored by editing the file back. Two of them found real holes.

**1 · `missing_executor_hint` loses its core guard** (`or name in CORE_EXECUTORS`
deleted):

```
_ TestEveryProviderTable.test_a_core_name_gets_no_install_hint[EXECUTOR_PROVIDERS] _
    def test_a_core_name_gets_no_install_hint(self, table: ProviderTable) -> None:
        for name in table.core_names:
>           assert table.hint_for(name) == ""
E           AssertionError: assert 'install func...o register it' == ''
E             + install functualize to register it
1 failed, 15 passed
```

**2 · the table loses its `"ai"` entry:**

```
>       assert table.hint_for("ai") == "install functualize-ai to register it"
E       AssertionError: assert '' == 'install func...o register it'
1 failed, 15 passed
```

**3 · a listed table is renamed so the source table goes unlisted** (`_TABLES`
entry pointed at `EXECUTOR_PROVIDERS_V2`) — proves the discovery guard bites:

```
FAILED ...::test_every_provider_table_in_src_is_listed_here - AssertionError:
  provider tables in src/ that this file does not check:
  [('functualize._engine.agent_providers', 'EXECUTOR_PROVIDERS')]. Add each to _TABLES.
6 failed, 10 passed
```

**4 · a real import of the plugin added to core** (`import functualize_ai` in
`agent_providers.py`) — the call path the task gate guards:

```
-- task gate --          $ grep -rn -E 'import functualize_(ai|mcp)' src/ | wc -l
1
-- derived test --
FAILED ...test_core_names_the_plugins_without_importing_them[EXECUTOR_PROVIDERS] -
  AssertionError: EXECUTOR_PROVIDERS names ['functualize-ai', 'functualize-mcp'], which core imports:
  src/functualize/_engine/agent_providers.py:29:import functualize_ai  # noqa: F401 — sabotage
2 failed, 14 deselected
```

**5 · the same import, spelled `from`-first** (`from functualize_ai import
something`) — **the task's gate does not fire:**

```
-- the task's own gate --   $ grep -rn -E 'import functualize_(ai|mcp)' src/ | wc -l
0
-- the T7 feature gate's spelling --
rg exit=1
-- derived test --
FAILED ...test_core_names_the_plugins_without_importing_them[STRATEGY_PROVIDERS] -
  AssertionError: STRATEGY_PROVIDERS names ['functualize-ai', 'functualize-mcp'], which core imports:
  src/functualize/_engine/agent_providers.py:29:from functualize_ai import something  # noqa: F401
2 failed, 14 deselected
```

Finding 3 below is the write-up. Restored; re-verified:

```
0                       # gate B restored
2                       # gate A restored
72 passed in 0.47s      # tests/gate/ + tests/test_public_api_surface.py
All checks passed!      # ruff check src/ tests/ plugins/
1104 files already formatted
Success: no issues found in 333 source files   # mypy src/
```

### The first version of this test could not fail

Worth recording, because the branch's rules exist for exactly this. My first
derived grep pattern was
`"functualize_(" + "|".join(p.replace("-", "_") …) + ")"`, which yields
`functualize_(functualize_ai|functualize_mcp)` — a pattern that matches nothing on
Earth. It passed 16/16 while `grep -rn -E 'import functualize_(ai|mcp)' src/`
returned `1`. Sabotage 4 caught it; a `-s` debug print showed the rendered argv:

```
DEBUG … ['import functualize_(functualize_ai|functualize_mcp)', 'src/'] '' '' 1
```

Fixed to `(^|[[:space:]])(from|import)[[:space:]]+(<modules>)` and re-sabotaged
(4 and 5 above). This is sabotage earning its keep, not ceremony.

---

## Findings the next waves need

1. **`FunctualizeError` does not exist.** Contracts §5 writes
   `class AgentExecutorUnavailableError(FunctualizeError)`.
   `rg 'FunctualizeError' src/` → **0 matches**; every class in
   `_types/errors.py` derives from `Exception`. I followed the file's convention
   (`Exception`) rather than invent a base class with one user. If a real base is
   wanted, that is a separate change with a separate decision — and it would add a
   public name.
   Exact messages, for T3's tests to align with (or to disagree with loudly):
   - `AgentExecutorUnavailableError(step_name, executor=None, *, registered=(), hint="")`
     → `Agent step 'write-migration' names executor 'ai', which is not registered (registered: cli-prompt). Install functualize-ai to register it. The step is refused — it is never answered by prompting a human instead.`
   - `AgentCapabilityRefusedError(step_name, *, executor, capability, declared=())`
     → `Agent step 'write-migration' requires 'enforces_tool_allowlist', which executor 'cli-prompt' does not declare (it declares: no capabilities). The step is refused — running it would leave the constraint unenforced.`
   Attributes: `.step_name`, `.executor`, `.registered`/`.declared`, `.hint`, `.capability`.
2. **`issubclass` raises `TypeError` on this Protocol** — `name` and
   `capabilities` are data members ("Protocols with non-method members don't
   support issubclass()"). Verified on 3.13.13 against the code as written.
   `isinstance` works and checks all three members. Whoever registers and filters
   executors (T5) must use `isinstance`; mypy will not warn at the call site.
3. **AC-9's gate spelling is narrower than AC-9.** `rg 'import
   functualize_(ai|mcp)' src/` never matches `from functualize_ai import x`: the
   literal `import ` does not precede the module name in a `from`-import. Proven
   by sabotage 5 — the gate read `0` while a real import sat in `src/`. My
   parametrized test asks the wider question; T7's checkpoint line and any later
   gate should adopt the wider spelling, otherwise the "core names packages, never
   imports them" rule holds only for one of two import syntaxes.
4. **Spec §3.3 says the table "copies it exactly, including … the known
   inconsistency" comment.** There is no executor validator, so copying that
   comment would be false: `AgentStep.executor` is a free-form name checked against
   the registry, not against the dict. `agent_providers.py` states the *divergence*
   instead (module docstring, last paragraph) so a later "reconcile the tables"
   task does not go hunting for an analogue that does not exist. Everything else —
   `CORE_*`, the empty hint, the package names — is copied exactly.
5. **`src/functualize/workflow/__init__.py` is in my file list but unused by
   waves 0–1.** The only thing it would carry is `AgentStep`, which is T3's. Left
   untouched.
6. **Unwired by design, again.** `EXECUTOR_PROVIDERS`/`missing_executor_hint` have
   no production consumer until T3's validation refusals. That is the wave graph's
   own ordering (W1 produces, W2 consumes), not an omission — and it is why the
   task gates, not a call path, are this wave's evidence.

---

## Verification actually run (real tail output)

Run at ~10:35, after the two suites below. **The tree is being edited by three
other agents**, so the workspace-wide `ruff` count is not a statement about my
change: it currently reports one error, in a file I do not own and must not touch
(`tests/plugins/test_three_doors_agree.py:35` — `TC001`, a sibling's in-flight
edit). Scoped to my files, everything is clean.

```
$ uv run ruff check src/functualize/_types/protocols.py src/functualize/_types/errors.py \
      src/functualize/_engine/agent_providers.py src/functualize/plugin/__init__.py \
      tests/gate/test_provider_tables.py tests/gate/test_registry.py tests/test_public_api_surface.py
All checks passed!

$ uv run ruff format --check <the same seven files>
7 files already formatted

$ uv run ruff check src/ tests/ plugins/          # workspace-wide, for the record
TC001 Move application import `functualize.types.RunRequest` into a type-checking block
  --> tests/plugins/test_three_doors_agree.py:35:31
Found 1 error.                                     # NOT mine; outside my file scope

$ uv run mypy src/
Success: no issues found in 335 source files

$ uv run lint-imports
Contracts: 6 kept, 0 broken.

$ uv run pytest tests/gate/ tests/test_public_api_surface.py tests/types/ tests/plugin/ -q --no-header
290 passed in 2.23s

$ rg -c 'class AgentStepExecutor' src/functualize/_types/protocols.py
1
$ rg -n 'class AgentStepExecutor' -B2 src/functualize/_types/protocols.py | rg -c 'runtime_checkable'
1
$ rg -n '^[A-Z_]+_PROVIDERS' src/functualize/ | wc -l
2
$ grep -rn -E 'import functualize_(ai|mcp)' src/ | wc -l
0
```

(Later than the 10:2x runs that said `1104 files already formatted` / `333 source
files`: the counts move as sibling agents add files. The seven files above are the
ones my change owns, and they are the ones that were checked.)

### Full slow suite and `examples/` (run once each, per the amended rules)

**`uv run pytest examples/ -q`** — exit 0:

```
........................................................................ [ 37%]
........................................................................ [ 74%]
..................................................                       [100%]
194 passed in 124.67s (0:02:04)
```

No broken example tests here, unlike the nine that had been escaping.

**`HYPOTHESIS_PROFILE=ci uv run pytest --run-slow -n auto -q`** — exit 1:

```
25 failed, 11181 passed, 140 skipped, 3090 warnings in 1645.20s (0:27:25)
```

All 25 are artifacts of running `-n auto` in a tree three other agents were
editing; none is mine, and each was re-run to prove it (the rule's test: a failure
that passes alone is an artifact, and I say which of the two it was).

**Bucket A — 17 of 25 pass when re-run serially** (57.11s):

```
$ HYPOTHESIS_PROFILE=ci uv run pytest --run-slow -q --no-header $(cat /tmp/w01-refail.txt)
0                       # failures
.................                                                        [100%]
17 passed in 57.11s
exit=0
```

That set is exactly the load-sensitive one you would expect under six-way
parallelism with three concurrent agents: plugin-load budget assertions
(`functualize-http took 229ms to load (budget: 50ms)`), warm-boot linear-scaling
(`Per-module cost 12.315ms exceeds hard limit of 1ms`), a Hypothesis
`DeadlineExceeded` at 6999.89ms against a 5000ms deadline, the `'NoneType' object
is not subscriptable` cluster in plugin registration / warm-boot / auto-scope
tests, `test_functualize_console_script_executable 2 == 0`, and
`OSError: …/.venv/bin/func: No such file or directory`.

The last two name the shared cause: **another agent was rebuilding this worktree's
venv mid-run**. `.venv/bin/func` did not exist during the run and its mtime is
`10:31`; the run spanned ~10:00–10:28. A missing console script explains the
`NoneType`/version-`split` failures and the plugin registry ones at once. The churn
is directly observable — a plain `uv run ruff check` minutes later began with:

```
   Building functualize @ file:///home/viltohmyst/code/raicing-ai/functualize/.worktrees/pi-parity
   Building functualize-bitwarden @ …/plugins/functualize-bitwarden
Uninstalled 2 packages in 3ms
Installed 2 packages in 10ms
```

**Bucket B — 4 of 25 are the documented known-red shell palettes.** With a real
terminal:

```
$ env -u NO_COLOR TERM=xterm-256color uv run pytest --run-slow -q --no-header tests/_cli/test_snapshot_baseline.py
....                                                                     [100%]
--------------------------- snapshot report summary ----------------------------
4 snapshots passed.
```

**Bucket C — 4 of 25 cannot be re-run at all, and that is the strongest evidence
they are not mine.** They were reported as
`tests/cli/test_stdin_integration_unit.py::TestTtyRequiredNoDefault::…` and
`::TestTtyWithDefault::…` (`Failed: DID NOT RAISE <class 'SystemExit'>`). Those
classes **do not exist in the file any more**:

```
$ grep -n "class TestTty" tests/cli/test_stdin_integration_unit.py
$ grep -n "^class " tests/cli/test_stdin_integration_unit.py
27:class TestPipePopulatesParam:
94:class TestExplicitFlagWins:
155:class TestATerminalResolvesNothing:
229:class TestMultipleStdinParams:
```

The file was rewritten at **10:25**, inside my 10:00–10:28 run — a sibling agent
replaced that module underneath the suite. Nothing in stdin/TTY resolution is
something I touched, and the tests as they now exist are different tests.

**Zero involvement, measured rather than asserted:**

```
$ grep -c "AgentStep\|agent_providers\|EXECUTOR_PROVIDERS\|agent_step" /tmp/functualize-w01-slow.log
0
$ grep -c "AgentStep\|agent_providers\|EXECUTOR_PROVIDERS" /tmp/functualize-w01-examples.log
0
$ grep -c "tests/gate/\|tests/test_public_api_surface.py\|tests/types/\|tests/plugin/" /tmp/w01-failed-nodes.txt
0
```

No failure names anything I added, and none of my files' test paths appears among
the 25.

**For completeness, the earlier full fast suite** (`uv run pytest tests/ -q --no-header`, 12m43s):
**9734 passed, 1575 skipped, 7 failed** — same three buckets, all re-checked:

```
FAILED tests/_cli/test_snapshot_baseline.py::test_snapshot_empty_state
FAILED tests/_cli/test_snapshot_baseline.py::test_snapshot_ready_bar
FAILED tests/_cli/test_snapshot_baseline.py::test_snapshot_panel_ring_open
FAILED tests/_cli/test_snapshot_baseline.py::test_snapshot_modal_open
FAILED tests/group_options/test_group_options_discovery.py::test_duplicate_binding_for_one_group_is_a_discovery_error
FAILED tests/skills/test_api_claims.py::test_capability_table_matches_the_engine
FAILED tests/skills/test_api_claims.py::test_no_invented_public_names[…capabilities.md] - names ['Freshness']
```

- The four `test_snapshot_baseline` ones are the shell's `NO_COLOR=1` / `TERM=dumb`
  (the shared rules' known-red list):
  `env -u NO_COLOR TERM=xterm-256color uv run pytest tests/_cli/test_snapshot_baseline.py -q`
  → **4 passed**.
- The other three pass in isolation, and `tests/skills/ tests/group_options/`
  together → **276 passed, 23 skipped**. They ran red inside a 12-minute window in
  which three other agents were editing this worktree — `Freshness` is a sibling's
  in-flight F9 work (it is in the public-API snapshot at lines 71–72 but not yet
  exported), and `tests/skills/` compares `skills/` prose against the live engine,
  so a half-landed capability fails exactly there.
- `grep -c "AgentStep|agent_providers|EXECUTOR_PROVIDERS" /tmp/functualize-w01-fast.log`
  → **0**: no failure mentions anything I touched.

---

## Requests

1. **Flip `T1` and `T2` to `[x]` in `.spec/features/agent-step-port/tasks.md`.** Not
   in my file list, and you were editing it while I worked, so I did not touch it.
2. Consider widening AC-9's gate to the `from`-import spelling (finding 3) before
   T7 runs it as the feature gate.

| Task | Done? | Gate before | Gate after |
|---|---|---|---|
| T1 (`AgentStepExecutor` + `AgentCapability` + 2 errors) | yes | `rg -c 'class AgentStepExecutor' …/protocols.py` → `0`; `runtime_checkable` gate `n/a` | `1`; `1` (and `isinstance` green, `issubclass` TypeError) |
| T2 (`EXECUTOR_PROVIDERS` + `CORE_EXECUTORS` + shared table test) | yes | `rg -n '^[A-Z_]+_PROVIDERS' src/functualize/ \| wc -l` → `1`; `grep -rn -E 'import functualize_(ai\|mcp)' src/ \| wc -l` → `0` | `2`; `0` |
