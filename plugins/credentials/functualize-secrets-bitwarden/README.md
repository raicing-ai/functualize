# functualize-bitwarden

Bitwarden **Secrets Manager** (`bws`) provider for functualize's remote
configuration layer.

```toml
[database]
password = "bws://8a9c2f0e-1b3d-4c5e-9f70-2a1b3c4d5e6f"
replica  = "bws://DB_REPLICA_PASSWORD"
audit    = "bws://AUDIT_TOKEN?project=aaaaaaaa-1111-2222-3333-444444444444"
```

Values are fetched by `func builtin vault sync` and stored in the project's
encrypted local vault. Job execution reads the vault, never the network
(ADR-016).

## Not Vaultwarden

Bitwarden ships two separate products:

| Product | CLI | This plugin |
|---|---|---|
| **Secrets Manager** | `bws` | ✅ what it speaks |
| Password Manager | `bw` | ❌ different API |

Vaultwarden reimplements the **Password Manager** API. Secrets Manager is
Bitwarden-licensed rather than open source, and Vaultwarden deliberately does
not implement it — so a self-hosted Vaultwarden cannot serve this provider at
all, however its URL is configured. The endpoints simply are not there.

`BWS_API_URL` and `BWS_IDENTITY_URL` do point this at a self-hosted
*Bitwarden* server, which is a different thing.

## Addressing a secret

| Form | Resolves | Needs an organization |
|---|---|---|
| `bws://<uuid>` | one call | no |
| `bws://<KEY_NAME>` | lists, then fetches | yes |

Bitwarden does not require key names to be unique across projects. A key
matching more than one secret is an **error** naming every candidate and its
id, not a silent pick — the wrong pick would be a working run with the wrong
credential.

## Override keys

| Key | Meaning |
|---|---|
| `project` | A project **uuid**, narrowing a key-name match. |
| `organization` | A uuid, overriding `$BWS_ORGANIZATION_ID` for this value. |

Both serve the key form only. An unknown key is an error, and so is a
correctly-spelled key that cannot apply — `bws://<uuid>?project=…` is refused
rather than silently ignored, because a line that reads as though it
constrains the lookup should either do so or say it cannot.

## Configuration

| Variable | Purpose |
|---|---|
| `BWS_ACCESS_TOKEN` | Machine-account access token. Same name the `bws` CLI reads. |
| `BWS_ORGANIZATION_ID` | Organization to search for key-name lookups. |
| `BWS_API_URL` | Self-hosted Bitwarden API. **This plugin's own name** — the `bws` CLI has no env var for it. |
| `BWS_IDENTITY_URL` | Self-hosted Bitwarden identity endpoint. Likewise. |

Authentication happens once per process, and the SDK's optional auth-state
file is left off: nothing this plugin holds outlives the process, and a state
file on disk is a credential at rest.

## Platform support

`bitwarden-sdk` is a Rust extension published as binary wheels with no source
fallback: Windows, Linux (glibc) and macOS, on x86-64 and ARM64. A musl
(Alpine) or unusual-arch host cannot install this plugin — which is precisely
why it is a plugin and not part of core.
