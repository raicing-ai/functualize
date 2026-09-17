# plugin-taxonomy — a plugin ecosystem whose names, folders and wiring agree

**Revision 2 · 2026-09-17 · base `feat/plugin-host-protocol` @ `80ec5f0`**
(revision 1: 2026-09-16 @ `79545ef`; master `11d77f6` in both.)

Re-run because **`plugin-host-protocol` landed** — 16 tasks, 11 waves, Verify
complete (`.spec/STATE.md`) — and it edited the plugin sources this feature
moves and renames. Every count, path and line number below was re-taken against
`80ec5f0`; see `research.md` for the ten findings, four of them new, that changed
this feature's shape since revision 1.

**Revision 2 also re-scopes the feature into three pull requests** on maintainer
instruction, 2026-09-17. See §B.

---

## A · Why

Three separate things drifted apart, and the drift is now user-visible.

### A.1 · Two plugins and one tutorial register in groups nothing reads

Core reads entry-point groups in exactly **nine** places, across seven files.
This is every `entry_points(group=…)` call in `src/`, re-measured:

```
$ rg -n 'entry_points\(group=' src/functualize --glob '*.py'
_app/boot.py:206                           functualize.jobs
_plugins/loader.py:326                     self._group            (default functualize.plugins)
_plugins/domain_registry.py:156            functualize.domains    (DOMAINS_ENTRY_POINT_GROUP)
_plugins/domain_registry.py:246            <domain>.entry_point_group -> ai_providers, tasks_providers
_discovery/providers.py:790                self._group            (a job source's own group)
_cli/skills.py:166                         functualize.skills     (SKILLS_ENTRY_POINT_GROUP)
_cli/tui/display_provider_discovery.py:82  functualize.displays   (_DISPLAY_ENTRY_POINT_GROUP)
_config/registry.py:169                    functualize.format_providers
_config/registry.py:193                    functualize.remote_providers
```

Three declared `functualize.*` groups appear in **no** reader:

| Group | Declared by | Consequence |
|---|---|---|
| `functualize.state_providers` | `plugins/functualize-state-sqlite/pyproject.toml:23` | `SQLiteStatePlugin.__call__` is never invoked. `pip install functualize-state-sqlite` installs a package that does nothing. |
| `functualize.state_providers` | `examples/plugins/custom_state_backend/pyproject.toml:10` | The **documented tutorial** for writing a substrate (mkdocs nav `mkdocs.yml:148`) teaches a dead group. |
| `functualize.interactivity_providers` | `plugins/functualize-inline/pyproject.toml:24` | `InlinePlugin.__call__` is never invoked. |
| `functualize.vault_key_providers` | root `pyproject.toml:49` | Harmless at runtime: core imports `EnvKeyProvider`/`KeychainKeyProvider` directly. Still a false advertisement — `_config/vault_keys.py:6` tells plugin authors to register through it. Dead-code audit finding #3, HIGH. |

`functualize-state-sqlite` was a `StateBackend` + `ExecutionStore` provider
until ADR-022 retired that domain. The implementation moved on — `_plugin.py`
installs a `StoreSubstrate`, `substrate.py` implements the port — and the
**registration did not**. The group outlived the domain it belonged to.

### A.2 · Names say the wrong thing

- `functualize-state-sqlite` is not a state backend. It is a substrate.
  Its own `README.md:16,19` still tells a reader to
  `from functualize_state_sqlite import SQLiteStateBackend` — a class defined
  **nowhere** (`__all__` is `['SQLiteStatePlugin', 'SQLiteSubstrate']`).
- `functualize-aws` and `functualize-bitwarden` do not say what they do. Both
  fetch secrets; `functualize-aws` also suggests a breadth (Lambda? S3?) it
  does not have.
- Two naming patterns already coexist: domain-first
  (`functualize-ai-pydantic`, `functualize-tasks-local`) and bare
  (`functualize-http`, `functualize-aws`).

### A.3 · Twelve flat directories with no grouping

```
$ ls -d plugins/functualize-*/ | wc -l
12
```

Nothing tells a reader that `functualize-tasks` publishes a protocol while
`functualize-tasks-local` implements it, or that `functualize-aws` and
`functualize-bitwarden` are alternatives rather than companions.

