# plugin-taxonomy — research

**Revision 2 · 2026-09-17 · base `feat/plugin-host-protocol` @ `80ec5f0`**
(revision 1 was 2026-09-16 @ `79545ef`; master `11d77f6` in both).

Re-run because `plugin-host-protocol` **landed** between the two revisions
(16 tasks, 11 waves, Verify complete — `.spec/STATE.md`). It edited plugin
sources this feature is about to move and rename, so every path, line number
and count in revision 1 had to be re-taken rather than trusted.

Everything below was produced by running a command. The command is shown.
Findings that only confirm the brief are in `spec.md`; this file holds the ones
that **change the shape of the feature**.

---

## Retrieval passes run (revision 2)

| Pass | Tool | What it answered |
|---|---|---|
| Prose — prior art | zvec-grep, existing index, background refresh 726/784 | ADR-022, `plugins/PUBLISHING.md`, `_primitives/plugin_kinds.py`, `docs/guides/domain-sdks.md`, `codemaps/entry-points.md` |
| Structure | serena / `ast` | `MCPAdapterPlugin`'s real method set; `AdapterPlugin`'s members |
| Premises — counts and negatives | `git grep` (tracked files only) + executed Python | every number in `spec.md` §A and §E |

**Two measurement corrections carried forward from revision 1.** Both changed
numbers, so they are recorded rather than silently applied:

1. **Counts must be taken with `git grep`, not `rg`.** The worktree carries an
   untracked `graphify-out/` (`graph.json`, 290k+ lines) that matches almost
   every identifier in the repo. Revision 1's `rg`-based counts included it.
   Every count in revision 2 is `git grep` over tracked files.
2. **Revision 1's gate commands use `\|` for alternation.** In `rg` (Rust
   regex) `\|` is a *literal pipe*, so `'StateBackend\|ExecutionStore'` matches
   the string `StateBackend|ExecutionStore` and finds nothing. Every gate in
   `spec.md` §E is rewritten as a command that was actually run.

**Index note (still true).** The worktree's `.zvec-grep/manifest.json` is
root-owned `0600` from an earlier backgrounded `zg index`; the `zg` CLI fails
`EACCES` and `zg status` reports *"Workspace index is not configured"*, which
reads like an absent index and is a permissions failure. The **MCP server
reads it fine** — `zvec_grep_search` served from the current index throughout
this pass. Use the MCP tool rather than the CLI in this worktree until someone
with `sudo` fixes the ownership. Worth adding to `code-intel/SKILL.md`.

---

## What `plugin-host-protocol` already did — revision 1's §G is now history

Revision 1 §G recorded two *same-line seams* and a sequencing requirement.
All three are resolved. Verified by reading the files at `80ec5f0`:

| Revision 1 said | State at `80ec5f0` |
|---|---|
| `state-sqlite/_plugin.py:74-78` — the other feature changes `app.substrate = …` to `app.install_substrate(…)` | **Done.** `_plugin.py:77` is `app.install_substrate(self._substrate)`. The swallow this feature owns is now `_plugin.py:75-83` |
| `tasks-local/_plugin.py:66` — the other feature changes `app.execution_engine.substrate` to `app.substrate` | **Done.** `_plugin.py:67` is `TaskDocument(app.substrate)`. The **ordering bug survives intact**, as designed |
| "Sequencing is a requirement — `plugin-host-protocol` lands first" | **Satisfied.** This feature is now free to `git mv` |

Both plugin modules now import `functualize.plugin.PluginHost` under
`TYPE_CHECKING` and annotate `app: PluginHost`. That is a **new constraint on
the rename**: `functualize_state_sqlite` and `functualize_tasks_local` are
name consumers in their own annotations, not only in packaging metadata.

Three defects were **handed to this feature** by that one's Execute phase
(`.spec/STATE.md` → *Owed elsewhere*, maintainer 2026-09-17). They are
findings R6–R8 below.

---

## R1 — The folder move silently disables this repo's own spec gate

**Unchanged from revision 1, and now verified by execution rather than by
reading.** Highest-severity finding here, because it disables the mechanism
that would catch the rest of the work.

`.claude/hooks/spec_gate.py:83-87` ends:

