# Tasks — vault-keyring-unlock

Jira: FOSS-88. Plan: `plan.md` (decisions D1–D9, smells S-1..S-6). Spec: `spec.md` A1–A12a.

Conventions
- **[F]** = files the task may touch = the hit set of the query named in the task.
- **Gate** = the command that decides `[x]`. Gates marked *(run at authoring)* were
  executed while writing this file and the count is recorded.
- Pytest gates name files; none may run the whole suite in one call (test-tiers:
  600 s tool cap). The suite runs by tier at the checkpoint.
- Wave gates run only the files a wave owns. Tests that belong to a *later* task
  (for example the TTY-rule cases in `tests/cli/test_vault_commands.py`, rewritten
  in 3.2) are not expected green until that task lands; the whole suite is run, by
  tier, at wave 6. This is disclosed here rather than discovered there.
- A task that intentionally leaves a non-final state marks the site
  `# TRANSITIONAL(<task id>): …` and says so here. There are exactly two such
  states, both closed by task 4.1: the temporary `encryption_key=` / `key_provider_id=`
  kwargs on `VaultSource` (open 2.1 -> closed 4.1) and the old `resolve_vault_key` /
  `KeyResolution` in `vault_keys.py` (open until 4.1).
- `uv sync --all-extras` first (a missing extra fakes ~86 failures).

---

## Wave 0 — foundations (disjoint)

- [x] **0.1 — Probe protocol and the redefined `interactive()`**
  - [F] `src/functualize/_types/enums.py`, `src/functualize/_types/protocols.py`,
    `src/functualize/plugin/__init__.py`, `tests/plugin/test_vault_key_provider.py`
    (hit set: `rg -l "VaultKeyProvider" src/functualize/_types src/functualize/plugin tests/plugin`)
  - Add `KeyAvailability`; add `VaultKeyProbe(VaultKeyProvider, Protocol)` with
    `probe()`; re-export both from `functualize.plugin`; rewrite the
    `interactive()` docstring and the class docstring's "Resolution order" paragraph
    to the new meaning ("needs a person at a terminal"; a provider that merely may
    block returns False and is bounded by the resolver).
  - Gate: `uv run pytest tests/plugin/test_vault_key_provider.py -q` green;
    `uv run python -c "from functualize.plugin import VaultKeyProbe, KeyAvailability"`;
    `uv run lint-imports` -> 7 kept; `rg -n "never consulted on an unattended run" src/functualize/_types/protocols.py` -> 0 hits
    (currently 1, *run at authoring*).
  - Spec: B2, contracts §2. Call path: consumed by 1.1/1.2.

