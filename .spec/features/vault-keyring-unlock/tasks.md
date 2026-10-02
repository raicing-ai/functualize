# Tasks — vault-keyring-unlock

Plan: `plan.md` (decisions D1–D9, smells S-1..S-6). Spec: `spec.md` A1–A12a.

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

- [x] **2.1 — `VaultSource` takes a lazy key**
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
  - **Executed 2026-10-02.** Gate green (175 passed over the three files plus
    the resolver tests); `wc -l` = 499 (the ~30 transitional lines go at 4.1).
    Reachability: `ResolutionChain._walk` -> `VaultSource.get` -> `_lookup` ->
    `VaultKeyResolver.lookup`; boot still reaches it through the transitional
    `encryption_key=` translation until 3.1. Sabotage (eager `_lookup()` before
    the stored-names check) turned 5 tests in `test_vault_source_lazy.py` red;
    restored. **Disclosed deviations:** (a) two `test_vault_miss.py` cases
    asserted the boot-time no-key silence that R-1 replaces
    (`test_an_unusable_vault_warns_per_run_not_per_key`,
    `test_no_file_and_no_key_stays_silent`); they now assert the moved
    warning, once per run — rewritten, not deleted. (b) `describe_key_failure`'s
    NOT_STORED text (task 1.2's file) now names the entry in its last-resort
    `vault remove <key>`, adds `vault clear` and "need no key", because the
    transitional `encryption_key=None` maps to NOT_STORED (3.4's rule) and the
    existing keyless-recovery test pins that text.

- [x] **2.2 — The func setting**
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
  - **Executed 2026-10-02.** Gate: `test_cli_config_vault.py` 11 passed;
    `test_func_settings_store.py` — `TestCatalog` (with `"vault"` added to its
    section list) green, and **one pre-existing failure** unrelated to this
    task: `TestChainPrecedence::test_default_when_nothing_sets_it` fails when
    the file runs alone because `tui.*` is registered only once the shell has
    been imported — reproduced identically on the base commit `65b2cc7` in a
    scratch worktree. Reachability: `_cli/main.py` -> `resolve_cli_config` ->
    `_get_value(..., section="vault")` -> `CliConfig.vault_keyring_timeout`;
    sabotaging the section name turned 7 of 11 tests red; restored.
    `CliConfig.config_sources()` has **no production caller until 3.3**
    (stated, not hidden). The value is carried as unparsed text; the warning
    for a bad value fires where it is parsed (`resolve_keyring_timeout`).

- [x] **2.3 — The public vault API**
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
  - **Executed 2026-10-02.** Gate: `test_vault_seam.py` 30 passed. The `rg`
    gate returns 3 lines, not "only the one mapping": the `Readability.
    KEY_UNAVAILABLE = "key_unavailable"` value (kept unchanged, as this task
    requires for inspect), and the compatibility mapping
    `VaultKeySourceError._LEGACY_REASONS` with its comment. Before the change
    the same command counted **2**, not 12 as recorded at authoring (the
    authoring count was likely case-insensitive). `vault_unlock` returns a
    `KeyLookup` with the key **stripped** and raises `VaultKeySourceError` on
    failure, so the CLI gets the reason and the message from the public API.
    It is added to `__all__`; it has **no `examples/` caller** yet
    (`public-api-example-coverage.md`, not test-enforced) — residual.
    Reachability: `vault_put` -> `_resolve_key` (bounded) and `vault_inspect`
    (silent) are live through `func builtin vault put/inspect`; `vault_unlock`
    is unwired until 3.2. Sabotage (inspect -> BOUNDED, unlock -> 1 s bound)
    turned 3 tests red; restored. **Disclosed fix to task 1.2's resolver:**
    SILENT access read every provider that lacked `probe()`, so a third-party
    backend with no probe (which may raise its own dialog) was read by
    `status`/`inspect`, contrary to schema D4 ("UNKNOWN/no probe -> no read").
    It now reads only `EnvKeyProvider` without a probe; the 1.2 test that
    covered the case used an *unavailable* provider and could not see it, and
    now uses an available one.

- [x] **2.4 — Status and sync**
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
  - **Executed 2026-10-02.** Gate: `test_vault_status_key_state.py` 8 passed;
    `rg -n "allow_interactive" src/functualize/app/utils.py` -> 0.
    `VaultKeyUnavailableError` gains `reason` (`key_locked` / `no_keyring` /
    `key_not_stored`). Reachability: `func builtin vault status` ->
    `vault_status` -> `resolve_vault_key(SILENT)` -> `probe()`; sabotage
    (SILENT -> BOUNDED) turned 2 tests red; restored.

## Wave 3 — consumers, part 2 (disjoint; depend on wave 2)

- [x] **3.1 — Boot builds one lazy resolver and resolves nothing**
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
  - **Executed 2026-10-02.** Gate: `test_remote_first.py` 29 passed, including
    the new `TestBootResolvesNothing::test_boot_never_touches_the_keyring`
    (vault file present, every backend method raises, app built, chain built
    and a job run -> 0 lookups, 0 backend calls). `rg -n "resolve_vault_key"
    src/functualize/_app/boot.py` -> 0. Both builders go through one
    `_lazy_vault_source`. Sabotage (a `resolver.lookup()` re-added at boot)
    turned that test red; restored. **Disclosed scope addition (task 1.2's
    resolver):** spec A12a requires that a run with `$FUNCTUALIZE_VAULT_KEY`
    set never reads the wait setting, which a boot-time
    `timeout=app_keyring_timeout(app)` would break (it parses — and warns
    about — the setting at boot). So boot builds `VaultKeyResolver.for_app`,
    which reads `app_keyring_timeout(app)` on first need, and BOUNDED access
    asks `EnvKeyProvider` before the deadline. Three resolver tests pin it
    (env set + bad setting -> no warning; `"1s"` bounds the keyring; a bad
    setting warns once over five lookups).

- [x] **3.2 — The CLI: `vault unlock`, status, honest wrong-key text**
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
  - **Executed 2026-10-02.** Gate: `test_vault_commands.py` 108 passed (with
    `test_command_inventory_parity.py`, 118). New: `TestUnlock` (A7: exit 0 +
    provider; key hex absent from stdout, stderr and `--json`; exit 3 with
    each of the three reasons; no deadline under a 1 s setting and a 1.5 s
    backend), three A8 cases at the CLI, `TestTheDifferentKeyMessage`. The
    TTY-rule tests were **rewritten** to the new rule (status's silent access,
    not the terminal, keeps it off a prompting provider; the control proves
    the forced terminal reaches it under bounded access). The put/remove
    non-terminal refusal tests (A9) are unmodified and green. The one
    `func builtin vault remove` hit in `vault_cmd.py` (status, different-key
    block) follows the keep-the-secret fixes and carries the destroys/only-copy
    warning (read at execution). Sabotage (unlock always refused; `key_state`
    dropped from JSON) turned 5 tests red; restored. **Disclosed scope
    additions:** (a) `_cli/builtins.py` declares the `unlock` subcommand — the
    inventory-parity tests require every mounted subcommand to be declared;
    (b) **`tests/conftest.py` gains an autouse `_isolate_os_keyring`** fixture
    (`PYTHON_KEYRING_BACKEND=keyring.backends.fail.Keyring`, an unreachable
    `DBUS_SESSION_BUS_ADDRESS`, and the fail backend forced if `keyring` is
    already imported). Until now the TTY gate kept the suite off the OS
    keyring by accident; with reads regardless of terminal, a test resolving a
    key without the env var would read — or raise an unlock dialog for — the
    real Secret Service of whoever runs the suite. Shared infrastructure, so
    the tip tier applies (wave 6). (c) `describe_key_failure`'s no-keyring
    text names `func builtin vault keygen` (an existing sync test asserts it).
    Three tests that patched `vault_keys.default_providers` were re-pointed at
    `vault_key_resolver.default_providers`, where the resolver looks it up.

- [x] **3.3 — All five doors carry the setting**
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
  - **Executed 2026-10-02.** Gate: `rg -c "ConfigSources\(" src/functualize/_cli/main.py`
    -> 0; `test_vault_timeout_door_parity.py` 5 passed (the `app` surface
    legs skip: the test is about `func`'s doors). Sabotage, one door at a
    time (each `config_sources()` site replaced by a `ConfigSources` without
    the setting): sites 0..4 turned exactly `builtin`, `bare`, `group`, `job`
    and `file` red respectively — every door is covered by its own case. The
    first draft's `file` case ran `jobs/hello.py`, which routes through the
    job door, and left the single-file site uncovered; caught by this
    sabotage and fixed (`scripts/greet.py`).

- [x] **3.4 — Migrate the remaining direct `VaultSource` constructions**
  - [F] `tests/config/test_vault_miss.py`, `tests/config/test_vault_staleness.py`,
    `tests/app/test_vault_paths.py`
    (hit set *run at authoring*: serena `find_referencing_symbols VaultSource` outside `_app/` ->
    these three plus `test_remote_first.py`, which 3.1 owns)
  - `VaultSource(path, encryption_key=k, …)` -> `VaultSource(path, key=VaultKeyResolver.fixed(k, "test"), …)`;
    `encryption_key=None` -> a resolver whose lookup is NOT_STORED.
  - Gate: `uv run pytest tests/config/test_vault_miss.py tests/config/test_vault_staleness.py tests/app/test_vault_paths.py -q` green.
  - **Executed 2026-10-02.** 132 passed. No `VaultSource(... encryption_key=...)`
    remains in `src` or `tests` (`rg`). Test-only task: no production path.

## Wave 4 — close the transitional states; end-to-end

- [x] **4.1 — Delete the old API**
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
  - **Executed 2026-10-02.** `rg -n "allow_interactive|KeyResolution" src plugins tests -g '*.py'`
    -> 0; the signature check passes; `rg -n "TRANSITIONAL\(4.1\)" src` -> 0
    — **both transitional states are closed** (the `encryption_key=` /
    `key_provider_id=` kwargs and `_NoKeyStored` in `vault_source.py`; the old
    `resolve_vault_key` / `KeyResolution` in `vault_keys.py`);
    `test_local_vault_e2e.py` green (in a 1238-test run of `tests/config`,
    `tests/app`, it and `test_vault_commands.py`). **Narrowed gate, disclosed:**
    `rg -n "isatty" src/functualize/_config` returns **1**, not 0 —
    `vault_key_resolver.py`'s `on_tty` check, which *is* B2.3 ("a provider that
    can only work by prompting at a terminal is still consulted only on a real
    TTY") and the schema's lookup table; the gate was authored when the only
    `isatty` lived in `vault_keys.py`, and that file now has 0. Also in scope
    and not in [F]: `tests/config/test_vault_keys.py` exercised the deleted
    function, so its ordering tests were **ported** to the resolver (forced
    terminal via the resolver's `sys`), and the resolver keeps the deleted
    function's two-pass order (terminal-needing providers last, only on a TTY);
    sabotage of that order turned `test_non_interactive_wins_over_interactive`
    red; restored. The `KeyResolution` repr test was dropped — its
    replacement is `TestTheLookupIsSafeToLog` in the resolver tests.

- [x] **4.2 — Capability test through the public entry point**
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
  - **Executed 2026-10-02.** Gate: 8 passed (`-n auto`, 28 s). Sabotage
    (commit first; `VaultKeyResolver._resolve` drops every non-env provider
    when `not sys.stdout.isatty()`) turned A1 red:
    `Error: Cannot open the stored vault entry 'deploy.api_token': no OS
    keyring is reachable here, … assert 3 == <ExitCode.OK: 0>`; restored.
    **Falsifying check against the old code** (for 7.1): the same A1 test,
    copied into a scratch worktree at the base commit `65b2cc7`, fails with
    the field report's own message — `The vault holds a value for
    'deploy.api_token', but no vault key is available on this machine. …
    Fix it with one of: func builtin vault sync / func builtin vault remove
    deploy.api_token / func builtin vault clear` — and passes on this branch.

## Wave 5 — documentation and the live check

- [x] **5.1 — Docs and the ADR amendment**
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
  - **Executed 2026-10-02.** `rg -n -i "only on a real terminal|a Lambda must not hang on a keychain dialog" docs/guides/configuration.md`
    -> 0; ADR-016 contains `Amended by` (3 blocks; the new one at §5).
    doc-verify, shell engine: `a-core-builtins` (harness control),
    `p-remote-vault` and `l-secrets` all ✅; `tests/skills` 71 passed. The
    `[vault]` TOML block has no command that echoes it (`func builtin config
    show` renders only `[discovery]`, `[cli]`, `[aliases]`), so it is pinned
    by `tests/cli/test_cli_config_vault.py`, which parses exactly that table,
    rather than by a doc-verify step. **Deviation, for the maintainer:** the
    ADR "Amended by" block does **not** embed the private decision record's
    address — this repository is public and no ADR links an internal page; it
    names the decision by feature and date instead. Add the link if you want
    it. Also touched (not in [F]): `examples/docs/scenarios/p-remote-vault.toml`'s
    `[source] lines`, moved to the vault-commands section's new range.

- (RETIRED — replaced by R7.2 and R8.2) **5.2 — The live check on this host**
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
  - **Prepared 2026-10-02, NOT RUN — needs the maintainer at the keyboard.**
    `live-check.sh` drives the four scenarios against a throwaway collection,
    pointed at by `KEYRING_PROPERTY_PREFERRED_COLLECTION` (read from the
    installed `keyring`: `KeyringBackend.__init__` applies
    `KEYRING_PROPERTY_*`, and its Secret Service backend reads and unlocks only
    `preferred_collection`); it refuses if that collection is the default one,
    reads `Login`'s `Locked` property before and after, and deletes the
    throwaway at exit. Checked only with `bash -n` here (this host has no
    desktop session). `live-check.md` says NOT RUN until real output replaces
    its placeholder.

## (retired) Wave 6 — checkpoint

- (RETIRED — replaced by R8.1) **6.1 — Full gates**
  - Gate: `uv run ruff check src/ tests/`; `uv run ruff format --check src/ tests/`;
    `uv run mypy src/`; `uv run lint-imports` -> 7 kept, 0 broken; pytest by tier
    (test-tiers: step -> wave -> tip, never one 600 s call); warm-boot import count
    unchanged and `keyring`/`secretstorage` absent from a vault-less run (A10, via the
    existing lazy-boot measurement); `agentic-verify` walk of `contracts.md`
    (every signature and CLI shape present; orphan scan).

## (retired) Wave 7 — knowledge and tracker close-out

- (RETIRED — replaced by R8.3) **7.1 — Knowledge and tracker close-out**
  - [F] none in the repository.
  - Decision record -> Accepted (status, date, link to the PR); the
    shipped behavior promoted in the **existing draft** under *50 — Current
    Reference* (the existing draft): follow its
    *Promotion checklist* — move the Proposed rows into Current behavior, delete the
    "Today" rows they replace, set Status Accepted / Authority Current, drop the
    `draft` label and the word DRAFT, add the PR link and the live-check result
    (A11) — do not write a second page; the story and the field report
    commented with the commit/PR and the re-run falsifying check (A1 against old
    and new code), then moved to Done; the agent-routes report commented that it is now triageable.
  - Gate: the Reference page exists and cites the PR; both tracker issues show the
    comment; the A1 repro output is pasted.

---

# Rework after the live findings (Addendum 1, 2026-10-02)

Waves 0-5 above are **done and stay valid** except where the addendum
(`spec.md` → *Addendum 1*, `plan.md` → *Addendum 1*) supersedes a behavior: a run
no longer raises an unlock prompt, the 30 s wait is no longer a prompt wait, the
keyring layer becomes a platform-neutral adapter port, and a lightweight
`vault_key_state` API is added. Tasks 5.2, 6.1 and 7.1 above are **retired**
(their work moves to R7.2, R8.1, R8.2 and R8.3) and are no longer in the
dependency graph. Read `research.md` R9-R12 first: they are the evidence.

**Rules that apply to every R-task**
- Nothing in the test suite, in CI, or in a script may raise an unlock prompt on a
  real user session. The suite-wide `_isolate_os_keyring` fixture in
  `tests/conftest.py` already fences this; do not weaken it.
- Messages are provider-neutral: they say "keyring", never a product name
  (gnome-keyring, KWallet, Keychain, Credential Manager). A test greps them.
- Never call `Prompt.Dismiss`, and never end an active unlock prompt from the
  client side (research R9). `vault unlock` waits for the prompt's own outcome.
- `get_key()` on a keyring-family provider **never prompts** (new contract, R1.1).

## Wave 6 — contracts first (disjoint)

- [x] **R1.1 — The provider contract: `get_key` never prompts; `VaultKeyUnlocker`**
  - [F] `src/functualize/_types/protocols.py`, `src/functualize/plugin/__init__.py`,
    `tests/plugin/test_vault_key_provider.py`, `tests/test_public_api_surface.py`
  - State in the `VaultKeyProvider` docstring that `get_key` must not prompt and
    must return promptly (or raise a typed locked/unavailable error); add the
    optional `VaultKeyUnlocker` Protocol (`unlock() -> bool`, may prompt) and export it
    from `functualize.plugin`. `interactive()` keeps its meaning (needs a person at a
    terminal).
  - Gate: `uv run pytest tests/plugin/test_vault_key_provider.py tests/test_public_api_surface.py -q`
    green; `uv run lint-imports` -> 7 kept.
  - Spec: B2', B4', contracts §8.
  - **Executed 2026-10-02.** Gate: 63 passed; lint-imports 7 kept. `VaultKeyProvider`
    docstring and `get_key` state the never-prompt contract (a test reads it);
    `VaultKeyUnlocker` exported from `functualize.plugin` and `_types.protocols.__all__`.
    Call path: satisfied by `KeychainKeyProvider` (R3.1), consumed by the resolver's
    FOREGROUND access (R4.1).

- [x] **R1.2 — The adapter contract suite (written before the adapters)**
  - [F] `tests/contracts/__init__.py` (new), `tests/contracts/_fake_platforms.py` (new),
    `tests/contracts/test_keyring_adapter_contract.py` (new)
  - A parametrized suite every keyring adapter must pass, using fakes that record
    "a prompt was requested": `read_silent()` on a locked fake returns LOCKED and
    records **zero** prompts; on an unlocked fake returns FOUND; no entry ->
    NOT_STORED; backend absent -> NO_KEYRING; `state()` agrees with those; `unlock()` is
    the only call that may record a prompt; no adapter blocks longer than its bound.
    The parameter list starts empty and each adapter task (R2.x) registers itself.
  - Gate: the suite collects and passes with the placeholder fake adapter;
    `uv run pytest tests/contracts -q` green.
  - Spec: B9, A15.
  - **Executed 2026-10-02.** Gate: `tests/contracts` 21 passed with the in-memory
    placeholder. **Disclosed scope addition:** the port types (`AdapterOutcome`,
    `AdapterRead`, `UnlockHow`, the `KeyringAdapter` Protocol) are created here in
    `src/functualize/_config/vault_keyring.py` — the wave-7 adapters return them, so
    they cannot wait for R3.1, which adds only `select_adapter` to that module.
    `AdapterRead` carries `secret: str` (the stored hex text) rather than schema's
    `key: bytes`, so one decoding rule stays in the provider; `how: UnlockHow` carries
    the unlock outcomes contracts §10 lists. Sabotage (the placeholder's locked read
    records a prompt) turned `test_no_prompt_in_any_world[in-memory-locked]` red;
    restored.

## Wave 7 — the adapters (disjoint new files)

- [x] **R2.1 — Linux Secret Service adapter (silent read, state, unlock)**
  - [F] `src/functualize/_config/vault_keyring_secretservice.py` (new),
    `tests/config/test_vault_keyring_secretservice.py` (new)
  - Uses `secretstorage` directly, imported lazily inside the adapter. `read_silent()`:
    default collection `is_locked()` -> LOCKED (return at once); else search by the
    clear-text attributes and `get_secret()`, mapping `LockedException` -> LOCKED. It
    **never calls `unlock()`** and never `keyring.get_password` (which auto-unlocks).
    `state()`: UNLOCKED / LOCKED / UNKNOWN (any D-Bus failure), bounded ~1 s.
    `unlock()`: the only prompt-capable call; runs `collection.unlock()` and waits for the
    prompt's own outcome; **no `Dismiss`**; a watcher notices "no prompt helper appeared
    within ~3 s" (gnome-keyring: `org.gnome.keyring.SystemPrompter` has no owner) and
    reports it through a neutral error. It speaks the Secret Service protocol, so it
    also serves any implementation of it (KWallet 6, KeePassXC).
  - Tests use a fake `secretstorage` module (no D-Bus). Register in R1.2's suite.
  - Gate: `uv run pytest tests/config/test_vault_keyring_secretservice.py tests/contracts -q`;
    `rg -n "get_password|Dismiss" src/functualize/_config/vault_keyring_secretservice.py` -> 0.
  - Spec: B2', B4', B9. Call path: R3.1 factory -> `KeychainKeyProvider`.
  - **Executed 2026-10-02.** Gate: 49 passed (adapter tests + contracts);
    `rg -n "get_password|Dismiss" …secretservice.py` -> 0. Opens the collection with
    `secretstorage.Collection(conn[, preferred])`, never `get_default_collection`
    (it creates one when absent, which prompts); honours the backend's attribute
    scheme and `preferred_collection` (what `KEYRING_PROPERTY_PREFERRED_COLLECTION`
    sets). The missing-dialog watcher applies only when `org.gnome.keyring` is owned;
    elsewhere a slow dialog is waited for (test). **Residual risk, stated:** on
    NO_PROMPT the pending Unlock request is left to the daemon (the spec's choice);
    whether that is safe on a wedged gnome-keyring is unmeasured. Sabotage
    (`read_silent` calls `collection.unlock()`) turned 3 contract cases red; restored.

- [x] **R2.2 — macOS adapter**
  - [F] `src/functualize/_config/vault_keyring_macos.py` (new),
    `tests/config/test_vault_keyring_macos.py` (new)
  - Reads through the Security framework with user interaction **disabled** around the
    read (`SecKeychainSetUserInteractionAllowed(false)` via ctypes, reusing `keyring`'s
    Security handle; restore on exit). Status `-25308` (interaction not allowed) ->
    LOCKED; item not found -> NOT_STORED. `unlock()`: interaction allowed + read.
    **Unverified on a real Mac** (research R10): the design is only as good as the
    macOS smoke job (R7.1) and the manual checklist (R7.2).
  - Tests inject a fake ctypes layer (so they run on Linux). Register in R1.2.
  - Gate: `uv run pytest tests/config/test_vault_keyring_macos.py tests/contracts -q`;
    `uv run mypy --platform darwin --follow-imports=silent src/functualize/_config/vault_keyring_macos.py`.
  - Spec: B9, A15, A16.
  - **Executed 2026-10-02.** Gate: 8 + contracts passed; `mypy --platform darwin
    --follow-imports=silent` clean, and clean on the host. The four Security calls sit
    behind `SecurityAPI`; the real `_CtypesSecurity` (ctypes over `keyring`'s
    `api._sec`) is **untested here** — only the darwin CI job (R7.1) can run it.
    Sabotage (interaction left on during the silent read) turned 7 red; restored.

- [x] **R2.3 — Windows adapter**
  - [F] `src/functualize/_config/vault_keyring_windows.py` (new),
    `tests/config/test_vault_keyring_windows.py` (new)
  - `CredRead` through `keyring`'s Windows backend; no lock model, so `state()` is
    UNLOCKED whenever the backend is present, `unlock()` is a no-op that reports
    "nothing to unlock", and a read never prompts. Not found (`winerror` 1168) ->
    NOT_STORED. Register in R1.2.
  - Gate: `uv run pytest tests/config/test_vault_keyring_windows.py tests/contracts -q`;
    `uv run mypy --platform win32 --follow-imports=silent src/functualize/_config/vault_keyring_windows.py`.
  - Spec: B9, A15, A16.
  - **Executed 2026-10-02.** Gate: 5 + contracts passed; `mypy --platform win32
    --follow-imports=silent` clean. Harness worlds are UNLOCKED/EMPTY/ABSENT (no lock
    model, no hangable state query). Sabotage (unlock reports UNLOCKED_NOW) turned 3
    red; restored.

- [x] **R2.4 — Generic adapter for unrecognised backends (fail-safe)**
  - [F] `src/functualize/_config/vault_keyring_generic.py` (new),
    `tests/config/test_vault_keyring_generic.py` (new)
  - For a `keyring` backend that is not on the allowlist (R3.1): `state()` is UNKNOWN,
    and `read_silent()` **refuses to read** (returns a new `UNVERIFIED` outcome that the
    resolver maps to the neutral "this keyring cannot be read without a possible
    prompt" message), because silence cannot be proven. `unlock()` reads once through
    `keyring` in the foreground (the backend may prompt; a person is present).
  - Gate: `uv run pytest tests/config/test_vault_keyring_generic.py tests/contracts -q`.
  - Spec: B9 (allowlist), A15.
  - **Executed 2026-10-02.** Gate: 4 + contracts passed (100 in the contract run).
    Sabotage (`read_silent` reads in the foreground) turned 5 red; restored.

## Wave 8 — selection and the provider

- [x] **R3.1 — Adapter factory; `KeychainKeyProvider` delegates**
  - [F] `src/functualize/_config/vault_keyring.py` (new), `src/functualize/_config/vault_keys.py`,
    `tests/config/test_vault_keys.py`
    (hit set: `rg -n "get_password" src` -> `vault_keys.py:254`, the only direct call)
  - The factory picks an adapter by `sys.platform` and the active `keyring` backend
    class, with a short allowlist (Secret Service family, macOS, Windows); everything
    else -> generic. Adapter modules are imported **lazily and only on their own
    platform**. `KeychainKeyProvider.get_key` delegates to `read_silent()`;
    `probe()` to `state()`; new `unlock()` (it satisfies `VaultKeyUnlocker`);
    `initialize_key` keeps writing through `keyring.set_password`. The `except
    Exception: return None` is already gone; do not reintroduce it.
  - Gate: `uv run pytest tests/config/test_vault_keys.py tests/contracts -q`;
    `rg -n "get_password" src/functualize/_config/vault_keys.py` -> 0 reads (the write path
    uses `set_password` only); `uv run lint-imports` -> 7 kept.
  - Spec: B2', B9.
  - **Executed 2026-10-02.** Gate: `test_vault_keys.py` + contracts 160 passed;
    `rg -n "get_password" src/functualize/_config/vault_keys.py` -> 0; lint-imports
    7 kept. `select_adapter(service, account, *, platform, backend)` — service and
    account added to schema's signature, because the adapters need them. Backends
    are matched by module/class name (a chainer by its first real backend), so
    choosing imports no other platform's module. `KeychainKeyProvider(adapter=…)`
    is the test seam; `unlock_key()` returns `UnlockedKey(outcome, how, key)`, used
    by the resolver's FOREGROUND path and by `initialize_key` (`vault init` is run by
    a person, so it reads through unlock). **Disclosed additions outside [F]:** new
    `KeyringUnverifiedError` in `_config/vault.py` (a `KeyringUnavailableError`
    subclass; carried a `TRANSITIONAL(R4.1)` marker, closed there). The
    keychain tests that faked the whole `keyring` module were rewritten at the
    adapter port (typed outcomes, probe = `state()`, unlock, scope by recording the
    factory's arguments, init over a store-backed adapter) plus 13 allowlist
    cases. **Expected red until R6.4:** 4 cases in
    `tests/integration/test_vault_keyring_unlock_e2e.py` — their fake `keyring`
    backend is now, correctly, an unproven backend a run refuses to read.
    Sabotage (`get_key` reads through `unlock()`) turned
    `test_get_key_never_unlocks` red; restored.

## Wave 9 — resolver and platform hygiene (disjoint)

- [x] **R4.1 — The resolver stops prompting; neutral messages**
  - [F] `src/functualize/_config/vault_key_resolver.py`, `tests/config/test_vault_key_resolver.py`,
    `tests/config/test_vault_source_lazy.py`
    (hit set *run at authoring*: `rg -n "_run_bounded" src` -> 4 sites in
    `vault_key_resolver.py` (136, 273, 343, 359))
  - BOUNDED and SILENT both call `read_silent()`: **locked -> LOCKED at once, no wait**.
    `_run_bounded` stays only as the safety net against a hung backend (its message
    says "did not answer"); it must never be the way a prompt is abandoned. FOREGROUND
    calls `unlock()` and has no deadline. If BOUNDED and SILENT become identical,
    collapse them (Speculative Generality). `describe_key_failure`: the locked text
    becomes *"The keyring is locked. Unlock it with your system's keyring manager, or
    run `func builtin vault unlock` in a terminal, or set `FUNCTUALIZE_VAULT_KEY`, then
    retry."*; add the UNVERIFIED text; no product names anywhere.
  - Gate: `uv run pytest tests/config/test_vault_key_resolver.py tests/config/test_vault_source_lazy.py -q`
    green, including a test that no message contains `gnome`, `kwallet`, `keychain`,
    `credential manager`, `secret service` (case-insensitive).
  - Spec: B2', B3', A4', A18.
  - **Executed 2026-10-02.** Gate: 81 passed, including
    `test_no_message_names_a_keyring_product` over every status (the
    `functualize[keychain]` extra is set aside first: it is a package name, and
    the no-keyring text must name it). BOUNDED reads silently; `_run_bounded` is
    the hung-backend guard only, with its own "did not answer within N s" text;
    FOREGROUND -> `_unlock()` (keychain: `unlock_key`; a third-party
    `VaultKeyUnlocker`: `unlock()` then `get_key`). `KeyLookup.unlock_how` carries
    how an unlock ended. **Transitional, marked `TRANSITIONAL(R5.1)`:**
    `KeyAccess.SILENT` (now the same silent read, never memoised) and
    `KeyStatus.UNKNOWN` (no longer produced) stay until R5.1 moves `vault_status`
    and `vault_inspect` off them. **Expected red until R6.1/R6.4:** the CLI and e2e
    assertions on the old "locked or did not answer" text. Sabotage (BOUNDED goes
    through `_unlock`) turned the bounded-path tests red; restored.

- [x] **R3.2 — No Linux-only code on other platforms**
  - [F] `tests/config/test_keyring_platform_imports.py` (new)
  - With `sys.platform` forced to `darwin` and then `win32` and an import hook that
    raises on `secretstorage` and `jeepney`, importing the factory and building a
    provider must succeed and must not import either; and the reverse (Linux) must not
    import the macOS or Windows adapter modules.
  - Gate: `uv run pytest tests/config/test_keyring_platform_imports.py -q`;
    `uv run mypy --platform darwin src/functualize/_config/` and
    `uv run mypy --platform win32 --follow-imports=silent src/functualize/_config/vault_key*.py`
    clean (research R10: the 8 Windows errors are pre-existing, elsewhere).
  - Spec: B9, A16.
  - **Executed 2026-10-02.** Gate: 3 passed; `mypy --platform darwin
    src/functualize/_config/` clean (29 files); `mypy --platform win32
    --follow-imports=silent src/functualize/_config/vault_key*.py` clean (7 files).
    `sys.platform` is forced *after* the imports (forcing it first breaks the
    stdlib's own start-up); the import hook is installed first, so an import-time
    load of a blocked library still fails. Sabotage (a top-level import of the
    Linux adapter in `vault_keyring.py`) turned all 3 red; restored.

## Wave 10 — the public API

- [x] **R5.1 — `vault_key_state`; `vault_unlock` signal policy; `vault_status` uses it**
  - [F] `src/functualize/app/vault.py`, `src/functualize/app/utils.py`,
    `tests/app/test_vault_seam.py`, `tests/app/test_vault_status_key_state.py`,
    `tests/app/test_vault_key_state.py` (new)
  - `vault_key_state(app=None, cwd=None) -> VaultKeyState` (`schema.md`): no vault file
    -> NOT_APPLICABLE; env set -> UNLOCKED with source `env`, **no keyring touch**;
    else the adapter `state()` plus whether an entry is stored (clear-text attributes);
    hard cap ~250 ms (UNKNOWN on timeout); process-level cache with a short TTL held on
    the resolver instance (no module global). Never prompts, never reads the secret,
    never unlocks. `vault_status()` fills `key_state` from it (one implementation).
    `vault_unlock`: while a prompt is outstanding, the first SIGINT/SIGTERM sets a flag
    and keeps waiting (the CLI prints guidance); a second one raises
    `UnlockAbandoned` after restoring handlers, with a warning that the keyring may
    misbehave; restores signal handlers in a `finally`.
  - Gate: `uv run pytest tests/app/test_vault_key_state.py tests/app/test_vault_status_key_state.py tests/app/test_vault_seam.py -q`
    green; a test asserts the state call makes **zero** `get_key`/secret reads and zero
    prompts on a locked fake, and finishes under the cap with a hung fake.
  - Spec: B4', B8, A7', A13.
  - **Executed 2026-10-02.** Gate: `test_vault_key_state.py` (9), `test_vault_status_key_state.py`,
    `test_vault_seam.py` (35) green; 985 passed with `tests/config` under `-n auto`.
    A13 covered: env -> UNLOCKED/`env` with zero keyring calls; no vault file ->
    NOT_APPLICABLE; locked -> zero `get_key` and zero `unlock`; a hung probe returns
    UNKNOWN inside 1 s; five calls on one app -> one probe (cache on the app's
    resolver). The state logic lives on `VaultKeyResolver.key_state()` (instance
    cache, `KeyringState`), reached through a new read-only `VaultSource.resolver`;
    `KeychainKeyProvider` gains `adapter_name()` / `key_stored()`, and the Linux
    adapter an optional `has_entry()` (clear-text attributes, no secret read).
    **Both `TRANSITIONAL(R5.1)` markers closed:** `KeyAccess.SILENT` and
    `KeyStatus.UNKNOWN` are removed; `vault_inspect` reads silently under a 2 s
    hung-backend bound, `vault_status` reads only when the state is unlocked.
    Signal policy: first SIGINT/SIGTERM logs the guidance and keeps waiting, second
    raises; handlers restored (tests send the signals from inside the fake read, so
    they never reach the runner). **Deviations:** the error is
    `UnlockAbandonedError` (Constitution: error classes end in `Error`), not
    contracts' `UnlockAbandoned`; `vault init` no longer treats a locked keyring as
    "no key" (`_init_with`). Touched outside [F] for the above: the resolver, the
    keychain provider, the Linux adapter, `vault_source.py`. Sabotage (the state
    probe reads the secret) turned 5 red; restored.

## Wave 11 — surfaces (disjoint)

- [x] **R6.1 — CLI: `vault unlock` behavior and wording**
  - [F] `src/functualize/_cli/vault_cmd.py`, `tests/cli/test_vault_commands.py`
  - Messages for: already unlocked (exit 0), unlocked now (exit 0, provider named), user
    cancelled in the dialog (exit 3), no prompt appeared (exit 3), nothing to unlock on
    this platform (exit 0), waiting guidance on the first signal. `--json` keeps the
    sibling envelope. Update tests asserting the old wording.
  - Gate: `uv run pytest tests/cli/test_vault_commands.py -q` green.
  - Spec: B4', A7'.
  - **Executed 2026-10-02.** Gate: `test_vault_commands.py` (+ inventory parity)
    125 passed. Outcomes: already unlocked / unlocked now / nothing to unlock /
    env (exit 0); cancelled / no prompt / locked / no keyring / not stored (exit 3);
    `--json` `{"ok", "reason", "provider"}`; drift-catcher declares `cancelled`,
    `no_prompt`, `key_unverified`, `unlock_abandoned`. `vault status` shows
    `(no vault)` for an absent key state (the schema maps `not_applicable` to None).
    The first-signal guidance is logged by `vault_unlock` (stderr through the CLI's
    logging). Sabotage (reason mapping) turned the JSON case red; restored.

- [x] **R6.2 — TUI: show the vault state (never blocks the UI thread)**
  - [F] `src/functualize/_cli/tui/bar_items.py`, `src/functualize/_cli/tui/dynamic_footer_widget.py`,
    `src/functualize/_cli/tui/app.py`, `tests/tui_audit/test_vault_state_item.py` (new)
    (candidates from `rg -l -i "status.?bar|StatusBar|DynamicFooter" src/functualize/_cli/tui`;
    the executor confirms the minimal subset by reading them)
  - **Read first:** `contributor/guides/steering_textual_tui.md` (§2.5 workers) and
    `contributor/guides/tui-panels.md`. Poll `vault_key_state` from a **thread worker**
    (`run_worker(fn, thread=True)` + `call_from_thread`) every ~10 s and on focus, show
    only when the project has a vault (`not_applicable` renders nothing). Public API only
    (`functualize.app.vault`). `func --help` is **not touched** (maintainer decision
    2026-10-02). Inline mode is not supported on Windows (steering doc), so the item
    simply never renders there.
  - Gate: `uv run pytest tests/tui_audit/ -q` green before and after (re-run per
    CLAUDE.md); the new test proves a hung `vault_key_state` does not block the event loop.
  - Spec: B8, A14.
  - **Executed 2026-10-02.** Gate: `tests/tui_audit/` 33 passed before, 40 after.
    Minimal subset: `bar_items.py` (pure `render_vault_state`) and `app.py` (thread
    worker at mount, every 10 s and on `AppFocus`; `call_from_thread`; text through
    the one `_update_status_bar`). `dynamic_footer_widget.py` not needed. `func
    --help` untouched. The first draft of the hung-probe test was **vacuous** — it
    started its clock after mount, where a loop-thread probe stalls; sabotage (probe
    on the loop thread) caught it, the clock now starts before `run_test`, and the
    same sabotage turns both Pilot tests red.

- [x] **R6.3 — Docs, ADR amendment, changelog**
  - [F] `docs/guides/configuration.md`, `contributor/adr/016-remote-source-activation.md`,
    `CHANGELOG.md`
  - Replace every statement that a locked keyring is waited on or that a dialog appears
    during a run; document `vault unlock`, `vault_key_state`, the TUI item, the platform
    support levels (Linux verified; macOS/Windows implemented and CI-smoked, not
    field-verified), and the advice "unlock before running agents". Adjust the ADR-016
    "Amended by" block: the reason (no unbounded hang on a prompt) is kept, the
    mechanism is now *no prompt from a run at all*. Keep the repository free of
    internal page links and tracker keys.
  - Gate: `rg -n -i "30 seconds|dialog.*within|waits? up to" docs/guides/configuration.md CHANGELOG.md`
    shows no remaining claim of a prompt wait; doc code blocks run (`doc-verify`).
  - Spec: A12.
  - **Executed 2026-10-02.** Gate: `rg -n -i "30 seconds|dialog.*within|waits? up to"
    docs/guides/configuration.md CHANGELOG.md` -> 0 (also no "bounded wait");
    doc-verify `a-core-builtins`, `p-remote-vault`, `l-secrets` ✅. The platform
    table says macOS/Windows are "implemented; not yet confirmed" — R7.1 decides
    whether "CI-smoked" may be added. No tracker key or internal link in any file.

- [x] **R6.4 — End-to-end tests follow the new behavior**
  - [F] `tests/integration/test_vault_keyring_unlock_e2e.py`, `tests/integration/_fake_keyring.py`
  - Mode `locked-blocks` becomes `locked` (raises a locked error at once). A4 becomes:
    locked + piped -> exit 3 in under 2 s, neutral message, backend recorded **no**
    prompt. Add: `vault unlock` against a fake that "unlocks" (exit 0) and then a piped
    run succeeds (the unlock-elsewhere story), and a fake that cancels (exit 3).
  - Gate: `uv run pytest tests/integration/test_vault_keyring_unlock_e2e.py -q` green;
    reachability by sabotage: making `read_silent` call the fake's prompt path turns A4 red.
  - Spec: A1-A6, A4'.
  - **Executed 2026-10-02.** Gate: 9 passed. The e2e now drives the **real**
    provider and Linux adapter: `keyring.backends.SecretService.Keyring` selected,
    and a two-line `secretstorage` shim (re-exporting `_fake_keyring.py`) put first
    on the child's `PYTHONPATH`; keyring state persists in a file between processes.
    A4': locked + piped -> exit 3, neutral text, no `unlock` call; plus unlock-then-run
    and cancelled-unlock. Sabotage (the Linux adapter's silent read calls
    `collection.unlock()`) turned A4' red: `assert 'unlock' not in ['import',
    'dbus_init', 'dbus_init', 'unlock']`; restored.

## Wave 12 — CI and the manual tier

- [ ] **R7.1 — Cross-platform keyring jobs (non-required at first)**
  - [F] `.github/workflows/keyring-platforms.yml` (new), `.github/scripts/keyring_smoke.py` (new)
  - Matrix `ubuntu-latest`, `macos-latest`, `windows-latest`. **Tier 1** (all three):
    the adapter contract suite plus a real-OS smoke — macOS: create a temporary keychain
    with `security`, lock it, assert the silent read returns LOCKED within 5 s (a hang
    means a dialog and fails the job); Windows: write then read a credential, assert
    UNLOCKED; Linux: private D-Bus session (`dbus-run-session`) with its own
    `gnome-keyring-daemon`, lock, assert LOCKED and **zero prompt objects**. Also
    `mypy --platform darwin|win32` on the keyring modules. **Tier 2 (spike with a
    prove-or-drop gate):** programmatic unlock stands in for "unlocked elsewhere" —
    macOS `security unlock-keychain -p`, Linux `gnome-keyring-daemon --unlock` (**unproven**,
    research R12); a platform whose tier 2 cannot be made reliable stays at tier 1 plus
    the manual tier and the docs say so. The jobs are not in the required-checks ruleset
    until the maintainer decides.
  - Gate: the workflow passes on a branch push for all three runners (link the run); the
    tier-2 outcome per platform is written into `research.md` R12.
  - Spec: B9, A15-A17.

- [ ] **R7.2 — The manual tier: live check v2 and the sandbox harness**
  - [F] `.spec/features/vault-keyring-unlock/live-check.sh`, `.spec/features/vault-keyring-unlock/live-check.md`,
    `.spec/features/vault-keyring-unlock/sandbox/run_sandbox.sh`,
    `.spec/features/vault-keyring-unlock/sandbox/interrupt_probe.py`,
    `.spec/features/vault-keyring-unlock/sandbox/unlock_roundtrip.py`
  - Rewrite the live check around the new design, on a **throwaway** collection only:
    (1) unlocked + piped -> `token ok`, no dialog; (2) locked + piped -> refusal in under
    2 s, **no dialog, no prompt object, no new coredump**; (3) locked, then
    `func builtin vault unlock` in a terminal, the maintainer answers the dialog, then
    piped works; (4) `vault unlock` and the maintainer presses **Cancel** in the dialog ->
    exit 3 and the next unlock still works; (5) two parallel piped jobs on a locked
    keyring -> both refuse, zero dialogs. Before and after: `Login` `Locked` property and
    `coredumpctl list | wc -l`, both shown unchanged. The sandbox directory holds the
    scripts used for the daemon-crash reproduction (copied from the maintainer session);
    they run only on a private bus and are never pointed at the real session. Add a
    macOS/Windows manual checklist to `live-check.md`.
  - Gate: scripts pass `bash -n`; `live-check.md` states what each scenario proves and
    that abandon-style scenarios run only in the sandbox.
  - Spec: A11'.

## Wave 13 — checkpoint

- [ ] **R8.1 — Full gates** `[verify-e2e:full]`
  - Gate: `uv run ruff check src/ tests/`; `uv run ruff format --check src/ tests/`;
    `uv run mypy src/`; `uv run lint-imports` -> 7 kept; pytest by tier (never one call
    over 600 s); `uv run pytest tests/tui_audit/ -q`; the warm-boot import count is
    unchanged and `keyring`/`secretstorage` are absent from a vault-less run (A10);
    `agentic-verify` walk of `contracts.md`. The pre-existing failure
    `tests/cli/test_func_settings_store.py::TestChainPrecedence::test_default_when_nothing_sets_it`
    (order-dependent on master at 04d90ac) is **not** this feature's; record it, do not fix it here.

## Wave 14 — the live check with the maintainer (a human step)

- [ ] **R8.2 — Run the live check, together**
  - Run `live-check.sh` (R7.2) with the maintainer at the keyboard of the Arch/niri
    machine; paste the real output into `live-check.md`. **Stop and ask** before any step
    that is not in the script. Never touch `Login`; never run abandon-style scenarios on the
    real session.
  - Gate: output pasted; `Login Locked: UNCHANGED`; `coredumpctl` count unchanged;
    scenarios 1-5 each marked pass/fail with the evidence.
  - Spec: A11'.

## Wave 15 — knowledge and tracker close-out

- [ ] **R8.3 — Knowledge and tracker close-out**
  - [F] none in the repository.
  - As the retired 7.1, plus: update the decision record and the draft
    reference to the final behavior *before* promoting; record the
    macOS/Windows evidence level per platform; comment on the story, the field report and the agent-routes report with
    the PR, the re-run falsifying check (A1 on old vs new code) and the live-check result.
  - Gate: the Reference page cites the PR and the live-check result; the tracker comments exist.

---

## Task Dependency Graph

```json
{
  "waves": [
    {
      "id": 0,
      "tasks": [
        "0.1",
        "0.2"
      ]
    },
    {
      "id": 1,
      "tasks": [
        "1.1",
        "1.2"
      ]
    },
    {
      "id": 2,
      "tasks": [
        "2.1",
        "2.2",
        "2.3",
        "2.4"
      ]
    },
    {
      "id": 3,
      "tasks": [
        "3.1",
        "3.2",
        "3.3",
        "3.4"
      ]
    },
    {
      "id": 4,
      "tasks": [
        "4.1",
        "4.2"
      ]
    },
    {
      "id": 5,
      "tasks": [
        "5.1"
      ]
    },
    {
      "id": 6,
      "tasks": [
        "R1.1",
        "R1.2"
      ]
    },
    {
      "id": 7,
      "tasks": [
        "R2.1",
        "R2.2",
        "R2.3",
        "R2.4"
      ]
    },
    {
      "id": 8,
      "tasks": [
        "R3.1"
      ]
    },
    {
      "id": 9,
      "tasks": [
        "R3.2",
        "R4.1"
      ]
    },
    {
      "id": 10,
      "tasks": [
        "R5.1"
      ]
    },
    {
      "id": 11,
      "tasks": [
        "R6.1",
        "R6.2",
        "R6.3",
        "R6.4"
      ]
    },
    {
      "id": 12,
      "tasks": [
        "R7.1",
        "R7.2"
      ]
    },
    {
      "id": 13,
      "tasks": [
        "R8.1"
      ]
    },
    {
      "id": 14,
      "tasks": [
        "R8.2"
      ]
    },
    {
      "id": 15,
      "tasks": [
        "R8.3"
      ]
    }
  ]
}
```
