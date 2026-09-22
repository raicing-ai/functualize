# FUN-24 — Plan

**Status:** architecture gate **satisfied** (2026-09-22, Factory Designer). Retrieval passes
run, BEFORE/AFTER drawn, smells named at all three points, surviving smells declared.
Two entries need maintainer review before Execute begins — see *Surviving smells*.

Evidence baseline: worktree `/home/ubuntu/orca/workspaces/functualize/rp-24-defect-repair`,
branch `fix/runtime-persistence-defects` @ `b82fc78`. `git diff --stat 8c06198..HEAD -- src
plugins` is **empty** — every `src/` and `plugins/` citation below is identical to
`origin/master` @ `8c06198`, so the research's line numbers can be checked against either.

---

## 1. Retrieval passes (gate step 1)

| Tool | Status | What it gave |
|---|---|---|
| `rg` / `grep` | ran | every count, negative and call-site claim below |
| `ast` walk | ran | the call-site census in §4 (regex over-counts docstrings) |
| **zvec-grep** | ran | index built for this worktree (843 files, 13 262 entities, 1 m 11 s); prose pass found `contributor/reference/pitfalls.md` §2/§13/§22, `09-decisions.md` D-15, `layer-contract-blind-spot.md` |
| **graphify** | ran, CLI | `graphify explain ScopeStore / ScopeStateStore` over `graphify-out/graph.json` — dependency direction in §2 |
| **serena** | **could not run** | see below |

**serena was unreachable, and that is recorded rather than worked around.** The MCP server
fails at startup in this runtime (`serena CONNECTION_CLOSED`). The binary is not absent —
`uvx --from serena-agent serena --help` runs — but the CLI entrypoint exposes only
`config / context / memories / mode / dashboard-viewer / print-system-prompt`; the symbol
tools (`find_symbol`, `find_referencing_symbols`) exist only over MCP. `.serena/memories/`
does not exist on this branch (`.serena/` holds `project.yml` and `.gitignore` only), so the
durable half carried nothing either.

Substituted for the 3b reference pass: a **Python `ast` walk** over all 1 369 `.py` files in
`src/functualize/`, `plugins/` and `tests/`, counting `ast.Call` nodes whose `func` is an
`Attribute` with the target name. That is stronger than `rg` for this question (it cannot
match a docstring) and weaker than serena for one specific thing: it matches by *attribute
name*, not by resolved symbol, so a same-named method on an unrelated class would be counted.
Checked by hand for each result in §4 — all 14 production hits are the intended receivers.

**graphify caveat.** `graphify-out/graph.json` is dated 2026-09-21 and its `GRAPH_REPORT.md`
header says `feat-local-vault-access (2026-09-17)`. Its edges still name
`plugins/functualize-mcp/...`, a path that no longer exists (the real path is
`plugins/adapters/functualize-mcp/`), so the graph predates the `plugin-taxonomy` reshuffle.
Its `src/` edges were spot-checked against the files and agree; its `plugins/` paths must not
be quoted.

## 2. Codemaps (gate step 2)

`contributor/architecture/codemaps/` is **silent on this region**, which is itself a finding:

```
grep -n 'ScopeStore|ScopeStateStore|StoreSubstrate|shell_history' \
    codemaps/dependencies.md codemaps/modules.md codemaps/data-flow.md
-> modules.md:153 only:
   | `functualize-substrate-sqlite` | Implementation | SQLite-backed state persistence |
```

So no diagram below can contradict a codemap — there is nothing to contradict. The codemaps
never absorbed the `store-substrate` feature. `overview.md` is current on the layer structure
and the plugin taxonomy (it carries the corrected "12 plugins" count), and both diagrams
below use its layer names. **Not fixed here** — regenerating codemaps is `/sync-docs` work and
belongs to no acceptance criterion on this ticket.

## 3. BEFORE

Layers per `codemaps/overview.md` → *Audience-Separated Package Structure*. `═══` marks an
import-linter boundary; `✗` marks a defect site.

