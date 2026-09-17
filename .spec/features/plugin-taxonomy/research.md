# plugin-taxonomy — research

**Date:** 2026-09-16 · **Base:** branch `feat/plugin-host-protocol` @ `79545ef`
(master `11d77f6`). Second feature folder on that branch, per maintainer
decision; `.spec/features/plugin-host-protocol/` is untouched.

Everything below was produced by running a command. The command is shown.
Findings that only confirm the brief are in `spec.md`; this file holds the four
that **change the shape of the feature** and were not in the brief.

---

## Retrieval passes run

| Pass | Tool | What it answered |
|---|---|---|
| Prose — prior art | zvec-grep (index rebuilt for this worktree: 780 files / 12 627 entities / 1 m 3 s) | ADR-015 §Correction, ADR-016, ADR-022, `contributor/guides/plugin-development.md` §4, `codemaps/dependencies.md` |
| Premises — counts and negatives | `rg` / `grep -rIl` | every number in `spec.md` |

**Index note for the next agent.** The worktree's `.zvec-grep/manifest.json`
came back **root-owned `0600`** after a backgrounded `zg index`, and every
subsequent `zg` call failed `EACCES`. `sudo chown -R ubuntu:ubuntu .zvec-grep`
then a foreground re-index fixed it. This is not the `[INDEX_MISSING]` case
`.claude/rules/spec-workflow.md` documents — `zg status` reported *"Workspace
index is not configured"*, which reads like an absent index and is actually a
permissions failure. Worth adding to `code-intel/SKILL.md`.

---

## R1 — The folder move silently disables this repo's own spec gate

**Not in the brief. Highest-severity finding here, because it disables the
mechanism that would catch the rest of the work.**

`.claude/hooks/spec_gate.py:79-87` decides whether a write is gated:

```python
plugins_root = os.path.realpath(os.path.join(root, "plugins"))
if not contained(plugins_root):
    return False
rel = os.path.relpath(target, plugins_root).split(os.sep)
# plugins/<pkg>/src/... -> gated. plugins/<pkg>/tests/..., conftest -> free.
return len(rel) >= 3 and rel[1] == "src"
```

`rel[1] == "src"` assumes exactly one directory level under `plugins/`. After
item A:

```
plugins/adapters/functualize-http/src/x.py
rel = ["adapters", "functualize-http", "src", "x.py"]
rel[1] == "functualize-http"   ->  != "src"  ->  NOT GATED
```

Every plugin source file leaves the gate. And `.claude/rules/spec-workflow.md`
says the gate **fails open** by design — so nothing reports it. The repository
would lose spec enforcement over `plugins/**/src/**` with no error, no test
failure and no log line.

The same one-level assumption is written into two more places, both verified:

| File | Line | Text |
|---|---|---|
| `.claude/hooks/spec_gate.py` | 25 | `GATED_GLOB_PARTS = ("plugins", "src")  # plugins/<pkg>/src/**` |
| `.claude/hooks/agent_contract.py` | 30 | ``Modifying `src/functualize/**` or `plugins/*/src/**` requires…`` |
| `.claude/hooks/plan_context.py` | 42 | same sentence |

**Consequence for the plan:** the gate fix is wave 1, before any directory
moves, and it needs an acceptance gate that *executes* `spec_gate.py`'s
predicate against a nested path — not a reading of it.

---

## R2 — The renames make `plugin available --remote` advertise the dead names

**Not in the brief.**

`src/functualize/_cli/plugin_cmd.py:395-425` enumerates the PyPI Simple index
and keeps every project whose name starts with `functualize-`:

```python
return tuple(sorted(
    name for project in payload.get("projects", [])
    if isinstance(name := project.get("name"), str)
    and name.startswith("functualize-")))
```

`available_rows` (`plugin_cmd.py:316-328`) then renders anything not in the
curated catalog as `kind="unknown"`, `source="remote"`, under the heading
(`plugin_cmd.py:_KIND_ORDER`):

```
UNCURATED — found on PyPI, not vetted by this project
```

The maintainer chose **no compatibility shims**, so `functualize-aws`,
`functualize-bitwarden` and `functualize-state-sqlite` stay on PyPI at 0.2.3
forever. `func builtin plugin available --remote` would therefore offer a user
three abandoned distributions, one of which (`functualize-state-sqlite`) does
nothing even when installed.

**This is a behaviour change the spec must own,** not a packaging footnote. Two
candidate answers for Plan: a denylist in `plugin_catalog.toml` that suppresses
retired names, or accept it and say so in the CHANGELOG. Recorded here rather
than decided.

---

## R3 — The dead group is taught by the repo's own tutorial

**Not in the brief.** F1 is worse than "two plugins don't load".

`examples/plugins/custom_state_backend/pyproject.toml:11`:

```toml
[project.entry-points."functualize.state_providers"]
memory = "functualize_state_memory:MemoryStatePlugin"
```

This is the documented example for writing a third-party substrate — it is in
the mkdocs nav (`mkdocs.yml:148`, *Custom State Backend*) and
`docs/examples/plugins/custom-state-backend.md`. A reader who follows it
end-to-end produces a plugin that **never loads**, for the same reason
`functualize-state-sqlite` never loads. The example's own README
(`examples/plugins/custom_state_backend/README.md:50-67`) correctly describes
installing a substrate at `APP_READY` — the body is right and the wiring is
dead.

So F1's fix must cover **three** registrations, not two: the sqlite plugin, the
inline plugin, and this example. The example's directory name, doc title and nav
entry also still say *state backend*, a protocol ADR-022 retired.

---

## R4 — A second `functualize-state-sqlite` example is broken at import

**Not in the brief.**

`plugins/functualize-state-sqlite/examples/persistent_counter/test_persistent_counter.py:10`:

```python
from functualize_state_sqlite import SQLiteStateBackend
```

`SQLiteStateBackend` is defined **nowhere** in the repository:

```
$ grep -rn "class SQLiteStateBackend\|SQLiteStateBackend =" --include=*.py .   # 0
$ python -c "import functualize_state_sqlite as m; print(m.__all__)"
  -> ['SQLiteStatePlugin', 'SQLiteSubstrate']
```

It survives because nothing collects it. Root `pyproject.toml:171` sets
`testpaths = ["tests"]`, and `ci.yml` runs plugin suites for exactly one plugin:

```
ci.yml:232  uv run pytest plugins/functualize-mcp/tests -q
ci.yml:235  uv run pytest plugins/functualize-mcp/examples -v
```

**The general fact behind it:** eleven of twelve plugins have test suites that
CI never runs. That is out of scope for this feature, but it is why F1–F4 could
all be true at once with a green pipeline, and it belongs in `.spec/STATUS.md`
regardless of what this feature does.

---

## R5 — A note on the dev environment, for whoever executes this

Under a plain `uv sync`, the workspace plugins are **not installed**:

```
$ python -c "…distributions() … startswith('functualize')"
functualize
functualize-bitwarden
```

Only core, plus `functualize-bitwarden` because it is in the `dev`
dependency-group (`pyproject.toml:71-79`). The plugins reach the test suite two
other ways — `uv sync --all-extras` / `--all-packages` in CI, and
`tests/conftest.py:352-360`, which inserts
`plugins/functualize-state-sqlite/src` on `sys.path` by **filesystem path**.

That `sys.path` insert is a path consumer of item A and a name consumer of item
B simultaneously. It is also why the sqlite plugin's substrate is exercised by
tests while its *plugin class* is not: the tests never go through an entry
point.

---

## Prior art consulted, and whether this feature contradicts it

| Source | Says | This feature |
|---|---|---|
| `contributor/adr/022` | `StateBackend`/`ExecutionStore` retired; storage is a substrate | **Follows.** F1/F2/G finish the cleanup 022 started; the artifacts 022 left behind are what this feature removes |
| `contributor/adr/016` | AWS/Bitwarden are *remote sources*; `grep -rn boto3 src/functualize/` must stay 0 (**verified: 0**) | **Contradicts the vocabulary.** Item D renames `remote_providers` → `secrets_providers`; ADR-016's language must be superseded in writing, not silently diverged from |
| `contributor/adr/015` §Correction | `[all]` is what the binary bakes (`PYAPP_PROJECT_FEATURES=all`); musl targets constrain it | **Follows, and inherits the consequence.** Item E removes AWS from `[all]`, so the binary loses AWS secrets — stated in `spec.md` AC-12 |
| `contributor/guides/plugin-development.md:78-89` | "`members = ["plugins/*"]` — Already a glob — your plugin is auto-included" | **Contradicted by item A.** The glob stops being sufficient; the guide is a required edit, not optional docs polish |
| `.spec/CONSTITUTION.md` → *Forbidden Patterns* | "`DeprecationWarning` / backward-compat shims — pre-release, no users to deprecate toward. Remove old code." | **Follows, and this is the constitutional basis for the maintainer's "no shims" and "hard cutover" choices.** Worth citing in the PR |

### One place prior art outranks the brief

The brief proposes registering the substrate plugin under `functualize.plugins`
"the group that is actually loaded". That works, but `_primitives/plugin_kinds.py:56`
classifies `functualize.plugins` → `PluginKind.ADAPTER`, and
`_cli/plugin_cmd.py:_KIND_ORDER` renders adapters as *"add commands or a
delivery surface"*. A substrate does neither.

So the cheap fix produces a correctly-loading plugin that the CLI describes
wrongly. The alternative — a `functualize.substrates` group that core actually
reads, plus a `PluginKind.SUBSTRATE` — costs more and says the truth.
**Deliberately left open: this is exactly the call the Plan phase's architecture
gate exists to make.** `spec.md` states the required *behaviour* (AC-1, AC-3)
without naming a group, so either shape can satisfy it.


---

## Input to Q2 from `plugin-host-protocol` (2026-09-17)

That feature's port gained two storage members on maintainer decision
(`.spec/features/plugin-host-protocol/spec.md` AC-2b, `contracts.md` §1):

```python
class PluginHost(Protocol):
    ...
    def install_substrate(self, substrate: StoreSubstrate) -> None: ...
    @property
    def fresh_root(self) -> Path: ...
```

Both were below its own ≥2-client threshold — one client each,
`functualize-state-sqlite/_plugin.py:78` and `:95` — and were included because
without them that plugin cannot adopt the port at all.

**Why this bears on Q2** (*"which group does a substrate register in —
`functualize.plugins`, or a new `functualize.substrates` with
`PluginKind.SUBSTRATE`?"*): that pair is now, in effect, the substrate-plugin
contract. A substrate plugin is distinguishable **by type** — it is the plugin
whose `__call__` uses `install_substrate` — rather than only by which
entry-point group it declared. That makes a distinct `PluginKind.SUBSTRATE`
easier to justify, because the kind would correspond to a real interface
difference rather than a label.

It does not decide Q2. `PluginKind` is resolved at load time from the
entry-point group (`_primitives/plugin_kinds.py:56`), and a type-level
distinction is not available there. But the option "a new group plus a new kind"
can now cite an interface, and "reuse `functualize.plugins` and accept the
ADAPTER label" has to argue against one.

**Also inherited**: `contributor/reference/public-api-example-coverage.md`
(maintainer, 2026-09-17) — every public API symbol needs a caller in
`examples/`. This feature's `functualize-substrate-s3` (D.5/AC-15) and anything
it newly exports fall under it.