- [x] **0.2 — Timeout resolution, typed keyring errors, the `ConfigSources` field**
  - [F] `src/functualize/_config/vault.py`, `src/functualize/app/config.py`,
    `tests/config/test_vault_keyring_timeout.py` (new)
  - In `_config/vault.py`: `DEFAULT_KEYRING_TIMEOUT`, `ENV_KEYRING_TIMEOUT`,
    `KeyringLockedError`, `KeyringUnavailableError`, `resolve_keyring_timeout`,
    `app_keyring_timeout`. In `app/config.py`: `ConfigSources.vault_keyring_timeout`
    (documented beside `vault_max_age`; **do not import `_config.vault` there** —
    that docstring's cold-boot rule applies).
  - Gate: new test covers env > field > default, `"30s"`, `"2m"`, bare `"30"`
    refused-with-warning, `""` , `"0s"` refused, and `app_keyring_timeout(None)`;
    `uv run pytest tests/config/test_vault_keyring_timeout.py tests/config/test_vault_staleness.py -q`
    green (staleness test asserts the `app/config.py` default duplication — still true);
    `uv run mypy src/functualize/_config/vault.py src/functualize/app/config.py`.
  - Spec: B2, A12a. Call path: `app_keyring_timeout` is called by 3.1, 2.3, 2.4.

## Wave 1 — providers and the resolver (disjoint; additive, old API kept)

- [x] **1.1 — Providers: not-TTY-gated keychain, typed errors, probe**
  - [F] `src/functualize/_config/vault_keys.py`, `tests/config/test_vault_keys.py`
    (hit set: *run at authoring* `rg -l "KeychainKeyProvider|EnvKeyProvider|default_providers" src tests` ->
    `_config/vault_keys.py`, `tests/config/test_vault_keys.py` among 6 files; the other four are 2.3, 3.2, 0.1 and `_types/protocols.py`)
  - `KeychainKeyProvider.interactive()` -> `False`. `get_key` stops swallowing:
    `keyring.errors.KeyringLocked` -> `KeyringLockedError`; `InitError`,
    `NoKeyringError`, backend-init `RuntimeError` -> `KeyringUnavailableError`;
    a live backend returning `None` -> `None`. Add `probe()` (D6) implementing
    `VaultKeyProbe`. **Do not remove** the old `resolve_vault_key`,
    `KeyResolution`, `allow_interactive` yet (`# TRANSITIONAL(4.1)`). Update the
    module docstring's "Resolution order is part of the contract" section.
  - Tests: fake `keyring` backend raising each exception -> typed error; `probe()`
    with a patched `secretstorage` (locked / unlocked / ImportError / DBus error ->
    LOCKED/UNLOCKED/UNKNOWN/UNKNOWN); tests that assert the keychain is skipped off a
    TTY are **rewritten** to the new rule, not deleted silently.
  - Gate: `uv run pytest tests/config/test_vault_keys.py -q` green;
    `rg -c "except Exception" src/functualize/_config/vault_keys.py` -> 2
    (currently 3, *run at authoring*: lines 194 `is_available`, 211 `get_key`, 251
    `initialize_key`; only the one in `get_key` goes).
    **Executed 2026-10-02: count is 3, not 2 — disclosed deviation, not a silent
    weakening.** The `get_key` blanket swallow (the one the gate targets) is
    gone; `probe()` added its own broad catch because contracts §2 requires
    "never raises" against arbitrary D-Bus failures, and without the catch a
    bus-less machine would print a thread excepthook traceback from
    `vault status`. The three remaining sites: `is_available` (capability
    probe), `probe()` (never-raises contract), `initialize_key` (write-path
    refusal). All noqa'd with their reason.
  - Spec: B2, B3, B5. Call path: 1.2 `VaultKeyResolver.lookup` -> `provider.get_key`.

- [x] **1.2 — The resolver, the deadline, the memo, the one message**
  - [F] `src/functualize/_config/vault_key_resolver.py` (new),
    `tests/config/test_vault_key_resolver.py` (new)
  - Implement `schema.md` §`vault_key_resolver`: `KeyAccess`, `KeyStatus`,
    `KeyLookup` (no key in `repr`), `VaultKeyResolver` (instance memo + `Lock`),
    `_run_bounded` (daemon thread), `resolve_vault_key` (new signature, one-shot),
    `describe_key_failure`. No module-level state.
  - Tests (spec A3–A6, A8, A10): env set -> providers other than env never called;
    blocking provider -> LOCKED after `timeout` (use 0.3 s); 10 lookups -> 1 provider
    call; two threads -> 1 call; SILENT with probe LOCKED -> no `get_key` call;
    SILENT with no probe -> UNKNOWN; FOREGROUND failure not memoised; bad hex
    propagates `VaultError`; `describe_key_failure` for each status contains the
    required next steps and — for LOCKED / NO_KEYRING — contains none of
    `vault remove`, `vault clear`, and (direct=True) `vault sync`; `repr(KeyLookup)`
    does not contain the key bytes; importing the module does not import `keyring`
    or `secretstorage` (`sys.modules` check in a subprocess).
  - Gate: `uv run pytest tests/config/test_vault_key_resolver.py -q` green;
    `uv run lint-imports` 7 kept; `uv run mypy src/functualize/_config/vault_key_resolver.py`;
    `rg -n "^_[a-z_]+\s*[:=]\s*(\{|\[|dict\(|list\()" src/functualize/_config/vault_key_resolver.py` -> 0
    (no module-level mutable).
    **Executed 2026-10-02: the scan as authored matches `__all__ = [` (the regex
    `_[a-z_]+` spans every module's `__all__` in this repository), so it reports
    1 hit on any file. Disclosed correction — the check was run dunder-excluded
    (`^_[a-z][a-z_]*…`) and returns 0 hits: no module-level mutable state
    exists besides the repo-conventional `__all__` list.**
  - Spec: B1–B3, B5, A3–A6, A8, A10. Call path: 2.1, 2.3, 2.4, 3.1.

## Wave 2 — consumers, part 1 (disjoint; depend on waves 0–1)

- [ ] **2.1 — `VaultSource` takes a lazy key**
  - [F] `src/functualize/_config/vault_source.py`,
    `tests/config/test_vault_source_lazy.py` (new)
  - Add `key: VaultKeyResolver` and implement the D1 table: stored-names check first;
    `has`/`keys` metadata-only; `usable` = file exists; `opens` resolves BOUNDED;
    `note_fallthrough` annotation-first, then `opens`, one warning when no key;
    `SecretsVault` replaced once with the provider id after the first FOUND;
    refusal text from `describe_key_failure` with `direct` taken from the entry's
    origin (the `_entries()` row). Put a comment at the `SecretsVault` swap saying why
    it is rebuilt (provider id is only known after the lookup; construction is two
    assignments, no I/O — plan S-3, reviewed). Keep `encryption_key=` / `key_provider_id=`
    accepted **temporarily** (`# TRANSITIONAL(4.1)`), mutually exclusive with `key=`.
  - Tests (spec A2, R-2, R-3): a source over a vault file whose resolver raises on
    any call: `get` of an absent key returns None and the resolver is never called;
    `keys("section")` with no stored entries -> no call; with a stored unopenable
    entry -> `get` refuses; `has` agrees with `get`; `note_fallthrough` of an
    un-annotated value never calls the resolver; with an annotation and no key it
    warns exactly once; a miss is recorded with no key.
  - Gate: `uv run pytest tests/config/test_vault_source_lazy.py -q` green;
    `uv run pytest tests/config/test_vault_miss.py tests/config/test_vault_staleness.py -q`
    still green (they use the old kwargs until 3.4); `wc -l src/functualize/_config/vault_source.py` < 500 (currently 3xx, *measure at execution*).
  - Spec: B1, B3, R-1..R-3. Call path: 3.1 (boot builds it), chain -> `VaultSource.get`.

- [ ] **2.2 — The func setting**
  - [F] `src/functualize/_cli/data/func_settings.py`, `src/functualize/_cli/config.py`,
    `tests/cli/test_func_settings_store.py`, `tests/cli/test_cli_config_vault.py` (new)
    (hit set: the drift-catcher is `tests/cli/test_func_settings_store.py::TestCatalog`;
    `_RECOGNIZED_SECTIONS` / `_RECOGNIZED_KEYS` are in `_cli/config.py:26,34`)
  - Register `vault.keyring_timeout` (D5); add `"vault"` to `_RECOGNIZED_SECTIONS`
    and its key to `_RECOGNIZED_KEYS`; `resolve_cli_config` reads it through
    `_get_value(..., section="vault")` into `CliConfig.vault_keyring_timeout`;
    add `CliConfig.config_sources()` (returns `ConfigSources(dotenv=…, dotenv_path=…,
    vault_keyring_timeout=…)`).
  - Gate: `uv run pytest tests/cli/test_func_settings_store.py tests/cli/test_cli_config_vault.py -q` green
    (new test: project `.functualize.toml` `[vault] keyring_timeout = "5s"` -> field
    `"5s"`; global file; nearest project wins; env `FUNCTUALIZE_VAULT_KEYRING_TIMEOUT`
    wins; unknown key in `[vault]` ignored with the existing warn path).
  - Spec: B2, A12a. Call path: 3.3 -> `CliConfig.config_sources()`.

- [ ] **2.3 — The public vault API**
  - [F] `src/functualize/app/vault.py`, `tests/app/test_vault_seam.py`
    (hit set: `rg -l "resolve_vault_key|KeyResolution|allow_interactive" src/functualize/app` -> `app/vault.py`, `app/utils.py`; `tests/app/test_vault_seam.py` has 4 hits)
  - `_resolve_key` -> BOUNDED `VaultKeyResolver.lookup`, timeout from
    `app_keyring_timeout(app)` (add an `app` parameter where the call chain has one);
    `VaultKeySourceError` reasons `key_locked` / `no_keyring` / `key_not_stored`
    (keep `key_unavailable` mapped to `no_keyring`, per contracts §5); `vault_inspect`
    -> SILENT (readability `KEY_UNAVAILABLE` unchanged for a locked/unknown key);
    new `vault_unlock(app=None, cwd=None) -> KeyLookup` (FOREGROUND, no deadline);
    the "no key" prose replaced by `describe_key_failure`. `vault_init` and
    `_non_interactive_first` untouched (S-4).
  - Gate: `uv run pytest tests/app/test_vault_seam.py -q` green;
    `rg -n "no vault key is available|key_unavailable" src/functualize/app/vault.py` -> only the one compatibility mapping
    (currently 12 hits in the file, *run at authoring*; record the new count).
  - Spec: B3, B4, B5. Call path: 3.2 (`_cli/vault_cmd.py`) -> `app.vault.vault_unlock/_resolve_key`.

- [ ] **2.4 — Status and sync**
  - [F] `src/functualize/app/utils.py`, `tests/app/test_vault_status_key_state.py` (new)
    (hit set: `rg -n "resolve_vault_key|allow_interactive" src/functualize/app/utils.py` -> lines 1835, 1837 (status), 1977 (sync); `rg -c` for the message = 6)
  - `vault_status` -> SILENT lookup; `VaultStatusReport.key_state`
    (`available`/`locked`/`unknown`/`None`); `key_provider` set only when FOUND.
    `vault_sync` -> BOUNDED, timeout from `app_keyring_timeout(app)`, error text from
    `describe_key_failure`.
  - Gate: `uv run pytest tests/app/test_vault_status_key_state.py -q` green
    (spec A8: LOCKED probe -> `key_state == "locked"` and the fake provider's
    `get_key` was never called; UNLOCKED -> `"available"` and provider id set; no
    probe -> `"unknown"`); `rg -n "allow_interactive" src/functualize/app/utils.py` -> 0
    (currently 1).
  - Spec: B5, B3. Call path: 3.2 -> `vault_status`.

## Wave 3 — consumers, part 2 (disjoint; depend on wave 2)

- [ ] **3.1 — Boot builds one lazy resolver and resolves nothing**
  - [F] `src/functualize/_app/boot.py`, `tests/app/test_remote_first.py`
    (hit set: `rg -n "resolve_vault_key|VaultSource\(" src/functualize/_app/boot.py` -> 1298/1303, 1313, 1317 (`build_vault_source`) and 1354/1364, 1370, 1372 (`_build_dormant_vault_source`) *run at authoring*; `tests/app/test_remote_first.py` has 11 constructor/kwarg hits)
  - Both builders construct `VaultKeyResolver(project_id, timeout=app_keyring_timeout(app))`
    and `VaultSource(path, key=resolver, …)`. Delete the eager `resolve_vault_key`
    calls and the "inert" `encryption_key=None` branches and the boot `logger.warning`
    (it now lives in `note_fallthrough`, R-1). Collapse the duplicated construction
    into one private helper (clears the *Duplicate Code* smell on these two).
    Update the stale comment at `boot.py:1360-1363`.
  - Gate: `uv run pytest tests/app/test_remote_first.py -q` green;
    **reachability by sabotage** (commit first, then break, then restore — see
    Constitution): re-adding `resolver.lookup()` at boot makes a new test red —
    `test_boot_never_touches_the_keyring` in the same file (backend that raises on any
    call, vault file present, `app` built and `--help`-equivalent run -> 0 calls);
    `rg -n "resolve_vault_key" src/functualize/_app/boot.py` -> 0 (currently 2).
  - Spec: B1, R-1, A2. Call path: `FunctualizeApp` boot -> `build_vault_source`.

- [ ] **3.2 — The CLI: `vault unlock`, status, honest wrong-key text**
  - [F] `src/functualize/_cli/vault_cmd.py`, `tests/cli/test_vault_commands.py`
    (hit set: `rg -c "interactive|allow_interactive|resolve_vault_key" tests/cli/test_vault_commands.py` = 9 + 1 + 4 *run at authoring*)
  - Add `@vault_app.command("unlock")` (`--json`; D4 FOREGROUND via
    `app.vault.vault_unlock`; exits 0 / 3; `_fail` envelope with reasons
    `key_locked` / `no_keyring` / `key_not_stored`; never prints the key). `status`:
    `Key state:` line and `"key_state"` JSON field. The "different key" message
    (`vault_cmd.py` status block) keeps `remove` / `clear` **last** with the
    destroys-the-only-copy warning. Update tests that asserted the TTY rule.
  - Gate: `uv run pytest tests/cli/test_vault_commands.py -q` green, including new
    cases for A7 (provider named; key bytes/hex absent from stdout, stderr and
    `--json`; exit 3 text; no deadline given a slow fake), A8 (CLI level) and the
    wrong-key message ordering. `rg -n "func builtin vault remove" src/functualize/_cli/vault_cmd.py`
    each hit is preceded by the warning (manual read at execution).
  - Spec: B3, B4, B5, B6, A7, A8, A9. Call path: `func builtin vault unlock` -> this file.

- [ ] **3.3 — All five doors carry the setting**
  - [F] `src/functualize/_cli/main.py`, `tests/cli/test_vault_timeout_door_parity.py` (new)
    (hit set *run at authoring*: `rg -c "ConfigSources\(" src/functualize/_cli/main.py` = 5, at lines 372, 602, 1280, 1404, 1773)
  - Replace each `ConfigSources(dotenv=cli_config.dotenv, dotenv_path=cli_config.dotenv_path)`
    with `cli_config.config_sources()`.
  - Gate: `rg -c "ConfigSources\(" src/functualize/_cli/main.py` -> 0 (currently 5);
    new test boots the app through each door (bare, group, job, builtin, file) with a
    `[vault] keyring_timeout = "7s"` project file and asserts each app's
    `_config_sources.vault_keyring_timeout == "7s"` — the pitfall §23 test
    ("three of four doors agreeing").
  - Spec: B2, A12a. Call path: every `func` invocation.

- [ ] **3.4 — Migrate the remaining direct `VaultSource` constructions**
  - [F] `tests/config/test_vault_miss.py`, `tests/config/test_vault_staleness.py`,
    `tests/app/test_vault_paths.py`
    (hit set *run at authoring*: serena `find_referencing_symbols VaultSource` outside `_app/` ->
    these three plus `test_remote_first.py`, which 3.1 owns)
  - `VaultSource(path, encryption_key=k, …)` -> `VaultSource(path, key=VaultKeyResolver.fixed(k, "test"), …)`;
    `encryption_key=None` -> a resolver whose lookup is NOT_STORED.
  - Gate: `uv run pytest tests/config/test_vault_miss.py tests/config/test_vault_staleness.py tests/app/test_vault_paths.py -q` green.

## Wave 4 — close the transitional states; end-to-end

- [ ] **4.1 — Delete the old API**
  - [F] `src/functualize/_config/vault_source.py`, `src/functualize/_config/vault_keys.py`,
    `tests/integration/test_local_vault_e2e.py`
    (hit set: *run at authoring* `rg -l "allow_interactive|KeyResolution" src tests` after waves 2–3 should list only these)
  - Remove `encryption_key=` / `key_provider_id=` from `VaultSource`; remove
    `resolve_vault_key`, `KeyResolution`, `allow_interactive`, the `isatty` gate and
    their `__all__` entries from `vault_keys.py`; fix the two `KeyResolution` uses in
    `test_local_vault_e2e.py`.
  - Gate (all must be empty/true): `rg -n "isatty" src/functualize/_config` -> 0
    (currently 2); `rg -n "allow_interactive|KeyResolution" src plugins tests -g '*.py'` -> 0
    (currently 4 files / 13 hits); `uv run python -c "import inspect; from functualize._config.vault_source import VaultSource as V; p=inspect.signature(V).parameters; assert 'encryption_key' not in p and 'key_provider_id' not in p"`;
    `rg -n "TRANSITIONAL\(4.1\)" src` -> 0; `uv run pytest tests/integration/test_local_vault_e2e.py -q`.
  - Spec: B2 (the gate is gone).

- [ ] **4.2 — Capability test through the public entry point**
  - [F] `tests/integration/test_vault_keyring_unlock_e2e.py` (new),
    `tests/integration/_fake_keyring.py` (new)
  - A `keyring` backend module selectable by `PYTHON_KEYRING_BACKEND`, controlled by
    env (`unlocked` / `locked-blocks` / `absent`), run through real subprocesses of
    `func` with stdout piped: A1 (unlocked + piped -> exit 0 and the value),
    A2 (job reading no stored entry -> backend call-count file stays 0),
    A3 (env key set -> 0 calls), A4 (`locked-blocks` + `FUNCTUALIZE_VAULT_KEYRING_TIMEOUT=1s`
    -> exit 3 within 1–3 s; message has `vault unlock`; lacks `vault remove`/`clear`),
    A5 (`absent` -> exit 3 fast), A6 (many lookups, one call).
  - Gate: `uv run pytest tests/integration/test_vault_keyring_unlock_e2e.py -q` green;
    **it must fail against the old rule** (reachability by sabotage, Constitution
    order): commit first, then make `VaultKeyResolver.lookup` skip every non-env
    provider when `not sys.stdout.isatty()`, run the A1 case -> red, restore, and
    record the red output in `STATE.md`. (Not run on the `master` checkout: this
    session is isolated to its worktree.)
  - Spec: A1–A6. Call path: the whole feature, through `func`.

## Wave 5 — documentation and the live check

- [ ] **5.1 — Docs and the ADR amendment**
  - [F] `contributor/adr/016-remote-source-activation.md`, `docs/guides/configuration.md`, `CHANGELOG.md`
    (hit set *run at authoring*: `docs/guides/configuration.md` — key table at 604–607
    and prose at 609–611; `contributor/adr/016-…md` — the "Ordering is part of the
    contract" paragraph at l.157; `CHANGELOG.md` — **add** an `[Unreleased]` entry; the
    existing l.1183 "the OS keyring only on a real terminal" is a shipped release's
    history and is **not** edited. `docs/guides/interactivity.md` also matches
    "real terminal" but is about EXCLUSIVE surfaces, unrelated.)
  - ADR-016: "Amended by" block at §5 in ADR-023's style, linking the Decision
    record; do not rewrite history. `configuration.md`: the key table's "Interactive"
    column becomes "Needs a terminal" (`env` no, `keychain` no), the `[vault]
    keyring_timeout` setting and env var, the lock/unlock flow and `vault unlock`,
    the library-mode caveat (K-7). `CHANGELOG.md` `[Unreleased]`: Changed (TTY gate),
    Added (`vault unlock`, `vault.keyring_timeout`, `key_state`), the two behavior
    notes R-1 and R-2.
  - Gate: `rg -n -i "only on a real terminal|a Lambda must not hang on a keychain dialog" docs/guides/configuration.md` -> 0
    (currently 1, line 611); the ADR contains `Amended by`; doc code blocks run
    (`doc-verify` on the new `[vault]` example).
  - Spec: A12.

- [ ] **5.2 — The live check on this host** `[verify-e2e:targeted]`
  - [F] `.spec/features/vault-keyring-unlock/live-check.md`,
    `.spec/features/vault-keyring-unlock/live-check.sh` (new; not shipped)
  - A script that creates a **throwaway** Secret Service collection (never `Login`),
    stores a test key under `functualize-vault`/`vault-key` **in that collection**,
    and drives: unlocked + piped; locked + dialog answered; locked + unanswered at
    `FUNCTUALIZE_VAULT_KEYRING_TIMEOUT=10s`; two parallel jobs (K-2); and observes
    whether the dialog survives the CLI's exit (K-1). Pairs with the maintainer at
    the keyboard for the dialog steps. Cleans up the collection.
  - Gate: output of all four scenarios pasted into `live-check.md`; the `Login`
    collection's `Locked` property is read before and after and shown **unchanged**
    (`busctl --user get-property org.freedesktop.secrets /org/freedesktop/secrets/aliases/default org.freedesktop.Secret.Collection Locked`).
  - Spec: A11.

## Wave 6 — checkpoint

- [ ] **6.1 — Full gates** `[verify-e2e:full]`
  - Gate: `uv run ruff check src/ tests/`; `uv run ruff format --check src/ tests/`;
    `uv run mypy src/`; `uv run lint-imports` -> 7 kept, 0 broken; pytest by tier
    (test-tiers: step -> wave -> tip, never one 600 s call); warm-boot import count
    unchanged and `keyring`/`secretstorage` absent from a vault-less run (A10, via the
    existing lazy-boot measurement); `agentic-verify` walk of `contracts.md`
    (every signature and CLI shape present; orphan scan).

## Wave 7 — knowledge and tracker close-out

- [ ] **7.1 — Confluence and Jira**
  - [F] none in the repository.
  - Decision record (page 12222468) -> Accepted (status, date, link to the PR); the
    shipped behavior promoted in the **existing draft** under *50 — Current
    Reference* (page 12255236, "Vault key resolution — DRAFT"): follow its
    *Promotion checklist* — move the Proposed rows into Current behavior, delete the
    "Today" rows they replace, set Status Accepted / Authority Current, drop the
    `draft` label and the word DRAFT, add the PR link and the live-check result
    (A11) — do not write a second page; FOSS-88 and FOSS-31
    commented with the commit/PR and the re-run falsifying check (A1 against old
    and new code), then moved to Done; FOSS-34 commented that it is now triageable.
  - Gate: the Reference page exists and cites the PR; both Jira issues show the
    comment; the A1 repro output is pasted.

---

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["0.1", "0.2"] },
    { "id": 1, "tasks": ["1.1", "1.2"] },
    { "id": 2, "tasks": ["2.1", "2.2", "2.3", "2.4"] },
    { "id": 3, "tasks": ["3.1", "3.2", "3.3", "3.4"] },
    { "id": 4, "tasks": ["4.1", "4.2"] },
    { "id": 5, "tasks": ["5.1", "5.2"] },
    { "id": 6, "tasks": ["6.1"] },
    { "id": 7, "tasks": ["7.1"] }
  ]
}
```