```python
rel = os.path.relpath(target, plugins_root).split(os.sep)
# plugins/<pkg>/src/... -> gated. plugins/<pkg>/tests/..., conftest -> free.
return len(rel) >= 3 and rel[1] == "src"
```

`is_gated` imported and **called** against five paths:

```
True   src/functualize/_app/boot.py
True   plugins/functualize-http/src/functualize_http/x.py
False  plugins/adapters/functualize-http/src/functualize_http/x.py      <-- the move
False  plugins/substrates/functualize-substrate-sqlite/src/pkg/x.py     <-- the move
False  plugins/functualize-http/tests/test_x.py
```

Every plugin source file leaves the gate, and `.claude/rules/spec-workflow.md`
says the gate **fails open** by design — so nothing reports it. The repository
loses spec enforcement over `plugins/**/src/**` with no error, no test failure
and no log line.

The same one-level assumption is written into three more places, all verified
at `80ec5f0`:

| File | Line | Text |
|---|---|---|
| `.claude/hooks/spec_gate.py` | 25 | `GATED_GLOB_PARTS = ("plugins", "src")` |
| `.claude/hooks/agent_contract.py` | 30 | ``Modifying `src/functualize/**` or `plugins/*/src/**` requires…`` |
| `.claude/hooks/plan_context.py` | 42 | same sentence |
| `.claude/rules/spec-workflow.md` | — | same sentence, in the contract itself |

**Consequence for the plan:** the gate fix is wave 1, before any directory
moves, with an acceptance gate that *executes* the predicate against a nested
path — not a reading of it.

---

## R1b — The move also breaks the uv workspace glob (new in revision 2)

Not in revision 1, and it is the same one-level assumption in a second
mechanism:

```
$ sed -n '/\[tool.uv.workspace\]/,/^\[/p' pyproject.toml
[tool.uv.workspace]
members = ["plugins/*"]
```

`plugins/*` matches `plugins/adapters/`, not
`plugins/adapters/functualize-http/`. After the move the workspace has **zero**
members that are packages, and `uv sync --all-packages` resolves nothing.