```
                      ┌──────────────────────── PUBLIC ────────────────────────┐
                      │ app/core.py:335   .substrate      -> engine's substrate │
                      │ app/core.py:338   .substrate_override                   │
                      │ app/core.py:353   .install_substrate                    │
                      │ app/utils.py:266-272  FreshStore ScopeStore RunStore    │
                      │                       ShellHistoryStore                 │
                      │                   (StoreSubstrate, Stored: absent)      │
                      └───────────────────────────┬────────────────────────────┘
                                                  │
  _cli/  (delivery — public API only)              │ public only
  ┌───────────────────────────────────────────┐    │
  │ _cli/builtins.py:661 _project_substrate ──┼────┘  reads app.substrate  ✔
  │   -> :959 :1062 :2092  ShellHistoryStore(substrate)                    ✔
  │                                            │
  │ _cli/tui/shell_mode.py:217 execute_shell_handoff(app, cmd)             │
  │   :243 -> _record_history_quietly(cmd, code)   ← app DROPPED HERE      │
  │            :312 ShellHistoryStore.for_project(Path.cwd())          ✗ B5 │
  └───────────────────────────════════════════════════════════════════─────┘
                                                  │
  _app/  (composition root)                        │
  ┌───────────────────────────────────────────┐    │
  │ _app/boot.py:619  _execution_engine = build_engine(app)               │
  │ _app/boot.py:868  # 9. APP_READY                                      │
  │       :879 try: hook(app)                                             │
  │       :881 except Exception: logger.warning(...)                  ✗ B2 │
  │ _app/boot.py:467-473  same loop, boot_static                      ✗ B2 │
  │ _app/impl.py:1584 install_substrate — refuses a LATE install only     │
  └───────────────────────────════════════════════════════════════════─────┘
                         ▲                        │
    plugins/ (peer, outside src)                  │
  ┌──────────────────────┴────────────────────┐   │
  │ substrates/functualize-substrate-sqlite/   │   │
  │   _plugin.py:61  app.hooks.on_ready(...)   │   │  ← install rides an
  │   _plugin.py:86  SQLiteSubstrate(path)  ───┼───┘    APP_READY hook, so
  │   _plugin.py:87  app.install_substrate()   │        its raise is caught
  │ domains/functualize-tasks-local/           │
  │   _provider.py:139-158  lock() + expect=   │  ← the ONLY expect= caller
  └────────────────────────────════════════════┘     anywhere in production
                                                  │
  _engine/  (peer layer)                           │
  ┌───────────────────────────────────────────┐    │
  │ _engine/frontier.py:183 claim_scope       │    │
  │                    :190 hold(gen)         │    │
  │ _engine/capabilities/state.py:106 get     │    │
  │                              :123 set  ───┼────┼──┐ the rc.state path:
  │                              :127 delete  │    │  │ its ONLY production
  │ app/_workflow_control.py:430 :438 :448    │    │  │ caller
  └───────────────────────────════════════════┘    │  │
                                                  │  │
  _primitives/  (zero-dep utilities)               │  │
  ┌───────────────────────────────────────────────────▼──────────────────┐
  │ scope_store.py:114  ScopeStore            ── owns `scopes.json` ──── │
  │   :102   _blank_scope()["state"] = {}        dead field          ✗ B6 │
  │   :235   _mutate(mutate, *, scope_id=None)                           │
  │   :249       _guarded -> check_generation    THE fence point      ✔  │
  │   :263       with substrate.lock(key)                                │
  │   :266       substrate.write(key, ...)       no expect=           ✗ B3 │
  │   :268   hold(scope_id, generation) -> self._generations              │
  │   :287   generation_for(scope_id)                                    │
  │   :471   _state_store() — "Cheap: no read of scopes.json" (:472)      │
  │   :512     memoized via setdefault                                    │
  │   :520   set_state ─┐ :516 get_state :529 delete_state :533 snapshot  │
  │          :537 clear_state :541 state_batch :550 discard_state         │
  │   :715   claim_scope│  -> _mutate(_apply)  scope_id=None             │
  │   :750       ^^^^^^^^^ fence SKIPPED for the claim itself         ✗ B4a│
  │            │                                                          │
  │            │ bypasses the fence entirely                              │
  │            ▼                                                          │
  │ scope_state_store.py:87  ScopeStateStore  ── owns `scope-state/<id>` ─│
  │   :144  _mutate: lock -> load -> mutate -> write   no fence       ✗ B1 │
  │   :154  batch(): exit write at :169               no fence        ✗ B1 │
  │   grep -c generation -> 0                                            │
  │                                                                       │
  │ lease.py:197 claim  :282 check_generation                            │
  │   :302  if existing.generation != generation   owner-blind        ✗ B4b│
  │ substrate.py:60 _revision_of -> int  :132 Stored(revision=int)        │
  │ substrate.py:164 current.revision != expect   real CAS, 0 callers     │
  │ shell_history.py:61 ShellHistoryStore  :76 for_project               │
  └───────────────────────────════════════════════════════════════════════┘
  _types/  (stdlib only)
  ┌───────────────────────────────────────────────────────────────────────┐
  │ protocols.py:765 Stored   :784 revision: int   docstring says OPAQUE ✗ B7│
  │ protocols.py:788 StoreSubstrate  :790 "Three members"                 │
  │                                  :812 "Six members, not three"    ✗ B8 │
  │ protocols.py:858 lock(*keys) — variadic; 13 call sites, all arity 1   │
  └───────────────────────────────────────────────────────────────────────┘
```

