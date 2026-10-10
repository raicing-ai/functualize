# Rise / RiseKit foundation — external contracts (revision 5)

These are the surfaces that a provider author, an environment author, or a CI
script depends on. Every Python name is **provisional**: SD/5407068 v18
leaves "exact serialization and policy schemas" to the specification (D27).
Names become stable only once listed in a release.

Canon references (`D<n>`) are to SD/5407068 v18. Behaviour references (`S<n>`)
are to `spec.md`.

## C1. Distributions and import packages

| Distribution | Import package | Directory (provisional) | Depends on | Role |
|---|---|---|---|---|
| `functualize-rise` | `functualize_rise` | `plugins/domains/functualize-rise/` | `functualize` (public API only) | the convention: declaration model, identities, roles, descriptors, `validate` / `diagnose` / `up`, realization port |
| `functualize-risekit` | `functualize_risekit` | `plugins/domains/functualize-risekit/` | `functualize-rise`, `functualize` (public API only) | the reference toolkit: substrate bases, typed observation models, contract-test helper. **No provider inside** (B5) |
| `functualize-rise-cloudflare` | `functualize_rise_cloudflare` | `plugins/substrates/functualize-rise-cloudflare/` | `functualize-risekit`, `functualize-rise`, `functualize` (public API only) | provider package; owns the `cloudflare` namespace |

**[5]** All three require `functualize>=0.5.0,<1.0.0`, which is the public API
the 0.5.0 cut ships (spec §0). They release in lockstep with the repository,
in the first release after 0.5.0 (spec R-1).

- None of the three goes into `functualize[all]` in this feature, because all
  three are experimental.
- The directory groups are an organizing convention, not a loader:
  `tests/spec/test_every_declared_group_has_a_reader.py` globs `plugins/*/*`.
- The provider lives in this repository only so that FUN-8's proof runs in this
  repository's CI. It uses nothing a third-party author could not use.

## C2. Entry points

**This feature declares no new entry-point group** (B6).

| Group (existing) | Name | Value | Distribution |
|---|---|---|---|
| `functualize.plugins` | `rise` | `functualize_rise.plugin:RisePlugin` | `functualize-rise` |
| `functualize.plugins` | `rise-cloudflare` | `functualize_rise_cloudflare.plugin:plugin` | `functualize-rise-cloudflare` **[5]**: binds its own subject classes (spec B6, A-1) |

**[4.1]** `RisePlugin` registers Rise's own three commands, and nothing else,
with `app.extensions.add_job_provider(StaticProvider([Job(fn, name=<verb>,
group="rise"), …]))`. That is public plugin API (`functualize.plugin.Job`,
`StaticProvider`), tested at `tests/plugins/test_public_provider_seam.py`.

The commands are not published under `functualize.jobs`. An entry-point job's
group is unknown until it is materialized
(`src/functualize/_discovery/providers.py:735-741`), so `func rise <verb>`
could not be listed. The plugin module imports only the command functions; the
heavy modules are imported inside the job bodies, which keeps boot cost to one
small import.

Provider subject classes reach Functualize through the generic class-discovery
path (C11, P-1), not through anything Rise registers. `functualize-risekit`
declares no entry point; it is a library.

## C3. Declaration surface (Python, provisional names)

```python
# functualize_rise_cloudflare/contracts.py — the namespace owner's contract
from functualize.types import Secret
from functualize_risekit.substrates import RemoteResource, RemoteResourceObservation
from functualize_rise import Realization, contract


@contract("cloudflare.d1@1")                     # identity grammar: C4
class D1Database(RemoteResource):                # abstract: this IS the contract
    account_id: str
    database_name: str
    api_token: Secret[str]                       # secret-marked config (S7)

    class Realized(Realization):                 # the contract's realization type (D18)
        uuid: str

    def diagnose(self) -> RemoteResourceObservation: ...    # role: read-only
    def up(self) -> "D1Database.Realized": ...              # role: convergent
```

```python
# functualize_rise_cloudflare/providers.py — one implementation (one candidate)
class CloudflareApiD1(D1Database):
    candidate = "api"          # [5] required: canonical group cloudflare.d1.api (C5)
    def diagnose(self) -> RemoteResourceObservation: ...
    def up(self) -> D1Database.Realized: ...
```

```python
# functualize_rise_cloudflare/plugin.py — [5] the provider binds its own classes (spec B6, A-1)
from functualize.plugin import StaticProvider
from functualize_rise import bind

from .providers import CloudflareApiD1, CloudflareApiWorker


class _Plugin:
    name = "rise-cloudflare"
    version = "…"
    description = "Bind the Cloudflare Rise subjects as jobs"

    def __call__(self, app) -> None:
        app.extensions.add_job_provider(
            StaticProvider(bind(CloudflareApiD1, CloudflareApiWorker))
        )


plugin = _Plugin()
```

```python
# a project's local subjects: .functualize/plugins/subjects.py — [5] same helper
from functualize.plugin import StaticProvider
from functualize_rise import bind
from modules.multica import MulticaStack   # a local subject: no contract ancestor

plugin = ...  # same shape as above, calling bind(MulticaStack)
```

