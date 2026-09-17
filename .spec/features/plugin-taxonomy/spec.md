# plugin-taxonomy — a plugin ecosystem whose names, folders and wiring agree

**Base:** branch `feat/plugin-host-protocol` @ `79545ef` (master `11d77f6`).
Second feature folder on that branch, alongside the in-flight
`.spec/features/plugin-host-protocol/`, per maintainer decision 2026-09-16.
Every count below was produced by running the command shown; see `research.md`
for the four findings that changed this feature's shape after the brief.

---

## A · Why

Three separate things drifted apart, and the drift is now user-visible.

### A.1 · Two plugins and one tutorial register in groups nothing reads

Core reads entry-point groups in exactly **nine** places. This is every
`entry_points(group=…)` call in `src/`:

```
$ rg -n 'entry_points\(group=' src/functualize --include=*.py
_app/boot.py:206                        functualize.jobs
_cli/skills.py:166                      functualize.skills            (SKILLS_ENTRY_POINT_GROUP)
_config/registry.py:169                 functualize.format_providers
_config/registry.py:193                 functualize.remote_providers
_plugins/domain_registry.py:156         functualize.domains           (DOMAINS_ENTRY_POINT_GROUP)
_plugins/domain_registry.py:246         <domain>.entry_point_group    -> ai_providers, tasks_providers
_cli/tui/display_provider_discovery.py:82  functualize.displays       (_DISPLAY_ENTRY_POINT_GROUP)
_plugins/loader.py:326                  self._group                   (default "functualize.plugins")
_discovery/providers.py:790             self._group                   (a job source's own group)
```

Three declared `functualize.*` groups appear in **no** reader:

| Group | Declared by | Consequence |
|---|---|---|
| `functualize.state_providers` | `plugins/functualize-state-sqlite/pyproject.toml:24` | `SQLiteStatePlugin.__call__` is never invoked. `pip install functualize-state-sqlite` installs a package that does nothing. |
| `functualize.state_providers` | `examples/plugins/custom_state_backend/pyproject.toml:11` | The **documented tutorial** for writing a substrate (mkdocs nav `mkdocs.yml:148`) teaches a dead group. |
| `functualize.interactivity_providers` | `plugins/functualize-inline/pyproject.toml` | `InlinePlugin.__call__` is never invoked. |
| `functualize.vault_key_providers` | root `pyproject.toml:46` | Harmless: core imports `EnvKeyProvider`/`KeychainKeyProvider` directly. Still a false advertisement — `_config/vault_keys.py:6` tells plugin authors to register through it. |

`functualize-state-sqlite` was a `StateBackend` + `ExecutionStore` provider until
ADR-022 retired that domain. The implementation moved on — `_plugin.py` installs
a `StoreSubstrate`, `substrate.py` implements the port — and the **registration
did not**. The group outlived the domain it belonged to.

### A.2 · Names say the wrong thing

- `functualize-state-sqlite` is not a state backend. It is a substrate.
  Its own README:46 still documents `SQLiteStateBackend`, `SQLiteExecutionStore`
  and `ON_SCOPE_CREATED` — all three retired by ADR-022.
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

`functualize-tasks-local` performs read-modify-write across the substrate with
neither `lock()` spanning the read nor `write(expect=)`. On `JsonFileSubstrate`
and `SQLiteSubstrate` the damage is bounded. The port documents that `lock()`
"may be a no-op for a backend that offers no mutual exclusion"
(`_types/protocols.py:795`) — which is what an S3 implementation is. **Adding
`functualize-substrate-s3` without fixing this ships silent task loss.**

---

## B · Decisions taken (maintainer, 2026-09-16 — recorded, not re-opened)

| # | Decision | Rejected alternative |
|---|---|---|
| D1 | Rename exactly three distributions, **no compatibility shims** | Renaming http/lambda too; shipping deprecation shims |
| D2 | Naming pattern is **domain-first** `<what-it-serves>-<which-one>` | Kind-first (`functualize-adapter-http`) |
| D3 | The word for AWS/Bitwarden is **secrets**, not *vault* | `vaultprovider-*` — "vault" already names the *local* encrypted file (`_config/vault.py`) and `functualize.vault_key_providers` |
| D4 | `functualize.remote_providers` → `functualize.secrets_providers`, **hard cutover**, core reads only the new name | Dual-read with a deprecation warning |
| D5 | The F-series bugs are fixed **in this feature**, before the rename | Deferring them; renaming dead wiring |
| D6 | Artifacts live on branch `feat/plugin-host-protocol` as a second feature | A separate branch off master |

D1 and D4 are consistent with `.spec/CONSTITUTION.md` → *Forbidden Patterns*:
*"`DeprecationWarning` / backward-compat shims — pre-release, no users to
deprecate toward. Remove old code."*

