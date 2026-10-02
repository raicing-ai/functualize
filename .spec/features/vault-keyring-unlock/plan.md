# Plan — vault-keyring-unlock

Spec: `spec.md` (confirmed 2026-10-02; **revisions R-1..R-3 below need re-confirmation**).
Tracked privately (story ← field report). Retrieval record: `research.md`.

Tools used, by absolute worktree path: zvec-grep (prose, Specify and Plan),
serena (`get_symbols_overview`, `find_referencing_symbols`; activated on the
worktree path, session `920cc4bf`), graphify (`get_neighbors`, shape only — its
`built_at_commit` is not in this worktree's history and its labels disagree with
HEAD (`build_remote_source` vs `build_vault_source`), so serena outranks it),
`rg` for every count, `uv run lint-imports` for the baseline (**7 kept, 0 broken**
before any change).

Design skills consulted: `python-design-patterns` (in-repo; KISS, SRP,
composition, Rule of Three) and `coding__design-patterns-refactoring` (user-level;
the Refactoring.Guru catalogue — smell names below are its names).

---

## 1. Architecture gate

### 1.1 BEFORE

Legend: `[P]` public package, `[I]` internal. `->` = imports/calls (arrow = dependency
direction). `||` = import-linter boundary.

```
 DELIVERY / PUBLIC                                   INTERNAL (peer + composition)
 ───────────────────────────────────────────────     ─────────────────────────────────────────────────
 [I] _cli/main.py   5x ConfigSources(dotenv=,        [I] _app/boot.py   (composition root)
        dotenv_path=cli_config.…)  <- DUPLICATED         build_vault_source()          ┐ both resolve the key
 [I] _cli/config.py  CliConfig                           _build_dormant_vault_source() ┘ EAGERLY AT BOOT
 [I] _cli/data/func_settings.py  FUNC_SETTINGS              │ resolve_vault_key(project_id)
 [I] _cli/vault_cmd.py  (put/remove: isatty() x2)           ▼
        │ public API only ||                           [I] _config/vault_keys.py
        ▼                                                    Env (interactive False) · Keychain (interactive True)
 [P] app/vault.py   _resolve_key -> resolve_vault_key        get_key: `except Exception: return None`   (3 states -> None)
 [P] app/utils.py   vault_status  (allow_interactive=False)  resolve_vault_key(…, allow_interactive: bool|None)
                    vault_sync    -> resolve_vault_key           └ isatty(stdin) and isatty(stdout)   <- THE GATE (l.307)
                                                                 -> KeyResolution | None
                                                       [I] _config/vault_source.py  VaultSource(path, encryption_key: bytes|None,
                                                                 key_provider_id: str)   <- key+id are a clump
                                                             get / has / keys / usable / opens / note_fallthrough
                                                       [I] _config/vault.py  SecretsVault(path, key_provider_id)
 Layers: _types, _primitives (foundation) < _events < peers {_discovery,_config,_engine,_plugins,_gate} ; _app = only composition root
 Crossings (all legal today): _app -> _config ; app -> _config ; _cli -> app (public only)
```

**Smells the BEFORE already carries** (Refactoring.Guru names):