**Smells the BEFORE already carries** (catalogue names from the
`design-patterns-refactoring` skill, confirmed present in it — see §7):

| Smell | Where | Evidence |
|---|---|---|
| **Shotgun surgery** | the fence rule: `ScopeStore._mutate:235` enforces it, `ScopeStateStore._mutate:144` does not, and both write documents that one logical claim governs | `grep -c generation scope_state_store.py` → **0** |
| **Primitive obsession** | `Stored.revision: int` (`protocols.py:784`) — a domain token carried as a raw primitive, and its own docstring at :776-781 forbids what the type permits | `substrate.py:66` says "the port types a revision as an int" |
| **Dead code** | `_blank_scope()["state"] = {}` (`scope_store.py:102`) with a 10-line docstring describing behaviour that moved to another document in `durable-run-layer`/T3 | only reader of a `"state"` key is `scope_state_store.py:125`, on a *different* document |
| **Speculative generality** | `StoreSubstrate.lock(*keys)` is variadic "for exactly this purpose" and **13** production call sites pass one key | `grep -rn '\.lock(' src plugins \| grep -v /tests/` → 13, all arity 1 |
| (not a catalogue smell — described plainly) | `_cli/tui/shell_mode.py:243` drops the `app` its own caller was given, so the writer cannot ask what the reader asks. `contributor/reference/pitfalls.md` §22 is this repo's own record of the same shape | §4 below |
| (not a catalogue smell — described plainly) | `boot.py:879-882` / `:467-473` catch `Exception` around a general extension point, so a plugin's deliberate raise cannot reach boot. `pitfalls.md` §2 is the repo's record of this shape | `_plugin.py:71-87` |

## 4. Call sites and blast radius (gate step 3b)

`ast` walk, 1 369 files, `ast.Call` on an `Attribute`. Production = outside `tests/`.

