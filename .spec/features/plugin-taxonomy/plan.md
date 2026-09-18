# plugin-taxonomy — plan (PR-1)

**2026-09-17 · base `feat/plugin-host-protocol` @ `80ec5f0`.**
Covers **PR-1 only** (`spec.md` §B D1′/D9). PR-2 and PR-3 are planned when cut.

---

## 0 · Skills consulted

| Skill | Source | Used for |
|---|---|---|
| `python-design-patterns` | in-repo, `.claude/skills/python-design-patterns` (symlink to `.agents/skills/`) | KISS, separation of concerns, single responsibility, composition over inheritance |
| `design-patterns-refactoring` | **user-level**, `/home/ubuntu/.claude/skills/design-patterns-refactoring` — Refactoring.Guru catalogue | the smell names below. Chapters read: ch33 (OO abusers), ch34 (change preventers), ch35 (dispensables) |

The catalogue is **not** in this repository (`.claude/rules/spec-workflow.md` says so,
and it is true here): every smell named below comes from the user-level skill.
A reader without it will not find these terms in-tree.

---

## 1 · Architecture pass — what was found

Three findings changed the shape of PR-1. Each was produced by running something,
and each **sent work back to Specify** (§6 of this plan records the revisions).

### 1.1 · The `_providers` suffix is not a naming convention — it is a mechanism

This is the finding that settles Q2, Q3 and Q5 together, and it makes
`contracts.md` revision 2's *Shape A* **wrong**.

Core reads entry-point groups in nine places, and they fall into two halves:

```
STATIC — seven groups, hard-coded in src/:
  functualize.jobs              _app/boot.py:206
  functualize.plugins           _plugins/loader.py:326        (PluginSources default)
  functualize.domains           _plugins/domain_registry.py:156
  functualize.skills            _cli/skills.py:166
  functualize.displays          _cli/tui/display_provider_discovery.py:82
  functualize.format_providers  _config/registry.py:169
  functualize.remote_providers  _config/registry.py:193
  <a job source's own group>    _discovery/providers.py:790   (caller-supplied)

DYNAMIC — one call, open-ended:
  _plugins/domain_registry.py:246
      eps = entry_points(group=metadata.entry_point_group)
```

That dynamic call is the **only** reader of any `functualize.<x>_providers`
group other than `format_providers` and `remote_providers`. And
`metadata.entry_point_group` comes from an installed **domain SDK**'s
`DomainMetadata`. Measured — every `entry_point_group=` in the tree:

```
$ git grep -rn 'entry_point_group=' -- plugins/ examples/ src/
plugins/functualize-ai/src/functualize_ai/_metadata.py:32     functualize.ai_providers
plugins/functualize-tasks/src/functualize_tasks/_metadata.py:32  functualize.tasks_providers
src/functualize/_cli/scaffold/templates/domain-sdk/_metadata.py.j2:32  (a template)
```

**Exactly two domain SDKs exist.** There is no `state` domain — ADR-022 removed
`functualize-state` — and there has never been an `interactivity` domain or a
`vault_key` domain.

So the three orphan groups are not "declared but nobody got round to reading
them". They are **unreadable by construction**:

> `functualize.<x>_providers` is the provider group of a domain SDK `<x>`,
> scanned from that domain's own `DomainMetadata.entry_point_group`. A
> `_providers` group with no live domain behind it has no reader and cannot be
> given one without inventing the domain.

`spec.md`'s Q2 offered `functualize.substrate_providers` as the cheap answer
that "classifies as `IMPLEMENTATION` for free". **It would be exactly as dead as
`state_providers`** — `classify_group` would label it correctly and nothing
would ever load it. Classification and loading are different questions, and
revision 2 of the spec conflated them just as revision 1 did, one level down.

`_primitives/plugin_kinds.py:17` states the confusion in its own docstring:

> *"a distribution publishing under `functualize.vault_providers` classifies as
> an implementation here without anyone editing this file."*

True, and irrelevant — it would classify and never load.

**The consequence for the AFTER shape:** a substrate plugin, an interactivity
plugin and a vault-key provider are all "a thing that extends the app at boot",
which is what `functualize.plugins` means. The repo already proves this works:

```
src/functualize/_cli/scaffold/templates/full-interactivity/pyproject.toml.j2:20
    [project.entry-points."functualize.plugins"]
    execution-state = "functualize_state_sqlite:SQLiteStatePlugin"
```

