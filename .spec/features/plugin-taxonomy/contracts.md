# plugin-taxonomy — contracts

**Revision 2 · 2026-09-17 · base `feat/plugin-host-protocol` @ `80ec5f0`.**

External interfaces only: distribution identities, entry-point groups, exported
symbols, config sections, and user-visible command output. Internal types and
storage schemas are not here.

Every line number below was re-taken at `80ec5f0` with `git grep`. Anything
marked **OPEN** is deliberately unsettled and is a Plan-phase decision
(`spec.md` §I).

**Revision 2 splits this contract across three pull requests** (`spec.md` §B
D1′, D9) and **removes `functualize-substrate-s3`** from the feature (D7). Each
section says which PR owns it.

---

## 0 · The three pull requests

| | Delivers | Claims on PyPI |
|---|---|---|
| **PR-1** | The directory move, the wiring fixes, the storage-correctness fixes, the plugin-surface fixes, the doc truth, **and one rename**: `functualize-state-sqlite` → `functualize-substrate-sqlite` | one new name |
| **PR-2** | `functualize-aws` → `functualize-secrets-aws`, plus the `remote_providers` → `secrets_providers` group cutover | one new name |
| **PR-3** | `functualize-bitwarden` → `functualize-secrets-bitwarden` | one new name |

**One new distribution name per PR is the constraint that produces this split.**
A *pending* trusted publisher is unique on `(owner, repo, workflow, environment)`,
so one workflow can claim exactly one not-yet-existing name
(`release.yml:119-130`). Capping each PR at one rename keeps every publish
automatic — no manual token upload anywhere.

PR-2 and PR-3 are cut **last**, each on its own branch, after PR-1 merges.

---

## 1 · Distribution identities

### 1.1 · Renamed — one per PR, no shims

| PR | Before | After | Import package before | Import package after |
|---|---|---|---|---|
| **1** | `functualize-state-sqlite` | `functualize-substrate-sqlite` | `functualize_state_sqlite` | `functualize_substrate_sqlite` |
| **2** | `functualize-aws` | `functualize-secrets-aws` | `functualize_aws` | `functualize_secrets_aws` |
| **3** | `functualize-bitwarden` | `functualize-secrets-bitwarden` | `functualize_bitwarden` | `functualize_secrets_bitwarden` |

Old PyPI names are abandoned at 0.2.3. No shim distribution, no
`DeprecationWarning` (`.spec/CONSTITUTION.md` → *Forbidden Patterns*).

### 1.2 · New — none

Revision 1 added `functualize-substrate-s3`. **Removed from this feature** (D7):
it is a second not-yet-existing PyPI name, and it must not exist in a version
carrying the `LocalTaskProvider` concurrency bug (`spec.md` A.4), which PR-1
fixes. It gets its own PR afterwards. Its intended surface is preserved in §9 so
that PR does not start from nothing.

### 1.3 · Unchanged — nine

`functualize-http`, `functualize-lambda`, `functualize-mcp`,
`functualize-flow-viz`, `functualize-inline`, `functualize-tasks`,
`functualize-tasks-local`, `functualize-ai`, `functualize-ai-pydantic`.

Their **directories** move in PR-1 (§2); their distribution and import names do
not.

---

## 2 · Repository layout — **PR-1** — **SETTLED (Q4, maintainer 2026-09-17)**

```
plugins/
  adapters/    functualize-http, functualize-lambda, functualize-mcp,
               functualize-flow-viz, functualize-inline
  substrates/  functualize-substrate-sqlite
  secrets/     functualize-aws, functualize-bitwarden
  domains/     functualize-ai, functualize-ai-pydantic,
               functualize-tasks, functualize-tasks-local
  conftest.py  PUBLISHING.md                    (stay at the plugins/ root)
```

**Four groups, not the five revision 1 proposed.** `providers/` is gone: its
three members are placed by what they actually are.

- **An implementation sits beside the contract it implements**, as a sibling
  under `domains/` — not nested inside it. `functualize-ai` /
  `functualize-ai-pydantic` and `functualize-tasks` / `functualize-tasks-local`
  sort adjacent, so the relationship the tree could not show before is now
  visible by reading the directory. Siblings rather than children keeps **every
  plugin at exactly two levels**, which is what `members = ["plugins/*/*"]` and
  the spec gate are taught; a third level would be a third special case in both.