| Smell | Where | Evidence |
|---|---|---|
| **Primitive Obsession** — `None`/`bool` standing in for a status | `KeychainKeyProvider.get_key` (`except Exception: return None`), `resolve_vault_key -> KeyResolution \| None`, `allow_interactive: bool \| None` | locked, absent, no-backend and not-stored are four states with one value; this is why the refusal text is false (the field report) |
| **Data Clumps** | `(encryption_key: bytes \| None, key_provider_id: str)` passed together through `VaultSource.__init__`, `SecretsVault.__init__`, `build_vault_source`, `_build_dormant_vault_source` | always travel as a pair |
| **Duplicate Code** | the key-unavailable message and its exception names (`no vault key is available`, `key_unavailable`, `VaultKeyUnavailableError`, `VaultKeySourceError`) in `_app/boot.py` (1 hit), `app/utils.py` (6), `app/vault.py` (12), `_cli/vault_cmd.py` (7), `_config/vault_source.py` (1) — 27 hits in 5 files, plus 8 in two test files (`rg`, run while authoring) | the ticket's core complaint is one wrong sentence that exists in several shapes; the hits are identifiers *and* prose, so the count is an upper bound on copies of the sentence |
| **Duplicate Code** + **Feature Envy** | `_cli/main.py` ×5: `ConfigSources(dotenv=cli_config.dotenv, dotenv_path=cli_config.dotenv_path)` (identical at 372, 602, 1280, 1404, 1773) | main.py reads `CliConfig`'s fields to build another object's arguments; adding a setting here is **Shotgun Surgery** (5 edits) |
| **Duplicate Code** | `build_vault_source` and `_build_dormant_vault_source` repeat "resolve → inert-or-construct `VaultSource`" | two builders, one idea |
| **Temporal Coupling** (not in the catalogue as a name; described plainly) | `VaultSource.note_fallthrough` tests `self.opens` *before* checking whether the value was declared remote | harmless while the key is a field; wrong once the key is lazy (it would resolve on every fall-through) |

### 1.2 AFTER (settled)

```
 DELIVERY / PUBLIC                                          INTERNAL
 ──────────────────────────────────────────────────         ─────────────────────────────────────────────────────────
 [I] _cli/main.py   5x -> cli_config.config_sources()        [I] _app/boot.py
 [I] _cli/config.py CliConfig.vault_keyring_timeout               ONE VaultKeyResolver per app (instance, not module state)
                    CliConfig.config_sources()  (NEW)             build_vault_source / _build_dormant_vault_source
 [I] _cli/data/func_settings.py  + vault.keyring_timeout         collapse to one lazy construction: VaultSource(path, key=resolver)
 [I] _cli/vault_cmd.py  + `unlock` ; status key_state            NOTHING resolves at boot
        │ public API only ||                                          │
        ▼                                                             ▼
 [P] app/config.py  ConfigSources.vault_keyring_timeout: str|None    [I] _config/vault_source.py
 [P] app/vault.py   _resolve_key(BOUNDED)                                VaultSource(path, key: VaultKeyResolver, …)
                    vault_inspect(SILENT) · vault_unlock(FOREGROUND)NEW  get(): stored? -> only then resolver.lookup()
 [P] app/utils.py   vault_status(SILENT) · vault_sync(BOUNDED)           has()/keys(): metadata only, no key
        │                                                                note_fallthrough(): annotation FIRST, then resolver
        └──────────── all call ───────────────────────────────▶ [I] _config/vault_key_resolver.py   (NEW — policy)
                                                                     KeyStatus · KeyAccess · KeyLookup
                                                                     VaultKeyResolver  (memo + Lock + deadline helper)
                                                                     resolve_vault_key()  (thin one-shot)
                                                                     describe_key_failure()  (the ONE message)
                                                                         │
                                                                         ▼
                                                              [I] _config/vault_keys.py   (providers only — sources)
                                                                     Env  ·  Keychain: interactive()=False, probe(),
                                                                     raises KeyringLockedError / KeyringUnavailableError
                                                              [I] _config/vault.py  + resolve_keyring_timeout(), + the two errors
 [I] _types/protocols.py  VaultKeyProvider (signatures unchanged), VaultKeyProbe (NEW optional) ; [I] _types/enums.py KeyAvailability
 [P] plugin/__init__.py   re-export VaultKeyProbe, KeyAvailability
```

What crosses a boundary, and why it is legal (checked against the 7 contracts):

- `_cli -> app.config.ConfigSources` — public, already imported by `main.py`. **The `[vault]` file setting travels as data in a public dataclass; `_config`/`_app` never import `_cli`.** This is the rejected-then-fixed point: reading `FuncSettingsStore` from `_app/boot.py` would invert the layers (`_app` is the kernel composition root; the Constitution forbids CLI runtime imports there), and `app/adapters/surface_gate.py`'s lazy read is a delivery adapter, which `_app` is not.
- `_app -> _config` (resolver, source) — existing edge.
- `app -> _config` (resolver) — existing edge.
- `_types -> nothing internal` — `VaultKeyProbe` and `KeyAvailability` live there; `plugin/` re-exports.
- Threading is stdlib; `keyring`/`secretstorage` are imported lazily inside methods, as today.