A **scaffolded** project registers the sqlite plugin under `functualize.plugins`
and it loads. A `pip install functualize-state-sqlite` user gets the dead group.
The same class, two groups, depending on how you obtained it.

### 1.2 · The substrate a project uses is decided by alphabetical plugin name

`spec.md` D.2-7 / AC-8 asserted hook-order dependence. **Proven by execution**,
and the mechanism is worse than the spec knew:

```
$ uv run python  # two plugins, explicit, only the tasks-local plugin's `name` differs
tasks-local name 'tasks-local'    (sorts AFTER  sqlite-state) -> SQLiteSubstrate
tasks-local name 'a-tasks-local'  (sorts BEFORE sqlite-state) -> JsonFileSubstrate
```

The chain: `PluginLoader.load_all` topologically sorts by `depends_on` with a
**stable alphabetical** tiebreak; each plugin's `__call__` registers its
`APP_READY` handler in that order; `boot.py:852` fires them in registration
order. `tasks-local`'s handler reads `app.substrate`, which resolves **and
caches** `engine._substrate` (`_engine/executor.py:1522-1528`); the sqlite
plugin's handler then calls `install_substrate`, which raises
(`_app/impl.py:1576`), and `_plugin.py:78-83` swallows it into
`logger.exception` and returns.

Today the project is correct **by the accident that `"sqlite-state" <
"tasks-local"`.** And PR-1 renames that plugin's `name` to `"substrate-sqlite"`
(`contracts.md` §4.1). `"substrate-sqlite" < "tasks-local"` still holds — but
the rename is now a change to a load-bearing sort key, which nothing records
and nothing tests. **The ordering fix must land before or with the rename**, not
after it.

### 1.3 · One deletion closes AC-5, AC-6 and AC-7

`TaskDocument` (`functualize-tasks-local/_provider.py:38-83`) is a **middle man**:
four methods (`get`, `set`, `delete`, `keys`) over one substrate document, each
routed through `_load()`, which does a full `substrate.read()`. Its own docstring
concedes the shape — *"it has no protocol, no plugin seam and one consumer"*.

The catalogue's answer to middle man is *remove the middle man*. Doing so closes
three acceptance criteria at once, which none of them reaches alone:

| AC | Today | After removing `TaskDocument` |
|---|---|---|
| AC-6 — reads per `list()` of N tasks | `keys()` = 1 read, then `get()` per key = N more → **1 + N** | the provider reads the one document once → **1** |
| AC-5 — two concurrent `update()` on a no-op `lock()` | `set()` holds `lock()` and calls `write()` with **no `expect=`** → last writer wins | read → modify → `write(expect=stored.revision)` → retry on `False`. `Stored.revision` and `write(expect=)` are **already in the port** (`_types/protocols.py:718-800`); nothing widens |
| AC-7 — `func builtin data show` | `_serialize_task` `json.dumps`es each task into a **string** stored as a value inside the document the substrate JSON-encodes again → escaped JSON | tasks are nested mappings; `data show` renders fields |

The key-value vocabulary (`get`/`set`/`delete`/`keys`) is the last echo of the
retired `StateBackend` protocol. Deleting it finishes what ADR-022 started.

**Blast radius, measured** (serena `find_referencing_symbols` + `git grep`):
`TaskDocument` has **two** production references — `_plugin.py:17,67` and
`LocalTaskProvider.__init__`'s parameter — plus two test files. It is **not** in
`functualize_tasks_local.__all__`. Deletable.

---

## 2 · BEFORE

Layer key: `[F]` foundation (`_types/`, `_primitives/`) · `[E]` events ·
`[P]` peer (`_discovery/ _config/ _engine/ _plugins/ _gate/`) ·
`[C]` composition root (`_app/`) · `[D]` delivery (`_cli/`) ·
`[pub]` public packages · `[x]` out-of-tree (plugin workspace, hooks, packaging).

