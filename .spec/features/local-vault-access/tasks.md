# Tasks: local-vault-access

Each task is ≈1–3 files and one context window. File lists `[F]` are the hit
sets of the gate commands recorded beside them, run at authoring time
(2026-09-17) — not composed from memory. Hit counts are recorded so drift
between authoring and execution is visible.

Conventions: `[F]` files to change · `[G]` acceptance gate, an executable
command or an observable · `[D]` depends on.

---

## Wave 0 — foundation

### [x] T1.1 — Extract the vault path, walking up like discovery (D4)

`vault_path_for_project` hashes the working directory; discovery walks upward
for `.functualize/` first. Move the function to a **crypto-free** module and fix
the disagreement in that one place, so every surface inherits it.

- `[F]` `src/functualize/_config/vault_paths.py` (new),
  `src/functualize/_config/vault.py` (remove the function, re-export the name),
  `tests/config/test_vault_paths.py` (new)
- `[G]` `grep -rn "^from cryptography\|^import cryptography" src/functualize/_config/vault_paths.py` → **0 hits**. The module must be importable without `cryptography`; it is the cold-boot gate.
- `[G]` `python -c "import functualize._config.vault_paths"` with `cryptography` uninstallable is out of scope to test, so assert the weaker, checkable form: `vault_paths` imports only from `functualize._primitives`.
- `[G]` A vault written from `<project>/` is found from `<project>/src/`. New test.
- `[G]` The two existing importers are untouched. **Gate corrected during execution:** as authored this predicted the grep would "still return 3 files", but after the move the new definition site matches its own grep, so the honest count is **4** (`_app/boot.py`, `_config/vault.py`, `_config/vault_paths.py`, `app/utils.py`). Counting files was the wrong instrument for the claim, which is that the re-export works — now asserted directly: `functualize._config.vault.vault_path_for_project is functualize._config.vault_paths.vault_path_for_project`, and both importing modules import cleanly.
- `[G]` `uv run pytest tests/config/ -q` green.

### [x] T1.2 — `VaultKeyInitializer` protocol

Additive structural capability beside `VaultKeyProvider`; read-only providers
stay valid.

- `[F]` `src/functualize/_types/protocols.py`, `src/functualize/plugin/__init__.py`, `tests/plugin/test_vault_key_provider.py`
- `[G]` A class with only the four `VaultKeyProvider` methods is **not** an instance of `VaultKeyInitializer`; adding `initialize_key` makes it one. `@runtime_checkable`, matching `VaultKeyProvider`.
- `[G]` `from functualize.plugin import VaultKeyInitializer` imports.
- `[G]` `uv run lint-imports` → 7 kept, 0 broken.

### [x] T1.3 — ADR-023, and the ADR-016 amendment

One ADR covers both: the new public protocol, and narrowing ADR-016 §7 for
present-but-unopenable entries (spec §8.1). Prior art is contradicted in
writing, not silently.

- `[F]` `contributor/adr/023-local-vault-access.md` (new), `contributor/adr/016-remote-source-activation.md` (amendment note in §7)
- `[G]` ADR-016 §7 links forward to ADR-023; ADR-023 states what still falls through (absent entry, declared-but-unsynced annotation) and what now refuses.
- `[G]` ADR-023 records the D6 trade-off: one user key now reaches every project's vault.

### [x] T1.4 — Move the vault command group out of `builtins.py`

Pure mechanical move, **no behavior change**, following the `plugin_cmd.py` /
`self_cmd.py` precedent. Done first so every later CLI task edits the new file.

- `[F]` `src/functualize/_cli/vault_cmd.py` (new), `src/functualize/_cli/builtins.py` (delete lines 2640–2891, add the 2-line mount)
- `[G]` `wc -l < src/functualize/_cli/builtins.py` → **≤ 2935** (from **3182**; the group is **253** lines).
- `[G]` `grep -c "vault_app" src/functualize/_cli/builtins.py` → **2** (the import and the `_mount` call), down from 9.
- `[G]` `uv run pytest tests/cli/test_vault_commands.py -q` green **unchanged** — this task must not alter a single assertion.
- `[G]` `uv run lint-imports` → 7 kept.