Contracts expected: *Peer layers independent* (kept — only `_config` files change in that layer),
*Internal never imports public* (kept — `_app`/`_config` import no `app/plugin/types`),
*_cli uses public API only* (kept), the other four untouched. Re-verified by `uv run lint-imports` in the gates of tasks 0.1 and 1.2 and again at the checkpoint (6.1).

### 1.3 Candidate AFTERs rejected, and what each would have introduced

| Candidate | Rejected because | Smell it would have introduced |
|---|---|---|
| Keep `encryption_key` **and** add `key_resolver=` to `VaultSource` (zero test churn) | two construction paths, one of which tests use and production never does | **Alternative Classes / Speculative Generality**; keeps the **Data Clump** |
| `VaultSource` takes `Callable[[], KeyLookup]` | Constitution: *implicit `Callable` conventions for ports* is forbidden | forbidden pattern → blocker |
| Memoise the outcome in a module-level dict | Constitution: *global mutable state / module-level singletons* | forbidden pattern → blocker |
| `_app/boot.py` reads `FuncSettingsStore` for the timeout | layer inversion `_app -> _cli`; `_cli` would also be dragged into every library-mode boot | **Inappropriate Intimacy** across layers |
| Add `vault_keyring_timeout=` to the 5 `ConfigSources(...)` sites by hand | 5 edits, and the repo already records "four doors disagreeing" as a pitfall (§23) | **Shotgun Surgery** |
| Strategy objects per `KeyAccess` mode | 3 modes differing by ~2 lines each; Rule of Three met in count but not in behaviour | **Speculative Generality** |
| Secret Service D-Bus directly for the deadline (`Unlock` + `Prompt.Completed` + `Dismiss`) | Linux-only, large surface; the daemon-thread guard is backend-agnostic (this is `gh`'s approach) | duplicated per-backend code (**Parallel Inheritance-like**) |
| Resolve on demand but a **second** wait per lookup | spec R8: N lookups × 30 s | (a defect, not a smell) |

---

## 2. Design decisions

**D1. How `VaultSource` receives a lazy key.** A concrete `VaultKeyResolver`
(same layer, not a port, so no Protocol and no `Callable`). Ctor becomes
`VaultSource(vault_path, *, key: VaultKeyResolver, providers=(), max_age=None)`;
`encryption_key` and `key_provider_id` are **removed** (clump dissolved).
Tests that want a fixed key use `VaultKeyResolver.fixed(key, provider_id="test")`.
`SecretsVault(path)` serves metadata; after a successful lookup it is replaced by
`SecretsVault(path, key_provider_id=lookup.provider_id)` (see surviving smell S-3).

`VaultSource` semantics after:

| Member | Before | After |
|---|---|---|
| `usable` | key present **and** file exists | file exists (metadata answerable) |
| `opens` | key present | resolves the key (BOUNDED) and reports FOUND; **only reached after the annotation check** |
| `get` | no key -> refuse-if-stored; else decrypt | file? -> **stored?** (clear-text names, no key) -> only then `lookup()`; not FOUND -> refuse via `describe_key_failure`; FOUND -> as before |
| `has` / `keys` | `False` / `set()` when no key | answer from clear-text metadata, **no key** (matches their own docstrings) |
| `note_fallthrough` | `if not self.opens: return` first | `_annotation_in(resolved)` first; then `opens`; no key -> one warning (the text boot used to print) |
| `_warn_if_stale` | after the key check | unchanged order is irrelevant: it needs only metadata, so it runs on the first *stored* read |

**D2. Where the deadline is enforced.** A daemon thread in
`_config/vault_key_resolver.py` (`_run_bounded(fn, seconds)`): start, `join(seconds)`,
return a timed-out sentinel if still alive. The blocked thread is abandoned and
dies with the process. Backend-agnostic; this is `gh`'s strategy. The Secret
Service API route is left as a later refinement if the live check (A11) shows a
lingering dialog is a real problem.

**D3. Where the memo lives.** On `VaultKeyResolver` instance fields
(`_outcome`, `_lock: threading.Lock`), created by `_app/boot.py` once per app. No
module global. Two threads asking at once serialise on the lock, so a locked
keyring costs ≤ one timeout total (spec R8, A6). Memoised: FOUND, and BOUNDED
failures. Not memoised: SILENT results, and FOREGROUND failures (the person is
there; let them retry).

**D4. `KeyAccess` modes.**

| Mode | Used by | Behaviour |
|---|---|---|
| `BOUNDED` (default) | run path, `vault put`, `vault sync` | env first; keyring with deadline; memoised |
| `FOREGROUND` | `vault unlock` | no deadline; failures not memoised |
| `SILENT` | `vault status`, `vault inspect` | `probe()`: `UNLOCKED` -> read (cannot prompt); `LOCKED` -> status `LOCKED` without reading; `UNKNOWN`/no probe -> status `UNKNOWN`, no read; never memoised |

**D5. Layering of `vault.keyring_timeout`.** `[vault] keyring_timeout` is a func
setting: registered in `FUNC_SETTINGS` + `_RECOGNIZED_SECTIONS/_KEYS`;
`resolve_cli_config` reads it into `CliConfig.vault_keyring_timeout`;
`CliConfig.config_sources()` puts it in `ConfigSources.vault_keyring_timeout`;
`_config.vault.resolve_keyring_timeout(configured)` applies
`$FUNCTUALIZE_VAULT_KEYRING_TIMEOUT` > configured > `30s`, exactly as
`resolve_max_age` does. One helper `app_keyring_timeout(app)` in `_config/vault.py`
holds the single `getattr(app._config_sources, …)` chain (so it is not copied into
five callers). Library-mode apps get env + default, or set the `ConfigSources`
field themselves.

**D6. Probe.** Optional `VaultKeyProbe` (Protocol, separate, like
`VaultKeyInitializer`). `KeychainKeyProvider.probe()` imports `secretstorage`
lazily, calls `dbus_init()` + `get_default_collection()` + `.is_locked()` under a
2 s bound, and returns `UNKNOWN` on any failure (no Secret Service, ImportError,
non-Linux). `keyring`'s own SecretService backend makes the identical
`is_locked()` call (read from the installed `keyring` 25.7.0 source), so the probe
asks the question the real read would ask, without the `unlock()` that follows it.

**D7. Typed outcomes from the keychain provider.** Mapped from the exceptions
`keyring` really raises (read from source): `KeyringLocked` -> `KeyringLockedError`
(LOCKED); `InitError`, `NoKeyringError`, `RuntimeError` from backend init ->
`KeyringUnavailableError` (NO_KEYRING); a `None` from a live backend -> NOT_STORED.
The previous blanket `except Exception: return None` is removed. Both errors are
`VaultError` subclasses in `_config/vault.py`.

**D8. The one message.** `describe_key_failure(lookup, *, qualified=None,
direct=None, timeout=None) -> str` in the resolver module returns the four
outcome texts of `spec.md` B3. Every site that wrote "no vault key" prose calls
it (T-sites below). That is the *Duplicate Code* smell removed, and the reason the
destructive-fix rule can be tested in one place.

**D9. `vault init` is unchanged.** It calls `provider.initialize_key` directly,
not `resolve_vault_key`, and runs only when a person asked for it. Out of scope.
`_non_interactive_first` (`app/vault.py:416`) becomes order-neutral for the two
shipped providers and stays for third-party ones — flagged in S-4.

---

## 3. Spec revisions found by the gate (confirmed by the maintainer 2026-10-02: R-1 = A, R-2 = A; R-3 is a consequence of R-2)

- **R-1. The `remote_first()` boot warning moves.** Today `_app/boot.py` prints
  *"remote_first() is active but no vault key is available…"* at boot. A boot that
  resolves nothing cannot print it. It is printed **once, at the first declared-remote
  value that falls through** — the first moment the key is needed. A `remote_first()`
  app whose values all come from env/file no longer warns at all.
- **R-2. `has()` / `keys()` stop needing the key.** They answer from clear-text
  metadata. Consequence: resolving a config *section* that contains a stored
  entry now **refuses** when that entry cannot be opened (ADR-023 §1), where before
  `keys()` returned empty and the entry was silently omitted from the section.
  A section with no stored entries is unaffected and never touches the keyring.
- **R-3. A miss is recorded even with no key.** `VaultSource.misses` previously
  skipped the append when the key was absent; a stored-names lookup makes the miss
  knowable without a key, so it is recorded. (Verify no consumer relies on the old
  behaviour — `rg "\.misses"` shows only `vault_source.py` reads it.)

Contract edits that follow (`contracts.md` updated): `KeyStatus.UNKNOWN` exists
(SILENT only); `resolve_vault_key` lives in `_config/vault_key_resolver.py`;
`KeyringLockedError` / `KeyringUnavailableError`.

---

## 4. Technical approach and files

Hit sets come from the queries in `research.md` and the commands run while
authoring `tasks.md`; the per-task file lists in `tasks.md` equal them.

Production call paths (reachability, one per behavior):

1. Pipe/agent run: `func report` -> `_cli/main.py` -> `FunctualizeApp` boot ->
   `_app/boot.py:_build_dormant_vault_source` -> `VaultSource.get` ->
   `VaultKeyResolver.lookup(BOUNDED)` -> `KeychainKeyProvider.get_key`.
2. Unlock: `func builtin vault unlock` -> `_cli/vault_cmd.py` -> `app/vault.py:vault_unlock`
   -> `VaultKeyResolver.lookup(FOREGROUND)`.
3. Status: `func builtin vault status` -> `app/utils.py:vault_status` ->
   `lookup(SILENT)` -> `KeychainKeyProvider.probe`.
4. Timeout: `.functualize.toml [vault]` -> `_cli/config.py` -> `CliConfig.config_sources()`
   -> `ConfigSources` -> `_app/boot.py` -> `app_keyring_timeout(app)` -> resolver.

## 5. Risks

| # | Risk | Mitigation |
|---|---|---|
| K-1 | A deadline abandons a thread blocked inside a D-Bus call; the gnome-keyring dialog may outlive the CLI's refusal | daemon thread dies with the process, and the D-Bus connection closing normally cancels the prompt; **checked live in A11** (observe the dialog after exit) |
| K-2 | `builtin parallel` (separate processes) can raise N dialogs on a locked keyring | out of scope per spec; live-test two parallel jobs; if bad, a follow-up ticket |
| K-3 | `keys()`/`has()` semantic change (R-2) alters section resolution for stored-but-unopenable entries | stated in the spec revision; covered by a test that a section with a stored entry refuses and a section without one never calls the backend |
| K-4 | 4 test files construct `VaultSource(encryption_key=…)` | one mechanical task (`VaultKeyResolver.fixed`), run before the rest of the suite |
| K-5 | `secretstorage` import cost / absence | lazy import inside `probe()`; ImportError -> `UNKNOWN` |
| K-6 | A fresh `VaultKeyResolver` per call site for `put`/`sync`/`status` loses the memo | they are single-shot commands; memo matters only for the long-lived run path, which has one resolver |
| K-7 | Settings reach only `func`-hosted runs (`CliConfig`), not a library-mode `FunctualizeApp` | documented in `docs/guides/configuration.md`; env var works everywhere |

---

## Surviving smells

Nothing on the Constitution's *Forbidden Patterns* list remains (no module-level
singleton, no `Callable` port, no ABC port, no `_cli -> internals`, no peer-layer
cross-import, no kernel-layer CLI import, no class near 500 LOC: the new resolver
module is ~200 lines; `vault_source.py` stays under 400).