### A.4 · The storage seam has a live data-loss bug waiting for S3

`TaskDocument` (`functualize-tasks-local/_provider.py:38-83`) performs
read-modify-write across the substrate under `lock()` but with **no
`write(expect=)`**:

```python
def set(self, key: str, value: str) -> None:
    with self._substrate.lock(self._key):
        entries = self._load()          # read
        entries[key] = value            # modify
        self._substrate.write(self._key, {"tasks": entries})   # write, no expect=
```

On `JsonFileSubstrate` and `SQLiteSubstrate` the damage is bounded, because
their `lock()` is real. The port documents that `lock()` *"may be a no-op for a
backend that offers no mutual exclusion"* (`_types/protocols.py:823`) — which is
what an S3 implementation is. **Adding a no-op-lock substrate without fixing
this ships silent task loss**, which is why the fix lands before S3 does (§B D7).

### A.5 · Three plugin defects inherited from `plugin-host-protocol`

Handed here by maintainer decision, 2026-09-17 (`.spec/STATE.md` → *Owed
elsewhere*). Each is a case of a plugin's declared role disagreeing with its
actual surface — the same disease as A.1 and A.2.

- **`functualize-ai`'s config probe has never run.** `_provider_discovery.py:218`
  guards on `hasattr(app, "resolve_model")`, which is **always False** —
  `resolve_model` lives on `app.configuration`, never on the app. The `[ai]`
  section has never been read there; every caller passing an `app` silently got
  `AIConfig()` defaults. Fixing it **changes behaviour**. (`research.md` R6.)
- **`MCPAdapterPlugin` is not an `AdapterPlugin`.** Its name, its
  `adapter_type = "mcp"` and its docstring all claim the protocol; an `ast` walk
  shows it has neither `run` nor `shutdown`, two of the three members
  `_types/protocols.py:96-132` requires. Unchecked because `validate_adapter`
  has **no production caller** — only a re-export and five test files.
  (`research.md` R7.)
- **`functualize_ai/__init__.py` hides its own types from mypy.** A
  `__getattr__` table at `:140` with no `TYPE_CHECKING` block, so mypy sees
  variables rather than types. Measured cause of most of `ai-pydantic`'s
  **47-error** baseline. (`research.md` R8.)

### A.6 · Four shipped documents describe a plugin set that does not exist

`plugins/PUBLISHING.md` — the document that governs which plugins may be
published — lists `functualize-state` at lines 104, 113-115, 194 and 226, as a
Tier 1 distribution and as a dependency of three other plugins. ADR-022 removed
it. The three codemaps say the same: `overview.md:73` and
`dependencies.md:117` both claim **13 plugins** (measured: 12) and
`modules.md:153` still tables `functualize-state`. (`research.md` R10.)

---

## B · Decisions taken (maintainer — recorded, not re-opened)

### Taken 2026-09-16

| # | Decision | Rejected alternative |
|---|---|---|
| D2 | Naming pattern is **domain-first** `<what-it-serves>-<which-one>` | Kind-first (`functualize-adapter-http`) |
| D3 | The word for AWS/Bitwarden is **secrets**, not *vault* | `vaultprovider-*` — "vault" already names the *local* encrypted file (`_config/vault.py`) and `functualize.vault_key_providers` |
| D4 | `functualize.remote_providers` → `functualize.secrets_providers`, **hard cutover**, core reads only the new name | Dual-read with a deprecation warning |
| D5 | The F-series bugs are fixed **before** the rename they sit under | Deferring them; renaming dead wiring |
| D6 | No compatibility shims on PyPI | Shipping deprecation shims |

### Taken 2026-09-17 — the re-scope

| # | Decision | Rejected alternative |
|---|---|---|
| **D1′** | **One distribution rename per pull request.** Three renames therefore become three PRs, in order: **(1) sqlite, (2) aws, (3) bitwarden.** Supersedes revision 1's D1 ("rename exactly three distributions" in one change) | All three in one PR |
| **D7** | **`functualize-substrate-s3` leaves the feature.** It is a second not-yet-existing PyPI name, and PR-1 already claims one. It ships in its own PR *after* the A.4 concurrency fix has landed, so it never exists in a version that can lose data | Shipping S3 alongside the sqlite rename and paying one manual token upload |
| **D8** | **The directory move stays in PR-1**, with the two mechanisms it breaks (R1, R1b) fixed in the same PR, gate first | Splitting the move into its own PR |
| **D9** | PRs 2 and 3 are cut **last**, each on its own branch, each a separate commit series | Folding them into PR-1's branch |