It is a one-character fix (`plugins/*/*`), which is exactly why it is worth
writing down: it fails loudly at `uv sync` time, unlike R1, but it also
contradicts a shipped instruction —
`contributor/guides/plugin-development.md:78-89` tells plugin authors
*"`members = ["plugins/*"]` — Already a glob — your plugin is auto-included"*.
That sentence stops being true.

---

## R2 — The renames make `plugin available --remote` advertise the dead names

**Unchanged from revision 1.** `src/functualize/_cli/plugin_cmd.py:424`
enumerates the PyPI Simple index and keeps every project whose name starts with
`functualize-`; `available_rows` (`plugin_cmd.py:256`) renders anything not in
the curated catalog as `kind="unknown"`, which `_KIND_ORDER`
(`plugin_cmd.py:335-339`) heads:

```
UNCURATED — found on PyPI, not vetted by this project
```

With no compatibility shims (D1), `functualize-aws`, `functualize-bitwarden`
and `functualize-state-sqlite` stay on PyPI at 0.2.3 forever, so
`func builtin plugin available --remote` offers a user three abandoned
distributions, one of which does nothing even when installed.

**A behaviour change the spec must own,** not a packaging footnote. Still
open as Q1.

---

## R3 — The dead group is taught by the repo's own tutorial

**Unchanged from revision 1.** `examples/plugins/custom_state_backend/pyproject.toml:10`:

```toml
[project.entry-points."functualize.state_providers"]
```

This is the documented example for writing a third-party substrate — mkdocs nav
(`mkdocs.yml:148`) and `docs/examples/plugins/custom-state-backend.md`. A reader
who follows it end-to-end produces a plugin that **never loads**.

F1's fix covers **three** registrations, not two: the sqlite plugin, the inline
plugin, and this example. The example's directory name, doc title and nav entry
also still say *state backend*, a protocol ADR-022 retired.

---

## R4 — A second `functualize-state-sqlite` example is broken at import

**Unchanged from revision 1, re-verified.**

```
$ git grep -l SQLiteStateBackend -- . ':!.spec'
plugins/functualize-state-sqlite/README.md
plugins/functualize-state-sqlite/examples/README.md
plugins/functualize-state-sqlite/examples/persistent_counter/persistent_counter.py
plugins/functualize-state-sqlite/examples/persistent_counter/test_persistent_counter.py

$ python -c "import functualize_state_sqlite as m; print(m.__all__)"
['SQLiteStatePlugin', 'SQLiteSubstrate']
```

Four files import or instantiate a class that **is defined nowhere**. It
survives because nothing collects it: root `pyproject.toml:171` sets
`testpaths = ["tests"]`, and `ci.yml:232,235` runs plugin suites for exactly
one plugin (`functualize-mcp`).

**The general fact behind it:** eleven of twelve plugins have test suites CI
never runs. Out of scope here, but it is why F1–F4 can all be true with a green
pipeline, and it belongs in `.spec/STATUS.md` regardless.

---

## R5 — Dev-environment note for whoever executes this

Under a plain `uv sync` the workspace plugins are **not installed** — only core
plus `functualize-bitwarden` (it is in the `dev` group). Plugins reach the test
suite two other ways: `uv sync --all-packages` in CI, and
`tests/conftest.py:356`, which inserts
`plugins/functualize-state-sqlite/src` on `sys.path` by **filesystem path**,
then `tests/conftest.py:360` imports `functualize_state_sqlite.substrate`.

Those two lines are a path consumer of item A and a name consumer of item B
**in the same fixture**. One task, both edits.

---

## R6 — `functualize-ai`'s config probe has never run (new; handed over)

Handed to this feature by `plugin-host-protocol`/T11 (maintainer, 2026-09-17).
`plugins/functualize-ai/src/functualize_ai/_provider_discovery.py:218`:

```python
if app is not None and hasattr(app, "resolve_model"):
    config = cast("AIConfig", app.configuration.resolve_model("ai", AIConfig))
else:
    config = AIConfig()
```

`resolve_model` lives on `app.configuration`, never on the app itself —
measured against a live app, and confirmed structurally: the only definitions
are `_app/configuration_facade.py:98`, `_app/impl.py:882` and the port at
`_types/host.py:167`. There is **no `FunctualizeApp.resolve_model`**.

So the guard is always `False`, the `[ai]` section has **never** been read
here, and every caller passing an `app` has silently received `AIConfig()`
defaults. The other feature left it standing on purpose — a 15-line comment at
`:205-217` records why — because **fixing the probe changes behaviour**:
projects with an `[ai]` section start being honoured.

That is a taxonomy decision (does the AI plugin read the app's config or not),
not an annotation sweep, which is why it is here. Fourth dead probe of this
exact shape found during that feature.

---

## R7 — `MCPAdapterPlugin` is not an `AdapterPlugin` (new; handed over)

Its name, its `adapter_type = "mcp"` and its docstring
(`_plugin.py:25`, *"Implements the AdapterPlugin protocol"*) all claim the
protocol. An `ast` walk of its class body:

```
MCPAdapterPlugin -> ['__init__', 'config', 'server', '__call__',
  '_on_app_ready', '_ensure_initialized', '_resolve_mcp_config',
  '_register_ai_outbound_strategy', '_register_cli_commands',
  '_register_serve_command', '_register_start_command',
  '_register_list_command', '_register_stop_command',
  '_register_schema_command', '_register_tools_command']
```

`AdapterPlugin` (`_types/protocols.py:96-132`) requires `__call__`, **`run`**
and **`shutdown`**. Two of three are missing.

Nothing caught it because `validate_adapter`
(`src/functualize/app/adapters/_validation.py:28`) has **no production caller**:
its only importers are `app/adapters/__init__.py` (a re-export) and five test
files. A protocol claimed in a docstring and checked only by tests that never
see this class.

This is a naming/taxonomy defect of exactly the kind the feature exists to
close — a plugin whose declared role and actual surface disagree.

---

## R8 — `functualize_ai.__init__` hides its types from mypy (new; handed over)

`plugins/functualize-ai/src/functualize_ai/__init__.py:140` resolves `AI` and
`AIConfig` through a `__getattr__` table with **no `TYPE_CHECKING` block**
(`git grep -n 'TYPE_CHECKING' plugins/functualize-ai/src/functualize_ai/__init__.py`
→ no match). mypy therefore sees module-level *variables*, not types.

Measured consequence, from `plugin-host-protocol`/T11: this is the source of
most of `functualize-ai-pydantic`'s **47-error** mypy baseline, and of the one
error that feature's port annotation added (47 → 48). It is the reason one
plugin cannot be brought to a clean baseline by annotating it.

---

## R9 — `AC-17` as written is unachievable, and would delete the right prose

**New in revision 2. This one indicts the spec, not the code.**

Revision 1's AC-17 is *"`rg -n 'StateBackend\|ExecutionStore' docs/ examples/
plugins/ --glob '!*/adr/*'` — 13 files → 0 files"*. Re-measured with working
alternation over tracked files:

```
$ git grep -l -E 'StateBackend|ExecutionStore' -- docs/ examples/ plugins/ ':!*/adr/*' | wc -l
24
```

But **16 of those 24 files mention the names only to record that they were
retired.** `functualize-state-sqlite/_plugin.py:5-16` is the clearest case — a
module docstring whose whole subject is that `StateBackend` and `ExecutionStore`
are gone and why, citing ADR-022 *"so it is not re-proposed"*. Driving that file
to zero matches means deleting the explanation.

The live references — the ones that are actually false — are **8 sites in 4
files**, found by asking for imports and calls rather than for the string:

```
$ git grep -n -E '^(from|import).*(StateBackend|ExecutionStore)|(StateBackend|ExecutionStore)\(' \
    -- docs/ examples/ plugins/ ':!*/adr/*'
plugins/functualize-ai-pydantic/tests/test_plugin.py:30  from functualize_ai._state_fallback import EphemeralStateBackend
plugins/functualize-ai/src/functualize_ai/_state_fallback.py:119  return EphemeralStateBackend()
plugins/functualize-state-sqlite/README.md:16,19          from functualize_state_sqlite import SQLiteStateBackend
plugins/functualize-state-sqlite/examples/persistent_counter/persistent_counter.py:10,19
plugins/functualize-state-sqlite/examples/persistent_counter/test_persistent_counter.py:10,22
```

Two different defects, and the spec was conflating them:

- **`SQLiteStateBackend` (3 files, 6 sites)** — imports a class that does not
  exist. Broken. This is R4.
- **`EphemeralStateBackend` (2 files, 2 sites)** — a class that *does* exist, in
  `_state_fallback.py`, built on a protocol that does not. This is the F2
  module, 119 LOC, whose warning text tells the user to
  *"Install functualize-state-sqlite for persistent storage"* — advice that
  cannot work, because that plugin no longer provides a `StateBackend`.

AC-17 is replaced in revision 2 by two gates that separate them, and the
prose-mention count is recorded as a *baseline to preserve*, not to drive to
zero.

---

## R10 — `plugins/PUBLISHING.md` still ships the retired `functualize-state`

**New in revision 2.** The maturity-tier document that governs which plugins may
be published lists a distribution ADR-022 removed:

```
PUBLISHING.md:104  ├── functualize-state           → pydantic (no core dep)
PUBLISHING.md:113  ├── functualize-ai              → functualize-state
PUBLISHING.md:114  ├── functualize-state-sqlite    → functualize-state, core
PUBLISHING.md:115  └── functualize-tasks-local     → functualize-tasks, functualize-state
PUBLISHING.md:194  | functualize-state | 1 — Ready | 0 | State management capability |
PUBLISHING.md:226  | functualize-state | functualize-state | `functualize_state` |
```

Three plugins are documented as depending on a package that does not exist.
Same class as the three codemaps:

```
codemaps/overview.md:73       "13 official plugins … (ai, interactivity, state, tasks …)"
codemaps/modules.md:153       | `functualize-state` | Domain SDK (protocols) | …
codemaps/dependencies.md:117  members = ["plugins/*"] — all 13 plugins auto-included
```

Measured: `ls -d plugins/functualize-*/ | wc -l` → **12**. All four documents
are consumers of both item A (the move) and item B (the renames), so they are
part of this feature rather than a later `/sync-docs` sweep.

---

## Q2 re-framed: the classification is cheaper one way than revision 1 assumed

Revision 1 posed Q2 as *"`functualize.plugins` (cheap, but classifies as
ADAPTER — wrong) vs a new `functualize.substrates` group plus
`PluginKind.SUBSTRATE` (costs more, says the truth)"*. Reading
`_primitives/plugin_kinds.py` changes the arithmetic.

`classify_group` is **derived, not enumerated** (`plugin_kinds.py:56-81`):

```
functualize.plugins            -> ADAPTER
functualize.domains            -> DOMAIN
functualize.<x>_providers      -> IMPLEMENTATION      (any x)
anything else                  -> UNKNOWN
```

Consequences revision 1 did not have:

1. **`functualize.state_providers` already classifies as `IMPLEMENTATION`**, not
   as ADAPTER — confirmed by `tests/primitives/test_plugin_kinds.py:27`. The
   problem with today's sqlite plugin is *only* that nothing reads the group; it
   is not mis-labelled. Revision 1's framing of Q2 was wrong on this point.
2. **A `functualize.substrates` group would classify as `UNKNOWN`** — "substrates"
   is not `plugins`, not `domains`, and does not end in `_providers`. Choosing
   that name *requires* editing `plugin_kinds.py`, and the file's own docstring
   (`:11-18`) argues against hard-coding names there: *"a distribution publishing
   under `functualize.vault_providers` classifies as an implementation here
   without anyone editing this file."*
3. **`functualize.substrate_providers` classifies as `IMPLEMENTATION` for free**,
   with zero edits to `_primitives`, and reads correctly in
   `plugin available` under *"Implementations: pick the one matching your
   infrastructure"* (`plugin_catalog.toml:67`).

So the real choice is now: *reuse the derived `_providers` convention and add a
reader*, versus *introduce a kind the derivation cannot produce*. That is a
different question from the one revision 1 asked, and it leans harder toward
the former. **Still the architecture gate's call** — AC-1 and AC-3 name
behaviour, not a group.

The type-level input from `plugin-host-protocol` stands: `PluginHost` declares
`install_substrate` and `fresh_root` (`_types/host.py`), so a substrate plugin
*is* distinguishable by interface. But `PluginKind` is resolved at load time
from the group string, where no type is available — so the interface argument
supports a distinct kind without supplying a mechanism for it.

---

## Prior art consulted, and whether this feature contradicts it

| Source | Says | This feature |
|---|---|---|
| `contributor/adr/022` | `StateBackend`/`ExecutionStore` retired; storage is a substrate | **Follows.** F1/F2/G finish the cleanup 022 started |
| `contributor/adr/016` | AWS/Bitwarden are *remote sources*; `boto3` in `src/` must stay 0 (**re-verified: 0**) | **Contradicts the vocabulary.** Item D renames `remote_providers` → `secrets_providers`; ADR-016's language must be superseded in writing |
| `contributor/adr/015` §Correction | `[all]` is what the binary bakes; musl targets constrain it | **Follows, and inherits the consequence.** Item E removes AWS from `[all]`, so the binary loses AWS secrets |
| `contributor/guides/plugin-development.md:78-89` | "`members = ["plugins/*"]` — already a glob — your plugin is auto-included" | **Contradicted by item A** (R1b). A required edit, not docs polish |
| `_primitives/plugin_kinds.py:11-18` | kinds are derived from the group name, "never from a list of package names" | **Constrains Q2** — see above |
| `plugins/PUBLISHING.md` | tiers, and a dependency graph naming `functualize-state` | **Contradicted by ADR-022 already** (R10); this feature is where it gets fixed |
| `.spec/CONSTITUTION.md` → *Forbidden Patterns* | "no `DeprecationWarning` / backward-compat shims — pre-release. Remove old code." | **Follows**, and is the constitutional basis for D1 and D4 |
| `contributor/reference/public-api-example-coverage.md` (new, 2026-09-17) | every public API symbol needs a caller in `examples/` | **Inherited.** `functualize-substrate-s3` and anything newly exported fall under it |