- **`functualize-inline` goes to `adapters/`**, not `domains/`. It implements no
  domain contract — the group it claimed (`functualize.interactivity_providers`)
  is one §3.3 deletes because the domain never existed. It is a delivery
  surface: `InlinePlugin` implements `InputProvider` and `OutputRenderer`. After
  §3.3 it registers under `functualize.plugins`, the same group as the four
  adapters, so its folder and its entry-point group agree by construction.

Folder names express **role**, which is independent of distribution names — so
`plugins/secrets/functualize-aws/` is a correct and temporary state between PR-1
and PR-2, not a half-migration.

### 2.1 · Path consumers that must change with it

Every one verified present at `80ec5f0`. A move that misses one of these breaks
**silently** rather than loudly, which is why they are a contract and not a note.

| File | Line | Current | Fails how |
|---|---|---|---|
| `pyproject.toml` | 133 | `members = ["plugins/*"]` | Loudly — `uv sync` finds no packages |
| `.claude/hooks/spec_gate.py` | 25 | `GATED_GLOB_PARTS = ("plugins", "src")` | **Silently** — the gate fails open |
| `.claude/hooks/spec_gate.py` | 87 | `return len(rel) >= 3 and rel[1] == "src"` | **Silently** — same |
| `.claude/hooks/agent_contract.py` | 30 | ``… or `plugins/*/src/**` requires…`` | Silently — prose only |
| `.claude/hooks/plan_context.py` | 42 | same sentence | Silently — prose only |
| `.claude/rules/spec-workflow.md` | 32 | same sentence, **in the contract itself** | Silently — prose only |
| `evals/providers/_harness.py` | 172 | `"plugins/*/pyproject.toml"` | Silently — an empty eval set |
| `tests/conftest.py` | 356, 360 | `… / "plugins" / "functualize-state-sqlite" / "src"`, then `import functualize_state_sqlite.substrate` | Loudly — path **and** name, one fixture |
| `tests/integration/test_substrate_durability.py` | 149, 231, 279 | three literal `plugins/functualize-state-sqlite/src` paths | Loudly |
| `.github/workflows/ci.yml` | 232, 235 | `plugins/functualize-mcp/tests`, `…/examples` | Loudly |
| `contributor/guides/plugin-development.md` | 78-89 | *"Already a glob — your plugin is auto-included"* | Becomes false; a required edit |
| `plugins/PUBLISHING.md` | throughout | `plugins/<name>/…` verification commands | Becomes false |

**Ordering is contractual:** `spec_gate.py` is fixed **before** anything moves.
It fails open by design (`.claude/rules/spec-workflow.md`), so a move-first
sequence leaves the repository unguarded with no signal.

---

## 3 · Entry-point groups

### 3.1 · Renamed — hard cutover — **PR-2**

```
functualize.remote_providers   ->   functualize.secrets_providers
```

Sole reader today: `src/functualize/_config/registry.py:193`. Core reads the new
name **only**; the old string must not survive in `src/`. Measured at `80ec5f0`:
**18 sites across 5 files in `src/`**, 60 sites across 20 files repo-wide
(tracked files, `.spec/` excluded).

**PR-2 also updates `functualize-bitwarden`'s declaration** to the new group —
its *distribution name* stays `functualize-bitwarden` until PR-3. Both declarants
must move with the reader, or master briefly carries a plugin registering in a
group nothing reads, which is the exact defect this feature exists to close.

Entry-point *names* within the group are unchanged: `aws-sm`, `aws-ssm`, `bws`.
They are what a user writes in config, and D1′–D4 did not touch them.

### 3.2 · Retired — declared by nobody afterwards — **PR-1**

```
functualize.state_providers           2 declarants:
                                        plugins/functualize-state-sqlite/pyproject.toml:23
                                        examples/plugins/custom_state_backend/pyproject.toml:10
functualize.interactivity_providers   1 declarant:
                                        plugins/functualize-inline/pyproject.toml:24
```

Measured reach of the two strings: **17 tracked files** outside `.spec/` and
`CHANGELOG.md`, including `src/functualize/_cli/data/plugin_catalog.toml:76,97`
and five test files.

### 3.3 · Where the retired declarants go — **SETTLED** — **PR-1**

**Revision 3, 2026-09-17.** The architecture gate (`plan.md` §1.1) found that
both earlier revisions asked the wrong question, one level apart. Revision 1
asked *"`functualize.plugins` (cheap, wrong label) or `functualize.substrates`
(costly, right label)?"*. Revision 2 corrected the classification arithmetic and
recommended `functualize.substrate_providers` as *"`IMPLEMENTATION` for free"*.
**Revision 2's recommendation is wrong**, and the reason invalidates the shape
of the question:

> `functualize.<x>_providers` is not a naming convention. It is the provider
> group of a **domain SDK** `<x>`, read by `_plugins/domain_registry.py:246`
> from the `entry_point_group` field of a live `DomainMetadata` published under
> `functualize.domains`. A `_providers` group with no domain behind it has no
> reader at all.

Measured — every `entry_point_group=` in the tree:

```
$ git grep -rn 'entry_point_group=' -- plugins/ examples/ src/
plugins/functualize-ai/src/functualize_ai/_metadata.py:32        functualize.ai_providers
plugins/functualize-tasks/src/functualize_tasks/_metadata.py:32  functualize.tasks_providers
src/functualize/_cli/scaffold/templates/domain-sdk/_metadata.py.j2:32   (a template)
```

Two domains: `ai` and `tasks`. No `state` domain (ADR-022 removed
`functualize-state`), no `interactivity` domain, no `vault_key` domain.
`functualize.substrate_providers` would have joined `functualize.state_providers`
in being classified correctly and loaded never.

**The contract, therefore:**

```toml
# plugins/substrates/functualize-substrate-sqlite/pyproject.toml
[project.entry-points."functualize.plugins"]
substrate-sqlite = "functualize_substrate_sqlite:SQLiteSubstratePlugin"

# plugins/providers/functualize-inline/pyproject.toml
[project.entry-points."functualize.plugins"]
inline = "functualize_inline:InlinePlugin"

# examples/plugins/custom_state_backend/pyproject.toml
[project.entry-points."functualize.plugins"]
memory = "functualize_state_memory:MemoryStatePlugin"
```

This is not a new pattern. `_cli/scaffold/templates/full-interactivity/pyproject.toml.j2:18-20`
**already** registers both `InlinePlugin` and `SQLiteStatePlugin` under
`functualize.plugins`, and a scaffolded project loads them. The same classes
work there and are dead when installed from PyPI — which is the defect, stated
as a contract.

**The accepted cost.** `functualize.plugins` classifies as `PluginKind.ADAPTER`
(`_primitives/plugin_kinds.py:73`), rendered by `_cli/plugin_cmd.py:335-339` as
*"adds commands or a delivery surface"*. A substrate does neither, so `spec.md`
U3 is **not fully met by PR-1**. Recorded as a surviving smell (`plan.md` §5
entry 2) and **flagged for maintainer review**. Two later remedies remain open,
neither in PR-1:

- a `functualize.substrates` group plus `PluginKind.SUBSTRATE` — a second
  loading mechanism beside the domain registry, and a hard-coded group name in
  `_primitives`, which that module's docstring (`:11-18`) argues against;
- broadening what `ADAPTER` renders as, since it now covers more than delivery.

**The rule that replaces the guesswork**, and which T6 enforces mechanically:

> Every `functualize.*` group a shipped `pyproject.toml` declares is either in
> `READ_GROUPS` (the seven core reads statically, newly named in
> `_primitives/entry_point_groups.py`) or is the `entry_point_group` of an
> installed `DomainMetadata`. Anything else is dead on arrival.

### 3.4 · `functualize.vault_key_providers` — **SETTLED: deleted** — **PR-1**

Declared at root `pyproject.toml:49`, read by no `entry_points(group=…)` call —
the whole repo has exactly **two** occurrences of the string:

```
pyproject.toml:49                        [project.entry-points."functualize.vault_key_providers"]
src/functualize/_config/vault_keys.py:6  "register through the `functualize.vault_key_providers` entry-point group"
```