| ID | Smell | Where | Why accepted | Review? |
|---|---|---|---|---|
| S-1 | **Data Clumps** (mild) | `ConfigSources.vault_max_age` + `vault_keyring_timeout` | two vault knobs; Rule of Three says wait. Trigger: a third vault knob -> Introduce Parameter Object `VaultSettings` | no (FYI) |
| S-2 | **Inappropriate Intimacy** (localised) | `app_keyring_timeout(app)` reads `app._config_sources` (private attribute) | the same pattern `vault_status` and `build_vault_source` already use for `vault_max_age`; collapsing it to one function *reduces* it from N copies to 1 | no |
| S-3 | **Temporal Coupling** | `VaultSource` replaces its `SecretsVault` once, after the first successful lookup, to bind `key_provider_id` | alternative: add `key_provider_id=` as a per-call argument on `SecretsVault.get/put` (a wide edit: `rg -c "encryption_key=|key_provider_id="` returns 42 in `test_vault_store.py` alone). The rebuild is local and `SecretsVault` is stateless between calls | reviewed 2026-10-02: **rebuild accepted**. Measured: `SecretsVault(...)` is two attribute assignments, 0.40 µs, no I/O; a comment at the swap site says why |
| S-4 | **Speculative Generality** (small) | `_non_interactive_first` (`app/vault.py:416`) is order-neutral for the two shipped providers once the keychain is `interactive() == False` | still correct for third-party providers; deleting it is a public-behavior change for providers that return `True` | reviewed 2026-10-02: **keep accepted** |
| S-5 | **Switch Statements** (mild) | `VaultKeyResolver.lookup` branches on `KeyAccess` (3 modes) | ~2 differing lines per mode; Strategy classes would cost more than they save (Rule of Three met in count, not in behavior) | no |
| S-6 | **Middle Man** | `app/vault.py:vault_unlock` / `_resolve_key` forward to the resolver | required by the `_cli uses public API only` contract: the CLI cannot call `_config`, so a thin public function is the legal path (same as every sibling in that file) | no |