| Symbol | calls | production call sites |
|---|---|---|
| `set_state` | 40 | **1** — `_engine/capabilities/state.py:123` |
| `get_state` | 19 | **1** — `_engine/capabilities/state.py:106` |
| `delete_state` | 4 | **1** — `_engine/capabilities/state.py:127` |
| `state_snapshot` | 9 | **2** — `_engine/capabilities/state.py:130,133` |
| `state_batch` | 7 | **1** — `_engine/capabilities/state.py:147` |
| `claim_scope` | 66 | **3** — `_engine/frontier.py:183`, `app/_workflow_control.py:430,504` |
| `hold` | 25 | **4** — `_engine/frontier.py:190,302`, `app/_workflow_control.py:438,448` |
| `renew_scope` | 4 | **1** — `_engine/frontier.py:282` |
| `release_scope` | 6 | **2** — `_engine/frontier.py:297`, `app/_workflow_control.py:505` |
| `install_substrate` | 4 | **1** — `substrates/functualize-substrate-sqlite/.../_plugin.py:87` |

Three consequences the diagrams made visible and a call-site trace would not:

1. **The whole `rc.state` blast radius is one file.** `_engine/capabilities/state.py`
   (`ScopeBackedStateStore`) is the sole production caller of all five `*_state` methods. So
   the production call path for AC-1 and AC-2 is exactly
   `rc.state.set()` → `state.py:123` → `scope_store.py:520` → `ScopeStateStore.set` →
   `scope_state_store.py:144` → `substrate.write`, and **fencing it changes no caller.**

2. **`_state_store()` (`:471`) memoizes at `scope_store.py:512-514`, and `hold()` mutates
   `self._generations` on `ScopeStore` (`:268-285`).** Therefore passing a generation into
   `ScopeStateStore.__init__` is wrong by construction: the first `_state_store()` call caches
   the object forever, so a `hold()` afterwards is invisible to it. `frontier.py:177-190` does
   `ensure_scope` → `claim_scope` → `hold` while `_state_store` is first built later, on the
   job's first `rc.state` touch — so the ordering happens to work today and would break the
   moment anything read state before claiming. The fence must be read **at write time**.

3. **`expect=` already has a working, tested implementation in this repo.** The research's
   B3 says "**Zero** production callers"; that is true of `src/functualize/` and **false of
   the repository**: `plugins/domains/functualize-tasks-local/.../_provider.py:153` is one, in
   a bounded retry loop at `:139-158`, with its own docstring recording the one race it cannot
   close. That is the shape to copy, not invent. See §6.

## 5. AFTER

Only the changed region is redrawn; everything omitted is unchanged from §3.