```
                        ENTRY-POINT GROUPS: DECLARED vs READ
                        ════════════════════════════════════

  DECLARED (13 pyproject.toml)                READ (9 call sites, 7 modules)
  ─────────────────────────────               ──────────────────────────────
  root         functualize.plugins      ─────► _plugins/loader.py:326      [P]
               functualize.format_prov. ─────► _config/registry.py:169     [P]
               functualize.remote_prov. ─────► _config/registry.py:193     [P]
               functualize.vault_key_pr.──╳    (no reader)
                                                _app/boot.py:206           [C]
  mcp/http/                                       functualize.jobs
  lambda/flow-viz
               functualize.plugins      ─────► _plugins/loader.py:326      [P]
                                                _cli/skills.py:166         [D]
  tasks   ┐                                       functualize.skills
  ai      ┴──  functualize.domains      ─────► _plugins/domain_registry    [P]
                                                  :156
                                                       │
  ai-pydantic  functualize.ai_providers ──┐            │ metadata
  tasks-local  functualize.tasks_prov.  ──┤            ▼ .entry_point_group
                                          └───► domain_registry.py:246     [P]
                                                  ▲ scans ONLY groups a
  state-sqlite functualize.state_prov.  ──╳       ▲ LIVE DomainMetadata
  inline       functualize.interactiv._p.──╳      ▲ names.  Two exist:
  example      functualize.state_prov.  ──╳       ▲ ai, tasks.
                                                _cli/tui/display_provider  [D]
                                                  _discovery.py:82
                                                    functualize.displays
                                                _discovery/providers.py:790 [P]
                                                    <job source's group>

  ╳ = declared, unreachable.  Nothing compares the two columns.
      SMELL: speculative generality (4 sites) — a declared extension
             point with no reader, kept because nobody can see it is dead.


                        THE STORAGE SEAM AT APP_READY
                        ══════════════════════════════

   _plugins/loader.py [P]            topological sort, ALPHABETICAL tiebreak
        │                                       │
        │ calls plugin.__call__(app) in that order
        ▼                                       ▼
   "sqlite-state"                         "tasks-local"
   plugins/functualize-state-sqlite [x]   plugins/functualize-tasks-local [x]
        │ app.hooks.on_ready(h1)                │ app.hooks.on_ready(h2)
        ▼                                       ▼
   _events/hooks [E]  _global_hooks[APP_READY] = [h1, h2]   ← order = sort order
        │
        │ _app/boot.py:852 fires in list order                      [C]
        ▼
   h1: app.install_substrate(sqlite)      h2: TaskDocument(app.substrate)
        │                                       │
        ▼                                       ▼
   _app/impl.py:1576 [C]                  app/core.py:321 [pub]
   raise if engine._substrate is not None       └──► _engine/executor.py:1522 [P]
        │                                              RESOLVES AND CACHES
        ▼
   _plugin.py:78-83  except Exception: logger.exception(); return
        SMELL: dead code — the swallow makes a real failure unobservable.

   If h2 runs first, h1 raises, the exception is swallowed, and the user's
   database is silently abandoned.  Which runs first is decided by
   `"sqlite-state" < "tasks-local"`.


                        INSIDE functualize-tasks-local [x]
                        ══════════════════════════════════

   LocalTaskProvider ──► TaskDocument ──► StoreSubstrate [F: _types/protocols]
     list()                 keys()  ─► _load() ─► substrate.read()   1
     (N tasks)              get()   ─► _load() ─► substrate.read()   ×N
     update()               set()   ─► lock(); _load(); write()      no expect=
                                                                     ▲
     SMELL: middle man — four methods, one consumer, no protocol,    │
            each re-reading the whole document.                      │
            The missing `expect=` is the data-loss bug. ─────────────┘


                        THE ONE-LEVEL-DEEP PATH ASSUMPTION
                        ══════════════════════════════════

   plugins/<pkg>/src/**   assumed by SEVEN sites in SIX files:        [x]
     pyproject.toml:133                members = ["plugins/*"]        (loud)
     .claude/hooks/spec_gate.py:25     GATED_GLOB_PARTS               (SILENT)
     .claude/hooks/spec_gate.py:87     rel[1] == "src"                (SILENT)
     .claude/hooks/agent_contract.py:30   prose                       (SILENT)
     .claude/hooks/plan_context.py:42     prose                       (SILENT)
     .claude/rules/spec-workflow.md:32    prose                       (SILENT)
     evals/providers/_harness.py:172   "plugins/*/pyproject.toml"     (SILENT)

     SMELL: shotgun surgery — one logical change ("plugins are two
            levels deep"), seven edits, five of them silent on failure.
```

---

## 3 · AFTER

