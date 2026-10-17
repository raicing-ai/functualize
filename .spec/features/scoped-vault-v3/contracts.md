# Scoped vault v3 — external contracts

Authority: [SD/12779576](https://raicing-ai.atlassian.net/wiki/spaces/SD/pages/12779576), page version **5**, read 2026-10-16, `Authority: Approved`. The maintainer confirmed these contracts on the issue at 2026-10-16 11:59 UTC. The page's Status and Last reviewed prose still describe the preceding proposal; its Authority field and the explicit confirmation establish the gate. The subject-address capability required by the Rise foundation is included here, unchanged from v3.

## CLI

```text
func builtin vault put     [--group GROUP] [--job JOB] --field FIELD
func builtin vault inspect [--group GROUP] [--job JOB] --field FIELD
func builtin vault remove  [--group GROUP] [--job JOB] --field FIELD
func builtin vault list
func builtin vault sync
```

At least one of `--group` or `--job` is required. They compose:

| Flags | Names | Scope | Stored target |
|---|---|---|---|
| `--group G` | the group `G`: a group option, or a subject field when `G` is a subject address | `group` | `G` |
| `--group G --job J` | job `J` whose group is exactly `G` | `job` | the registered name `G.J` |
| `--job J` | job `J` that is in no group | `job` | `J` |

```text
# func app deploy service: job "service" in group "app.deploy"
func builtin vault put --group app.deploy --job service --field iam_key
# option of the group app.deploy itself
func builtin vault put --group app.deploy --field token
# job "myjob", in no group
func builtin vault put --job myjob --field api_key
# environment comes from the process, never a vault flag
FUNCTUALIZE_ENV=prod func builtin vault put --group deploy.infra --job app --field api_token
FUNCTUALIZE_ENV=prod func builtin vault put --group prod.apps.web --field tls_crt
```

- `GROUP` is a command-group path or a Rise subject address, dots kept as-is.
- `JOB` is one job name. It never contains a dot and never repeats the group.
- `FIELD` is a secret-marked option of the group, or a secret-marked config field of the job.
- Group and job segments use the normal canonical spelling, so `run_etl` reaches `run-etl`.

Refusals happen before any value is read. Each one names the spelling to use:

| Input | Refusal |
|---|---|
| neither `--group` nor `--job` | a target is required |
| `--job app.deploy.service` | a job name has no dots; use `--group app.deploy --job service` |
| `--job service`, where `service` exists only in `app.deploy` | no top-level job `service`; add `--group app.deploy` |
| `--group app.deploy --job nope` | group `app.deploy` has no job `nope` |
| `--group G` and `G` declares no options and is not a subject address | unknown group |
| `FIELD` missing, not secret, or an ordinary function parameter | the existing v2 refusals |

`FUNCTUALIZE_ENV=base` selects the shared slot. There is no vault environment flag. `inspect` and `list` show metadata and the exact resolved identity without values, and spell each entry the way the flags do (`prod: --group deploy.infra --job app --field api_token`). `remove` acts on the exact active-environment identity.

## Config declaration

```toml
# config.base.toml: shared
[[vault_secret]]
group = "app.deploy"      # job "service" in group "app.deploy"
job = "service"
field = "iam_key"
source = "provider://iam-key"

[[vault_secret]]
job = "myjob"             # job in no group
field = "api_key"
source = "provider://myjob-key"

# config.prod.toml: prod
[[vault_secret]]
group = "prod.apps.web"   # group or subject address
field = "tls_crt"
source = "provider://reference"
```

`group` and `job` follow the same rule as the flags: `group` alone, `group` with `job`, or `job` alone. At least one is required. `field` and `source` are required. A dotted `job` value is refused with the split spelling. A `config.base.*` or unslotted declaration is shared; a `config.<env>.*` declaration takes that file's environment. An `environment` key in a declaration is unsupported. Sync processes only shared and active-overlay declarations.

## Observable identity and resolution

The conceptual entry identity is `(scope, target, field, environment)`; `environment` is absent for shared entries. A job's `target` is its registered name, which Functualize builds from the group and the job name. Today's registry already uses that name: `JOB_GROUP = "deploy.infra"` plus function `app` registers `deploy.infra.app`. So the storage encoding is unchanged, and a job entry written before this change is the same entry under the composed flags. Shared entries retain the v2 three-part encoded spelling and ciphertext authentication. Environment entries add a fourth part. The encoding is a storage detail, not a user-supplied path grammar.

For a group address `a.b.c` and active environment `prod`, candidate order is `prod/a.b.c`, `prod/a.b`, `prod/a`, then `shared/a.b.c`, `shared/a.b`, `shared/a`, always with the same group scope and field. A job uses exactly its group and job, `prod` then shared. It never checks the same job name in an ancestor group or the group's own option. A present entry that cannot be read terminates lookup with an error. Field-source order remains runtime override, explicit CLI value, vault, environment, config file, default.

## Public vault API

The existing `functualize.app.vault` operations (`resolve_vault_identity`, `vault_put`, `vault_remove`, and `vault_inspect`) continue to validate and operate on a scoped identity. `resolve_vault_identity(app, *, group=None, job=None, field)` accepts `group` and `job` together under the composition rule above. It no longer rejects both being given, and it rejects a dotted `job`. Their reports must expose the environment context and, for inspection, the exact identity selected by lookup. Plan decides any signature additions that subject-field resolution needs, after mapping existing public callers. No independent environment selector is added to the API.

## Privacy and compatibility

Metadata output and errors never include plaintext. Stored v2 shared entries remain readable as-is. Old flat-key stores remain refused without mutation, with the existing `vault clear` recovery instruction. Direct and provider-backed entries cannot silently replace one another. The v2 grammar, which made `--group` and `--job` mutually exclusive and took a full dotted path after `--job`, is unreleased: #88 (`ba36b859`) is in no tag, and its `CHANGELOG.md` entry is under Unreleased. Replacing that grammar needs no compatibility alias. The Unreleased changelog entry is rewritten to describe the composed form.