---

## Alignment

Preflight, run 2026-10-02 against the private tracker and knowledge base.

**Areas:** `config` (vault, key resolution), `engine` (`_app/boot.py`), `cli`
(`vault_cmd`, settings), `docs`.

**Constraints honored**
- ADR-023 §1 — a stored entry that cannot be opened refuses the run: kept, and now
  also applied to section resolution (R-2).
- ADR-023 §3 — `remove`/`clear` need no key: kept; the refusal merely stops
  recommending them where the key may still exist.
- ADR-023 §4 — one key per user, `functualize-vault` / `vault-key`: untouched.
- ADR-016 §6 — sync explicit, staleness warns and still runs: kept (the warning
  now fires on the first stored read).
- Constitution *Forbidden Patterns* and *Quality Gates* — checked above.
- `keep-behavior` issues: none exist in the private tracker.
- Decision records labelled `decision` + `area-config`: none exist; the other
  decision pages read by title concern an unrelated design review and do not
  bind this area.

**Claims absorbed:** the field report (Accepted). **Linked, not absorbed:** the agent-routes report (still
`Reported`; same root cause for the agent routes; triage it after merge).
**Implementing issue:** the story.

**Open items in `area-config` checked in code (labels are hints):** one item
(`vault put` group paths) touches `app/vault.py` `resolve_canonical_path` —
same file as task 2.3 (`app/vault.py`), different function, textual merge risk only.
others (env vs vault ordering; the `builtin env` source label;
two more, one a *win*, `Reported` not `Accepted`): no symbol overlap
(`rg` for `resolve_canonical_path`, `source_type`, `_resolve_key`).