Core imports `EnvKeyProvider` and `KeychainKeyProvider` directly, so nothing is
broken at runtime. But `vault_keys.py:6` tells plugin authors they may register
through it, which is false. (Dead-code audit finding #3, HIGH.)

**Settled by §3.3's rule: deleted.** It is a `<x>_providers` group for a
`vault_key` domain that does not exist, so "give it a reader" is not available —
the reader would have to be the domain registry, and the domain registry only
scans groups a live `DomainMetadata` names. Both sites go: the declaration at
root `pyproject.toml:49` and the sentence at `_config/vault_keys.py:6`.

---

## 4 · Exported symbols of the renamed packages

Symbol names are unchanged except where noted; the module path moves.

| PR | Package | `__all__` at `80ec5f0` |
|---|---|---|
| **1** | `functualize_substrate_sqlite` | `SQLiteSubstrate`, `SQLiteSubstratePlugin` (**renamed**, below) — today `functualize_state_sqlite.__all__` is `['SQLiteStatePlugin', 'SQLiteSubstrate']` |
| **2** | `functualize_secrets_aws` | `HONOURED_KEYS`, `AccountMismatchError`, `AwsReference`, `InvalidReferenceError`, `ParameterStoreProvider`, `SecretNotFoundError`, `SecretsManagerProvider`, `clear_credential_cache`, `parse_reference` |
| **3** | `functualize_secrets_bitwarden` | `ACCESS_TOKEN_VAR`, `HONOURED_KEYS`, `ORGANIZATION_VAR`, `AmbiguousKeyError`, `BitwardenAuthError`, `BitwardenRequestError`, `BwsReference`, `InvalidReferenceError`, `MissingOrganizationError`, `SecretNotFoundError`, `SecretsManagerProvider`, `clear_client_cache`, `parse_reference` |

Revision 1's bitwarden list was short by three (`MissingOrganizationError`,
`clear_client_cache`, `parse_reference`); corrected from
`functualize_bitwarden/__init__.py:54-68`.

### 4.1 · One class rename — **PR-1**

`SQLiteStatePlugin` → `SQLiteSubstratePlugin`. The word *State* names a domain
ADR-022 retired; keeping it reintroduces the mismatch this feature exists to
remove. Three things move with it:

| | Before | After |
|---|---|---|
| Class | `SQLiteStatePlugin` | `SQLiteSubstratePlugin` |
| `name` attribute (`_plugin.py:46`) | `"sqlite-state"` | `"substrate-sqlite"` |
| Config section (`_plugin.py:115`) | `plugin.sqlite-state` | `plugin.substrate-sqlite` |
| `description` (`_plugin.py:48`) | *"Keeps this project's runtime state in SQLite"* | says *substrate* |

The config-section move is **user-visible**: a `[plugin.sqlite-state]` block in
someone's `.functualize.toml` stops being read. CHANGELOG entry required.

### 4.2 · Symbols that must **stop** existing in documentation — **PR-1**

`SQLiteStateBackend` is imported or instantiated in four tracked files and is
defined nowhere:

```
plugins/functualize-state-sqlite/README.md:16,19
plugins/functualize-state-sqlite/examples/README.md
plugins/functualize-state-sqlite/examples/persistent_counter/persistent_counter.py:10,19
plugins/functualize-state-sqlite/examples/persistent_counter/test_persistent_counter.py:10,22
```

These are the published surface of the package, so removing them is a contract
change, not a docs fix. (`spec.md` AC-12.)

---

## 5 · Plugin-surface contracts — **PR-1**

### 5.1 · `MCPAdapterPlugin` and `AdapterPlugin` — **OPEN (Q6)**

`AdapterPlugin` (`src/functualize/_types/protocols.py:96-132`) requires:

```python
class AdapterPlugin(Protocol):
    def __call__(self, app: PluginHost) -> None: ...
    def run(self, *args: Any, **kwargs: Any) -> Any: ...
    def shutdown(self) -> None: ...
```

`MCPAdapterPlugin` (`plugins/functualize-mcp/src/functualize_mcp/_plugin.py:22`)
has `__call__` and neither of the other two — measured by an `ast` walk of its
`ClassDef`, not by grep. It nonetheless declares `adapter_type = "mcp"` (`:34`)
and its docstring says *"Implements the AdapterPlugin protocol"* (`:25`).

Two contracts satisfy `spec.md` AC-17; the Plan phase picks one:

- **Grow the class** — add `run` and `shutdown`, making the claim true. `run`
  would serve the MCP server; `shutdown` would stop it.
- **Drop the claim** — remove `adapter_type` and the docstring sentence. It
  remains a perfectly good plugin; it is just not an *adapter*.

Either way `validate_adapter` (`src/functualize/app/adapters/_validation.py:28`)
gains a **production caller**. It has none today — its only importers are
`app/adapters/__init__.py:35` (a re-export) and five test files — which is why a
protocol claimed in three places went unchecked.

### 5.2 · `functualize-ai` config resolution

`_provider_discovery.py:218` guards on `hasattr(app, "resolve_model")`. There is
no `FunctualizeApp.resolve_model`: the only definitions are
`_app/configuration_facade.py:98`, `_app/impl.py:882`, and the port at
`_types/host.py:167` — all reached as `app.configuration.resolve_model`. The
guard is therefore always `False`.