**Why sqlite is first (D1′).** It is the only one of the three that is also
*broken*: dead entry point (A.1), a README and an example importing a class that
does not exist (A.2, `research.md` R4). Renaming it and fixing it are the same
work. `functualize-aws` and `functualize-bitwarden` function correctly today and
are only misnamed.

**The new name is `functualize-substrate-sqlite`** (import package
`functualize_substrate_sqlite`), applying D2: it serves the *substrate* role,
and `sqlite` is which one.

**Accepted cost of D1′/D6**, stated so a reviewer sees it was priced: three PyPI
projects are abandoned at 0.2.3, and each new name needs its release to claim it.
A *pending* trusted publisher is unique on `(owner, repo, workflow, environment)`
and one workflow can claim exactly one not-yet-existing name
(`release.yml:119-130`) — which is precisely why D1′ caps a PR at one rename:
every PR's publish stays automatic, with no manual token upload anywhere.

D1′, D4 and D6 are consistent with `.spec/CONSTITUTION.md` → *Forbidden
Patterns*: *"`DeprecationWarning` / backward-compat shims — pre-release, no users
to deprecate toward. Remove old code."*

---

## C · Users and stories

**U1 · Someone choosing where their state lives.** Installs a substrate plugin
and their runs use it. Today they install `functualize-state-sqlite` and nothing
happens, with no error.

**U2 · Someone writing a third-party substrate.** Follows
`docs/examples/plugins/custom-state-backend.md`, and the plugin they build
loads. Today it does not.

**U3 · Someone browsing plugins.** Runs `func builtin plugin available` and sees
each plugin under a heading that describes what it is.

**U4 · A contributor opening `plugins/`.** Sees which plugins are alternatives
for the same job and which layer each belongs to, from the directory tree.

**U5 · Someone with concurrent task writers.** Two processes update different
tasks; both survive. Today one is silently lost.

**U6 · Someone with an `[ai]` section in their config.** Their settings are
honoured. Today they are silently discarded (A.5).

**U7 · A maintainer reading `plugins/PUBLISHING.md` before a release.** The tiers
and the dependency graph describe the plugins that exist (A.6).

---

## D · Behaviour

Each item is tagged with the PR that delivers it. **PR-1** is this branch's
work; **PR-2** and **PR-3** are cut afterwards, one rename each (D1′, D9).

### D.1 · Wiring (PR-1)

1. Every first-party plugin that declares an entry point is **reachable through
   that entry point** from a clean install. No plugin registers in a group core
   does not read. This covers **three** registrations — the sqlite plugin, the
   inline plugin, and the `custom_state_backend` example — plus the
   `functualize.vault_key_providers` declaration in the root `pyproject.toml`,
   which is either read or removed.
2. A substrate plugin installed by a user takes effect for every store in the
   run, or fails **loudly**. It never falls back to the filesystem silently.
3. `func builtin plugin available` describes a substrate as a substrate.

### D.2 · Storage correctness (PR-1)

4. A read-modify-write through `functualize-tasks-local` is **atomic against a
   concurrent writer on a substrate whose `lock()` is a no-op**. Compare-and-swap
   via `write(expect=)`, not lock ordering.
5. Listing N tasks costs a bounded number of substrate reads, independent of N.
6. A task document is readable as data — `func builtin data show` renders task
   fields, not an opaque escaped string.
