# Contracts: local-vault-access

This file defines externally observable surfaces. Internal SQLite tables and
private implementation types belong in `schema.md` during Plan.

## 1. Canonical path

```text
VaultPath := <command-segment>("."<command-segment>)*"."<field-name>
```

- Command segments are the exact strings in the published command-tree path,
  in their normalized lowercase-hyphenated registration spelling.
- The field is a top-level property name from the canonical job input schema
  **and must come from the job's config model** (`from_config_model`). A secret
  plain function parameter is not addressable: config resolution never reads
  one, so no value stored against it could ever be delivered.
- The field segment is the **config-model field name** (`api_token`), which is
  the string resolution is keyed on — not the CLI flag spelling
  (`--api-token`). Flag spelling is accepted on input and normalized; every
  report echoes the canonical form.
- **Parsing is a rightmost split**: everything before the final dot is the job's
  full dotted name, everything after it is the field. Correct because a
  registered job carries its group in its canonical name, and stable for a leaf
  name containing a dot.
- The identified command must be a runnable job.
- The field descriptor must have `secret = true`.
- Example: command path `infra deploy`, field `api_token` →
  `infra.deploy.api_token`.

Nested field paths are not accepted in this increment.

**Store location.** The project is the directory found by walking upward for
`.functualize/`, falling back to hashing the working directory. Every surface
here and the resolution path resolve it identically.

## 2. CLI contracts

### 2.1 Initialize

```text
func builtin vault init [--key-source TEXT] [--json]
```

Human success output names the provider identifier and whether the key was
created or already existed. It never prints the key, and it never says a
generic "initialized": `created: true` renders as "created a key in your OS
keyring", `created: false` with `key_source: "env"` renders as "validated
$FUNCTUALIZE_VAULT_KEY — nothing was written".

The key is **user-scoped**, so no project appears in the response.

JSON success:

```json
{
  "ok": true,
  "key_scope": "user",
  "key_provider": "string",
  "created": true
}
```

Reason codes:

- `unknown_key_source`
- `key_source_unavailable`
- `key_source_not_initializable`
- `key_missing`

`key_source_unavailable` on a stock install is the teaching surface: its
`message` names both `pip install 'functualize[keychain]'` and the
`keygen` → export → `--key-source env` route.

`init` writes nothing to the vault file, so it has no `existing_store_unreadable`
case.

### 2.2 Put

```text
func builtin vault put PATH [--stdin | --file FILE] [--replace] [--json]
```

JSON success:

```json
{
  "ok": true,
  "path": "deploy.api_token",
  "origin": "direct",
  "created": true,
  "replaced": false,
  "updated_at": "RFC-3339 timestamp"
}
```

Reason codes:

- `unknown_job`
- `unknown_field`
- `field_not_secret`
- `field_not_config_model`
- `nested_field_not_supported`
- `input_source_required`
- `conflicting_input_sources`
- `invalid_utf8`
- `empty_value`
- `entry_exists`
- `provider_entry_conflict`
- `key_unavailable`
- `decryption_failed`

No response shape has a `value`, `ciphertext`, `nonce`, or `key` field.

### 2.3 Inspect

```text
func builtin vault inspect PATH [--json]
```

JSON success:

```json
{
  "ok": true,
  "path": "deploy.api_token",
  "eligible": true,
  "exists": true,
  "origin": "direct",
  "provider": null,
  "reference": null,
  "created_at": "RFC-3339 timestamp",
  "updated_at": "RFC-3339 timestamp",
  "synced_at": null,
  "key_provider": "keychain",
  "readability": "readable",
  "stale": null,
  "winning_source": "vault"
}
```

Enums:

- `origin`: `direct | provider | null`
- `readability`: `readable | key_unavailable | wrong_key | absent`
- `winning_source`: `override | cli | vault | env | file | default | missing`