```
                        ENTRY-POINT GROUPS: ONE RULE, ONE GATE
                        ══════════════════════════════════════

                    NEW: _primitives/entry_point_groups.py           [F]
                    ┌──────────────────────────────────────┐
                    │ READ_GROUPS: frozenset[str] = {       │
                    │   "functualize.jobs",                 │
                    │   "functualize.plugins",              │
                    │   "functualize.domains",              │
                    │   "functualize.skills",               │
                    │   "functualize.displays",             │
                    │   "functualize.format_providers",     │
                    │   "functualize.remote_providers",     │
                    │ }                                     │
                    │ # A `<x>_providers` group beyond these│
                    │ # is read ONLY if a live DomainMetadata│
                    │ # names it.  That is the whole rule.  │
                    └──────────┬───────────────────────────┘
                               │ imported by every reader
     ┌──────────────┬──────────┼──────────┬─────────────┬──────────────┐
     ▼              ▼          ▼          ▼             ▼              ▼
  _app/boot     _plugins/   _plugins/  _config/    _cli/skills   _cli/tui/
   :206  [C]    loader [P]  domain_    registry     [D] ◄────┐   display_
                            registry   [P]                   │   provider_
                            [P]                              │   discovery [D]
                                                             │        ▲
                        _cli/ may not import _primitives ────┘        │
                        → re-exported through functualize.app.utils ──┘
                        (the seam `classify_group` already uses, utils.py:60)

  DECLARED, AFTER                                    every one lands in a reader
  ───────────────                                    ─────────────────────────
  root        functualize.plugins                ──► loader
              functualize.format_providers       ──► _config/registry
              functualize.remote_providers       ──► _config/registry
              (functualize.vault_key_providers)  ──► DELETED  (Q5)
  mcp/http/lambda/flow-viz  functualize.plugins  ──► loader
  tasks, ai                 functualize.domains  ──► domain_registry
  ai-pydantic  functualize.ai_providers          ──► domain_registry (ai)
  tasks-local  functualize.tasks_providers       ──► domain_registry (tasks)
  substrate-sqlite  functualize.plugins          ──► loader        (Q2)
  inline            functualize.plugins          ──► loader        (Q3)
  example           functualize.plugins          ──► loader        (Q2)

           NEW GATE (tests/): for every shipped pyproject.toml,
           every declared `functualize.*` group is in READ_GROUPS
           or is some installed DomainMetadata.entry_point_group.
           → speculative generality cannot come back silently.


                        THE STORAGE SEAM AT APP_READY
                        ══════════════════════════════

   _plugins/loader.py [P]    order still alphabetical — and it no longer matters
        │
        ├──────────────────────────┬────────────────────────────┐
        ▼                          ▼                            │
   "substrate-sqlite"         "tasks-local"                     │
   h1: app.install_substrate  h2: LocalTaskProvider(            │
         (sqlite)                   substrate_source=           │
        │                            lambda: app.substrate)     │
        │                          │  ▲                         │
        │                          │  └── NOT CALLED at boot ───┘
        ▼                          ▼
   _app/impl.py [C]           app.di.provide(TaskProvider, provider)
   raise if already resolved
        │                          … first task operation, well after boot …
        ▼                                     │
   _plugin.py: NO except        ─────────────►▼
   → the failure surfaces                app/core.py:321 [pub]
     (AC-4)                                └──► _engine/executor.py:1522 [P]
                                                 resolves ONCE — sees sqlite
                                                 whatever the sort order was.

   The coupling is removed, not ordered.  Matches the engine's own design:
   it already resolves lazily for exactly this reason.


                        INSIDE functualize-tasks-local [x]
                        ══════════════════════════════════

   LocalTaskProvider ───────────────────► StoreSubstrate [F]
     list()     read("tasks")  ──────────► 1 read, O(1)          AC-6
     update()   read → modify → write(expect=rev) → retry        AC-5
     tasks stored as nested mappings, not json.dumps strings     AC-7

   TaskDocument: DELETED.   (middle man removed; 2 production refs, 2 test files)


                        PATHS: ONE LEVEL BECOMES TWO
                        ════════════════════════════

   plugins/<group>/<pkg>/src/**      EVERY plugin at exactly two levels
     adapters/ substrates/ credentials/ domains/    (four groups -- Q4 settled)
     pyproject.toml            members = ["plugins/*/*"]
     spec_gate.py              GATED_GLOB_PARTS + a predicate that does not
                               index a fixed position  ← FIXED FIRST, wave 0
     agent_contract.py / plan_context.py / spec-workflow.md   prose updated
     evals/providers/_harness.py   "plugins/*/*/pyproject.toml"

   The seven sites stay seven (shotgun surgery SURVIVES — see §5).
```