7. The order in which plugins' `APP_READY` hooks run **cannot** change which
   substrate a project uses. Today `functualize-tasks-local/_plugin.py:67` reads
   `app.substrate`, which resolves and caches `engine._substrate`
   (`_engine/executor.py:1522-1528`); a later `install_substrate`
   (`_app/impl.py:1556`) then raises, and `SQLiteStatePlugin._on_app_ready`
   (`_plugin.py:78-83`) swallows the exception into `logger.exception` and
   returns.

   **Proven by execution, 2026-09-17, and the mechanism is narrower than
   "ordering"** (`plan.md` §1.2). `PluginLoader.load_all` sorts topologically
   with a stable **alphabetical** tiebreak, so the deciding fact is the plugin's
   `name` attribute. Two runs differing only in that string:

   ```
   tasks-local name 'tasks-local'    (sorts AFTER  sqlite-state) -> SQLiteSubstrate
   tasks-local name 'a-tasks-local'  (sorts BEFORE sqlite-state) -> JsonFileSubstrate
   ```

   The project is correct today by the accident that `"sqlite-state" <
   "tasks-local"`. **D.3-9 renames that `name` to `"substrate-sqlite"`** — still
   before `"tasks-local"`, still lucky. The rename is therefore a change to a
   load-bearing sort key, and this item must land **before or with** it.

### D.3 · Names and structure

8. **(PR-1)** `plugins/` groups its members by what they serve. A reader
   identifies a plugin's role from its path.
9. **(PR-1)** `functualize-state-sqlite` is renamed to
   **`functualize-substrate-sqlite`**, carrying the new name in distribution
   metadata, import package, entry points, tests, examples, docs and the curated
   catalog — with **zero** surviving references to the old name except a
   CHANGELOG entry recording the rename.
10. **(PR-2)** `functualize-aws` is renamed to `functualize-secrets-aws`, and
    core resolves secrets providers from `functualize.secrets_providers`
    (D4). Because the group is shared, PR-2 also updates
    `functualize-bitwarden`'s *entry-point declaration* to the new group — its
    distribution name is untouched — so no intermediate state on master has a
    plugin declaring a group nothing reads.
11. **(PR-3)** `functualize-bitwarden` is renamed to
    `functualize-secrets-bitwarden`.
12. **(PR-2)** Neither secrets plugin is installed by `functualize[cli]` or
    `functualize[all]`. **Consequence, stated deliberately:** `[all]` is what the
    standalone binary bakes (`PYAPP_PROJECT_FEATURES=all`, ADR-015 §Correction),
    so **the standalone binary loses AWS Secrets Manager and SSM support.** Users
    needing it install `functualize-secrets-aws` themselves.
13. **(PR-2, PR-3)** Both first-party secrets plugins remain directly
    installable and first-class; not being in `[all]` is not a demotion (the
    existing `functualize-bitwarden` precedent, `pyproject.toml:105-118` and
    `plugin_catalog.toml:113-121`).

### D.4 · The enforcement that must survive the move (PR-1)

14. The spec-workflow `PreToolUse` gate still refuses an ungated write to plugin
    source **after** the directories move, and the uv workspace still finds every
    plugin. Both mechanisms assume exactly one level under `plugins/`
    (`spec_gate.py:87` tests `rel[1] == "src"`; `pyproject.toml` declares
    `members = ["plugins/*"]`) — and **the gate fails open**, so its breakage
    would be silent. The gate fix lands before any directory moves.

### D.5 · Plugin-surface honesty (PR-1)

15. A plugin that claims a protocol satisfies it, and that is **checked in
    production, not only in tests**. `MCPAdapterPlugin` either gains `run` and
    `shutdown` or stops claiming `AdapterPlugin` in its name, its `adapter_type`
    and its docstring (A.5).
16. `functualize-ai` either reads the `[ai]` config section through the port it
    is annotated against, or states in its own documentation that it does not.
    The always-False `hasattr` probe does not survive in either case. **This
    changes behaviour** for projects that have an `[ai]` section (A.5).
17. `functualize-ai` exposes its types to a type checker: `functualize-ai-pydantic`
    has a mypy baseline that is not inflated by its dependency's lazy-import
    table (A.5).

### D.6 · Documentation truth (PR-1)

18. No shipped document or runnable example references a symbol that does not
    exist, or a distribution that was removed. Prose that *records* a retirement
    — ADR-022's reasoning, quoted in module docstrings so it is not re-proposed —
    is **preserved, not deleted**; the two are distinguished by whether the name
    is imported or merely named (`research.md` R9).
19. `functualize-ai`'s user-facing advice does not tell a user to install a
    package to get a capability that package no longer provides
    (`_state_fallback.py:30`).

---

## E · Acceptance criteria

Each is a command. **Today** is what it returned on 2026-09-17 against
`80ec5f0`; **Required** is the value after the change. Every command in this
table was run to produce its Today column — see §J.