**Conflict.** This feature **contradicts ADR-016 §5**: *"Ordering is part of the
contract: non-interactive providers first, and interactive ones only when no key
was found and a TTY exists."* The maintainer decided on 2026-10-02 to change it
(recorded on the field report). A **decision record** (private knowledge base,
from its decision template, labels `decision` +
`area-config`, status Proposed) supersedes the clause, and ADR-016 gets an
"Amended by" note in ADR-023's style. The ADR's *reason* — an unattended run must
not hang on a prompt — is **kept**: the bounded wait is its replacement mechanism.


---

# Addendum 1 — plan changes after the live findings (2026-10-02)

Evidence: `research.md` R9-R12. Behavior: `spec.md` → Addendum 1. This addendum
**supersedes** D2 (deadline) and the K-1 mitigation above; D1, D3, D5-D9 stand.
Skills consulted again: `python-design-patterns`, `coding__design-patterns-refactoring`.

## 1. AFTER' — the keyring layer behind a platform-neutral port

```
 [P] app/vault.py     vault_key_state()  vault_unlock()  _resolve_key()   <- public API (the only door for _cli)
 [P] app/utils.py     vault_status()  -> uses vault_key_state()
        ▲ public API only ||
 [I] _cli/vault_cmd.py   `unlock` UX (two-signal policy)        [I] _cli/tui/{bar_items,dynamic_footer_widget}.py
                                                                      status item, polled from a THREAD WORKER
 ───────────────────────────────────────────────────────────────────────────────────────────────────────
 [I] _config/vault_key_resolver.py   VaultKeyResolver: memo + lock; BOUNDED/SILENT -> read_silent() (no prompt, no wait)
        │                                            FOREGROUND -> unlock()      _run_bounded = hung-backend guard only
        ▼
 [I] _config/vault_keys.py   KeychainKeyProvider (VaultKeyProvider + VaultKeyProbe + VaultKeyUnlocker)
        │ delegates to
        ▼
 [I] _config/vault_keyring.py  select_adapter(platform, backend)  -- lazy import, allowlist, fail-safe --
        ├── vault_keyring_secretservice.py  (Linux; secretstorage; never unlock() in read_silent)
        ├── vault_keyring_macos.py          (darwin; ctypes Security; interaction disabled; -25308 -> LOCKED)
        ├── vault_keyring_windows.py        (win32; CredRead; no lock model)
        └── vault_keyring_generic.py        (anything else; state UNKNOWN; read_silent -> UNVERIFIED)
 [I] _types/protocols.py   VaultKeyProvider (get_key never prompts), VaultKeyProbe, VaultKeyUnlocker (NEW)
```