---

## Wave 1 — key providers and the store schema

### [x] T2.1 — One key per user; keyring becomes an extra (D5, D6)

- `[F]` `src/functualize/_config/vault_keys.py`, `pyproject.toml`, `tests/config/test_vault_keys.py`
- `[D]` T1.2
- `[G]` `KeychainKeyProvider.get_key` ignores `project_id`: two different project ids return the same key. It satisfies `VaultKeyInitializer`; `EnvKeyProvider` does not.
- `[G]` `grep -n "keychain" pyproject.toml` shows an `[project.optional-dependencies]` entry; `keyring` is **absent** from the base `dependencies` list.
- `[G]` `initialize_key` is idempotent — two calls return identical bytes, `len == KEY_BYTES` (32).
- `[G]` `tests/config/test_vault_store.py::TestProjectScoping::test_one_project_cannot_read_anothers_entry` passes **unchanged**. It already uses one key across two files and asserts isolation comes from the files, so it encodes D6's position; if it fails, D6 was implemented wrong.

### [x] T2.2 — Schema v1 and the in-place upgrade (D1)

The one step that touches existing rows. SQLite cannot drop `NOT NULL` with
`ALTER`, so `secrets` is rebuilt inside one transaction — see `schema.md` §3.

- `[F]` `src/functualize/_config/vault.py`, `tests/config/test_vault_store.py`
- `[D]` T1.1 (same file)
- `[G]` A v0 store (built by today's `_SCHEMA`, three rows) opens after upgrade with **all three rows present and `ciphertext`/`nonce` byte-identical**, `origin == "provider"` on each, and `PRAGMA user_version == 1`.
- `[G]` Running `_upgrade` twice changes nothing (row count, `user_version`, and every ciphertext equal).
- `[G]` A fresh store is created at v1 directly.
- `[G]` A `direct` row inserts with `annotation`, `provider`, `synced_at` all `NULL` — impossible before this task.
- `[G]` `uv run pytest tests/config/test_vault_store.py -q` green.

---

## Wave 2 — store operations

### [x] T3.1 — Check value, no-clobber `put`, `delete`, honest audit

- `[F]` `src/functualize/_config/vault.py`, `tests/config/test_vault_store.py`
- `[D]` T2.2
- `[G]` `opens_with(key)` returns `True` for the writing key, `False` for another, and `None` on a store with no `vault_meta` row (an upgraded v0 store) — and **never decrypts a `secrets` row** to answer.
- `[G]` The check row is written by the first `put`/`sync`, not before: a store whose file was created but never written has no `vault_meta` row.
- `[G]` `put` on an existing key without `replace=True` raises rather than overwriting; today's `ON CONFLICT DO UPDATE` is gone.
- `[G]` `put(origin=PROVIDER)` over an existing `direct` row is refused regardless of `replace` (spec §9.5).
- `[G]` `delete(key)` removes a row of **either** origin, returns its `VaultEntry`, returns `None` for a missing key, and **takes no `encryption_key` argument** — `grep -n "def delete" -A3 src/functualize/_config/vault.py` shows no key parameter.
- `[G]` A direct write records audit action `"put"`, not `"sync"`.

---

## Wave 3 — the seam and the resolution change

### [x] T4.1 — `app/vault.py`: canonical paths and report types

- `[F]` `src/functualize/app/vault.py` (new), `tests/app/test_vault_paths.py` (new)
- `[D]` T3.1, T2.1
- `[G]` **The identity test**: for a job whose config section prefix is its full dotted canonical name, `resolve_canonical_path(app, "infra.deploy.api_token")` produces the same string `VaultSource._qualified("api_token", "infra.deploy")` is asked for at run time. This is why a stored value resolves at all; it is a test, not a comment.
- `[G]` Rightmost split: a job named `infra.deploy` with field `api_token` resolves; `infra.deploy` with a field containing a dot is rejected as nested.
- `[G]` A `Secret[str]` **function parameter** on a job with no config model is rejected with `field_not_config_model` — the B1 finding.
- `[G]` Flag spelling `infra.deploy.api-token` resolves to `api_token`; the report echoes the canonical form.
- `[G]` Every report dataclass is reflected over: no field named `value`, `ciphertext`, `nonce` or `key`, and no field typed to hold one.
- `[G]` `uv run lint-imports` → 7 kept. `app/vault.py` imports no peer layer.

### [x] T4.2 — `VaultSource`: present-but-unopenable refuses (D2)

- `[F]` `src/functualize/_config/vault_source.py`, `tests/config/test_vault_miss.py`
- `[D]` T3.1
- `[G]` Entry **absent** + no key → falls through, unchanged; the existing miss and fall-through tests pass untouched.
- `[G]` Entry **present** + no key → refuses; a lower-precedence env value is **not** returned.
- `[G]` Entry present + wrong key → refuses (already true; must stay true).
- `[G]` The decision is made via `opens_with`, so no secret is decrypted to reach it.
- `[G]` The refusal message names `vault sync`, `vault remove PATH` and `vault clear`.
- `[G]` Staleness behavior is untouched: `uv run pytest tests/config/test_vault_staleness.py -q` green.

---

## Wave 4 — operations and composition

### [x] T5.1 — `app/vault.py`: the four operations

- `[F]` `src/functualize/app/vault.py`, `tests/app/test_vault_seam.py` (new)
- `[D]` T4.1
- `[G]` `vault_init` with `--key-source env` writes nothing anywhere: the vault file does not appear, and the keyring is not called.
- `[G]` `vault_put` validates the path **before** reading any input — a bad path with a value on stdin consumes nothing.
- `[G]` `vault_remove` succeeds with **no key available at all**, for both origins, and sets `warning` only for `direct`.
- `[G]` `vault_inspect` on a store it cannot open still reports origin and timestamps, with `readability == "wrong_key"` or `"key_unavailable"`.

### [x] T5.2 — Collapse the two chain call sites into one

Maintainer decision (plan §3.6): merge, do not guard. The guard was already
tried on this function — `tests/core/test_app_persistent_consumer_api.py:219`
exists because `environment` was omitted here once and leaked a prod config file
into a dev run — and the next argument, `remote_source`, was omitted anyway.

- `[F]` `src/functualize/_app/boot.py`, `src/functualize/_app/impl.py`, `src/functualize/app/core.py`
- `[D]` T1.1
- `[G]` **Gate corrected during execution:** as authored this said `grep -c "build_resolution_chain(" boot.py` → 0, which can never hold — that substring also matches the function's own `def` and `_build_resolution_chain`. The claim is about *call sites*, so it is now matched as such: `grep -rnE "(^|[^_a-zA-Z])build_resolution_chain\(" src/functualize/ --include=*.py`, excluding the `def` line, returns exactly **1** (`_app/impl.py`). Asserted by a test that walks the tree, since the defect is structural.
- `[G]` `custom_regex` is computed in exactly one place. `grep -rn "file_pattern" src/functualize/_app/ src/functualize/app/core.py` → the comparison appears **once**, using `type(app._config_sources).file_pattern` (boot's internal-safe form, which needs no public import).
- `[G]` `uv run lint-imports` → 7 kept, 0 broken. This is the check the original split existed to satisfy; the merge must not break it.
- `[G]` The prior-drift regression still passes untouched: `uv run pytest tests/core/test_app_persistent_consumer_api.py -q` green, including `test_rebuilt_chain_excludes_inactive_environment_files`.
- `[G]` `FunctualizeApp.refresh()` leaves a vault source in the chain — the defect that exists today.

### [ ] T5.3 — Dormant vault source (spec §8 rule 2)

- `[F]` `src/functualize/_app/boot.py`, `tests/app/test_remote_first.py`
- `[D]` T5.2, T4.2
- `[G]` **The cold-boot gate**: for a project with no vault file, booting imports neither `functualize._config.vault` nor `cryptography`. Assert on `sys.modules` after a boot in a subprocess.
- `[G]` `remote=True` behavior is unchanged: the existing `build_remote_source` tests pass, renamed call included.
- `[G]` A `classic()` app **with** a vault file gets a vault source; without one, gets `None`.
- `[G]` **Sabotage**: removing the dormant branch makes an E2E test in T8.1 fail, not only a unit test.

---

## Wave 5 — new CLI commands

### [ ] T6.1 — `init`, `put`, `inspect`, `remove`

- `[F]` `src/functualize/_cli/vault_cmd.py`, `tests/cli/test_vault_commands.py`
- `[D]` T5.1, T1.4
- `[G]` Non-TTY `put` with neither `--stdin` nor `--file` exits `ExitCode.USAGE` (2) and **does not block** — asserted with a timeout.
- `[G]` stdin strips exactly one trailing `LF`/`CRLF` and preserves everything else; empty input is refused.
- `[G]` `init` on a machine with no keyring exits `ExitCode.REFUSED` (3) and its message names **both** `functualize[keychain]` and the `keygen` → export route.
- `[G]` `--json` failure envelopes carry a stable `reason` for every code in `contracts.md` §2; no human-stderr parsing is needed to classify a failure.
- `[G]` `_vault_app(ctx)`'s error text no longer hardcodes "`vault sync` needs the application" — it names the invoked command.

---

## Wave 6 — existing CLI commands

### [ ] T7.1 — Origin-aware `list`/`status`/`clear`/`sync`

- `[F]` `src/functualize/_cli/vault_cmd.py`, `tests/cli/test_vault_commands.py`
- `[D]` T6.1 (same file), T3.1
- `[G]` `list` renders a store containing **one direct and one provider** entry without raising. Today's renderer measures `len(entry.provider)` and calls `entry.synced_at.isoformat()`; the authoring grep found **4** such field reads, all in the moved group.
- `[G]` `list --json` emits `null` for `provider`/`annotation`/`synced_at` on a direct entry, and every pre-existing field is still present.
- `[G]` `clear --json` exists and reports direct and provider counts separately; `clear` still needs no key.
- `[G]` `status --json` carries `direct_entries`, `provider_entries`, `key_matches_store`.
- `[G]` `sync` against a store whose check value the resolved key does not open **refuses before writing**, with reason `key_mismatch` and a `would_orphan` list. No new row is written.
- `[G]` `sync` over an existing direct entry reports `direct_entry_conflict` in `failed`, retains other successes, exits non-zero.

---

## Wave 7 — proof

### [ ] T8.1 — Reachability and cold/warm parity (AC-2, AC-3, AC-13)

- `[F]` `tests/integration/test_local_vault_e2e.py` (new)
- `[D]` all prior
- `[G]` The full journey runs through the **public CLI**: `init` → `put` → job run, with the job receiving the submitted secret as `Secret[str]`.
- `[G]` The same value resolves through direct `FunctualizeApp` execution, not only `func` dispatch.
- `[G]` Identical result on cold discovery and on a second boot using the discovery cache.
- `[G]` Precedence: explicit argument beats vault; vault beats env, file and default; removing the entry restores the previous resolution.
- `[G]` **Sabotage, per `contributor/guides/wiring-discipline.md` §3 — commit first.** Break each composition wire in turn (`boot.build_vault_source`, `impl._build_resolution_chain`) and confirm a test fails for each. Then `git checkout --`.
- `[G]` Offline: the job run succeeds with outbound access denied and makes no provider call.

### [ ] T8.2 — No plaintext anywhere (AC-10)

- `[F]` `tests/integration/test_local_vault_no_plaintext.py` (new)
- `[D]` all prior
- `[G]` For a distinctive submitted secret, the exact bytes are absent from stdout, stderr, logs, JSON, exception text, the database file **and its `-wal` / `-shm` sidecars** — WAL is on (`PRAGMA journal_mode=WAL`), so the sidecars are real and must be scanned.
- `[G]` Swept across `init`, `put`, `inspect`, `list`, `status`, `remove`, `clear`, `sync` and a job run.

### [ ] T8.4 — An example project that uses the public vault API

**Added during Execute, at maintainer request.** The public seam is only proven
public if something outside the framework uses it the way a user would. The
`_cli` layer dogfoods it, but `_cli` is ours; an example is theirs.

- `[F]` `examples/quickstart/step9_vault/` (`secrets_job.py`, `test_step9.py`, `conftest.py`), `examples/quickstart/README.md`
- `[D]` T5.1 (the operations), T6.1 (the commands it documents)
- `[G]` The example job declares a `Secret[str]` config field and receives the value from the vault — through `FunctualizeApp`, not through `func`, so it proves the seam is reachable without the CLI.
- `[G]` It calls `vault_init`, `vault_put`, `vault_inspect` and `vault_remove` from `functualize.app.vault` — the public path, never `_config`.
- `[G]` `grep -rn "functualize\._" examples/quickstart/step9_vault/` → **0 hits**. An example reaching into an internal package would be documenting a layer violation.
- `[G]` `uv run pytest examples/quickstart/step9_vault/ -v` green. Note `testpaths = ["tests"]`, so the root pytest run does not collect it; CI's `examples` job does.
- `[G]` It runs with **no keyring and no network** — the env-key route — so it works in the CI examples job and on a stock install.
- `[G]` The submitted secret does not appear in the example's own output.

### [ ] T8.3 — Documentation

- `[F]` `docs/guides/configuration.md`, `README.md`, `CHANGELOG.md`
- `[D]` all prior
- `[G]` `docs/guides/configuration.md:566` — *"With no key at all the vault does not open. There is no plaintext fallback: resolution falls through to the next source"* — is corrected. D2 makes that sentence false for a **present** entry. This is a required edit, not a `/sync-docs` leftover.
- `[G]` The key-provider table records that both shipped providers are user-scoped.
- `[G]` CHANGELOG records the three behavior changes: presence-based refusal, keychain key scope, nullable `list --json` fields.
- `[G]` `uv run pytest tests/ -q` green; `uv run lint-imports` → 7 kept, 0 broken.

---

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1.1", "1.2", "1.3", "1.4"] },
    { "id": 1, "tasks": ["2.1", "2.2"] },
    { "id": 2, "tasks": ["3.1"] },
    { "id": 3, "tasks": ["4.1", "4.2"] },
    { "id": 4, "tasks": ["5.1", "5.2"] },
    { "id": 5, "tasks": ["5.3"] },
    { "id": 6, "tasks": ["6.1"] },
    { "id": 7, "tasks": ["7.1"] },
    { "id": 8, "tasks": ["8.1", "8.2", "8.3", "8.4"] }
  ]
}
```

Wave construction notes:

- **Disjoint file sets hold within every wave.** `_config/vault.py` is touched
  by 1.1, 2.2 and 3.1 — all in different waves, deliberately. `app/vault.py` is
  touched by 4.1 and 5.1; `_cli/vault_cmd.py` by 1.4, 6.1 and 7.1; `_app/boot.py`
  by 5.2 and 5.3. Each pair is serialized rather than parallelized.
- **5.2 before 5.3, in its own wave.** The merge is a behavior-preserving
  refactor of the composition root; the dormant source is a behavior change.
  Landing them together would make a regression in either one hard to attribute,
  and 5.2 is the task whose whole claim is "nothing observable changed".
- **1.4 runs first on purpose.** Moving the command group before anything is
  added to it means 6.1 and 7.1 edit one new file instead of racing
  `builtins.py`, and the move stays reviewable as a pure no-op diff.
- **Wave 8 is a checkpoint wave.** Its three tasks touch only new test files and
  docs, so they are genuinely parallel, and each depends on all prior work.
