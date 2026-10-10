# functualize-secrets-bitwarden

Bitwarden providers for functualize's remote configuration layer — two
Bitwarden products, one package:

| Entry point | Scheme | Product | Speaks through |
|---|---|---|---|
| `bws` | `bws://` | **Secrets Manager** (machine accounts) | Bitwarden's own SDK |
| `bwpm` | `bwpm://` | **Password Manager** (the personal vault) | your `bw` CLI, as a subprocess |

Both are consulted by `func builtin vault sync` and stored in the project's
encrypted local vault. Job execution reads the vault, never the network
(ADR-016).

## Two products, not one

The APIs do not overlap. The `bws` endpoints are exactly the ones
Vaultwarden does not implement; the Password Manager API is exactly what
Vaultwarden does. So:

- a self-hosted **Vaultwarden** cannot serve `bws://` at all, however its URL
  is configured — the endpoints are not there;
- `bwpm://` works against Vaultwarden **and** bitwarden.com, because server
  selection belongs to the `bw` CLI's own configuration (`bw config server`).
  This provider invents no `BW_*` variables of its own.

That makes `bwpm` the project's first self-hosted-friendly secret source.

`BWS_API_URL` and `BWS_IDENTITY_URL` point the SDK at a self-hosted
*Bitwarden* server — a different thing from Vaultwarden.

## `bwpm://` — addressing an item

```toml
[[vault_secret]]
group = "deploy"
field = "token"
source = "bwpm://deploy-token/password"

[[vault_secret]]
job = "data-sync"
field = "seed"
source = "bwpm://3f2b9c81-5d4e-4a77-8b21-9c0d2e4f6a88/totp"

[[vault_secret]]
group = "deploy"
field = "api_key"
source = "bwpm://deploy-token/field:api-key"
```

    bwpm://<item>/<field>

`<item>` is an item uuid or an exact item name. `<field>` is never defaulted:

| Field | Reads |
|---|---|
| `password`, `username`, `totp`, `notes`, `uri` | the built-in slots |
| `field:<name>` | a custom field, by exact name |

`totp` returns the stored **seed**, never a generated code — a code baked
into the vault would silently expire. `uri` returns the first URI, which is
`bw`'s own convention. An item name that holds a `/` is addressed by uuid.

An unknown field is an error, not a no-op; so is any `?query` (this grammar
has nothing to override), a name matching more than one item, or a field
storing no value. Every refusal names what it found — the wrong pick would
otherwise be a working run with the wrong credential.

## `bwpm://` — the session, and what sync will not do

The provider consumes the state you have already put the `bw` CLI in and
invents nothing:

- **It never logs in.** `bw login` (credentials, 2FA) is yours.
- **It never unlocks.** A locked vault is a refusal naming itself; the
  recovery is a human running `bw unlock` and exporting `$BW_SESSION` as it
  instructs.
- **It never persists a session.** The key reaches the child only through
  the inherited environment — never a `--session` argument (`ps` makes argv
  world-readable), never a log, never an error message, never the vault.

The operational consequence: ambient state is less durable than a BWS
token. A sync that worked yesterday can meet a locked vault this morning;
it fails specifically, and a human re-unlocks. This is the same shape as
the vault keyring's own lock.

The `bw` CLI is a **runtime dependency of `bwpm` alone** — the provider
detects its absence and refuses accurately (binary missing, not signed in,
and locked are three different errors).

## `bws://` — addressing a secret

| Form | Resolves | Needs an organization |
|---|---|---|
| `bws://<uuid>` | one call | no |
| `bws://<KEY_NAME>` | lists, then fetches | yes |

Bitwarden does not require key names to be unique across projects. A key
matching more than one secret is an **error** naming every candidate and its
id, not a silent pick.

| Override | Meaning |
|---|---|
| `project` | A project **uuid**, narrowing a key-name match. |
| `organization` | A uuid, overriding `$BWS_ORGANIZATION_ID` for this value. |

Both serve the key form only, and an unknown or inapplicable override is an
error rather than a silent no-op.

| Variable | Purpose |
|---|---|
| `BWS_ACCESS_TOKEN` | Machine-account access token. Same name the `bws` CLI reads. |
| `BWS_ORGANIZATION_ID` | Organization to search for key-name lookups. |
| `BWS_API_URL` | Self-hosted Bitwarden API. **This plugin's own name** — the `bws` CLI has no env var for it. |
| `BWS_IDENTITY_URL` | Self-hosted Bitwarden identity endpoint. Likewise. |

Authentication happens once per process, and the SDK's optional auth-state
file is left off: nothing this plugin holds outlives the process, and a
state file on disk is a credential at rest.

## Platform support

`bws` depends on `bitwarden-sdk`, a Rust extension published as binary
wheels with no source fallback: Windows, Linux (glibc) and macOS, on x86-64
and ARM64. A musl (Alpine) or unusual-arch host cannot install the plugin —
which is precisely why it is a plugin and not part of core. `bwpm` adds no
Python dependency; it needs whatever platform your `bw` CLI runs on.