### PR-1 — wiring, storage, the move, the sqlite rename

| AC | Gate | Today | Required |
|---|---|---|---|
| AC-1 | Every `functualize.*` group declared by a first-party plugin, shipped example or the root `pyproject.toml` appears in some `entry_points(group=…)` reader in `src/` | 3 orphan groups (`state_providers`, `interactivity_providers`, `vault_key_providers`) | 0 orphans |
| AC-2 | `git grep -l -E 'functualize\.(state\|interactivity)_providers' -- . ':!.spec' ':!CHANGELOG.md'` | 17 files | 0 files |
| AC-3 | A test boots an app with a substrate plugin installed **via its entry point** and asserts every store resolved to it | absent | present, green |
| AC-4 | Installing a substrate after the engine resolved one surfaces an error to the user rather than a swallowed `logger.exception` (`functualize-state-sqlite/_plugin.py:78-83`) | swallowed | raised or reported |
| AC-5 | A test drives two concurrent `LocalTaskProvider.update()` calls over a substrate whose `lock()` is a no-op and asserts both land | absent | present, green |
| AC-6 | Substrate reads per `LocalTaskProvider.list()` of N tasks — `TaskDocument.keys()` is 1 read, then `.get()` per key is 1 each (`_provider.py:166-169`) | `1 + N` | O(1) |
| AC-7 | `func builtin data show` on a project with tasks renders task titles, not escaped JSON | escaped | readable |
| AC-8 | Hook-ordering independence: a test registers `tasks-local` **before** the substrate plugin and asserts the substrate still wins | absent | present, green |
| AC-9 | `git grep -l -F functualize-state-sqlite -- . ':!CHANGELOG.md' ':!.spec'` | **49 files** | 0 files |
| AC-9b | `git grep -l -F functualize_state_sqlite -- . ':!CHANGELOG.md' ':!.spec'` | **14 files** | 0 files |
| AC-10 | `python -c "import functualize_substrate_sqlite as m; print(m.__all__)"` and every symbol in it resolves | n/a | resolves |
| AC-11 | `git grep -n -E '^(from\|import).*(StateBackend\|ExecutionStore)\|(StateBackend\|ExecutionStore)\(' -- docs/ examples/ plugins/ ':!*/adr/*'` — **live** references (imports and calls), not prose | **8 sites / 4 files** | 0 sites |
| AC-11b | Prose mentions recording the retirement, same paths: `git grep -l -E 'StateBackend\|ExecutionStore' -- docs/ examples/ plugins/ ':!*/adr/*'` | 24 files | **≥ 16 files preserved** — this one must NOT go to zero (`research.md` R9) |
| AC-12 | `git grep -l -F SQLiteStateBackend -- . ':!.spec'` — a class defined nowhere | 4 files | 0 files |
| AC-13 | `spec_gate.is_gated`, **imported and executed** against `plugins/<group>/<pkg>/src/x.py` | returns **False** | returns True |
| AC-14 | `uv sync --all-packages` resolves and `uv build --all-packages` exits 0, **after** the move | green | still green |
| AC-15 | Workspace membership: `[tool.uv.workspace] members` matches every plugin `pyproject.toml` after the move — `ls plugins/*/pyproject.toml \| wc -l` today | 12 found by `plugins/*` | 12 found by the new glob |
| AC-16 | `plugins/functualize-*/examples/persistent_counter/` imports resolve and the directory is **collected** by a test run | broken, uncollected (`testpaths = ["tests"]`, `pyproject.toml:171`) | resolves, and is collected |
| AC-17 | `validate_adapter` has a production caller, and `MCPAdapterPlugin` passes it | 0 production callers; 2 of 3 protocol members missing | ≥1 production caller; passes |
| AC-18 | `git grep -n 'hasattr(app, "resolve_model")' -- plugins/` | 1 site, always False | 0 sites |
| AC-19 | `functualize-ai-pydantic` mypy baseline | **47 errors** | recorded and not increased; the `__getattr__`-caused share removed |
| AC-20 | `git grep -l -F functualize-state -- plugins/PUBLISHING.md contributor/architecture/codemaps/` — a distribution ADR-022 removed | 4 files | 0 files |
| AC-21 | `uv run lint-imports` | 7 kept / 0 broken | 7 kept / 0 broken |
| AC-22 | `uv run pytest` plus every relocated plugin suite | green (root 10,681 passed; sqlite suite has **4 failures proved pre-existing**, `.spec/STATE.md` wave 10) | green, with the 4 pre-existing failures unchanged or fixed — **not newly masked** |

