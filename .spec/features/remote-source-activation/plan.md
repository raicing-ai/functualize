# Plan — Remote source activation

## 1. Measured state (run against `537efe7` at authoring time)

| Claim | Command | Result |
|---|---|---|
| Boot never builds a remote source | `grep -c remote src/functualize/_app/boot.py` | **0** |
| `parse_annotation` has no production caller | `grep -rn parse_annotation src/` | only `_config/manifest.py` + unrelated `_cli/annotation_utils` |
| The provider group is empty | `pyproject.toml:43` | `[project.entry-points."functualize.remote_providers"]` with **no entries** |
| No crypto dependency exists | `grep -rn "cryptography\|libsql\|sqlcipher" pyproject.toml plugins/*/pyproject.toml` | **0** |
| `remote_first()` returns a stub | `app/presets.py:110-114` | `config_resolution_chain=None` |

### The feasibility probe, run before planning

A throwaway provider pair was written against real services in a local Floci
container (`floci/floci:latest`, port 4566) — nothing was written into `src/`:

```
registered providers: {'aws-sm': ..., 'aws-ssm': ...}
  db_password  -> 's3cret-from-secrets-manager'    # Secrets Manager
  api_url      -> 'https://api.internal'           # SSM Parameter Store
  api_token    -> 'tok-abc123'                     # SSM SecureString, decrypted
  fallback     -> 'https://api.internal'           # aws-sm://missing | aws-ssm://... fell through
```

**Conclusion: `RemoteSource`, `ProviderRegistry` and `parse_annotation` are
correct and unreachable.** This feature is wiring, not building. The
`RemoteProvider` protocol needs no widening — each provider was ~10 lines.

## 2. Code sites

| Item | Site | What is there now |
|---|---|---|
| Chain construction | `_app/boot.py:772` `build_resolution_chain(...)` | builds `CLI → Env → Files → Defaults`; no remote slot |
| Chain selection | `_app/boot.py:565-573` | `config_resolution_chain is not None` → use it; else build classic |
| Preset stub | `app/presets.py:110-114` | returns `config_resolution_chain=None` |
| Annotation parser | `_config/manifest.py:37` | complete, uncalled |
| Remote source | `_config/sources.py:246` | complete, never constructed |
| Registry | `_config/registry.py:69,117,147,193` | complete; group empty |
| Project id | `_primitives/locator.py:527` `compute_project_id` | used by the discovery cache; reused verbatim for the vault path |
| Lambda handler | `plugins/functualize-lambda/.../__init__.py:126` | `return {"statusCode": 200, "body": result.return_value}` — `status` unread |
| Status enum | `_types/enums.py:12` | 8 members; `.ran` / `.resumable` have **zero** production callers |

## 3. Layer placement

The constitution's table is binding here, and it is what decides the file
layout:

- `_config/` may import `_types/`, `_primitives/`, `_events/` only. The vault
  store is a config concern and lives in `_config/vault.py`; it reaches
  `compute_project_id` in `_primitives/`, which is permitted.
- `_types/` is **stdlib only**. The `RunStatus → HTTP` table is a pure mapping
  over an enum already there, so it lives in `_types/` beside the enum without
  violating that.
- Extension protocols are public. `VaultKeyProvider` goes in `plugin/`,
  alongside the protocols third parties already implement.
- `_cli/` may import public folders only. The `builtin vault` commands reach
  the vault through `app/` re-exports, exactly as the cache commands do
  (`app/utils.py` is the existing precedent).
- `_app/` is the composition root and the only place allowed to wire
  `_config` + `_plugins` together — so V1's chain assembly belongs there and
  nowhere else.

`uv run lint-imports` is the gate on every one of these.

## 4. Approach

**V1 — chain assembly.** `build_resolution_chain` gains an optional remote
slot rather than a parallel function; one builder keeps `classic()` and
`remote_first()` from drifting. `remote_first()` stops returning a bare `None`
and instead carries a marker the boot path reads, so "the preset asked for
remote" is a fact in the data rather than an inference from absence — absence
is what produced the original silent degradation.

**Construction-time refusal.** V1's error must fire where
`is_fully_explicit()` is already consulted, at app construction, because
`ConfigSources` cannot see the plugin registry on its own.