```python
# example project: jobs/environments.py — an environment declaration (D22)
from functualize_rise import Environment, Ref

def cloudflare_dev() -> Environment:             # any job returning Environment
    return Environment(
        d1={"main": CloudflareApiD1(account_id="…", database_name="app")},
        worker={"api": CloudflareApiWorker(account_id="…", script_name="api",
                                           database=Ref["cloudflare_dev.d1.main"])},
    )
```

The rules the surface must keep. Only the class shapes and fields are
contract here; the spellings above are illustrative.

- **Subject.** Fields are typed, immutable and serializable configuration.
  Constructing a subject performs no operational I/O (S1).
- **Contract.** The class is abstract and carries an identity. Its abstract
  methods are the contract's operations and signatures. Exactly one nested or
  declared `Realization` subtype is the realization type (S2).
- **Local subject.** A concrete class with no contract ancestor. Its identity
  is `local:<qualified class name>` (S2).
- **No Rise decorator on operations, and no hand-written Rise tags** (D16). A
  method may carry Functualize's own `@job(...)` for Functualize features.
- **`Ref`.** A `Ref[T]` or `Ref["address"]` field is an ordering edge with
  criticality `required` by default. The spelling for `optional` criticality
  and for an informational relation is provisional, and Plan fixes it (S12).
  Either way, both are declared on the field, never in a separate table.

## C4. Identities

```
contract       := namespace "." name "@" major          e.g. cloudflare.d1@1
operation      := contract "/" verb [ "+" strategy ]    e.g. cloudflare.d1@1/up
local subject  := "local:" qualified-name
namespace      := segment ( "." segment )*      segment := [a-z][a-z0-9-]*
name, verb     := [a-z][a-z0-9_-]*              major   := [1-9][0-9]*
address        := environment-job-address ( "." local-id )+
```

- The shape `ns.name@major/op[+strategy]` is from D27. It is provisional, and
  `+strategy` is reserved: no strategy is selectable in this feature (S24).