```
  _cli/
  ┌───────────────────────────────────────────────────────────────────────┐
  │ _cli/tui/shell_mode.py:217 execute_shell_handoff(app, cmd)            │
  │   :243 -> _record_history_quietly(app, cmd, code)   ← app THREADED    │
  │            :312 ShellHistoryStore(app.substrate)                 ✔ B5 │
  │              app.substrate is app/core.py:335 — the SAME public       │
  │              accessor _cli/builtins.py:691 reads. One derivation,     │
  │              writer and reader (pitfalls.md §22).                     │
  │            fallback: .for_project(Path.cwd()) when app is None        │
  └────────────── still public-API-only; no new boundary crossing ────────┘

  _app/
  ┌───────────────────────────────────────────────────────────────────────┐
  │ _types/errors.py   + SubstrateInstallError                            │
  │        ▲ imported by both, and _types imports nothing internal        │
  │        │                                                              │
  │ _app/boot.py:879  try: hook(app)                                      │
  │            :881  except SubstrateInstallError: raise            ✔ B2  │
  │            :882  except Exception as exc: logger.warning(...)         │
  │ _app/boot.py:467-473  identical pair, boot_static               ✔ B2  │
  │   -> a telemetry plugin that throws still does NOT kill boot          │
  └───────────────────────────────────════════════════════════════════════┘
             ▲
  plugins/   │
  ┌──────────┴────────────────────────────────────────────────────────────┐
  │ _plugin.py:86  wrap SQLiteSubstrate(...) failure in                   │
  │                SubstrateInstallError                            ✔ B2  │
  │   (imported from functualize.plugin — public; a plugin may not        │
  │    reach _types directly)                                             │
  └───────────────────────────────────────────────────────────────────────┘

  _primitives/
  ┌───────────────────────────────────────────────────────────────────────┐
  │ scope_store.py                                                        │
  │   :102  "state": {}  ─────────────────────────────── DELETED    ✔ B6  │
  │   :235  _mutate(mutate, *, scope_id=None)                             │
  │           for _ in range(_WRITE_ATTEMPTS):                            │
  │             with substrate.lock(key):                                 │
  │               stored = substrate.read(key)      ← revision captured   │
  │               _guarded(envelope)                  fence UNMOVED  ✔    │
  │               if substrate.write(key, ..., expect=stored.revision):   │
  │                  return                                         ✔ B3  │
  │           raise  (lost every round)                                   │
  │     -> claim_scope:750 routes through this, so the CLAIM is now  ✔ B4a │
  │        compare-and-swapped: two racers cannot both reach gen 1        │
  │                                                                       │
  │   :471  _state_store()   unchanged, memoized at :512                  │
  │   NEW   _fenced_state(scope_id) — ONE new fence point:                │
  │           check_generation(scope_id,                                  │
  │                            read_lease(self._read()["scopes"].get(id)),│
  │                            self._generations[id])   if a hold exists  │
  │           return self._state_store(scope_id)                          │
  │   FENCED (writes, 5):  :520 set_state    :529 delete_state            │
  │                        :537 clear_state  :541 state_batch             │
  │                        :550 discard_state                      ✔ B1  │
  │     state_batch checks at entry AND at the exit write — the stale     │
  │     window is the whole block, not its first instant                  │
  │   UNFENCED (reads, 2): :516 get_state    :533 state_snapshot          │
  │     _mutate:249 fences writes only; fencing reads is wider than AC-2  │
  │                                                                       │
  │ scope_state_store.py                                                  │
  │   :144  _mutate: lock -> read -> mutate -> write(expect=rev)    ✔ B3  │
  │   :169  batch() exit write: same                                ✔ B3  │
  │   -> still knows NOTHING about generations; grep -c generation        │
  │      stays 0. It owns one document and does not read scopes.json.     │
  │                                                                       │
  │ lease.py — UNCHANGED. :302 stays generation-only.               ⚠ B4b │
  │   Justified: owner-blindness can only bite when two runners share    │
  │   a generation, which the CAS above makes unreachable. Declared as   │
  │   a surviving risk, not fixed, not silently dropped.                  │
  │                                                                       │
  │ substrate.py:60 _revision_of -> Revision   :132 Stored(revision=...) │
  │ substrate.py:164 current.revision != expect   unchanged, compare-only │
  └───────────────────────────════════════════════════════════════════════┘
  _types/
  ┌───────────────────────────────────────────────────────────────────────┐
  │ protocols.py:784  revision: Revision                            ✔ B7 │
  │             NEW   Revision = NewType("Revision", str)                 │
  │   -> arithmetic on it is now a mypy error, which is what the         │
  │      docstring at :776-781 has always asserted in prose              │
  │   :790  "Three members" -> "Six members" (see contracts.md)     ✔ B8 │
  └───────────────────────────────────────────────────────────────────────┘
```

**Boundary check.** No new layer, no new peer-to-peer edge, no `_cli` → internal import.
`_types/errors.py` is imported by `_app/` (allowed: `_app` may import all internal layers)
and re-exported through `functualize.plugin` for the plugin (allowed: a plugin uses public
API). `_primitives/` gains no import. Baseline measured at authoring time:

```
uv run lint-imports
-> Analyzed 363 files, 1007 dependencies.
   Peer layers are independent KEPT
   Events depends on foundation only KEPT
   Primitives import nothing internal KEPT
   Types import nothing internal KEPT
   Internal never imports public KEPT
   _cli uses public API only KEPT
   Delivery adapters go through the request, not the engine KEPT
   Contracts: 7 kept, 0 broken.
```

**Smells the AFTER introduces** (gate step 4 — checked, not assumed):