**V2 — annotation discovery.** Scanning resolved config for `provider://`
values has an ordering trap: the scan must run over values that have been
*located* but not yet *resolved*, or resolving a file value would already have
consumed the annotation as a literal. The scan therefore sits between
`FileSource` discovery and chain assembly.

**V3 — the store.** `sqlite3` is stdlib; only `cryptography` is added. AES-256-GCM
with a fresh 12-byte nonce per entry, stored beside the ciphertext. The
`key`/`annotation`/`provider`/`synced_at` columns stay cleartext so `vault list`
works without the key — that is a deliberate contract (`contracts.md` §4), not
an oversight.

Concurrency: `builtin parallel` means several readers at once. SQLite in WAL
mode handles concurrent readers with a single writer, which is exactly the
access pattern — many reads per run, writes only during `vault sync`.

**V4 — the key seam.** The protocol ships with two implementations, and the
*ordering rule* is the part with real design content: non-interactive first,
interactive only on a TTY. Getting this backwards would hang an unattended
Lambda run on a keychain prompt.

**V5/V6 — staleness and misses.** Both are warnings on the run path, so both
must go through the existing event/warning channel rather than bare `print`,
and neither may render a value. The miss warning must name *which source
answered instead* — a warning that only says "not in vault" leaves the
operator with the same question the original bug posed.

**V7 — the plugins.** `functualize-aws` wraps boto3. `functualize-bitwarden`
wraps Bitwarden Secrets Manager. Both are thin; the probe already showed the
shape. Neither may be imported by core (`contracts.md` §2) — they arrive only
through the entry-point group.

## 5. Risks

| Risk | Mitigation |
|---|---|
| `cryptography` in core inflates the standalone binary across **7 build targets** | measure the delta before and after; it is a wheel with no compiler requirement, but the size is a real cost the maintainer accepted knowingly |
| The annotation scan resolves values it should not | the scan reads located-but-unresolved values; a test asserts a literal containing `://` (a URL in a config file) is **not** treated as an annotation |
| A vault written under one key is read under another | AES-GCM fails authentication rather than returning garbage; the error must name the key provider in use, not just "decryption failed" |
| Warning fatigue makes V5/V6 invisible | the miss warning is per-key per-run, not per-access; a job reading one secret ten times warns once |
| `bitwarden` needs a live account to test | the provider is tested against a fake; only the AWS pair gets a live integration test, against Floci |
| Floci is a young project to depend on in CI | it is MIT, needs no auth token, and is a drop-in for the LocalStack image; if it proves unstable the same test runs against any LocalStack-compatible endpoint via `AWS_ENDPOINT_URL` |

## 6. Files to change

```
src/functualize/plugin/__init__.py           V4 (VaultKeyProvider protocol)
src/functualize/_config/vault.py             V3 (new — the store)
src/functualize/_config/vault_keys.py        V4 (new — env + keychain)
src/functualize/_config/annotations.py       V2 (new — the scan)
src/functualize/_app/boot.py                 V1, V2 (chain assembly)
src/functualize/app/presets.py               V1 (remote_first marker)
src/functualize/app/utils.py                 V3 (re-export for _cli)
src/functualize/_cli/builtins.py             V6 (builtin vault family)
src/functualize/_types/enums.py              §7 (RunStatus → HTTP table)
plugins/functualize-lambda/…/__init__.py     §7 (consume the table)
plugins/functualize-http/…/__init__.py       §7 (consume the table)
plugins/functualize-aws/                     V7 (new plugin)
plugins/functualize-bitwarden/               V7 (new plugin)
pyproject.toml                               cryptography; entry-point groups
docs/guides/configuration.md                 all
tests/…                                      one per V, plus a Floci integration tier
```

`src/functualize/**` and `plugins/*/src/**` are spec-gated; `tasks.md` with a
parseable wave graph must exist before any of these are written.

## 7. Open items carried, not resolved

- **The commercial boundary.** `spec.md`'s closing note records that "FuncCloud
  in core by default" contradicts the Lark proposal's open-core framing. The
  ADR this feature requires is where that is settled; no task here depends on
  it.
- **`oss-remote-source-activation.md`** is referenced by the commercial
  proposal and exists nowhere. On merge, this feature's durable half should be
  migrated under that name so the dependency resolves rather than dangling.
