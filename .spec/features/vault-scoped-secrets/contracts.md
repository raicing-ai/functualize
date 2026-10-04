# Contracts — vault-scoped-secrets

External interfaces only: what a caller writes, imports, types or parses.
Internal types — the SQLite row, the chain's private helpers, the declaration
parser — are plan-phase decisions and are not declared here.

Everything below is stated against the branch's merge-base with `master`
(`38561b9`). "Before" is that base; "after" is this branch.

## 1. The identity — `functualize.app.vault.VaultIdentity`

```python
@dataclass(frozen=True)
class VaultIdentity:
    scope: Literal["group", "job"]
    target: str          # the canonical command path, e.g. "deploy" or "deploy.service"
    field: str           # one declared field on that target, e.g. "token"

    def encode(self) -> str: ...                    # the storage key
    @classmethod
    def decode(cls, key: str) -> VaultIdentity: ...
```

- Construction refuses a scope other than `group`/`job` and an empty target or
  field (`ValueError`). It does **not** check the target exists; that is
  `resolve_vault_identity`'s job (§2.1).
- `encode()` is a compact JSON array, `["group","deploy","token"]`, and is the
  SQLite key and AES-GCM associated data. A dot in `target` is never split, and
  `("group", "deploy", "token")` and `("job", "deploy", "token")` encode
  differently. Callers should not parse it: every report in §2 and every JSON
  payload in §4 carries `scope`, `target` and `field` separately.
- Re-exported from `functualize.app.vault` and listed in its `__all__`; defined
  in `functualize._primitives.vault_identity` (stdlib only).

## 2. Public Python API — `functualize.app.vault`

### 2.1 New: `resolve_vault_identity`

```python
def resolve_vault_identity(
    app: Any, *, group: str | None = None, job: str | None = None, field: str
) -> VaultIdentity
```

Validates against the live app before any value is read: exactly one of
`group`/`job`; the target exists (cached and dynamically registered group
declarations both count); the field belongs to that target's group options or
job config model; the field is secret by the existing classification rule.
Returns the canonical spelling (`build_wheel` → `build-wheel`,
`api-token` → `api_token`). Raises `VaultPathError` with `.reason` one of
`scope_required`, `unknown_group`, `unknown_job`, `unknown_field`,
`field_not_secret`, `field_not_config_model`. An ordinary function parameter is
refused; it is not a vault target.

Replaces `resolve_canonical_path(app, path: str) -> ResolvedVaultPath`, which is
**removed** together with `ResolvedVaultPath`.

### 2.2 Changed signatures — a typed identity replaces the dotted string

| Function | Before | After |
|---|---|---|
| `vault_put` | `vault_put(app, path: str, value: str, *, replace=False, cwd=None)` | `vault_put(app, identity: VaultIdentity, value: str, *, replace=False, cwd=None)` |
| `vault_remove` | `vault_remove(app, path: str, *, cwd=None)` | `vault_remove(app, identity: VaultIdentity, *, cwd=None)` |
| `vault_inspect` | `vault_inspect(app, path: str, *, cwd=None)` | `vault_inspect(app, identity: VaultIdentity, *, cwd=None)` |

All three return the same report types as before. A string is not accepted;
`vault_put(app, "report.token", v)` becomes
`vault_put(app, VaultIdentity("job", "report", "token"), v)`.

Behaviour carried over unchanged:

- `vault_put` re-validates the identity (it may not assume the caller did), stores
  a `DIRECT` entry, and refuses an existing entry without `replace=True` and any
  `PROVIDER` entry at that identity.
- `vault_remove` needs no key. An identity that no longer validates (its job or
  group was deleted) is still removed as given, so orphans stay recoverable.
  Removing a direct entry still carries the "no upstream copy" warning.
- `vault_inspect` decrypts nothing. An ineligible identity is reported as
  `eligible=False`, not raised.

### 2.3 Report fields

| Type | Before | After |
|---|---|---|
| `VaultMutationReport` | `path: str` | `identity: VaultIdentity` |
| `VaultInspectionReport` | `path: str` | `identity: VaultIdentity` |

No other field changes. Neither report carries a value.

### 2.4 Errors

- `VaultPathError(reason, message, *, path)` keeps its shape. `path` is now a
  readable label (`--job deploy --field token`), not a storage key. New
  reasons: `scope_required`, `unknown_group`.