- An address uses dots as Functualize command paths do (SD/12779576 v2: "A dot
  belongs only to the command path"). A local id must not contain a dot.

## C5. Generated job metadata (S3)

| Tag on the canonical operation job | Example |
|---|---|
| `rise:op:<verb>` | `rise:op:up` |
| `rise:implements:<contract>/<verb>` | `rise:implements:cloudflare.d1@1/up` (absent for a local subject) |
| `effect:<role>` | `effect:convergent` |

Roles and their defaults:

| Verb | Role |
|---|---|
| `validate`, `diagnose` | `read-only` |
| `up`, `update` | `convergent` |
| `start`, `stop` | `mutating` |
| `down` | `destructive` |
| anything else | `mutating`, unless explicitly declared otherwise (spec OQ-2) |

These tags are generated from the declaration and written through
Functualize's public job-declaration surface, so they appear in
`func builtin info` like any other tag. An author never writes them.

**[5] Canonical job produced by `bind()`** (spec S4):

| Part | Contract implementation | Local subject |
|---|---|---|
| `group` | `<namespace>.<name>.<candidate>`, e.g. `cloudflare.d1.api` | the class's `group`, else `local.<snake_class_name>` |
| `name` | `<group>.<verb>`, e.g. `cloudflare.d1.api.up` | `<group>.<verb>` |
| parameters | `subject: <implementing class>` (the job config model, F-2) and `address: str` | same |
| declaration | the method's own `JobDeclaration` (read from the documented `__functualize_job__`, `docs/guides/jobs-discovery.md:377`), with the generated tags appended through `dataclasses.replace` | same |

## C6. Descriptor (S5)

A JSON document generated on demand from a contract or a local subject class,
and cached under Functualize's per-project cache directory. Its location is
provisional; the precedent is `$XDG_CACHE_HOME/functualize/<project_id>/`,
`src/functualize/_primitives/fresh_format.py:17`. It is never committed.

```json
{"rise": "1", "kind": "contract", "id": "cloudflare.d1@1",
 "substrate": "remote-resource",
 "config": {"account_id": {"type": "str"}, "database_name": {"type": "str"},
            "api_token": {"type": "str", "secret": true}},
 "operations": {"diagnose": {"role": "read-only", "returns": "RemoteResourceObservation"},
                "up": {"role": "convergent", "returns": "D1Database.Realized"}},
 "realization": {"type": "D1Database.Realized", "fields": {"uuid": {"type": "str"}}},
 "refs": {}, "source_digest": "sha256:<digest of the declaring module>"}
```

- A descriptor carries types and secret **markers**, never values (S8).
- `rise validate` regenerates the descriptor and compares it with the runtime
  metadata. A disagreement is a finding (S15.11).

## C7. Environment and scope

- An environment is the return value of a job annotated `-> Environment`. Its
  address is the job's address (S9).
- Nested scopes are named mappings inside an `Environment`. A subject's address
  is `<env-address>.<scope>…<local-id>` (S11).
- The unscoped root is a Functualize configuration value (S13). Provisional
  spelling:

  ```toml
  [rise]
  root = "cloudflare_dev"   # an environment or scope address
  ```

  The key is `root`; there is no `hosting` key and no `protected_by` (D25).

## C8. Diagnosis record (one NDJSON line, S17–S20)

```json
{"rise":"1","record":"subject","id":"cloudflare_dev.worker.api",
 "contract":"cloudflare.worker@1","candidate":"functualize_rise_cloudflare.providers:CloudflareApiWorker",
 "diagnosis_id":"<uuid4 per invocation>","observed_at":"<RFC3339 UTC>",
 "status":"fail","observation":{"state":"present","present":true,"...":"..."},
 "requires":[{"target":"cloudflare_dev.d1.main","criticality":"required","status":"fail"}],
 "issues":[{"code":"required_dependency_failed","ref":"cloudflare_dev.d1.main"}]}
```

- `record` is `"subject"` or `"root"`. The root record comes last. Its
  `requires` lists every top-level subject in scope, and its `status` is the
  aggregate.
- Issue codes in this feature are `required_dependency_failed`,
  `observation_error`, `nonconformant_observation`, `state_not_passing` and
  `unknown_target`. Ordering cycles are refused by `validate` (S15.9) before
  traversal.
- Key names and value types are contract; field order is not.

## C9. Realization record and port (S26)

```json
{"rise":"1","subject":"cloudflare_dev.d1.main","contract":"cloudflare.d1@1",
 "candidate":"functualize_rise_cloudflare.providers:CloudflareApiD1",
 "identity":{"uuid":"<uuid>"},"config_fingerprint":"sha256:<non-secret fields only>",
 "secrets":{"api_token":"vault"},"isolation":"remote","recorded_at":"<RFC3339 UTC>",
 "dependency_chain":[],"shared":false}
```

- The port is a typing `Protocol` with two operations: append a record, and read
  the records for an address. That follows the constitution's rule of
  Protocol, not ABC, for ports.
- Records are append-only.
- This feature ships one backend, a local file. The shared backend is deferred.
  `shared: false` is the OD-2 (a) marker.
- `secrets` maps each secret field to its **source class** only (S8).

## C10. Commands and exit status

| Command | Exit `OK` (0) | Non-zero | Stdout |
|---|---|---|---|
| `func rise validate [--scope <address>]` | no findings | `JOB_RAISED` (1) on findings | one line per finding |
| `func rise diagnose [--scope <address>]` | root `status: pass` | `JOB_RAISED` (1) when the root fails | NDJSON (C8) |
| `func rise up [--scope <address>]` | every subject in scope converged | `JOB_RAISED` (1) on an operation failure; `REFUSED` (3) for several candidates, a destructive role, or a declaration with findings | one line per subject: converged, changed, not attempted |
| any of the above, unscoped with no root and not exactly one environment, or an unknown address | — | `USAGE` (2) | the environment addresses found |

- These codes are Functualize's existing `ExitCode`
  (`src/functualize/_types/exit_codes.py:36-44`, public through
  `functualize.types`). Rise adds no exit code (D27).
- The mapping above is a proposal, confirmed with the spec.
- The commands are ordinary jobs, so they reach MCP and the TUI through the
  existing surfaces.

## C11. Required of Functualize

**[5] Rise v1 requires nothing beyond Functualize 0.5.0's public API.** The
seams it uses were all exercised by the spec §0 probe on `4e816a0f`:

- `functualize.plugin.Job` and `StaticProvider`, and
  `app.extensions.add_job_provider`;
- `functualize.job.Invoke`, `job` and `JobDeclaration`;
- `functualize.types.RunRequest`, `Secret` and `ExitCode`;
- pydantic models as job config;
- `.functualize/plugins/` and `functualize.plugins` discovery.

What a **later** core release would let Rise drop or improve. These are the
migration triggers of spec §6, and none of them is required:

- **P-1 class discovery.** One canonical job per (subject class, method),
  invoked with an address. Tags contributed by the class merge with the
  author's `@job`. Literal values are fixed per address. With it, providers
  delete their `bind()` plugin, and job identities (C5) are kept.
- **P-8 shared section for plugin jobs.** A grouped plugin job reads its
  group's section, and `get_job_config_section` agrees with the run. With it,
  one `[<ns>.<name>.<candidate>]` section serves every operation of a subject.
- **Vault v3 implemented** (SD/12779576 v3). Subject address as the vault
  group, and environment-qualified entries. With it, per-operation vault
  entries are no longer needed.
- **P-2 to P-6.** Not consumed. Instance routes (D23), `Setting()` (D24), route
  provenance, and Gate-backed choice (D20) stay deferred.

## C12. Live tier

`CLOUDFLARE_ACCOUNT_ID` and `CLOUDFLARE_API_TOKEN` are the names the substrate
probe already uses (`tests/substrate_probe/d1.py`). The live tier supplies them
to the subjects' configuration through Functualize's environment source; no
Rise code reads them. A live test **skips, never fails**, when either variable
is absent, and names the missing one. Live tests create resources only under a
`rise-test-` name prefix and never delete outside that prefix (S27: the
cleanup is the test's own, not a Rise `down`).
