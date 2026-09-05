# Contracts — Remote source activation

New public surface, plus the shape of what lands on disk. Placement follows the
constitution's audience split — public folders are `app/`, `job/`, `plugin/`,
`types/`, `testing/`.

## 1. `VaultKeyProvider` — the key seam

```python
# functualize/plugin  (with the other extension protocols)

@runtime_checkable
class VaultKeyProvider(Protocol):
    def identifier(self) -> str:
        """Short name, e.g. 'env', 'keychain', 'funccloud'."""

    def interactive(self) -> bool:
        """Whether obtaining the key may prompt or block.

        Non-interactive providers are safe on an unattended run.
        """

    def is_available(self) -> bool:
        """Whether this provider can supply a key in this environment."""

    def get_key(self, project_id: str) -> bytes | None:
        """Return a 32-byte key for the project's vault, or None."""
```

Registered via a new entry-point group:

```toml
[project.entry-points."functualize.vault_key_providers"]
env      = "functualize._config.vault_keys:EnvKeyProvider"
keychain = "functualize._config.vault_keys:KeychainKeyProvider"
```

**Resolution order.** A provider reporting `interactive() is False` is tried
first, in registration order; `env` is one of these and is the shipped default.
Interactive providers are consulted only when no non-interactive provider
returned a key, and only when a TTY is present. This keeps an unattended run
deterministic: it either has the key in its environment or it fails, and it
never blocks on a prompt.

`keychain` is the first interactive implementation. It is **one implementation
of the seam, not the seam itself** — KMS, 1Password and FuncCloud are the same
protocol with no core change.

## 2. `RemoteProvider` — unchanged

The existing protocol (`_config/protocols.py:60`) is the contract for a remote
source and does **not** change:

```python
def identifier(self) -> str: ...   # 'aws-sm', 'aws-ssm', 'bitwarden'
def is_ready(self) -> bool: ...    # credentials from the environment ONLY
def fetch(self, reference: str) -> str: ...
```

Proven satisfiable against real services at authoring time: a ~10-line
implementation of each of `aws-sm` and `aws-ssm` resolved Secrets Manager
values, SSM `String` and `SecureString` parameters, and a fallback chain
against a local Floci container. The protocol needs no widening.

Registered through the existing, currently-empty group:

```toml
[project.entry-points."functualize.remote_providers"]
aws-sm  = "functualize_aws:SecretsManagerProvider"
aws-ssm = "functualize_aws:ParameterStoreProvider"
```

## 3. Annotation syntax — unchanged

`provider://reference`, with a `|`-separated fallback chain of at most 5
entries, exactly as `_config/manifest.py` already parses:

```toml
[database]
password = "aws-sm://floci/db-password"
api_url  = "aws-ssm:///floci/api-url"
token    = "aws-sm://prod/token | aws-ssm:///fallback/token"
```

A value that does not match the pattern is a literal. This is unchanged
behaviour; what changes is that something now calls the parser.

### The scheme must be a **registered provider**, not merely a URL scheme

Decided 2026-09-05. `ANNOTATION_PATTERN` matches any `scheme://rest`, so on the
pattern alone `https://api.example.com` parses as provider `https`,
`postgres://user:pw@host/db` as `postgres`, and `s3://bucket/key` as `s3` —
verified. Classifying on shape would turn every URL in a config file into an
annotation and send boot looking for a provider named `https`.

So a value is an annotation **only when its scheme is a registered remote
provider identifier**.

That choice creates one hazard, and it is handled rather than accepted:
`aws-sm://prod/db` with the AWS plugin *not installed* is no longer an
annotation, so a job would receive the literal string `"aws-sm://prod/db"` as
its password — silently, which is the failure class this feature exists to
remove. Any annotation-shaped value naming an **unregistered** scheme is
therefore reported as an `UnresolvedAnnotation`. Ordinary URL schemes are
excluded from that report to keep it quiet.

The exclusion list is consulted **only** to decide whether to complain, never
to decide what a value *is*. A scheme missing from it costs a spurious warning;
it can never cause a wrong resolution.

### The reference is opaque to core

Everything after `://` belongs to the provider. Core does not parse, split,
normalise or truncate it, and `RemoteProvider.fetch(reference)` receives it
whole.

This is what lets the AWS provider accept credential overrides. boto3's normal
precedence applies by default, and the annotation overrides it per value:

```toml
[database]
password = "aws-sm://prod/db-password?profile=prod-admin"
replica  = "aws-sm://prod/db?account=123456789012&region=eu-west-1"
audit    = "aws-ssm:///p/audit?role=arn:aws:iam::123456789012:role/Deploy"
```

Verified to survive parsing verbatim, including role ARNs (whose colons a
naive scheme-splitter would truncate) and per-entry overrides inside a fallback
chain — failing over must not carry the first entry's profile to the second.
Pinned by `tests/config/test_annotation_scan.py::TestTheReferenceIsOpaqueToCore`.