- New `VaultFormatError(VaultError)` in `__all__`: the store predates scoped
  identities. Raised by every read or write of such a store. Its message names
  `func builtin vault clear`.

### 2.5 `functualize.app.utils.vault_sync`

The signature is unchanged: `vault_sync(app, cwd=None) -> VaultSyncReport`. The input is now
`[[vault_secret]]` blocks (§3), not inline annotations. `VaultSyncReport.synced`
and `.failed` keep their `(key, provider|reason)` tuple shape. The key is now
an encoded `VaultIdentity` (§1) rather than `section.field`, and `scanned`
counts declaration blocks.

## 3. Config file — `[[vault_secret]]`

```toml
[[vault_secret]]
group = "deploy"                       # exactly one of group / job
field = "token"
source = "aws-sm://prod/deploy-token"  # a provider reference, never a literal

[[vault_secret]]
job = "deploy.service"
field = "iam_key"
source = "aws-sm://prod/deploy-service-iam-key"
```

- Each block needs exactly one of `group`/`job`, plus `field` and `source`. The
  identity is validated as in §2.1 **before any fetch**.
- Blocks are read per discovered file. Two blocks naming one identity, in the
  same file or different files, are refused as a duplicate. File order does not
  pick a winner.
- An inline `provider://reference` value on a **secret** config field is
  refused with an instruction to use `[[vault_secret]]`. This applies to `vault
  sync`, and to a job run even when a higher source (the environment) would
  have supplied the value. A `provider://`-shaped string on a non-secret field
  is ordinary data.
- Only `vault sync` contacts a provider; a run reads the local vault only.

## 4. CLI — `func builtin vault`

### 4.1 Addressing

`put`, `inspect` and `remove` take `--field NAME` and exactly one of
`--group PATH` / `--job PATH`. The positional `<job>.<field>` argument is
removed. Click rejects it as an unexpected extra argument (exit **2**). No
alias exists.

```console
func builtin vault put --group deploy --field token
func builtin vault put --job deploy.service --field iam_key
func builtin vault inspect --group deploy --field token
func builtin vault remove --job deploy.service --field iam_key
```

Validation (§2.1) happens before `put` prompts or reads `--stdin` / `--file`.

### 4.2 JSON payloads

| Payload | Before | After |
|---|---|---|
| `put` / `inspect` / `remove` success | `"path"` | `"scope"`, `"target"`, `"field"` |
| failure envelope that names an entry | `"path"` | `"scope"`, `"target"`, `"field"` |
| `list` entry | `"key"` | `"key"` (now the encoded identity, §1) **plus** `"scope"`, `"target"`, `"field"` — all three `null` for a row that does not decode |
| `sync` `synced` / `failed` item | `"key"` | `"scope"`, `"target"`, `"field"` |
| `sync` `unresolved` item | `"key"`, `"value"` | `"scope"`, `"target"`, `"field"`; `"value"` is gone |

For example, a `put --json` success payload is exactly
`{"ok", "scope", "target", "field", "origin", "created", "replaced", "updated_at"}`.

Human output names an entry as `--group deploy --field token` (`put`, `remove`),
as three `Scope:` / `Target:` / `Field:` lines (`inspect`), and as three columns
(`list`).

### 4.3 New reason codes

Each lands in the failure envelope's `"reason"` field,
`{"ok": false, "reason": "<code>", "message": "..."}`. Human mode prints
`Error: <message>` on stderr. Neither form carries a value.

| `reason` | When | Exit | Commands |
|---|---|---|---|
| `scope_required` | neither or both of `--group`/`--job`, or an empty target/field | **2** (usage) | `put`, `inspect`, `remove` |
| `unknown_group` | `--group PATH` names no declared group options | **2** (usage) | `put` |
| `vault_format_unsupported` | the store predates scoped identities. The message names `func builtin vault clear`; the store is not changed | **3** (refused) | `list`, `status`, `put`, `inspect`, `remove`, `sync` |
| `invalid_declaration` | a `[[vault_secret]]` block is malformed, names an ineligible identity, duplicates another, or a secret field carries a legacy inline reference (§3). Nothing is fetched | **3** (refused) | `sync` |

`clear` stays usable on such a store, and without a key. Its confirmation
prompt says the store is in the old format instead of counting entries.

## 5. Resolution order (observable through any run)

