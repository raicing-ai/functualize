# Rise / RiseKit foundation — external contracts (revision 7)

This records observable v1 surfaces against SD/18153475 v26 (approved v21
plus the owner's confirmed deltas and comments 18808989 / 18809013).
Example module names, builders, JSON schema details and the F6 function name
remain provisional where §7 says so. Released 0.5.0 owns core API spelling.

## C1. Distributions and public boundary

`functualize-rise` defines the convention, commands, and routing.
`functualize-risekit` depends on Rise and supplies typed substrate bases and
conformance helpers without a provider. `functualize-rise-cloudflare` is a
separate provider package. Providers may depend directly on Rise without
RiseKit. All three depend on Functualize public API only. No core module
imports these distributions.

## C2. Declarations

```python
@contract("cloudflare.d1@1")
class D1Database(RemoteResource):       # abstract; never a job class
    account_id: str
    database_name: str
    api_token: Secret[str]

    class Realized(Realization):
        uuid: str

    def diagnose(self) -> RemoteResourceObservation: ...
    def up(self) -> "D1Database.Realized": ...

@job(group="cloudflare.d1")             # concrete ordinary Functualize job class
class CloudflareApiD1(D1Database):
    def diagnose(self) -> RemoteResourceObservation: ...
    @job(timeout=120)
    def up(self) -> D1Database.Realized: ...

def cloudflare_dev() -> Environment:    # ordinary, lazily evaluated job
    return Environment(d1={"main": CloudflareApiD1(
        account_id="0a1b2c", database_name="app")})
```

The example's symbols are illustrative; the contract is the separation:
abstract promise, concrete job class, ordinary environment job. The class's
operations share `[cloudflare.d1]` configuration. Core discovery, not Rise,
creates their canonical jobs. `@job(timeout=120)` survives Rise metadata
generation. A plain Functualize invocation of the concrete class's job works
without Rise. Rise invokes that same job with ordinary explicit field values;
it supplies no address or scope as a new core invocation input.

`Ref[T]` is required; `Ref[T] | None` is optional. A local concrete subject
without a contract ancestor uses `local:<name>`. Role defaults and tags follow
spec S2. Contract identities use `namespace.name@major`; an operation identity
adds `/verb`. Dotted addresses derive from the environment job and local keys.

## C3. Config and policy

```toml
# Committed project configuration
[rise]
default = ["cloudflare_dev", "local_tools"]
registries = ["https://rise.example.dev/index.json"]

[rise.policy."python.ruff@1"]
forbid = ["python.ruff.pipx"]
# require = ["python.ruff.uv-tool"]

# Cloner's ~/.config/functualize/config.toml, never committed
[rise.policy."python.uv@1"]
prefer = ["python.uv.installer"]
```

An overlay replaces `default` and `registries` lists wholesale. Project
`require`/`forbid` filter before any preference. Existing local binding
persists until `--choose` changes it. Cloner preference outranks project soft
preference. A tie refuses. `--choose ADDRESS=CANDIDATE` is explicit and
recorded. `install_scope` and `existing` may express general cloner policy.

The machine-local `rise-lock.json` holds subject-to-candidate bindings,
dependency chains, chosen identities, reasons, and registry additions. Its
proposed path is `.functualize/rise-lock.json`; it is never committed. This is
provenance, not a portable dependency lockfile. Exact JSON fields are
provisional. Policy drift appears in `ps`; it never silently reroutes a
binding. Implicit dependencies get one subject per environment and contract.

Field resolution for one subject is: environment-declared explicit value;
public vault read at the subject-address group for unset secrets; Functualize
environment; shared job-group section; default. The public vault read is a
generic core prerequisite, not an API Rise introduces into core. Secret
source classes may be recorded, never secret bytes.

## C4. Commands and exit status

| Command | Operation and result | Codes |
|---|---|---|
| `func rise config [ADDRESS...]` | `validate`; findings or masked resolved tree | 0 clean, 1 findings, 2 usage |
| `func rise ps [ADDRESS...]` | `diagnose`; table or NDJSON with `--format json` | 0 pass, 1 any fail, 2 usage |
| `func rise up [ADDRESS...]` | diagnose, then converge in dependency order | 0 converged, 1 failed, 2 usage, 3 refused |
| `func rise start/stop [ADDRESS...]` | corresponding mutating operation | 0, 1, 2, 3 if unavailable/refused |
| `func rise down [ADDRESS...]` | destructive action refused in v1 | 3 |
| `func rise search CONTRACT` | read configured indexes | 0 found, 1 none, 2 usage |
| `func rise add PACKAGE` | explicit plugin install and local record | 0, 1, 2 |

No positional address means `[rise] default`; several addresses are allowed.
There is no Rise `--env` flag, `--scope` flag, or `--yes` choice shortcut.
`up --force-reconcile` invokes `up` even if diagnosis passes. `up --dry-run`
shows candidate chains and planned actions without mutation. `up --no-deps`
still checks required dependencies. `up --wait --wait-timeout N` rechecks
diagnosis. `ps -q`, `ps --status`, `ps --filter`, and `ps --orphans`; `config
-q`, `config --subjects`, `config --environments`, `config --hash`, and
`config --sources` follow SD/18153475 §5.2. Rise reuses Functualize's exit
codes and root output controls.

## C5. Observable records

One NDJSON diagnosis line has keys `rise`, `record`, `id`, `contract`,
`candidate`, `diagnosis_id`, `observed_at`, `status`, `observation`, `requires`,
and `issues`. `status` is `pass` or `fail`; `candidate` names the job group.
`requires` refers to child records; the child's observation is not copied.
Records are deterministic and each subject is observed once per diagnosis.

A realization records subject, contract, candidate, identity, nonsecret config
fingerprint, secret source classes, timestamp, dependency chain, and whether
it is shared. A local backend implements the persistence Protocol. The
descriptor is generated on demand from the declaration and cached; it holds
types and secret markers, never secret values. No output or run record prints
secret bytes.

## C6. Registry v1

`[rise] registries` holds read-only HTTPS index URLs, disk paths, or Git/GitHub
repository references. A Git source may have an optional revision and an
optional path to a folder or single index file. Its config spelling and
folder-to-index convention remain provisional. Entries describe packages and
their provided contracts/candidates; the index JSON schema is provisional.
`search` reads indexes. `up --dry-run` marks registry
candidates `available`, while normal `up` refuses an uninstalled selection:

```text
refused: javascript.degit.npx is available but not installed
add it: func rise add functualize-rise-node
```

`up` never installs. Only `add` delegates to `func builtin plugin install`,
checks the package digest, records the package and registry in local
`rise-lock.json`, then uses ordinary discovery. Registry order resolves the
same package name. Signing, publishing, and trust policy are deferred.

V1 `add` uses a Python package/plugin discovered by Python. The other owner
options (comment 18809013), installation into the global Functualize XDG
directory or the repository-level `.functualize/` directory, are deferred.
The first needs global lifecycle rules; the second needs repository package
and trust rules. Neither is an implicit `up` behavior.

## C7. Core prerequisites and live tier

Released 0.5.0 must discover concrete job classes and their methods, preserve
the author's `@job` metadata, expose one shared config section, report job
name collisions, and accept ordinary explicit field values. Scoped vault v3
must resolve a secret at a subject-address group with nearest-ancestor and
active-environment precedence. A public job-callable resolved-secret read (F6)
must expose that result as `Secret` without printing it. The exact public
spelling is owned by the core prerequisite spec. These are release-entry
checks; Rise must not emulate them privately.

The offline Cloudflare provider uses a fake transport. A live tier requires
`CLOUDFLARE_ACCOUNT_ID` and `CLOUDFLARE_API_TOKEN`, skips when absent, and
creates only resources under a `rise-test-` prefix.
