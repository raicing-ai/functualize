# Tasks — Remote source activation

Gates were run at authoring time against `537efe7`; each task records the count
its command returned, so drift between authoring and execution is visible.
`[F]` equals the gate's hit set.

---

## 1. Foundations

- [x] **1.1 — ADR: activating the remote layer**
  Records the decision STATUS #16 says needs one: `remote_first()` is wired,
  not removed; the vault is the read path; providers are plugins.
  Must also record the **commercial-boundary divergence** (`spec.md` closing
  note): the Lark proposal places the paid boundary at the plugin seam, the
  maintainer's direction places FuncCloud in core by default.
  - `[F]` `contributor/adr/016-remote-source-activation.md`
  - Acceptance: the ADR names both positions and which one this repo builds to.
  - Not gated by the spec hook (`contributor/` is exempt), but sequenced first
    because 2.1 and 3.1 encode its decisions.

- [x] **1.2 — `VaultKeyProvider` protocol + entry-point group** — DONE
  Declare the protocol, register the group in `pyproject.toml`.
  - `[F]` `src/functualize/_types/protocols.py`,
    `src/functualize/plugin/__init__.py`, `pyproject.toml`,
    `tests/plugin/test_vault_key_provider.py`,
    `tests/test_public_api_surface.py`
  - Acceptance: a test asserts a duck-typed object satisfies the
    `@runtime_checkable` protocol. `uv run lint-imports` green. **Met** — 6
    tests, including a negative case (a provider missing `get_key` is
    correctly rejected).
  - Acceptance: `grep -c "functualize.vault_key_providers" pyproject.toml` = 1.
    **Met.**

  **Three deviations from this task as written, disclosed:**

  1. **Declaration site.** Written as `plugin/__init__.py`; declared in
     `_types/protocols.py` and re-exported from `functualize.plugin`. That is
     where the plugin-author protocol family already lives — `JobProvider`,
     `AdapterPlugin`, `Source`, `FormatProvider`, `JobTransform` — and
     `plugin/protocols.py` is scoped to TUI extension points
     ("Extension protocols for TUI architecture v2"). `_types` is stdlib-only
     and this protocol is too, so the layer rule holds; `lint-imports` confirms.

  2. **`tests/test_public_api_surface.py` was outside `[F]` and failed.** It
     pins `__all__` for every public package and refused the addition:
     *"functualize.plugin: unexpected additions to __all__:
     ['VaultKeyProvider']"*. Intentional, so it is registered there. Same class
     as the `test_discovery_hash.py` gap found in `third-party-host-seams`/2.1
     — a designed tripwire outside the task's declared scope. `[F]` updated.

  3. **The entry-point group ships EMPTY.** It was briefly registered with
     `env` and `keychain` pointing at `_config/vault_keys.py`, which task 2.2
     has not built. A group entry naming a module that cannot import surfaces
     on any command scanning the group — the same hazard flagged for
     third-party skills. The group is declared with a comment naming 2.2 as
     what fills it.

  **Verification.** 72 tests pass across the protocol, the public-surface pin,
  and the status table. `ruff check`, `ruff format --check`, `lint-imports`
  green.

  **Environment note.** `uv run mypy src/` reported 6 errors in
  `_cli/tui/functualize_autocomplete.py` — a file untouched by this work. Cause
  was a missing `textual-autocomplete`, not code: `uv sync --all-extras` then
  `mypy src/` → *Success: no issues found in 312 source files*. Anyone running
  a checkpoint gate without `--all-extras` will see a false red here
  (STATUS follow-up #1).

- [x] **1.3 — `RunStatus` → HTTP table, beside the enum** — DONE
  The mapping from `contracts.md` §7, declared once in `_types/`.
  - `[F]` `src/functualize/_types/http_status.py` (new),
    `tests/types/test_http_status.py`
  - Acceptance: a test asserts the table covers **every** `RunStatus` member —
    parameterized over the enum, so a new member fails rather than defaulting.
  - `_types/` is stdlib-only; a plain dict over an enum keeps that true.
  - Note the Lark finding *"six incompatible answers to 'is it finished?'"*:
    this is a seventh **consumer**, not a seventh partition, because it is
    declared once and imported. Do not inline it anywhere.

  **Two deviations from this task as written, disclosed:**

  1. **Placement.** Written as `_types/enums.py`; built as a new sibling module
     `_types/http_status.py`. `_types/exit_codes.py` is the existing precedent
     — it answers the same question for the process boundary and lives in its
     own module rather than inside `enums.py`. Matching it keeps the two
     tables legible side by side. `[F]` updated above.

  2. **The enum has NINE members, not eight.** `RunStatus.REFUSED` exists
     (`_types/enums.py:32`) and post-dates the Lark finding this task quoted.
     `contracts.md` §7's table listed eight and omitted it; corrected there.
     REFUSED maps to **412 Precondition Failed** — its docstring is "a declared
     precondition for running it was not met", and `_STATUS_EXIT_CODES` already
     keeps it distinct from FAILURE at exit code 3 for the same reason.

     The parameterized-over-the-enum criterion is what caught this, before any
     code was written. It is worth keeping for exactly that reason.

  **Verification.** 24 tests pass. Reachability proven by sabotage: removing
  `RunStatus.REFUSED: 412` from the table fails
  `test_every_terminal_status_is_mapped_explicitly` **and**
  `test_refused_is_distinct_from_failure`, 2 failed / 22 passed, then restored
  green. `ruff check`, `ruff format --check`, `mypy`, `lint-imports` all green
  — including the *"Types import nothing internal"* contract.

---

## 2. The vault

- [x] **2.1 — V3: the encrypted store** — DONE
  SQLite (stdlib) in WAL mode at
  `$XDG_DATA_HOME/functualize/vaults/<project_id>/vault.db`, per
  `contracts.md` §4. AES-256-GCM per value, fresh nonce per entry. Reuses
  `compute_project_id` (`_primitives/locator.py:527`) and `_xdg_data_dir()`.
  - `[F]` `src/functualize/_config/vault.py`, `pyproject.toml`, `tests/config/test_vault_store.py`
  - Acceptance: a test writes a value, then asserts the **raw file bytes do not
    contain the plaintext**. **Met** — see the finding below; the test as first
    written did *not* meet it.
  - Second acceptance: two different `project_id`s produce two files, and one
    cannot read the other's entry (`spec.md` A7). **Met.**
  - Third acceptance: a wrong key fails **authentication** and raises an error
    naming the key provider in use — never returns garbage. **Met**, plus a
    test that the error does not leak the value.
  - `uv run lint-imports` green: `_config` must not acquire a `_cli` or public
    import. **Met** — all 5 contracts kept.

  **Finding: the headline acceptance test was vacuous, and sabotage caught it.**

  `test_the_plaintext_is_not_in_the_file` read `vault.path.read_bytes()` and
  passed. Under sabotage — `put()` storing the plaintext instead of the
  ciphertext — **it still passed**, while five other tests failed.

  Cause: in WAL mode a fresh write lands in the `-wal` sidecar and the main
  database file can still be empty. So the one assertion the acceptance
  criterion names was asserting against an empty file.

  Rewritten as `test_the_plaintext_is_in_no_file_the_vault_writes`, which scans
  every file the vault produces and asserts it wrote *something* first, plus a
  second test that checkpoints the WAL and re-checks the main database. Under
  the same sabotage both now fail (6 failed / 19 passed), and both pass
  restored.

  This is the reason the workflow requires breaking the call rather than
  trusting a green run: 25/25 passed on the first attempt against a test that
  could not fail.

  **Also done here:** `cryptography>=42.0.0` added to core `dependencies` with
  a comment recording *why* it is core rather than an extra (ADR-016) and that
  the standalone-binary cost is accepted and measured at checkpoint.

  **Verification.** 25 tests. `ruff check`, `ruff format`, `mypy`,
  `lint-imports` green.

- [ ] **2.2 — V4: the two key providers**
  `EnvKeyProvider` (non-interactive, `FUNCTUALIZE_VAULT_KEY`) and
  `KeychainKeyProvider` (interactive). Resolution order per `contracts.md` §1.
  - `[F]` `src/functualize/_config/vault_keys.py`, `tests/config/test_vault_keys.py`
  - Acceptance: a test asserts the env var **wins when set**, even with an
    interactive provider registered and available.
  - Second acceptance: a test asserts that with **no TTY**, an interactive
    provider is never consulted — the Lambda-hangs-on-a-prompt case.
  - Third acceptance: with no key available at all, the vault does not open and
    there is **no plaintext fallback**.

- [ ] **2.3 — V2: annotation discovery**
  Scan located-but-unresolved config values for `provider://reference`; build
  the `annotations` map `RemoteSource` already accepts. First production caller
  of `parse_annotation`.
  - `[F]` `src/functualize/_config/annotations.py`, `tests/config/test_annotation_scan.py`
  - Acceptance: `grep -rn "parse_annotation" src/functualize/_config/annotations.py`
    ≥ 1. Authoring-time production callers: **0**.
  - Second acceptance: a literal containing `://` — an ordinary URL in a config
    file — is **not** treated as an annotation.
  - Third acceptance: the fallback chain (`a | b`, max 5) parses, and a 6-entry
    chain raises.

---

## 3. Wiring

- [ ] **3.1 — V1: the boot path builds the chain**
  `build_resolution_chain` (`_app/boot.py:772`) gains an optional remote slot;
  `remote_first()` carries a marker instead of a bare `None`.
  - `[F]` `src/functualize/_app/boot.py`, `src/functualize/app/presets.py`, `tests/app/test_remote_first.py`
  - Acceptance: `grep -c "remote" src/functualize/_app/boot.py` ≥ 1.
    Authoring-time count: **0**.
  - Second acceptance: `remote_first()` with **no** registered provider raises
    at construction, naming the entry-point group. It must **not** degrade to
    `classic()` — that degradation is the defect this feature closes.
  - Third acceptance: `classic()` is byte-identical before and after. One
    builder serves both; a regression here means they have drifted.
  - Reachability: `FunctualizeApp(config_sources=remote_first())` → boot →
    chain. Verify by removing the remote slot and watching the test fail.
  - `[verify-e2e:TARGETED]`

- [ ] **3.2 — V6: a miss falls through, loudly**
  Warn naming the key, its annotation, **which source answered instead**, and
  the fix command. Never render the value.
  - `[F]` `src/functualize/_config/vault.py`, `src/functualize/_app/boot.py`, `tests/config/test_vault_miss.py`
  - Acceptance: a test asserts the next source's value **is** returned and a
    warning **is** emitted naming the annotation.
  - Second acceptance: the warning fires **once per key per run**, not per
    access — a job reading one secret ten times warns once.
  - Third acceptance: ADR-008 — the warning contains no plaintext value. Assert
    against a value that would be conspicuous if leaked.

- [ ] **3.3 — V5: staleness warning**
  `synced_at` per entry; `[vault] max_age` (default `24h`); warn and **still
  run**.
  - `[F]` `src/functualize/_config/vault.py`, `src/functualize/app/config.py`, `tests/config/test_vault_staleness.py`
  - Acceptance: a test with a backdated vault asserts a warning **and**
    `RunStatus.SUCCESS` — offline work must stay possible.

---

## 4. Surfaces

- [ ] **4.1 — V6: the `builtin vault` family**
  `sync`, `list`, `status`, `clear`, `keygen` per `contracts.md` §6.
  - `[F]` `src/functualize/_cli/builtins.py`, `src/functualize/app/utils.py`, `tests/cli/test_vault_commands.py`
  - Acceptance: `func builtin vault list --json` renders names, providers and
    `synced_at` with **no** value present anywhere in the payload.
  - Flag spelling is `--json`, matching `builtin info` as shipped. **Not**
    `--output json` — that option does not exist
    (`Error: No such option '--output'`, verified at authoring time).
  - `_cli` reaches the vault through `app/utils.py`, never `_config` directly;
    `lint-imports` is the gate.

- [ ] **4.2 — §7: the trigger plugins consume the status table**
  Lambda and HTTP both read the `_types/` table from 1.3.
  - `[F]` `plugins/functualize-lambda/src/functualize_lambda/__init__.py`, `plugins/functualize-http/src/functualize_http/__init__.py`, `plugins/functualize-lambda/tests/`
  - Acceptance: a test asserts a `BLOCKED` result reaches the Lambda handler as
    **202**, not 200. Authoring-time behaviour: `{"statusCode": 200, "body":
    null}` for *every* outcome, because `result.status` is never read
    (`__init__.py:126`). Closes STATUS #21.
  - Second acceptance: parameterized over all **8** statuses.
  - Depends on `discovery-and-gate-defects`/3.3 landing, which is what makes an
    unresolvable gate produce `BLOCKED` instead of raising.

---

## 5. Providers

- [ ] **5.1 — `functualize-aws`**
  `aws-sm` (Secrets Manager) and `aws-ssm` (Parameter Store, incl.
  `SecureString`). Registered through `functualize.remote_providers`.
  - `[F]` `plugins/functualize-aws/`, `tests/…`
  - Acceptance: an integration test against a local Floci container
    (`floci/floci:latest`, port 4566) resolves a secret, a `String`, a
    `SecureString`, and a fallback chain (`spec.md` A9). The endpoint comes
    from `AWS_ENDPOINT_URL`, so any LocalStack-compatible emulator works.
  - Second acceptance: `grep -rn "boto3" src/functualize/` returns **0** —
    core must not import the provider's dependency.
  - The probe proved this shape at authoring time; each provider was ~10 lines.

- [ ] **5.2 — `functualize-bitwarden`**
  Bitwarden Secrets Manager, same seam.
  - `[F]` `plugins/functualize-bitwarden/`, `tests/…`
  - Acceptance: tested against a fake, not a live account. Only the AWS pair
    gets a live integration test.
  - Confirm the target product before building: **Bitwarden Secrets Manager**
    (`bws`), not the password-manager CLI.

---

## 6. Documentation

- [ ] **6.1 — Document the remote layer**
  `docs/guides/configuration.md` gains the annotation syntax, the vault, the
  key seam and the sync workflow. Correct the existing text that says
  `remote_first()` is not wired.
  - `[F]` the doc files touched
  - Acceptance: every snippet executes; `mkdocs build --strict` exits 0.
  - Sequenced last so it describes shipped behaviour.

---

## 7. Checkpoint

- [ ] **7.1 — Full gate run**
  - Acceptance: `uv run pytest`, `uv run ruff check src/ tests/`,
    `uv run ruff format --check src/ tests/`, `uv run mypy src/`,
    `uv run lint-imports` — all green.
  - Walk `spec.md`'s A1–A10 item by item and record each as met.
  - Measure the standalone binary size delta from `cryptography` across the
    7 build targets and record it (`plan.md` §5).
  - `[verify-e2e:FULL]`

---

## Task Dependency Graph

1.1 is the ADR both 2.1 and 3.1 encode. 1.2 declares the protocol 2.2
implements. 1.3 declares the table 4.2 consumes. 2.1 builds the store 3.2 and
3.3 extend, and 4.1 renders. 2.3 produces the annotation map 3.1 assembles.
5.1 and 5.2 are independent of each other and of the wiring — they only need
the protocol, which already exists unchanged.

Disjoint file sets, checked per wave:

| Wave | Task | Files |
|---|---|---|
| 0 | 1.1 | `contributor/adr/` |
| 1 | 1.2 | `plugin/__init__.py`, `pyproject.toml` |
| 1 | 1.3 | `_types/enums.py` |
| 1 | 5.1 | `plugins/functualize-aws/` |
| 1 | 5.2 | `plugins/functualize-bitwarden/` |
| 2 | 2.1 | `_config/vault.py`, `pyproject.toml` |
| 2 | 2.3 | `_config/annotations.py` |
| 3 | 2.2 | `_config/vault_keys.py` |
| 3 | 3.1 | `_app/boot.py`, `app/presets.py` |
| 4 | 3.2 | `_config/vault.py`, `_app/boot.py` |
| 4 | 4.2 | `plugins/functualize-{lambda,http}/` |
| 5 | 3.3 | `_config/vault.py`, `app/config.py` |
| 5 | 4.1 | `_cli/builtins.py`, `app/utils.py` |
| 6 | 6.1 | `docs/` |
| 7 | 7.1 | — |

1.2 and 2.1 both touch `pyproject.toml`, which is why 2.1 is in wave 2.
3.2 and 3.3 both touch `_config/vault.py` and are therefore in different waves.

```json
{
  "waves": [
    { "id": 0, "tasks": ["1.1"] },
    { "id": 1, "tasks": ["1.2", "1.3", "5.1", "5.2"] },
    { "id": 2, "tasks": ["2.1", "2.3"] },
    { "id": 3, "tasks": ["2.2", "3.1"] },
    { "id": 4, "tasks": ["3.2", "4.2"] },
    { "id": 5, "tasks": ["3.3", "4.1"] },
    { "id": 6, "tasks": ["6.1"] },
    { "id": 7, "tasks": ["7.1"] }
  ]
}
```