### Boundary check — is the AFTER legal?

| Crossing | Contract | Verdict |
|---|---|---|
| `_primitives/entry_point_groups.py` imports nothing internal | *"Primitives import nothing internal"* | ✅ a `frozenset[str]` |
| `_app`, `_plugins`, `_config`, `_discovery` import `_primitives` | no contract forbids it | ✅ |
| `_cli/skills.py`, `_cli/tui/…` need the constants | *"`_cli` uses public API only"* — `_cli` may **not** import `_primitives` | ✅ **only** via re-export through `functualize.app.utils`, the seam `classify_group` already uses (`app/utils.py:60,189`) |
| `functualize.app.utils` imports `_primitives` | *"Internal never imports public"* is one-directional | ✅ precedent in the same file |
| Peer layers unchanged | *"Peer layers are independent"* | ✅ nothing new crosses `_discovery`↔`_config`↔`_engine`↔`_plugins` |
| `app.adapters` → `_engine` | *"Delivery adapters go through the request"* | ✅ untouched |

Seven contracts, none broken. Verified in Execute by `uv run lint-imports`.

### Forbidden-pattern check (`.spec/CONSTITUTION.md`)

| Pattern | Present in AFTER? |
|---|---|
| God object > ~500 LOC | No. `entry_point_groups.py` is a constant module; `LocalTaskProvider` shrinks |
| Peer-layer cross-import | No |
| Global mutable state / module-level singleton | No — `READ_GROUPS` is a `frozenset` constant, immutable |
| ABC for a port | No — nothing new is a port |
| Implicit `Callable` convention for a port | **Watch.** `substrate_source: Callable[[], StoreSubstrate]` is a callable parameter. It is **not a port**: one consumer, no discovery, no registry, no plugin seam. Ports here are `@runtime_checkable` Protocols with multiple implementations; this is a deferred read of one attribute. Recorded in §5 |
| Hard-coded config path | No |
| `_cli/` importing internals | No — see the boundary table |
| Backward-compat shim | No — D6 |

---

## 4 · Smells

### 4.1 · BEFORE — what the current design carries

| Smell | Where | Evidence |
|---|---|---|
| **Speculative generality** | `plugins/functualize-state-sqlite/pyproject.toml:23`, `plugins/functualize-inline/pyproject.toml:24`, `examples/plugins/custom_state_backend/pyproject.toml:10`, root `pyproject.toml:49` | Four declared extension points with no reader, and none can be given one (§1.1) |
| **Shotgun surgery** | `pyproject.toml:133`, `spec_gate.py:25,87`, `agent_contract.py:30`, `plan_context.py:42`, `spec-workflow.md:32`, `evals/providers/_harness.py:172` | One logical change, seven edits, five silent on failure |
| **Middle man** | `functualize-tasks-local/_provider.py:38-83` (`TaskDocument`) | Four methods over one document, one consumer, no protocol — its own docstring says so |
| **Dead code** | `functualize-ai/_provider_discovery.py:218` (`hasattr(app, "resolve_model")` — always False); `functualize-ai/_state_fallback.py` (119 LOC on a retired protocol); `SQLiteStateBackend` imported in 4 files, defined nowhere; `_plugin.py:78-83` (the swallow) | Catalogue: *unreachable conditional branch → delete the branch* |
| **Refused bequest** | `functualize-mcp/_plugin.py:22` — `MCPAdapterPlugin` claims `AdapterPlugin` in its name, its `adapter_type` (`:34`) and its docstring (`:25`); an `ast` walk shows no `run`, no `shutdown` — 2 of the protocol's 3 members | Catalogue fix: *make the relationship real, or replace it with delegation.* Unchecked because `validate_adapter` has **no production caller** |
| **Comments** (as deodorant) | `functualize-ai/_provider_discovery.py:205-217` | A 13-line comment explaining that the code below never runs. The catalogue's rule: the comment is the refactoring instruction |

### 4.2 · Candidate AFTERs rejected, and the smell each introduced