- **Shotgun surgery, reduced but not removed.** The fence rule now lives at **two** points in
  one file (`_mutate:249` for `scopes.json`, `_fenced_state` for `scope-state/<id>`) instead
  of one point plus a hole. Two is worse than one and much better than one-plus-a-hole; both
  are in `scope_store.py`, which is the file that owns both documents. Declared below.
- **No divergent change introduced.** `scope_store.py` gains one method and loses a dead
  field; it stays at ~923 LOC, under no new pressure. It is already over the Constitution's
  ~500-LOC god-object threshold and this plan does not worsen that — see below.
- **No middle man introduced.** `_fenced_state` is not a pass-through: it performs the check
  and returns the collaborator. Deleting it would delete the fence.
- **No new `Callable` port.** The rejected alternative in §6 would have introduced one, which
  `.spec/CONSTITUTION.md` → *Forbidden Patterns* rules out.

## 6. Alternatives considered and rejected

**For B1 (AC-2), how does the fence reach `scope-state/<id>`?**

| Option | Verdict |
|---|---|
| Pass the generation into `ScopeStateStore.__init__` | **Rejected — wrong by construction.** `_state_store()` memoizes at `scope_store.py:512-514`; a `hold()` after the first call would never be seen. §4.2. |
| Put `check_generation` inside `ScopeStateStore._mutate` | **Rejected.** It would have to read `scopes.json` for the current lease — a new cross-document dependency from the store that owns exactly one document. That coupling is what FUN-17's `RuntimeTransaction` exists to introduce deliberately; smuggling it in here is the scope creep this ticket's guard names. |
| Give `ScopeStateStore` a fence callback | **Rejected.** `.spec/CONSTITUTION.md` → *Forbidden Patterns*: "Implicit `Callable` conventions for ports". A Protocol would be legal but is a new port for one internal caller. |
| Put `check_generation` on each of the five `*_state` methods | **Rejected.** Exactly the design `scope_store.py:239-244` and `tests/primitives/test_fenced_writes.py:10-15` argue against by name: "Putting the check on each of the eleven write methods would fence them all today and miss the twelfth." |
| **One `_fenced_state(scope_id)` seam in `ScopeStore`** | **Chosen.** `ScopeStore` is the only thing that has both facts (the held generation *and* the lease on `scopes.json`); it is already the sole constructor of every `ScopeStateStore` (`graphify explain ScopeStateStore` → one inbound production edge, `scope_store.py:513`). One check point, no new dependency, no caller changes. |

**For B2 (AC-4), where does the raise escape?**

The research's `05-the-design.md` §4 proposes a new boot step 6.5 with
`resolve_runtime_store_config`, `select_factory`, `RuntimeStoreFactory`, `StoreProfile` and
`app._runtime_store`. **That is FUN-17…FUN-23 work and must not be built here** — it replaces
the substrate port with a runtime-store port, which is the next wave's deliverable, not a
repair. (Its line citations have also drifted: it cites `boot.py:614/718/754/841`; the real
lines are `:619/:742/:780/:868`.)

| Option | Verdict |
|---|---|
| New boot step that constructs and installs the substrate | **Rejected for this wave.** Three shipped documents tell plugin authors to install from `APP_READY` (`docs/guides/workflows.md:391`, `docs/examples/plugins/custom-state-backend.md:61`, `examples/plugins/custom_state_backend/README.md:65`). Changing that is a plugin-contract break, and FUN-17 will revisit the same seam. |
| Widen the hook loop to re-raise everything | **Rejected**, and the research says so too: `APP_READY` is a general extension point; a telemetry plugin that throws must not kill the app. |
| **Exempt one named error type from the swallow** | **Chosen, with a review flag.** `except SubstrateInstallError: raise` before `except Exception` in both loops (`boot.py:879-882`, `:467-473`); the plugin wraps its construction failure in it. Choosing storage is a boot decision with no safe default; observing is not. Two `src/` files plus one plugin file, and what an `APP_READY` hook means for every other plugin is unchanged. |

## 7. Design skills consulted