The contract after PR-1 is one of:

- **`resolve_ai_provider(app=…)` reads the `[ai]` section** through
  `app.configuration.resolve_model("ai", AIConfig)`. **This changes behaviour**
  for any project with an `[ai]` block — today those settings are discarded.
  CHANGELOG entry required.
- **It documents that it does not**, and takes `config` explicitly.

The always-False probe survives in neither. (`spec.md` AC-18.)

### 5.3 · `functualize_ai.__init__` type visibility

`plugins/functualize-ai/src/functualize_ai/__init__.py:140` resolves `AI` and
`AIConfig` through a `__getattr__` table with **no `TYPE_CHECKING` block**, so a
type checker sees module-level variables rather than types. The contract is that
`from functualize_ai import AI, AIConfig` yields *types* to mypy — the standard
lazy-import shape, a `TYPE_CHECKING` block re-declaring the real imports.

Measured consequence: this is the source of most of `functualize-ai-pydantic`'s
**47-error** mypy baseline. (`spec.md` AC-19.)

---

## 6 · Packaging surface

### 6.1 · Root `pyproject.toml` — **PR-2**

```toml
[project.optional-dependencies]
cli = [ … unchanged, no plugins … ]
all = [
    "functualize[cli]",
    # NOT here: functualize-secrets-aws, functualize-secrets-bitwarden
    …
]
```

`functualize-aws` leaves `[all]` in **PR-2**, joining `functualize-bitwarden`'s
existing precedent (`pyproject.toml:105-118`, and the same argument recorded at
`plugin_catalog.toml:113-121`). `[cli]` never contained either.

**Downstream consequence, contractual because it is user-visible:** `[all]` is
what the standalone binary bakes (`PYAPP_PROJECT_FEATURES=all`, ADR-015
§Correction / `release.yml`). The binary therefore ships **without** AWS Secrets
Manager and SSM support. Breaking for standalone users; CHANGELOG entry saying
so, in PR-2.

`[tool.uv.sources]` renames one key per PR. Workspace membership stays at **12**
throughout — no package is added or removed by this feature.

### 6.2 · `src/functualize/_cli/data/plugin_catalog.toml`

`tests/cli/test_plugin_catalog.py::test_recommended_set_matches_the_all_extra`
asserts `set(recommended_distributions()) == the [all] extra`, so the catalog
moves in lockstep with §6.1.

| PR | Entry | `distribution` | `group` | `recommended` |
|---|---|---|---|---|
| 1 | `sqlite` → `substrate-sqlite` | `functualize-substrate-sqlite` | **OPEN (Q2)** | `true` |
| 1 | `inline` | `functualize-inline` | **OPEN (Q3)** | `true` |
| 2 | `aws-sm` | `functualize-secrets-aws` | `functualize.secrets_providers` | **`false`** ← changed |
| 2 | `bws` | `functualize-bitwarden` (name unchanged in PR-2) | `functualize.secrets_providers` | `false` |
| 3 | `bws` | `functualize-secrets-bitwarden` | `functualize.secrets_providers` | `false` |

`test_all_three_kinds_are_represented` must still pass. Under Shape A or B
(§3.3) `tasks-local` and `ai-pydantic` keep `implementation` covered regardless.

### 6.3 · PyPI trusted publishers

| PR | Project | Action |
|---|---|---|
| 1 | `functualize-substrate-sqlite` | **automatic** — the workflow's one pending-publisher slot |
| 2 | `functualize-secrets-aws` | **automatic** — the slot is free again once PR-1's name exists |
| 3 | `functualize-secrets-bitwarden` | **automatic** — same |
| — | `functualize-state-sqlite`, `functualize-aws`, `functualize-bitwarden` | left at 0.2.3; publishers may be revoked |

This is the whole point of D1′: **no manual token upload at any step.** Revision
1's single-PR plan required three of them.

---

## 7 · User-visible command output

### 7.1 · `func builtin plugin available` — **PR-1**

Headings come from `_cli/plugin_cmd.py:335` (`_KIND_ORDER`). Under §3.3 Shape A
the substrate appears under the existing *Implementations* heading; under Shape B
a fourth heading is added; under Shape C it appears under *Adapters*, which
`spec.md` U3 rejects. **OPEN (Q2).**