| Candidate | Rejected because |
|---|---|
| **`functualize.substrate_providers` + a new reader** (`contracts.md` rev-2 Shape A) | **Wrong, not merely costly** (§1.1): `_providers` groups are read by the domain registry from a live `DomainMetadata`. With no substrate domain, this group is as dead as `state_providers`. A new *ad-hoc* reader beside the domain registry would introduce **divergent change** in `_plugins/` — two mechanisms answering "who implements X" |
| **`functualize.substrates` + `PluginKind.SUBSTRATE`** (Shape B) | Legal, and it does say the truth. But it hard-codes a group name in `_primitives/plugin_kinds.py`, which that file's docstring argues against, and it buys a label at the cost of a second loading mechanism. Deferred, not refused — see §5 and Q2 below |
| **Order the APP_READY hooks** (a priority field, or a "substrate installers first" phase) | Introduces **shotgun surgery**: every future plugin author must know its phase, and the knowledge lives in the loader, the hook registry and each plugin. Removing the coupling (lazy read) needs no such knowledge |
| **Keep `TaskDocument`, add `expect=` inside it** | Fixes AC-5 alone and leaves AC-6 and AC-7 untouched — `_load()` per `get()` is the N+1, and the `json.dumps` string is the escaped output. Keeps the middle man and pays three times |
| **Move the seven path sites behind one shared helper** | Attractive, and rejected: the seven live in four *different* execution contexts — `uv`'s TOML, three standalone hook scripts with no import path into the repo, a prose contract, and an eval harness. A shared helper reachable from all four does not exist without inventing one, and inventing it is a bigger change than the move it serves |

---

## 5 · Surviving smells

Five. Each is absent from `.spec/CONSTITUTION.md` → *Forbidden Patterns*, so
each is eligible to be accepted; each is accepted here in writing.

1. **Shotgun surgery — the one-level-deep path assumption, `plugins/*` → `plugins/*/*`.**
   *Where:* `pyproject.toml:133`, `.claude/hooks/spec_gate.py:25,87`,
   `.claude/hooks/agent_contract.py:30`, `.claude/hooks/plan_context.py:42`,
   `.claude/rules/spec-workflow.md:32`, `evals/providers/_harness.py:172`.
   *Why accepted:* the seven sites span four execution contexts that share no
   import path (§4.2). Consolidating them means inventing a shared module the
   hook scripts can reach, which is a larger change than the move.
   *Mitigation, and it is the real answer:* the smell is tolerable once it is no
   longer **silent**. T2 adds a test that executes `spec_gate.is_gated` against a
   nested path, so the next person who deepens the tree gets a red test instead
   of a quietly unguarded repository.
   **Needs maintainer review: NO.**

2. **Speculative generality — `PluginKind.ADAPTER` will describe a substrate.**
   *Where:* `_primitives/plugin_kinds.py:46`, rendered by
   `_cli/plugin_cmd.py:335` as *"adds commands or a delivery surface"*.
   *Why accepted:* the substrate plugin moves to `functualize.plugins` because
   that is the only group with a reader (§1.1), and that group classifies as
   `ADAPTER`. `spec.md` U3 wants the heading to describe what the plugin is.
   The honest position is that **PR-1 buys correctness and defers the label**.
   *Mitigation:* the plugin's `description` field carries the truth
   (*"Keeps this project's runtime state in SQLite"* → a substrate wording), and
   `plugin available` prints it on the same row.
   **Needs maintainer review: YES — this is Q2, and it is the one place PR-1
   knowingly ships a user-visible inaccuracy.**

3. **Implicit `Callable` for deferred substrate access.**
   *Where:* `LocalTaskProvider.__init__(substrate_source: Callable[[], StoreSubstrate])`.
   *Why accepted:* the Constitution forbids *implicit `Callable` conventions for
   **ports***. This is not a port — one consumer, no discovery, no registry, no
   plugin seam, and the thing it returns (`StoreSubstrate`) **is** the port. A
   Protocol here would be a one-method interface with one implementation, which
   is the shape ADR-022 argues against on its own terms.
   **Needs maintainer review: NO** — but it is the entry a reviewer is most
   likely to challenge, so it is named rather than left to be noticed.