The override **grammar** — which keys are honoured, and their precedence
against the ambient boto3 chain — is `functualize-aws`'s contract, specified in
task 5.1, not core's.

## 4. On-disk vault

`$XDG_DATA_HOME/functualize/vaults/<project_id>/vault.db` — one per project,
`<project_id>` computed the same way the discovery cache computes it.

```sql
CREATE TABLE secrets (
    key         TEXT PRIMARY KEY,   -- 'database.password'
    annotation  TEXT NOT NULL,      -- 'aws-sm://floci/db-password'
    provider    TEXT NOT NULL,      -- which one actually answered
    nonce       BLOB NOT NULL,      -- per-entry, never reused
    ciphertext  BLOB NOT NULL,      -- AES-256-GCM
    synced_at   TEXT NOT NULL       -- ISO-8601 UTC
);

CREATE TABLE audit_log (            -- append-only
    ts        TEXT NOT NULL,
    key       TEXT NOT NULL,
    provider  TEXT,
    action    TEXT NOT NULL,        -- 'sync' | 'read' | 'miss'
    outcome   TEXT NOT NULL         -- 'ok' | 'error' | 'fell-through'
);
```

`key`, `annotation`, `provider` and `synced_at` are **cleartext on purpose** —
`vault list` reports what is stored and how fresh it is without holding the
key, and none of them is the secret. Only `ciphertext` requires it. This
mirrors Turso's split between queryable metadata and an unreadable value.

`audit_log` never holds a value.

## 5. `[vault]` settings

```toml
[vault]
max_age = "24h"     # warn when the vault is older; never fails the run
enabled = true
```

`max_age` accepts a duration string. Absent, the default is `24h`.

## 6. CLI surface

```
func builtin vault sync      # fetch every annotation, write the vault
func builtin vault list      # names, providers, synced_at -- never values
func builtin vault status    # key provider in use, age, entry count
func builtin vault clear     # delete this project's vault
func builtin vault keygen    # emit a fresh 32-byte key, hex-encoded
```

`list` and `status` obey ADR-008: they render through the same masking path as
every other surface, and add no independent opinion about what is secret.

**Flag spelling.** These use `--json`, matching `builtin info` as shipped —
**not** `--output json`, which does not exist. If
`shape-intents/output-flag-normalization.md` lands first, these move with every
other command, not ahead of them.

## 7. `RunStatus` → HTTP, in core

Not strictly this feature's surface, but the same release and the same file, so
recorded once. Per the Lark finding *"One RunStatus enum, six incompatible
answers to 'is it finished?'"*, the mapping is declared **once**, beside the
enum in `_types/`, rather than a seventh scattered answer:

| status | code | meaning |
|---|---|---|
| `SUCCESS` | 200 | ran, fine |
| `SKIPPED` | 200 | nothing to do; success at the boundary, as it is exit 0 |
| `BLOCKED` | 202 | paused at a gate, resumable |
| `REFUSED` | 412 | a declared precondition was not met; it never started |
| `FAILURE` | 500 | it broke |
| `TIMEOUT` | 504 | exceeded its budget — the one retryable failure |
| `CANCELLED` | 500 | stopped deliberately |
| `UNKNOWN` | 500 | unknown is not success |
| `RUNNING` | *unmapped* | falls back to 500; never observed at a request boundary |

**Corrected 2026-09-05.** This table first listed eight members and omitted
`REFUSED`, following the Lark finding *"One RunStatus enum, six incompatible
answers"*, which pre-dates it. The enum has **nine** members
(`_types/enums.py:32`). `REFUSED` is 412 because its own docstring is *"a
declared precondition for running it was not met"*, and because
`_STATUS_EXIT_CODES` already keeps it distinct from `FAILURE` — *"a refusal is
not a skip and not a raise"*.

`RUNNING` is deliberately unmapped, mirroring `_STATUS_EXIT_CODES`'s rule that
*"anything unmapped is a bug in the caller, not a new exit code."*

**The one deliberate divergence between the two boundaries** is `BLOCKED`: exit
code **5** (so a shell pipeline stops) but HTTP **202** (so a caller knows to
resume). Pinned by a test so it cannot drift silently.

Shipped as `_types/http_status.py` — a sibling of `exit_codes.py`, not an
addition to `enums.py`.

`functualize-lambda` and `functualize-http` both consume it. The Lambda handler
today reads `result.status` **not at all** and answers `200 / null` for every
outcome; that is STATUS follow-up #21 and is closed here.

## 8. What is deliberately *not* exported

- The vault store class. It is reached through config resolution and the
  `builtin vault` commands, never imported by a job.
- Anything that returns a decrypted value in bulk. There is no
  `vault.dump()` — matching the "write-only secrets" constraint the FuncCloud
  proposal adopts as a requirement from Rundeck, AAP and n8n.
- A second answer to "is this a secret". `is_secret_field` remains sole owner
  (ADR-008).