**Accepted cost of D1**, stated so a reviewer sees it was priced: three PyPI
projects are abandoned at 0.2.3, and three new ones need a one-time manual token
upload each, because a *pending* trusted publisher is unique on
`(owner, repo, workflow, environment)` and one workflow can claim exactly one
not-yet-existing name (`release.yml:119-130`). `functualize-substrate-s3` is
new rather than renamed, so it consumes the single automatic slot.

---

## C · Users and stories

**U1 · Someone choosing where their state lives.** Installs a substrate plugin
and their runs use it. Today they install `functualize-state-sqlite` and nothing
happens, with no error.

**U2 · Someone writing a third-party substrate.** Follows
`docs/examples/plugins/custom-state-backend.md`, and the plugin they build
loads. Today it does not.

**U3 · Someone browsing plugins.** Runs `func builtin plugin available` and sees
each plugin under a heading that describes what it is. A substrate is not "adds
commands or a delivery surface".

**U4 · Someone deploying to a constrained target.** Installs `functualize[all]`
or takes the standalone binary and does not receive `boto3`.

**U5 · A contributor opening `plugins/`.** Sees which plugins are alternatives
for the same job and which layer each belongs to, from the directory tree.

**U6 · Someone with concurrent task writers.** Two processes update different
tasks; both survive. Today one is silently lost.

---

## D · Behaviour

### D.1 · Wiring (F1, F2)

1. Every first-party plugin that declares an entry point is **reachable through
   that entry point** from a clean install. No plugin registers in a group core
   does not read.
2. A substrate plugin installed by a user takes effect for every store in the
   run, or fails **loudly**. It never falls back to the filesystem silently.
3. `func builtin plugin available` describes a substrate as a substrate.
4. `functualize-ai` no longer advises installing a package that cannot satisfy
   the need it names. Its budget/checkpoint state either uses the app's
   substrate or is honestly documented as ephemeral.

### D.2 · Storage correctness (F3, F4)

5. A read-modify-write through `functualize-tasks-local` is **atomic against a
   concurrent writer on a substrate whose `lock()` is a no-op**. Compare-and-swap,
   not lock ordering.
6. Listing N tasks costs a bounded number of substrate reads, independent of N.
7. A task document is readable as data — `func builtin data show` renders task
   fields, not an opaque escaped string.
8. The order in which plugins' `APP_READY` hooks run **cannot** change which
   substrate a project uses. (Today `functualize-tasks-local/_plugin.py` reads
   `app.execution_engine.substrate`, caching `engine._substrate`
   (`_engine/executor.py:1522-1527`), after which `install_substrate`
   (`_app/impl.py:1564`) raises — and `SQLiteStatePlugin` swallows it.)

### D.3 · Names and structure (A, B, D, E)

9. `plugins/` groups its members by what they serve. A reader identifies a
   plugin's role from its path.
10. The three renamed distributions carry their new names in distribution
    metadata, import package, entry points, tests, examples, docs and the
    curated catalog — with **zero** surviving references to the old names except
    a CHANGELOG entry recording the rename.
11. Core resolves secrets providers from `functualize.secrets_providers`. The
    string `remote_providers` does not appear in `src/`.
12. Neither secrets plugin is installed by `functualize[cli]` or
    `functualize[all]`. **Consequence, stated deliberately:** `[all]` is what
    the standalone binary bakes (`PYAPP_PROJECT_FEATURES=all`, ADR-015
    §Correction), so **the standalone binary loses AWS Secrets Manager and SSM
    support.** Users needing it install `functualize-secrets-aws` themselves.
13. Both first-party secrets plugins remain directly installable and
    first-class; not being in `[all]` is not a demotion (the existing
    `functualize-bitwarden` precedent, `pyproject.toml:105-118`).

### D.4 · The enforcement that must survive the move (R1)

14. The spec-workflow `PreToolUse` gate still refuses an ungated write to plugin
    source **after** the directories move. (`.claude/hooks/spec_gate.py:87`
    tests `rel[1] == "src"`, which a second directory level breaks — and the
    gate fails open, so nothing would report it.)

### D.5 · New capability (C)

15. `functualize-substrate-s3` satisfies `StoreSubstrate` against S3, honouring
    `write(expect=)` as a real compare-and-swap. `lock()` is a documented no-op.
16. It carries no import of `boto3` into core: `rg -n boto3 src/functualize/`
    stays at **0** (verified today: 0), the invariant ADR-016 set.

### D.6 · Documentation truth (G, R3, R4)

17. No shipped document or runnable example references a protocol ADR-022
    retired, or a symbol that does not exist.

---

## E · Acceptance criteria

Each is a command. The number beside it is what it returns **today**, measured
2026-09-16; the criterion is the required value after the feature.

