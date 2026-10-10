# Contracts: bitwarden-pm-provider

## Public surface (the package exports)

```python
class PasswordManagerProvider:          # satisfies RemoteProvider
    def identifier(self) -> str: ...    # "bwpm"
    def is_ready(self) -> bool: ...     # true; specific refusals happen in fetch()
    def fetch(self, reference: str) -> str: ...
```

New exceptions (all `RuntimeError`/`LookupError` subclasses, exported):

| Exception | Means |
|---|---|
| `BwBinaryMissingError` | No `bw` executable on `PATH`. |
| `BwNotLoggedInError` | `bw status` reports `unauthenticated`. |
| `BwSessionLockedError` | `bw status` reports `locked`. |
| `BwCommandError` | A `bw` invocation failed otherwise; CLI output is withheld. |
| `InvalidReferenceError` | The `bwpm://` reference is malformed or names an unknown field. |
| `ItemNotFoundError` | Well-formed reference; no such item. |
| `FieldNotFoundError` | The item exists but the requested field has no value. |
| `AmbiguousItemError` | An item name matches more than one item (names candidate ids). |
| `AmbiguousFieldError` | Duplicate custom-field names inside one item. |

Existing `InvalidReferenceError` is reused for grammar failures; a shared
`_is_uuid` helper is imported from `_reference` (same package — the
cross-package duplication rationale in `_reference.py` does not apply
intra-package).

## Entry point

```toml
[project.entry-points."functualize.remote_providers"]
bws  = "functualize_secrets_bitwarden:SecretsManagerProvider"
bwpm = "functualize_secrets_bitwarden:PasswordManagerProvider"
```

No new distribution, no new dependency, no `pyproject.toml` dependency change.
Core is untouched: the entry-point group, `vault sync`, and the declaration
parser already accept any registered provider identifier.

## The `bwpm://` grammar (parsed by `_pm_reference.parse_reference`)

    bwpm://<item>/<field>

- `reference` is everything after `bwpm://`, exactly as core passes it
  (fallback chains are already split upstream).
- Split on the **first** `/`: segment 1 is the item, segment 2 the field.
  A `field:` name may itself contain `/`; an item name may not be addressed
  through this grammar if it contains `/` — address such items by uuid.
- `<field>` ∈ {`password`, `username`, `totp`, `notes`, `uri`} or
  `field:<custom-name>`. Anything else, including an empty field, a bare
  custom name, or an empty custom name, is `InvalidReferenceError` (with a
  close-match suggestion where one exists).
- Any `?` is refused: this grammar has no query, and a query-looking suffix
  must not read as an override that silently does nothing.
- No percent-decoding: decoding could corrupt an identifier into another one,
  the same reasoning the `bws` grammar records for its override block.

Parsed result (frozen dataclass): `item_id` (uuid form) or `item_name`,
`field` (built-in name) or `custom_field` (custom name), and a `label`
property that never carries a value.

## The subprocess contract (`_pm_client`)

| Rule | Value |
|---|---|
| State probe | `bw status --nointeraction` → JSON `{"status": "unlocked"\|"locked"\|"unauthenticated"}` |
| Item by uuid | `bw get item <uuid> --raw` → one item JSON object |
| Item by name | `bw list items --raw` → JSON array; exact `name` match client-side |
| Session | Ambient only: the child inherits `os.environ` (`BW_SESSION` flows through). **Never** a `--session` argv (argv is world-readable via `ps`). |
| stdin | `DEVNULL` always — no invocation can wait on input. |
| stdout/stderr | Captured, decoded; neither raw stream is included in exceptions. |
| Timeout | 20 s per invocation (`subprocess.run` kills the child on expiry); core's 30 s fetch wrapper still governs each value. |
| State probe lifetime | Each fetch probes the current CLI state; no module cache survives a session or `PATH` change. |

Field extraction, from the item JSON: `login.password`, `login.username`,
`login.totp` (the stored seed/URI — `bw get totp` is never invoked, it emits a
generated code), first `login.uris[].uri`, top-level `notes`, and `fields[]`
entries matched by exact `name` for `field:` references. A `None`/empty value,
or a login-slot field on an item with no `login` block, refuses.

## Integration option

`tests/test_integration_vaultwarden.py` mirrors the AWS suite's emulator
module: it skips unless `bw` is on `PATH`, `bw status` reports `unlocked`,
**and** `FUNCTUALIZE_BWPM_INTEGRATION=1` (opt-in, because unlike a localhost
emulator this is the operator's real vault). Expected backend: Vaultwarden in
Docker with `bw config server` pointed at it. The module seeds a uuid-tagged
item, asserts every field path against the live CLI, and removes the item.