4. **Duplicate code — the retirement prose.**
   *Where:* 16 files repeat, in their own words, that `StateBackend` and
   `ExecutionStore` were retired and why (`research.md` R9).
   *Why accepted:* deliberate. `functualize-state-sqlite/_plugin.py:5-16` cites
   ADR-022 *"so it is not re-proposed"*. The duplication **is** the mechanism —
   a single ADR nobody opens does not stop a re-proposal at the call site.
   AC-11b turns this into a floor rather than a target.
   **Needs maintainer review: NO.**

5. **Divergent change — `tests/conftest.py` reaching into a plugin by filesystem path.**
   *Where:* `tests/conftest.py:356,360`;
   `tests/integration/test_substrate_durability.py:149,231,279`.
   *Why accepted:* four literal `plugins/functualize-state-sqlite/src` paths
   exist because a plain `uv sync` does not install workspace plugins
   (`research.md` R5). Fixing that properly means changing how the dev
   environment installs plugins, which is out of PR-1's scope and touches CI.
   PR-1 updates the paths and the import name; it does not remove the reach.
   **Needs maintainer review: NO** — recorded for `.spec/STATUS.md`.

---

6. **The port cannot express "create if absent" — found during T7.**
   *Where:* `functualize-tasks-local/_provider.py::LocalTaskProvider._mutate`.
   *What:* `StoreSubstrate.write(key, payload, expect=None)` is *unconditional*,
   and `expect=` takes "the revision the caller last read". A document that has
   never been written has no revision, so the first writer cannot detect a
   second one. On a backend whose `lock()` is a no-op the two can collide and
   one task is lost.
   *Why accepted:* closing it means widening the port, which is out of this
   feature's scope and is a decision about every substrate rather than about
   tasks. Bounded in practice — the document is created once, and `lock()` is
   real on both shipped backends. AC-5 asks about concurrent **`update()`**,
   which operates on an existing document and *is* compare-and-swapped.
   *Not hidden:* `test_the_very_first_write_cannot_be_compare_and_swapped`
   asserts the limitation rather than a false guarantee, and says in its
   docstring that if the port gains the capability the test should fail and be
   replaced. Carried to `sdd/substrate-conformance` as Q2.
   **Needs maintainer review: NO** — it is recorded as the next feature's open
   question, which is where the decision belongs.

## 6 · What this sent back to Specify

Per `.claude/rules/spec-workflow.md`, the gate is expected to revise `spec.md`
rather than plan around it. Three revisions, applied:

| Finding | Was | Now |
|---|---|---|
| §1.1 — `_providers` is a mechanism, not a convention | Q2 open, with `functualize.substrate_providers` recommended as "free"; Q3 and Q5 open separately | **Q2, Q3, Q5 answered together**: all three orphans go to `functualize.plugins`; `vault_key_providers` is deleted. `contracts.md` §3.3 *Shape A* removed as incorrect |
| §1.2 — the ordering bug's mechanism | "hook ordering can change the substrate" | **the sort key is the plugin `name`, which PR-1 renames.** New risk row; the ordering fix is sequenced before the rename |
| §1.3 — `TaskDocument` is a middle man | AC-5, AC-6, AC-7 read as three separate fixes | **one deletion closes all three**; task decomposition collapses from three tasks to one |

---

## 7 · Technical approach

Eight tasks, five waves. Wave 0 is the gate; nothing moves until it holds.

### Wave 0 — make the enforcement survive the move

**T1 · `spec_gate.py` stops assuming one level.** Replace the fixed-index
predicate (`rel[1] == "src"`) with one that accepts `src` at any depth below
`plugins/`, and update `GATED_GLOB_PARTS`. Prose in `agent_contract.py:30`,
`plan_context.py:42` and `.claude/rules/spec-workflow.md:32` follows.
*Gate:* import `spec_gate` and **call** `is_gated` against
`plugins/adapters/functualize-http/src/x.py` → `True`;
`plugins/functualize-http/tests/t.py` → `False`. Today the first is `False`.

**T2 · A test that fails when the gate stops guarding.** The mitigation for
surviving smell 1. Lives in `tests/` (ungated), executes the predicate against
both a one-level and a two-level path.

### Wave 1 — the move

**T3 · `git mv` twelve directories, and nothing else in the commit.**
the four groups of `contracts.md` §2 (Q4 settled). Then
`pyproject.toml:133` → `members = ["plugins/*/*"]`,
`evals/providers/_harness.py:172`, `tests/conftest.py:356`,
`tests/integration/test_substrate_durability.py:149,231,279`,
`.github/workflows/ci.yml:232,235`,
`contributor/guides/plugin-development.md:78-89`, `plugins/PUBLISHING.md`.
*Gate:* `uv sync --all-packages` resolves; `uv build --all-packages` exits 0;
twelve members found.