| AC | Gate | Today | Required |
|---|---|---|---|
| AC-1 | Every `functualize.*` group declared by a first-party plugin or shipped example appears in some `entry_points(group=…)` reader in `src/` | 3 orphans | 0 orphans |
| AC-2 | `rg -n 'functualize\.state_providers\|functualize\.interactivity_providers' --glob '!.spec'` | non-empty | empty |
| AC-3 | A test boots an app with a substrate plugin installed **via its entry point** and asserts every store resolved to it | absent | present, green |
| AC-4 | Installing a substrate after the engine resolved one surfaces an error to the user rather than a debug log | swallowed (`_plugin.py:70-77`) | raised or reported |
| AC-5 | A test drives two concurrent `LocalTaskProvider.update()` calls over a substrate whose `lock()` is a no-op and asserts both land | absent | present, green |
| AC-6 | Substrate reads per `LocalTaskProvider.list()` of N tasks | `1 + N` | O(1) |
| AC-7 | `func builtin data show` on a project with tasks renders task titles, not escaped JSON | escaped | readable |
| AC-8 | Hook-ordering independence: a test registers `tasks-local` **before** the substrate plugin and asserts the substrate still wins | absent | present, green |
| AC-9 | `rg -n 'functualize.state.sqlite\|functualize_state_sqlite\|functualize-aws\|functualize_aws\|functualize-bitwarden\|functualize_bitwarden' --glob '!CHANGELOG.md' --glob '!.spec'` | 44 / 11 / 17 / 9 / 16 / 6 files | 0 files |
| AC-10 | `rg -n remote_providers src/` | 5 files, part of 53 sites / 19 files repo-wide | 0 in `src/` |
| AC-11 | `tests/cli/test_plugin_catalog.py::test_recommended_set_matches_the_all_extra` | green | still green, with AWS in neither |
| AC-12 | `rg -n 'functualize-secrets-aws\|functualize-secrets-bitwarden' pyproject.toml` inside `[all]`/`[cli]` | — | 0 matches |
| AC-13 | `spec_gate.py`'s predicate, **executed** against `plugins/<group>/<pkg>/src/x.py` | returns False after the move | returns True |
| AC-14 | `uv sync --all-packages` resolves and `uv build --all-packages` exits 0 | green | still green |
| AC-15 | `rg -n boto3 src/functualize/` | 0 | 0 |
| AC-16 | Every plugin `pyproject.toml` is found by the workspace: `uv run python -c "…"` counts members | 12 | 13 (12 + s3) |
| AC-17 | `rg -n 'StateBackend\|ExecutionStore' docs/ examples/ plugins/ --glob '!*/adr/*'` | 13 files | 0 files |
| AC-18 | `plugins/functualize-state-sqlite/examples/persistent_counter/` imports resolve (`SQLiteStateBackend` is defined nowhere: `grep -c` → 0) | broken, uncollected | resolves, and is collected |
| AC-19 | `uv run lint-imports` | green | green |
| AC-20 | `uv run pytest` plus every relocated plugin suite | green | green |

**AC-9 excludes `CHANGELOG.md` deliberately** — the changelog must name the old
names, because recording the rename is the point.

---

## F · Explicitly out of scope

- **Renaming http, lambda, mcp, flow-viz, inline, tasks, tasks-local, ai,
  ai-pydantic.** D1/D2 settled this. Their *directories* move (item A); their
  distribution names do not.
- **Compatibility shims on PyPI.** D1.
- **Dual-reading the old `remote_providers` group.** D4.
- **Making CI run every plugin's test suite.** `research.md` R4 shows CI runs
  one plugin's suite (`ci.yml:232,235`) out of twelve, which is why F1–F4 could
  all be true with a green pipeline. Real, worth doing, not this feature —
  record in `.spec/STATUS.md`.
- **The `app: Any` typing problem.** Owned by `plugin-host-protocol`; see §G.

---

## G · Boundary with `plugin-host-protocol`

The two features touch the same files and must not both claim the same fix.

| Defect | Owner | Why |
|---|---|---|
| `app: Any` on plugin entry points; `di.resolve(T)` | **plugin-host-protocol** | It is a typing/surface feature |
| `functualize-mcp` reaching `app.resolve` / `app._tasks` (dead branches) | **plugin-host-protocol** | Already documented in its `spec.md` §A |
| `functualize-ai-pydantic`'s dead `from functualize_state import StateBackend` guard | **plugin-host-protocol** | Same — already in its spec |
| `functualize-ai/_state_fallback.py` built on retired `StateBackend` (F2) | **plugin-taxonomy** | Not a typing bug; the module is obsolete outright and its user-facing advice is false |
| `tasks-local` reading `app.execution_engine.substrate` (F4) | **plugin-taxonomy** owns the *ordering* fix; **plugin-host-protocol** owns whether that attribute is a typed surface | Two different defects at one call site |