### PR-2 — `functualize-aws` → `functualize-secrets-aws`, and the group cutover

| AC | Gate | Today | Required |
|---|---|---|---|
| AC-23 | `git grep -c remote_providers -- src/` | **5 files / 18 sites** | 0 |
| AC-24 | `git grep -l -F functualize-aws -- . ':!CHANGELOG.md' ':!.spec'` | **17 files** | 0 files |
| AC-24b | `git grep -l -F functualize_aws -- . ':!CHANGELOG.md' ':!.spec'` | **10 files** | 0 files |
| AC-25 | `git grep -n -E 'functualize-secrets-aws\|functualize-secrets-bitwarden' pyproject.toml` inside `[all]`/`[cli]` | — | 0 matches |
| AC-26 | `tests/cli/test_plugin_catalog.py::test_recommended_set_matches_the_all_extra` | green | still green, with AWS in neither |
| AC-27 | `functualize-bitwarden` declares `functualize.secrets_providers` (declaration only; distribution name unchanged until PR-3) | declares `remote_providers` | declares `secrets_providers` |
| AC-28 | `git grep -c boto3 -- src/functualize/` — the invariant ADR-016 set | **0** | 0 |

### PR-3 — `functualize-bitwarden` → `functualize-secrets-bitwarden`

| AC | Gate | Today | Required |
|---|---|---|---|
| AC-29 | `git grep -l -F functualize-bitwarden -- . ':!CHANGELOG.md' ':!.spec'` | **16 files** | 0 files |
| AC-29b | `git grep -l -F functualize_bitwarden -- . ':!CHANGELOG.md' ':!.spec'` | **7 files** | 0 files |
| AC-30 | `functualize-secrets-bitwarden` remains in the `dev` dependency group and directly installable | in `dev` (`pyproject.toml:71-79`) | unchanged, under the new name |

**Every AC-9 / AC-24 / AC-29 family gate excludes `CHANGELOG.md` deliberately** —
the changelog must name the old names, because recording the rename is the point.

**Counts are `git grep`, not `rg`.** The worktree carries an untracked
`graphify-out/graph.json` that matches almost every identifier in the repo;
revision 1's `rg`-based counts included it. (`research.md`, *Retrieval passes*.)

---

## F · Explicitly out of scope

### Out of this feature entirely

- **`functualize-substrate-s3`.** D7. It is a second not-yet-existing PyPI name,
  and it must not exist in a version carrying the A.4 concurrency bug. Its own
  PR, after PR-1.
- **Renaming http, lambda, mcp, flow-viz, inline, tasks, tasks-local, ai,
  ai-pydantic.** D2 settled this. Their *directories* move in PR-1; their
  distribution names do not.
- **Compatibility shims on PyPI.** D6.
- **Dual-reading the old `remote_providers` group.** D4.
- **Making CI run every plugin's test suite.** `research.md` R4 shows CI runs one
  plugin's suite (`ci.yml:232,235`) out of twelve, which is why every defect in
  §A could be true at once with a green pipeline. Real, worth doing, not this
  feature — record in `.spec/STATUS.md`.
- **The `app: Any` typing problem.** Owned by `plugin-host-protocol`, **landed**.

### Out of PR-1, in a later PR of this feature

- Renaming `functualize-aws` and `functualize-bitwarden`, and the
  `remote_providers` → `secrets_providers` cutover. D1′, D9 — **done last**.
- Removing the secrets plugins from `[all]`/`[cli]`. It belongs with the rename
  that gives them their `secrets` name.

---

## G · What `plugin-host-protocol` already did

Revision 1 §G recorded two *same-line seams* with that feature and made
sequencing a requirement. **All of it is resolved** — verified by reading the
files at `80ec5f0`:

| Revision 1 recorded | State at `80ec5f0` |
|---|---|
| `state-sqlite/_plugin.py:74-78` — that feature changes the call *spelling* to `app.install_substrate(…)`; this feature owns the *error handling* | Spelling **done** (`_plugin.py:77`). The swallow this feature owns is now `_plugin.py:78-83` |
| `tasks-local/_plugin.py:66` — that feature changes `app.execution_engine.substrate` to `app.substrate`; this feature owns the *ordering bug* | Spelling **done** (`_plugin.py:67`). The ordering bug **survives intact**, by design |
| `functualize.vault_key_providers` — this feature owns it | Unchanged; now D.1-1 and AC-1 |
| "Sequencing is a requirement — `plugin-host-protocol` lands first" | **Satisfied.** Free to `git mv` |

**Two constraints it leaves behind.**

- Both plugin modules now import `functualize.plugin.PluginHost` under
  `TYPE_CHECKING` and annotate `app: PluginHost`. `functualize_state_sqlite` is a
  name consumer **in its own annotations**, not only in packaging metadata.
- `contributor/reference/public-api-example-coverage.md` (new, 2026-09-17):
  every public API symbol needs a caller in `examples/`. Anything PR-1 makes
  public inherits it.

**Three defects it handed here**, listed in A.5 and detailed in `research.md`
R6–R8.

---

## H · Risks

| Risk | Severity | Handling |
|---|---|---|
| Spec gate silently stops enforcing plugin source after the move (R1) | **High** — disables the mechanism guarding the rest, and fails open so nothing reports it | AC-13, wave 1, gate fix **before** any move, verified by *executing* the predicate |
| The move breaks `[tool.uv.workspace] members = ["plugins/*"]` (R1b) | Medium — but loud, at `uv sync` | AC-15, same wave as the gate fix. Also contradicts `contributor/guides/plugin-development.md:78-89`, a required edit |
| `plugin available --remote` advertises abandoned names (R2) | Medium, user-visible, **recurs once per PR** under D1′ | Q1 below — and the answer must work three times, not once |
| The rename changes `SQLiteStatePlugin.name`, which is the **sort key that decides the substrate** (D.2-7) | **High** — silent, and a plausible future rename (`sqlite-substrate`, `zsqlite`) breaks it | D.2-7 lands first, removing the dependence entirely; then the rename cannot matter |
| A `git mv` of twelve directories obscures the sqlite plugin's real edits | Medium — git detects renames, but not for files that moved *and* changed, which is exactly the sqlite plugin | Move in one commit that does nothing else, then edit |
| Standalone binary loses AWS support (AC-25) | Medium, accepted | Stated in the spec; must appear in CHANGELOG as a breaking note, in **PR-2** |
| Fixing the `[ai]` config probe changes behaviour for existing projects (A.5, D.5-16) | Medium — silent today, so nobody has an `[ai]` section that works | CHANGELOG entry; the fix is explicitly in scope rather than absorbed |
| `tests/conftest.py:356,360` reaches `plugins/functualize-state-sqlite/src` by **filesystem path** and imports `functualize_state_sqlite` | Low, but fails obscurely | Path consumer of the move and name consumer of the rename **in one fixture** — one task, both edits |
| `uv.lock` churn across 12 packages, three times | Low | Regenerate once per PR, at the end |
| Three PRs means three chances for the feature dir to drift from reality | Low | `.spec/STATE.md` updated after each task; §E's Today column is re-measured at the head of PR-2 and PR-3 |

---

## I · Open questions for the Plan phase

**Q1 — the abandoned names on PyPI (R2).** Suppress them from
`plugin available --remote` via a retired-names list in `plugin_catalog.toml`, or
accept the listing and document it? Under D1′ this now recurs **three times**, so
a one-off answer will not do. *Recommendation: a retired-names list — the
command's own heading calls uncurated results "not vetted by this project", and
these three were.*

**Q2, Q3, Q5 — ANSWERED by the architecture gate, 2026-09-17** (`plan.md` §1.1).
Left here with their reasoning because they were open when the spec was written
and a reader needs to know they were asked.

The question was *"which group does a substrate register in?"*. Both revisions
of this spec treated `functualize.<x>_providers` as a **naming convention** and
asked which name reads best. It is not a convention. It is a **mechanism**:

> A `functualize.<x>_providers` group is scanned by
> `_plugins/domain_registry.py:246`, from the `entry_point_group` field of a
> **live `DomainMetadata`** published under `functualize.domains`. A
> `_providers` group with no domain SDK behind it has no reader, and cannot be
> given one without inventing the domain.

Measured — every `entry_point_group=` in the tree is one of two domains:

```
$ git grep -rn 'entry_point_group=' -- plugins/ examples/ src/
plugins/functualize-ai/src/functualize_ai/_metadata.py:32     functualize.ai_providers
plugins/functualize-tasks/src/functualize_tasks/_metadata.py:32  functualize.tasks_providers
src/functualize/_cli/scaffold/templates/domain-sdk/_metadata.py.j2:32   (a template)
```

There is no `state` domain (ADR-022 removed `functualize-state`), no
`interactivity` domain, and no `vault_key` domain. So:

- **Q2 → `functualize.plugins`.** Revision 2's recommended
  `functualize.substrate_providers` would have been **exactly as dead as
  `state_providers`** — `classify_group` would label it `IMPLEMENTATION` and
  nothing would ever load it. Classification and loading are different
  questions. The repo already proves `functualize.plugins` works for this
  class: `_cli/scaffold/templates/full-interactivity/pyproject.toml.j2:20`
  registers `SQLiteStatePlugin` there and a scaffolded project loads it.
- **Q3 → `functualize.plugins`** for `functualize-inline`, same reasoning.
- **Q5 → delete.** `functualize.vault_key_providers` is a provider group for a
  domain that never existed. Both sites go: root `pyproject.toml:49` and the
  sentence at `_config/vault_keys.py:6` that advertises it.

**The cost, stated rather than hidden:** `functualize.plugins` classifies as
`PluginKind.ADAPTER`, which `plugin available` renders as *"adds commands or a
delivery surface"*. A substrate does neither, so §C U3 is **not fully met by
PR-1**. Declared as a surviving smell (`plan.md` §5, entry 2) and **flagged for
maintainer review** — it is the one place PR-1 knowingly ships a user-visible
inaccuracy.

**Q4 — directory names. ANSWERED** (maintainer, 2026-09-17). Revision 1
proposed five groups, `adapters/ substrates/ secrets/ domains/ providers/`, and
flagged `providers/` as the weak one. It is **four**: an implementation is
placed beside the contract it implements, as a **sibling** under `domains/`, and
`functualize-inline` — which implements no contract — goes to `adapters/`,
matching the group T5 moves it to. Full layout and reasoning in `contracts.md`
§2. Siblings rather than children keeps every plugin at exactly two levels,
the one depth `members = ["plugins/*/*"]` and the spec gate are taught.

**Q6 — `MCPAdapterPlugin` (D.5-15): grow the class, or drop the claim?** Adding
`run`/`shutdown` makes the name true; dropping `adapter_type` and the docstring
claim makes it honest as a plain plugin. AC-17 accepts either, but it needs
`validate_adapter` to gain a production caller in both cases.

---

## J · Verification note

Every count in §A and §E was produced by running its command on **2026-09-17**
against **`80ec5f0`**. No count here was obtained by reading a file.

- **`git grep`, not `rg`**, so the untracked `graphify-out/` (290k+ lines, matches
  nearly every identifier) cannot inflate a count. This corrects revision 1.
- **Alternation is real alternation.** Revision 1's gates used `\|`, which in
  `rg`'s Rust regex is a *literal pipe* and matches nothing. Every gate above was
  re-expressed and run.
- **Repository-wide negatives** — *"three groups have no reader"*,
  *"`SQLiteStateBackend` is defined nowhere"*, *"`validate_adapter` has no
  production caller"*, *"`boto3` does not appear in `src/`"* — were established
  over the whole tree, not by inspection, per `.spec/CONSTITUTION.md` →
  *Retrieval Before Assertion*.
- **Two claims about syntax were taken from the AST, not from a regex**, per
  `.claude/rules/spec-workflow.md`: `MCPAdapterPlugin`'s method set (an `ast`
  walk of its `ClassDef`) and `AdapterPlugin`'s required members.
- **One claim was verified by execution**: AC-13 imports `spec_gate.py` and calls
  `is_gated` against five paths (`research.md` R1). Reading that predicate is how
  revision 1 established it; running it is how revision 2 does.