`readability` is answered against the store's **key check value**, never by
decrypting the entry. `wrong_key` replaces the draft's `decryption_failed`
because that is what the check value can truthfully report: a key that does not
open this store. `inspect` therefore holds no plaintext at any point.

For an unknown or ineligible path, the command returns a usage failure with a
safe reason payload rather than this success object.

### 2.4 Remove

```text
func builtin vault remove PATH [--yes] [--json]
```

JSON success:

```json
{
  "ok": true,
  "path": "deploy.api_token",
  "origin": "direct",
  "removed": true
}
```

A missing entry returns `ok: true`, `origin: null`, `removed: false`.

`remove` accepts an entry of **either** origin and **never requires the vault
key** — metadata is cleartext and a delete decrypts nothing, which is what makes
this the recovery path for a store this machine cannot open. It reports the
origin it removed and warns only when that origin was `direct`, the one kind
with no upstream copy:

```json
{
  "ok": true,
  "path": "deploy.api_token",
  "origin": "direct",
  "removed": true,
  "warning": "no upstream copy; this value is gone"
}
```

`warning` is absent for a provider entry.

Reason codes:

- `confirmation_required`

`provider_entry_conflict`, `key_unavailable` and `decryption_failed` are
**removed** from this command: none of them can arise now.

### 2.5 Existing command extensions

**Compatibility note, not a purely additive change.** `list --json` today
publishes `provider`, `annotation` and `synced_at` as always-present strings,
because every row came from a sync. A direct entry has none of the three, so
those three fields become **nullable**. No field is removed or renamed, but a
consumer that assumed `provider` was always a string must handle `null`. The
human renderer must stop assuming them too: it currently measures
`len(entry.provider)` and calls `entry.synced_at.isoformat()`, and both raise on
a direct row.

`list --json` entry objects:

```json
{
  "key": "deploy.api_token",
  "origin": "direct",
  "annotation": null,
  "provider": null,
  "reference": null,
  "created_at": "RFC-3339 timestamp",
  "updated_at": "RFC-3339 timestamp",
  "synced_at": null
}
```

`status --json` retains its existing fields and adds:

```json
{
  "direct_entries": 1,
  "provider_entries": 2,
  "key_matches_store": true
}
```

`key_matches_store` is `null` when the store does not exist or holds no check
value yet, `false` when the resolved key does not open the store's check value.

`clear` retains `--yes` and **gains `--json`** — it has no JSON mode today. Its
human confirmation and JSON report distinguish direct and provider entry counts
and warn that direct values may have no upstream recovery source. It continues
to require no key.

`sync --json` retains its existing shape. A direct-entry collision appears in
the existing `failed` collection with safe reason `direct_entry_conflict`; `ok`
is false and other successful syncs remain.

`sync` additionally **refuses before writing** when the resolved key does not
open the store's check value, rather than writing fresh rows beside rows it can
no longer read. It writes only currently-declared annotations, so proceeding
would strand every undeclared and every direct row under the old key —
permanently, under the presence rule. The refusal envelope carries reason
`key_mismatch` and names the paths that would have been orphaned:

```json
{
  "ok": false,
  "reason": "key_mismatch",
  "message": "safe human-readable text",
  "would_orphan": ["deploy.legacy_token"]
}
```

## 3. Exit contract

| Outcome | Exit code |
| --- | --- |
| Success, including idempotent init and missing-entry remove | `ExitCode.OK` (`0`) |
| Invalid syntax/path/eligibility/input option | `ExitCode.USAGE` (`2`) |
| Key, overwrite, origin, or decryption refusal | `ExitCode.REFUSED` (`3`) |

Human mode writes a concise safe diagnostic to stderr. JSON mode returns one
object with this failure envelope and exits with the same code:

```json
{
  "ok": false,
  "reason": "stable_snake_case_code",
  "message": "safe human-readable text",
  "path": "optional canonical path"
}
```

## 4. Public Python compatibility

These existing contracts remain present and retain their required signatures:

```python
remote_first(*, file_pattern: str = ..., dotenv: bool = ..., max_age: str | None = ...) -> ConfigSources

class VaultKeyProvider(Protocol):
    def identifier(self) -> str: ...
    def interactive(self) -> bool: ...
    def is_available(self) -> bool: ...
    def get_key(self, project_id: str) -> bytes | None: ...
```

Existing public vault exports from `functualize.app.utils` remain callable.
Existing provider annotation strings remain accepted.

## 5. Key initialization capability

Initialization is additive and does not widen `VaultKeyProvider`:

```python
@runtime_checkable
class VaultKeyInitializer(VaultKeyProvider, Protocol):
    def initialize_key(self, project_id: str) -> bytes:
        """Return the existing key, or create, persist, and return one."""
```

Contract:

- The returned key has the existing vault cipher's required length.
- Repeated calls return the same stored key.
- The method never logs or renders the key.
- Read-only `VaultKeyProvider` implementations remain valid providers.
- Provider selection uses `identifier()`; no class-name or module-name
  inference.
- **`project_id` is retained but scope is the provider's choice.** Both shipped
  providers are user-scoped and ignore it, exactly as `EnvKeyProvider.get_key`
  already does — the keychain provider changes to match (spec §10.2a). The
  parameter stays so a third-party KMS or hosted provider may still scope per
  project; the seam is unchanged.

The exact public module that exports this new protocol is an architecture
decision for Plan and, because it adds public API, requires an ADR.

## 6. Public vault operation contracts

The delivery-neutral public seam must provide operations equivalent to:

```python
vault_init(
    *, key_source: str | None = None, cwd: str | Path | None = None
) -> VaultInitReport

vault_put(
    app: FunctualizeApp,
    path: str,
    value: str,
    *,
    replace: bool = False,
    cwd: str | Path | None = None,
) -> VaultMutationReport

vault_inspect(
    app: FunctualizeApp, path: str, *, cwd: str | Path | None = None
) -> VaultInspectionReport

vault_remove(
    app: FunctualizeApp, path: str, *, cwd: str | Path | None = None
) -> VaultMutationReport
```

**`vault_init` takes no app.** It carried one in the first draft; D6 removed the
need. A user-scoped key means there is no project to discover and no schema to
check, so requiring a booted app would be asking for something the operation
does not use — and would make `init` impossible on a project that cannot boot,
which is one of the moments you most want it.

It still resolves a `project_id` (cheaply, without booting) and passes it to the
provider. Both shipped providers ignore it, but key scope is a *provider's*
choice and a third-party KMS may hold one key per project; passing a placeholder
would quietly break exactly those.

`cwd` is on each operation so a caller can act on a project other than the
working directory — an embedding application, or a test.

**`vault_remove` does not require `path` to be eligible.** It canonicalizes a
path that resolves, so flag spelling works, and uses one that does not
verbatim. The entries most needing removal are the ones whose job has since been
renamed or deleted; validating against the current schema would make the
orphans this command exists to clear unreachable.

The precise module and report class layout are settled by the architecture
gate. The behavior is fixed:

- operations validate against the canonical job schema;
- reports carry metadata only;
- no operation returns plaintext;
- `_cli` invokes this public seam and does not import internal vault modules.

## 7. Resolution contract

For a matching eligible path:

```text
explicit invocation value > readable vault entry > env > file > default
```

Absence is a miss. Existing-but-unreadable is a refusal. Decryption and
authentication errors are never softened into misses.

The job receives the existing declared type (`Secret[str]` for the primary
case), not a vault reference, metadata object, or provider object.

## 8. Security contract

- Metadata response types cannot carry plaintext values.
- Secret input never appears in argument values in documented examples.
- `put` validates the path before consuming input.
- Exact secret bytes are absent from output, logs, exceptions, database files,
  and SQLite sidecars.
- Job execution performs no provider network call.
- No project-file key storage or plaintext fallback is added.