### Same-line seams (added 2026-09-17)

`plugin-host-protocol`'s decisions of 2026-09-17 put both features on the same
lines in two files. Recorded exactly, so neither claims the other's fix.

| Site | `plugin-host-protocol` changes | **this feature** changes |
|---|---|---|
| `functualize-state-sqlite/_plugin.py:74-78` | the **call spelling** — `app.substrate = self._substrate` becomes `app.install_substrate(self._substrate)` (its AC-14/T4) | the **error handling** — AC-4 here, stop swallowing the install failure. Applies to the new spelling. |
| `functualize-tasks-local/_plugin.py:66` | the **spelling only** — `app.execution_engine.substrate` → `app.substrate` (its AC-13/T4). Behaviour is identical: the new property returns `self.execution_engine.substrate`. Its T4 is explicitly instructed **not** to fix the ordering bug. | the **ordering bug** — F4/AC-8 here. It survives the other feature intact, by design. |
| `functualize.vault_key_providers` | nothing | **this feature owns it** (§A.1, and dead-code audit finding #3, HIGH) |

Two further notes from that feature's revision:

- Its port now declares `install_substrate` and `fresh_root`
  (`.spec/features/plugin-host-protocol/spec.md` AC-2b), which is effectively
  **the substrate-plugin contract**. That gives **Q2** below a type-level
  answer: a substrate plugin is one whose `__call__` uses those two members.
  Offered as an input; the decision stays here.
- It adds `contributor/reference/public-api-example-coverage.md` — every public
  API needs a caller in `examples/`. This feature renames three distributions
  and adds `functualize-substrate-s3`, so anything it makes public inherits that
  rule.

**Sequencing is now a requirement, not a suggestion.** `plugin-host-protocol`
lands first. It makes line edits inside plugin directories; this feature
`git mv`s all twelve. An annotation survives a move; a file list does not
survive a rename — and that feature's `tasks.md` file lists are paths.

---

## H · Risks

| Risk | Severity | Handling |
|---|---|---|
| Spec gate silently stops enforcing plugin source (R1) | **High** — disables the mechanism guarding the rest | AC-13, wave 1, gate fix **before** any move |
| `plugin available --remote` advertises the three abandoned names (R2) | Medium, user-visible | Open question Q1 below |
| A `git mv` of twelve directories collides with `plugin-host-protocol`'s edits | Medium | Land the other feature first, or move directories in one commit that does nothing else |
| Standalone binary loses AWS support (AC-12 / D.3-12) | Medium, accepted | Stated in the spec, must appear in CHANGELOG as a breaking note |
| Renaming the import package breaks `tests/conftest.py:352-360`, which reaches `plugins/functualize-state-sqlite/src` by filesystem path | Low, but fails obscurely | It is both a path consumer and a name consumer; one task, both edits |
| `uv.lock` churn across 13 packages | Low | Regenerate once, at the end |

---

## I · Open questions for the Plan phase

**Q1 — the abandoned names on PyPI (R2).** Suppress them from
`plugin available --remote` via a retired-names list in `plugin_catalog.toml`,
or accept the listing and document it? *Recommendation: suppress — the command's
own heading calls them "not vetted by this project", and these three were.*

**Q2 — which group a substrate registers in (research.md §"One place prior art
outranks the brief").** `functualize.plugins` loads today but classifies as
`ADAPTER` (`_primitives/plugin_kinds.py:56`), which `plugin available` renders
as *"add commands or a delivery surface"* — wrong for a substrate. A
`functualize.substrates` group plus a `PluginKind.SUBSTRATE` says the truth and
costs more. **Left open on purpose: this is the architecture gate's call.**
AC-1/AC-3 are written so either satisfies them.

**Q3 — the same question for `functualize-inline`.** Its group
(`interactivity_providers`) is equally dead. Does it become a `functualize.plugins`
adapter, a `functualize.displays` provider (the group `_cli/tui/` already reads),
or does core gain a reader for it?

**Q4 — directory names.** The brief proposes
`adapters/ substrates/ secrets/ domains/ providers/`. `providers/` is the weak
one: `tasks-local` and `ai-pydantic` are implementations of a *domain*, so
`implementations/` or nesting under the domain they serve may read better. Cheap
to change now, expensive later.

---

## J · Verification note

Every count in §A and §E was produced by running its command on
2026-09-16 against `79545ef`. No count here was obtained by reading a file. The
two claims that are repository-wide negatives — *"three groups have no reader"*
and *"`SQLiteStateBackend` is defined nowhere"* — were established with `rg`
over the whole tree, not by inspection, per `.spec/CONSTITUTION.md` →
*Retrieval Before Assertion*.