### Wave 2 — the group rule

**T4 · `_primitives/entry_point_groups.py`, and nine readers import it.**
The seven static constants; `DOMAINS_ENTRY_POINT_GROUP`,
`SKILLS_ENTRY_POINT_GROUP`, `_DISPLAY_ENTRY_POINT_GROUP` re-defined there and
re-exported from their current homes; three inline literals replaced; `_cli`'s
two readers reach it through `functualize.app.utils`.
*Gate:* `uv run lint-imports` 7 kept / 0 broken; no `entry_points(group="…")`
string literal remains in `src/`.

**T5 · The orphans move to `functualize.plugins`; `vault_key_providers` is deleted.**
`functualize-state-sqlite/pyproject.toml:23`,
`functualize-inline/pyproject.toml:24`,
`examples/plugins/custom_state_backend/pyproject.toml:10` → `functualize.plugins`.
Root `pyproject.toml:49` and `_config/vault_keys.py:6` → removed.
`plugin_catalog.toml:76,97` follows.
*Gate:* the new conformance test (T6) is green; a boot with the sqlite plugin
installed **via its entry point** resolves every store to it (AC-3).

**T6 · The gate that stops this recurring.** A test parsing every shipped
`pyproject.toml` (core, 12 plugins, 3 examples) and asserting each declared
`functualize.*` group is in `READ_GROUPS` or is an installed
`DomainMetadata.entry_point_group`.
*Gate:* passes now; fails when T5's edits are reverted.

### Wave 3 — the storage seam

**T7 · Remove the middle man; make the provider lazy and compare-and-swap.**
Delete `TaskDocument`; `LocalTaskProvider` takes
`substrate_source: Callable[[], StoreSubstrate]` and owns the one document;
`list()` is one read; every mutation is read → modify → `write(expect=)` → retry;
tasks stored as mappings. `_plugin.py` passes `lambda: app.substrate` and no
longer touches the substrate at APP_READY. Stop swallowing in
`functualize-state-sqlite/_plugin.py:78-83`.
*Gate:* AC-4, AC-5, AC-6, AC-7, AC-8 — including the §1.2 probe with
`tasks-local` forced to sort first.

### Wave 4 — the rename, then truth

**T8 · `functualize-state-sqlite` → `functualize-substrate-sqlite`.**
49 + 14 files. Import package, class (`SQLiteStatePlugin` →
`SQLiteSubstratePlugin`), `name` (`"sqlite-state"` → `"substrate-sqlite"`),
config section, entry point, catalog, `[all]`, `[tool.uv.sources]`,
`tests/conftest.py`, the scaffold template, the README and the two examples —
including deleting the `SQLiteStateBackend` imports that resolve to nothing.
*Ordering:* **after T7**, because `name` is the sort key §1.2 proved load-bearing.

**T9 · Plugin-surface honesty and doc truth.** `MCPAdapterPlugin` (Q6),
the `functualize-ai` probe and `__getattr__` table, `_state_fallback.py`,
`plugins/PUBLISHING.md`, the three codemaps, `codemaps/entry-points.md`
(which lists 3 groups where 7 static ones exist).

---

## 8 · Risks specific to this plan

| Risk | Handling |
|---|---|
| T3's `git mv` and T8's edits land on the same files; git detects renames only when content is unchanged | T3 is a **move-only commit**. T8 comes two waves later |
| T4 touches nine readers across five layers; a missed one silently keeps a literal | Gate is mechanical: no `entry_points(group="` literal left in `src/` |
| T7 changes the on-disk shape of the `tasks` document | No migration: pre-release, and the document is derived project state under `.functualize/`. Stated in CHANGELOG |
| T5 changes which group `functualize-inline` declares; `tests/_cli/test_plugin_cmd.py:52,58,104` assert the old one | Those three sites are in T5's file list, taken from the query that found them |
| The `sqlite` plugin suite has 4 failures proved pre-existing (`.spec/STATE.md` wave 10) | AC-22 requires them unchanged or fixed — **not newly masked**. Re-measured at the head of T3 and again at T8 |