For a group option and a job config field alike:

```text
runtime override > explicit command-line value > vault > environment > config file > model default
```

- Environment spelling: `JOB_FIELD` for a job config field (`DEPLOY_TOKEN`),
  `GROUP__FIELD` for a group option (`DEPLOY__TOKEN`, `DEPLOY_WEB__TOKEN`). A
  group no longer reads the job spelling, and a job no longer reads the group
  spelling.
- An inherited group option resolves under the **declaring** group's identity.
  A nearer declaration uses its own.

### Public protocol — `functualize.plugin.Source`

```python
def get(self, key: str, section: str | None = None, *, scope: Literal["group", "job"] = "job") -> Any | None
def has(self, key: str, section: str | None = None, *, scope: Literal["group", "job"] = "job") -> bool
def keys(self, section: str, *, scope: Literal["group", "job"] = "job") -> set[str]
```

`scope` is new and keyword-only. Every source in the chain receives it. A
third-party source written to the former signature fails with `TypeError`, and
is not silently ignored.

## 6. Deliberately unchanged

- `vault_init` and `func builtin vault init`, `keygen`, `status`'s fields other
  than its legacy-store refusal, and `clear` (still keyless and still confirmed).
- Key handling, providers, freshness, origin rules and missing-versus-unreadable
  behaviour (ADR-016, ADR-023).
- What counts as secret: one rule, `Secret[...]` or the explicit marker
  (ADR-008).
- Group secret masking and CLI/app parity for group options (ADR-009).
- `VaultOrigin`, `Readability`, `WinningSource`, `VaultInitReport` and every
  existing error type other than §2.4's additions.
- There is no migration. An old store is refused (§4.3), never read or rewritten.

## 7. Not a contract

How the identity is stored (schema version, column layout), how the chain hands
scope to sources internally, how declarations are deduplicated, and how the
executor builds group-scoped views.

## Verification walk (`/agentic-verify` step 2b)

One row per declared item. Each names the test that drives it **through a public
entry point**, which means the `func builtin vault` CLI, `functualize.app.vault`
or `functualize.app.utils`, or a `FunctualizeApp` run. Tests that call `_config`
or `_engine` directly are listed only as supporting evidence, never as the
covering test. Walked at `3a91d1f`.