Boundaries and direction are unchanged from the first AFTER: `_cli -> app` (public), `app -> _config`,
`_app -> _config`; the adapters live in `_config` and import nothing above it; platform
libraries (`secretstorage`, `jeepney`, `ctypes` Security, `win32ctypes`) are imported lazily inside
their own adapter only. Re-verify with `uv run lint-imports` (7 kept) and the per-platform mypy runs.

## 2. Decisions (new or changed)

- **D2' (replaces D2).** The daemon-thread deadline no longer implements "wait for a
  prompt". On the keyring family it is a guard against a hung backend. A deadline must
  never be the mechanism by which an active unlock prompt is abandoned (R9).
- **D10. One port, four adapters.** The keyring layer is an internal Protocol with three
  operations (`read_silent`, `state`, `unlock`); `KeychainKeyProvider` is a thin delegate.
  This is the "abstraction that hides the implementation" and keeps platform APIs out of
  every caller. It also removes the single direct `keyring.get_password` read
  (`vault_keys.py:254`), which was the unsafe call.
- **D11. Linux adapter speaks the Secret Service protocol, not gnome-keyring.** It serves
  KWallet 6 and KeePassXC too. The "prompt helper never appeared" watcher inside
  `unlock()` is gnome-keyring-specific and optional; its output is neutral.
- **D12. macOS adapter** forces "interaction not allowed" around reads (unverified; tier-1/2
  CI and the manual tier decide). **D13. Windows adapter** has no lock model.
- **D14. Allowlist, fail-safe.** A backend not on the allowlist is not read by a run
  (`UNVERIFIED`), because silence cannot be proven; the user gets the env var or `vault unlock`.
- **D15. `vault_key_state`** is the single status function; the TUI polls it from a thread
  worker; `--help` is untouched (maintainer decision). A short-TTL cache lives on the
  resolver instance (no module global).
- **D16. Verification tiers.** (1) contract suite with fakes on every OS; (2) real-OS smoke
  on macOS/Windows/Linux runners, non-required at first; (2b) a "unlocked elsewhere" step
  only where a no-dialog unlock exists, as a prove-or-drop spike (R12); (3) the dialog
  itself is manual (live check v2) plus field reports. No mock prompter, no screen automation.