### 7.2 · `func builtin plugin available --remote` — **OPEN (Q1)** — every PR

`plugin_cmd.py:424` enumerates the PyPI Simple index for every project named
`functualize-*`; `available_rows` (`:256`) renders anything outside the curated
catalog as `kind="unknown"`, headed at `:339`:

```
UNCURATED — found on PyPI, not vetted by this project
  state-sqlite    functualize-state-sqlite      (after PR-1)
  aws             functualize-aws               (after PR-2)
  bitwarden       functualize-bitwarden         (after PR-3)
```

**Under D1′ this recurs once per PR**, so a one-off answer will not do. Two
candidate contracts:

- **Suppress** — `plugin_catalog.toml` gains a `retired = [...]` list that
  `available_rows` subtracts from the remote set, appended to in each PR.
  *Recommended:* the heading claims these were never vetted by this project, and
  all three were.
- **Accept** — document the listing in the CHANGELOG and leave the code alone.

### 7.3 · `func builtin data show` — **PR-1**

`spec.md` AC-7: with `functualize-tasks-local` installed, task documents render
as readable fields. Today `LocalTaskProvider._serialize_task`
(`_provider.py:159`) `json.dumps`es each task into a *string*, which
`TaskDocument` stores as a value inside the `{"tasks": {...}}` document the
substrate JSON-encodes again — so the command prints escaped JSON.

Flattening that changes the on-disk shape of the `tasks` document. That is an
internal schema (`schema.md` if one is written); what is contractual here is only
the rendered output.

### 7.4 · `func builtin data show` and the substrate install failure — **PR-1**

`spec.md` AC-4. Today `SQLiteStatePlugin._on_app_ready`
(`_plugin.py:75-83`) catches every exception from `install_substrate`, writes
`logger.exception`, and returns — so a user whose substrate did not install sees
a working program on the filesystem default and no error. The contract after
PR-1 is that this surfaces: raised, or reported through a user-visible channel.
The module's own docstring (`:70-73`) currently documents the swallow as
deliberate, so it changes with the behaviour.

---

## 8 · What does **not** change

- The `StoreSubstrate` protocol itself (`_types/protocols.py:741`). Six members,
  unchanged. This feature fixes a *caller*; it does not widen the port.
- `PluginHost` (`_types/host.py`), 11 members and 5 views, shipped by
  `plugin-host-protocol`. This feature consumes it; it does not extend it.
- `TaskProvider`, `TaskItem`, `TaskLink`, `TaskStatus` from `functualize_tasks`.
  The storage fixes change how `functualize-tasks-local` *stores* tasks, not what
  the domain publishes.
- Entry-point *names* inside the secrets group: `aws-sm`, `aws-ssm`, `bws`.
  Users have these in config files.
- `functualize.jobs`, `functualize.skills`, `functualize.domains`,
  `functualize.format_providers`, `functualize.displays`,
  `functualize.ai_providers`, `functualize.tasks_providers`.
- Workspace membership count: **12** plugins before and after.
- `boto3` stays out of core: `git grep -c boto3 -- src/functualize/` → **0**,
  today and after (ADR-016; `spec.md` AC-28).

---

## 9 · Deferred: `functualize-substrate-s3`

Not part of this feature (D7). Preserved so its own PR does not start from
nothing, and because it is *why* `spec.md` AC-5 and AC-6 are urgent.

```python
__all__ = ["S3Substrate", "S3SubstratePlugin"]

class S3Substrate:
    def __init__(self, bucket: str, prefix: str = "", *,
                 client: Any | None = None) -> None: ...
    # StoreSubstrate — all six members (_types/protocols.py:741)
```

| Member | Contract |
|---|---|
| `lock()` | **A no-op**, explicitly. The port permits it (`protocols.py:823`: *"May be a no-op for a backend that offers no mutual exclusion"*). Documented at the class, not discovered. |
| `write(expect=)` | **The only safety mechanism there**, therefore a real conditional write. Returns `False` on mismatch — an ordinary outcome, not an error. |
| `read()` | Missing object → `None`; present but undecodable → `SubstrateUnreadableError` (`_types/errors.py:525`). |

**`lock()` being a no-op is why `spec.md` AC-5 is a prerequisite, not a
companion.** Any caller doing read-modify-write without `expect=` is silently
lossy there — and `TaskDocument.set` / `.delete`
(`functualize-tasks-local/_provider.py:64-73`) are exactly such callers today.
PR-1 fixes them; S3 ships afterwards.