| § | Declared item | Covering test (public entry point) | Status |
|---|---|---|---|
| 1 | `VaultIdentity` constructed by a caller, imported from `functualize.app.vault` | `examples/standalone/secrets_lab/tests/test_vault_lifecycle.py` (all lifecycle tests, and `test_the_example_uses_only_the_published_api`) | covered |
| 1 | group and job with the same text are distinct entries | `tests/cli/test_vault_commands.py::TestScopedFlags::test_group_and_job_entries_with_the_same_text_stay_distinct` (CLI put/list/remove/inspect); `tests/app/test_vault_seam.py::TestScope::test_group_and_job_entries_with_the_same_text_stay_distinct` | covered |
| 1 | a dotted target is not split | `tests/app/test_vault_paths.py::test_nested_job_path_is_target_not_field`; e2e `deploy.service` / `deploy.web` in `tests/integration/test_local_vault_e2e.py::TestScopedAcceptance::test_direct_and_provider_entries_resolve_offline_with_scope_and_precedence` | covered |
| 2.1 | `resolve_vault_identity` validates and canonicalizes | `tests/app/test_vault_paths.py::test_same_target_and_field_are_distinct_by_scope`, `::test_canonical_spelling_and_secret_marker`, `::test_ineligible_target_or_field`, `::test_exactly_one_scope_is_required`, `::test_dynamic_group_declaration_is_visible` | covered |
| 2.1 | a function parameter is not a vault target | `tests/integration/test_local_vault_e2e.py::TestScopedAcceptance::test_function_parameter_is_not_a_vault_target` (CLI) | covered |
| 2.1 | `resolve_canonical_path` / `ResolvedVaultPath` removed | No test; `functualize.app.vault.__all__` no longer lists them, and `git grep` finds no reference in `src/`, `docs/` or `CHANGELOG.md` | not covered (absence checked by search only) |
| 2.2 | `vault_put(app, identity, value, ...)` | `examples/.../test_vault_lifecycle.py::test_put_then_run_delivers_the_secret_to_the_job` (put → `app.execute`); `tests/app/test_vault_seam.py::TestPut::*` | covered |
| 2.2 | `vault_put` refuses replace-less overwrite and provider takeover | `tests/app/test_vault_seam.py::TestPut::test_a_second_write_needs_replace`, `::test_it_cannot_take_over_a_provider_entry` | covered |
| 2.2 | `vault_remove(app, identity, ...)`, keyless, orphan-tolerant, direct warning | `examples/.../test_vault_lifecycle.py::test_remove_takes_it_back_and_says_what_was_lost`; `tests/app/test_vault_seam.py::TestRemove::test_it_needs_no_key`, `::test_an_orphan_from_a_deleted_job_can_still_be_removed`, `::test_it_removes_and_warns_only_for_a_direct_entry` | covered |
| 2.2 | `vault_inspect(app, identity, ...)`, ineligible reported not raised | `examples/.../test_vault_lifecycle.py::test_inspect_explains_the_entry_without_revealing_it`, `::test_inspect_explains_why_a_plain_field_is_refused`; `tests/app/test_vault_seam.py::TestInspect::*` | covered |
| 2.3 | `VaultMutationReport.identity` / `VaultInspectionReport.identity` | `tests/app/test_vault_seam.py:148`, `:228` and `:346` assert `report.identity == VaultIdentity(...)`; `tests/app/test_vault_paths.py::test_reports_have_no_plaintext_field` | covered |
| 2.4 | `VaultPathError.reason` `scope_required` / `unknown_group` | `tests/app/test_vault_paths.py::test_exactly_one_scope_is_required`, `::test_ineligible_target_or_field` (its `("group", "missing", "token", "unknown_group")` case) | covered |
| 2.4 | `VaultFormatError` on an old store | `tests/cli/test_vault_commands.py::TestALegacyStore::test_it_is_refused_with_the_clear_instruction` (CLI raises it via the public seam for put/inspect/remove/list/status) | covered |
| 2.5 | `vault_sync` reads `[[vault_secret]]`, reports encoded identities | `tests/cli/test_vault_commands.py::TestSync::test_group_and_job_blocks_store_distinct_scoped_entries` (CLI `sync --json` → `vault_sync`) | covered |
| 3 | exactly-one-scope / field / source per block, validated before fetch | `tests/cli/test_vault_commands.py::TestSync::test_invalid_target_refuses_before_any_fetch` | covered |
| 3 | duplicate identity across files refused before fetch | `tests/cli/test_vault_commands.py::TestSync::test_duplicate_across_files_refuses_before_any_fetch` | covered |
| 3 | legacy inline secret refused — sync and run, even below env | `tests/cli/test_vault_commands.py::TestSync::test_inline_secret_below_environment_is_refused_without_fetch` (CLI), `::test_job_run_refuses_inline_secret_below_environment` (`FunctualizeApp.execute`) | covered |
| 3 | non-secret URL is ordinary data | `tests/cli/test_vault_commands.py::TestSync::test_an_ordinary_url_is_not_synced` | covered |
| 3 | runs never contact a provider | `tests/integration/test_local_vault_e2e.py::TestScopedAcceptance::test_direct_and_provider_entries_resolve_offline_with_scope_and_precedence` (fetch patched to raise during runs); `::TestTheRunIsOffline::test_no_provider_is_contacted` | covered |
| 4.1 | positional form removed | `tests/cli/test_vault_commands.py::TestScopedFlags::test_the_positional_form_is_gone[put/inspect/remove]` | covered |
| 4.1 | `--field` required; validation before input is read | `tests/cli/test_vault_commands.py::TestScopedFlags::test_a_field_is_required`, `::test_group_validation_precedes_reading_input`, `::TestALegacyStore::test_put_refuses_before_the_value_is_read` | covered |
| 4.1 | help shows only the scoped form | `tests/cli/test_vault_commands.py::TestScopedFlags::test_help_shows_the_scoped_form` | covered |
| 4.2 | `scope`/`target`/`field` in JSON payloads | `tests/cli/test_vault_commands.py::test_put_json_success_matches_the_declared_payload` (exact key set), `::TestScopedFlags::test_a_group_secret_is_stored_under_its_own_scope`, `::test_group_and_job_entries_with_the_same_text_stay_distinct` (list/remove/inspect), `::TestSync::test_group_and_job_blocks_store_distinct_scoped_entries` (sync) | covered |
| 4.2 | human `list` columns | `tests/cli/test_vault_commands.py::TestScopedFlags::test_list_renders_scope_target_and_field_as_columns` | covered |
| 4.3 | `scope_required`, exit 2 | `tests/cli/test_vault_commands.py::TestScopedFlags::test_exactly_one_scope_is_required[neither/both × put/inspect/remove]` | covered |
| 4.3 | `unknown_group`, exit 2, before input | `tests/cli/test_vault_commands.py::TestScopedFlags::test_an_unknown_group_is_refused_before_reading_input` | covered |
| 4.3 | `vault_format_unsupported`, exit 3, store unchanged, message names `clear` | `tests/cli/test_vault_commands.py::TestALegacyStore::test_it_is_refused_with_the_clear_instruction[put/inspect/remove/list/status]` | covered |
| 4.3 | `clear` works on an old store without a key | `tests/cli/test_vault_commands.py::TestALegacyStore::test_clear_removes_it_without_a_key`; `tests/integration/test_local_vault_e2e.py::TestScopedAcceptance::test_v1_store_refuses_without_deleting_and_clear_needs_no_key` | covered |
| 4.3 | `invalid_declaration`, exit 3, nothing fetched | `tests/cli/test_vault_commands.py::TestSync::test_duplicate_across_files_refuses_before_any_fetch`, `::test_invalid_target_refuses_before_any_fetch`, `::test_inline_secret_below_environment_is_refused_without_fetch` assert exit 3 and no fetch in human mode; no test reads the `--json` envelope's `"reason"` | partly covered: the JSON reason string is untested |
| 4.2 | `list` keeps `"key"` and adds nullable identity fields; `sync` `unresolved` drops `"value"` | `tests/cli/test_vault_commands.py::TestScopedFlags::test_group_and_job_entries_with_the_same_text_stay_distinct` reads `list` identity fields; no test asserts a `null` identity row or the `unresolved` item shape | partly covered |
| 4.3 | every emitted code is declared | `tests/cli/test_vault_commands.py::test_every_code_the_cli_can_emit_is_declared` (a source scan of `_fail(` and `VaultPathError(` calls, so supporting evidence only; it does not see `sync`'s `invalid_declaration`, which is not emitted through `_fail`) | supporting |
| 5 | CLI > vault > env > file > default, both scopes | `tests/integration/test_local_vault_e2e.py::TestScopedAcceptance::test_direct_and_provider_entries_resolve_offline_with_scope_and_precedence` (env set for both spellings; vault wins; explicit group and job CLI win over vault); `::TestPrecedence::*` (job) | covered |
| 5 | runtime override > command line | `tests/config/test_job_config_view_properties.py` drives `JobConfigView` directly; no test sets `config.set()` inside a run and compares it with a CLI value | not covered through a public entry point |
| 5 | `GROUP__FIELD` for groups, `JOB_FIELD` for jobs | the e2e above (`DEPLOY__TOKEN` vs `DEPLOY_TOKEN` resolve to different fields); `tests/group_options/test_group_options_injection.py::TestGroupOptionsInjection::test_the_facade_resolves_the_same_non_cli_layers` (`app.execute`) | covered |
| 5 | inherited identity; nearer declaration wins | the e2e above: `deploy.web.web` reads group `deploy`'s entry, then `deploy.web`'s once it is put | covered |
| 5 | `functualize.plugin.Source` passes `scope` to a third-party source | `tests/config/test_resolution_chain.py` exercises `ResolutionChain` with test doubles directly; no test installs a custom `Source` through `ConfigSources(config_resolution_chain=...)` and runs a group-scoped job | not covered through a public entry point |

**Remaining work this walk found:** three rows lack a public-entry-point test,
and two more are covered only in part.

Not covered:

- `resolve_canonical_path` / `ResolvedVaultPath` removal is a negative claim,
  established by search rather than a test.
- runtime override over command line is tested only on `JobConfigView`.
- `Source.scope` reaching a third-party source is tested only on the chain.

Partly covered:

- `sync --json`'s `invalid_declaration` reason string.
- the `list` null-identity row and the `sync` `unresolved` item shape.

None of these is a behaviour this branch is known to get wrong. Each is a
declared surface no test drives through its public entry point. Closing them
needs new tests and therefore a new review round.