- **D17. Sandbox harness.** The private-bus scripts used to reproduce the crash ship under
  `.spec/features/vault-keyring-unlock/sandbox/` (not shipped with the package) and run only
  on a private session.

## 3. Candidates rejected in this round

| Candidate | Rejected because | Smell it would have introduced |
|---|---|---|
| Keep design A and make `Dismiss` the clean cancel | `Dismiss` is itself a crash trigger on the real daemon (R9) | — (unsafe, not a smell) |
| Detect a wedged daemon in every run and warn | adds a D-Bus probe to every run for a state that only interrupted prompts create; with no prompts from runs the state no longer arises | **Speculative Generality** |
| One class with `if sys.platform` branches | three platforms in one module defeats lazy import and per-platform typing | **Large Class**, **Switch Statements** |
| Shell out to `secret-tool`/`security`/`cmdkey` | a new process per read, parsing text, extra binaries | **Primitive Obsession** at the boundary |
| A mock prompter to auto-answer dialogs in CI | brittle, and it exercises the crash path | — |

## 4. Smells — status after the addendum

Still accepted from the first plan: S-1 Data Clumps (`vault_max_age` + `vault_keyring_timeout`),
S-2 Inappropriate Intimacy (`app_keyring_timeout` reading `app._config_sources`), S-3 Temporal
Coupling (rebuilding `SecretsVault`), S-4 Speculative Generality (`_non_interactive_first`), S-6
Middle Man (public wrappers).

- **S-5 (Switch Statements on `KeyAccess`)** shrinks: BOUNDED and SILENT now differ little. R4.1
  collapses them if they become identical.
- **S-7 — Switch Statements (mild)**: `select_adapter` chooses by platform/backend. Accepted: a
  short ordered list of (predicate, adapter) beats a Strategy registry for four entries.
  *Needs maintainer review? no.*
- **S-8 — Duplicate Code risk across adapters** is contained by the shared contract suite
  (R1.2), which every adapter must pass. *No review.*
- No Forbidden Pattern is introduced: no module-level mutable state (the cache is instance
  state), no `Callable` ports, no ABC ports, no `_cli -> internals`, no peer-layer imports.

## 5. Risks (updated)

| # | Risk | Status / mitigation |
|---|---|---|
| K-1 | A client leaving a prompt crashes the daemon | **Evidenced** (R9). Runs never create a prompt; `vault unlock` never cancels from the client and holds on the first interrupt. A user can still kill `vault unlock` with SIGKILL or a second Ctrl-C: documented |
| K-2 | Parallel runs on a locked keyring | Resolved by design: each refuses at once, no dialogs |
| K-8 | macOS/Windows adapters are not verified on real systems | Stated support levels; real-OS CI smoke (R7.1); manual checklist; field reports |
| K-9 | The tier-2 headless unlock may not work (R12) | prove-or-drop spike with its own gate; the docs say what each platform is verified at |
| K-10 | `vault unlock` ignoring the first Ctrl-C may read as a hang | explicit message on the first signal; second Ctrl-C exits |
| K-11 | TUI polling cost | ~250 ms cap, ~10 s interval, thread worker; hidden when there is no vault |
| K-12 | The maintainer's real keyring daemon could be destabilised by tests | the suite fixture fences it; CI uses private sessions; R8.2 runs only the safe scenarios on the real session |

## 6. Alignment (changes)

- **The decision record** is updated to the new decision (it is still Proposed): the
  mechanism changes from "bounded wait" to "no prompt from a run"; the reason stays.
- **The agent-routes report** is now served directly: unlock once, then agent runs read silently.
- **Per-key fresh fetch** (tracked separately) unchanged. **ADR-016 §5** remains contradicted deliberately; ADR-023 §1/§4 untouched.
- The maintainer's decisions of 2026-10-02 are recorded: switch to this design; follow the
  CI tiering; the state is shown in the TUI and `vault status` only, `--help` untouched.