- [x] **`python-design-patterns`** (in-repo, `.claude/skills/python-design-patterns`) — KISS,
      separation of concerns, single responsibility, God-class decomposition, composition over
      inheritance. Used for the `_fenced_state` vs five-call-sites decision.
- [x] **`design-patterns-refactoring`** (user-level, this machine) — carries the
      Refactoring.Guru catalogue. Loaded and **verified to contain the names used**, per
      `.spec/CONSTITUTION.md` → *Retrieval Before Assertion* ("a description of a thing is not
      the thing"):

      Shotgun Surgery 5 files · Middle Man 8 · Divergent Change 5 · Primitive Obsession 5 ·
      Speculative Generality 5 · Dead Code 3 · Long Method 10 · **Temporal Coupling 0**

      "Temporal coupling" is **not** in this catalogue, so it is not used as a catalogue name
      anywhere above; the ordering problem at `scope_store.py:512` is described plainly instead.
- [x] `.spec/CONSTITUTION.md` → *Forbidden Patterns* checked against the AFTER: no
      peer-layer cross-import, no global mutable state, no ABC port, no implicit `Callable`
      port, no `_cli` → internal import, no hard-coded config path, no `DeprecationWarning`
      shim, no new god object.
- [ ] No other design/refactoring/architecture skill appears in this session's listing.

## 8. Files expected to change

Every size below was measured in this worktree at authoring time (`wc -l`). **Two numbers in
the previous draft of this table were wrong** and are corrected here.

| File | Size | Change | AC |
|---|---|---|---|
| `src/functualize/_primitives/scope_store.py` | 923 | `expect=` + bounded retry in `_mutate` (:235-266); new `_fenced_state`; route the five `*_state` methods through it; delete the dead `"state": {}` (:102) and its docstring (:92-101) | 1, 2, 3 |
| `src/functualize/_primitives/scope_state_store.py` | 235 | `expect=` on the `_mutate` write (:152) and the `batch` exit write (:169). **No generations** — `grep -c generation` stays 0 | 3 |
| `src/functualize/_types/protocols.py` | **958** (was recorded as 930) | `Revision = NewType("Revision", str)`; `Stored.revision: Revision` (:784); fix "Three members" → "Six" (:790) | 5 |
| `src/functualize/_primitives/substrate.py` | 273 | `_revision_of` returns `Revision` (:60-67); `Stored(...)` at :132 | 5 |
| `src/functualize/_app/boot.py` | **2079** (was recorded as 2016) | `except SubstrateInstallError: raise` in both APP_READY loops (:879-882, :467-473) | 4 |
| `src/functualize/_types/errors.py` | — | new `SubstrateInstallError` | 4 |
| `src/functualize/_cli/tui/shell_mode.py` | 331 | thread `app` from :243 into `_record_history_quietly`; `ShellHistoryStore(app.substrate)` at :312 | 6 |
| `plugins/substrates/functualize-substrate-sqlite/src/functualize_substrate_sqlite/_plugin.py` | 147 | wrap the construction failure at :86 in `SubstrateInstallError` | 4 |
| `plugins/substrates/functualize-substrate-sqlite/src/functualize_substrate_sqlite/substrate.py` | 225 | `Stored(revision=...)` at :112 stringifies the row version | 5 |
| `plugins/domains/functualize-tasks-local/src/functualize_tasks_local/_provider.py` | — | `_read` return annotation `int \| None` → `Revision \| None` (:106) | 5 |
| `src/functualize/_primitives/lease.py` | 305 | **no change.** It is correct; the bug was that callers bypassed it | — |

## Surviving smells

Every entry here is a smell **absent from** `.spec/CONSTITUTION.md` → *Forbidden Patterns*, so
each is eligible to be accepted. Nothing on that list survives in the AFTER.

1. **Shotgun surgery — the fence is enforced per store, not at one commit point.**
   Where: `scope_store.py:249` (`_guarded`, for `scopes.json`) and the new `_fenced_state`
   (for `scope-state/<id>`). Why accepted: the two documents have no shared write point to put
   one check on — creating one is `RuntimeTransaction`, which is **FUN-17's** deliverable. This
   wave repairs; it does not redesign. Both points sit in one file, so the rule is still
   readable in one place. *Carried forward from the research, confirmed against the code.*
   Needs maintainer review: **no**.

2. **God object — `scope_store.py` is 923 LOC against the Constitution's ~500 threshold.**
   Pre-existing, not introduced, and this plan adds one method (~15 lines) while deleting a
   dead field. Why accepted: decomposing it is a redesign, and the natural decomposition is
   precisely the store/transaction split FUN-17 performs. Recorded so it is not mistaken for
   unexamined. Needs maintainer review: **no** — but it is the one item that would make a
   reviewer ask "why is this not a blocker", so: the Forbidden-Patterns entry reads "if a class
   exceeds ~500 LOC, decompose it", and the AFTER does not grow it past any new threshold.

3. **Primitive obsession survives one level down.** `Revision = NewType("Revision", str)`
   forbids arithmetic at type-check time but is still a string at runtime; a caller that casts
   can still misuse it. Why accepted: a full value object costs an allocation on every
   document read for a token that is only ever compared, and `NewType` is what makes `mypy`
   catch AC-5's actual failure mode. Needs maintainer review: **no**.

4. **Speculative generality — `lock(*keys)` stays variadic with 13 arity-1 call sites.**
   Why accepted: not this ticket's defect, and FUN-17 is the wave that either uses the
   variadicity or removes it. Deleting it here would remove the mechanism the next wave needs.
   Needs maintainer review: **no**.

### Needs maintainer review — put these by name, answer before Execute

5. ⚠ **The B2 fix settles a plugin-contract shape that FUN-17 will revisit.** Exempting
   `SubstrateInstallError` from the `APP_READY` swallow (§6) keeps `APP_READY` as the install
   point, which the three shipped docs describe. The research's §4 instead moves installation
   into a raising boot step, deleting the problem rather than exempting from it — but that
   carries `RuntimeStoreFactory`/`StoreProfile` with it and is out of scope here. **Question
   for the maintainer: accept the exemption as the FUN-24 repair, knowing FUN-17 may replace
   the whole seam?** The alternative is to declare AC-4 unsatisfiable inside this wave's
   scope and move it to FUN-17.

6. ⚠ **Fencing `rc.state` adds one `scopes.json` read per state write, contradicting a
   documented property of the path it is on.** `scope_store.py:472` states it outright:
   `_state_store` is *"This scope's state file. **Cheap: no read of `scopes.json`.**"* The
   `_fenced_state` seam must read that document for the current lease, so the docstring
   becomes false the moment the fence lands. That is a design statement being reversed, not
   a comment going stale — `.spec/CONSTITUTION.md` → *Transitional Changes* requires the
   reversal be disclosed at the site, and `plan.md` requires it be reasoned about here.
   `scopes.json` is also the document this repo has already measured as a cost:
   `_cli/builtins.py:920` records "2,188 records costing 58 ms per state write,
   and nobody noticed until an external review measured the file". A per-write lease read on a
   large `scopes.json` is the same shape of regression. Mitigation in the plan: `state_batch`
   checks once at entry and once at the exit write rather than per `set`. **Question for the
   maintainer: is a per-write lease read acceptable, or should the fence be armed once per
   walk and re-validated only at batch boundaries?** The second is cheaper and weaker — it
   reopens a window between the walk's claim and its next write. A third option, cheapest
   and narrowest: fence only the **five write paths** (`set_state`, `delete_state`,
   `clear_state`, `state_batch`, `discard_state`) and leave the two reads (`get_state`,
   `state_snapshot`) on the unfenced `_state_store`, which keeps the cheap-read property
   true for reads and is what `tasks.md` 2.1 specifies. That is the recommendation; the
   question that remains is whether a per-*write* lease read is acceptable.

**Nothing else survives.** Asked and answered, rather than skipped.
