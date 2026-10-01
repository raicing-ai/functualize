# Rise / RiseKit foundation — external contracts

These are the surfaces that a provider author, a consumer, or a CI script
depends on. Names are **provisional** in the sense of the 1.0 promise decision
(stable only once listed). Spelling that waits on a member decision is marked
**[D-n]**.

## C1. Distributions and import packages  [D-3]

| Distribution | Import package | Directory | Depends on |
|---|---|---|---|
| `functualize-rise` | `functualize_rise` | `plugins/domains/functualize-rise/` | `functualize` (public API only) |
| `functualize-risekit` | `functualize_risekit` (reference package: `functualize_risekit.cloudflare`) | `plugins/domains/functualize-risekit/` | `functualize-rise`, `functualize` (public API only) |

Neither package goes into `functualize[all]` in this feature. `[all]` is what
the standalone binary bakes in, and both are experimental.

## C2. Entry points

| Group | Name | Value | Owner |
|---|---|---|---|
| `functualize.plugins` | `rise` | `functualize_rise:RisePlugin` | Rise. Owns metadata namespace `rise` (`functualize_ext_namespaces = ("rise",)`) |
| `functualize.jobs` | `rise-validate` | `functualize_rise.jobs:rise_validate` | Rise |
| `functualize.jobs` | `rise-diagnose` | `functualize_rise.jobs:rise_diagnose` | Rise |
| `functualize.rise_contracts` | `cloudflare.d1@1`, `cloudflare.worker@1` | `functualize_risekit.cloudflare.contracts:<NAME>` | RiseKit (namespace owner of `cloudflare`) |
| `functualize.jobs` | `cloudflare-d1-diagnose`, `cloudflare-d1-provision`, `cloudflare-worker-diagnose` | `functualize_risekit.cloudflare.jobs:<fn>` | RiseKit |

`functualize.rise_contracts` classifies as `UNKNOWN` under
`_primitives/plugin_kinds.classify_group`, because it is neither `plugins`,
`domains` nor `*_providers`. The classification is accepted for this feature:
it changes only how `func builtin plugin` labels the group, and renaming it to
fit the taxonomy is a stage-5 question (plan.md § *Surviving smells*, SM-3).

## C3. Job metadata (Rise metadata on a Functualize job)

The job carries the attribute `__functualize_ext_rise__`. Discovery places its
value at `JobDescriptor.metadata["plugins"]["rise"]`. The value must be
JSON-serializable:

```json
{
  "rise": "1",
  "package": "acme.app",
  "contract": "cloudflare.d1@1",
  "operation": "diagnose",
  "subject": "d1.production",
  "relations": [
    {"kind": "binds", "target": "d1.production", "criticality": "required"}
  ]
}
```

- `rise`: schema generation, currently `"1"`.
- `contract`: has the form `<namespace>.<name>@<major>`. The namespace is
  dot-separated lowercase and the name is lowercase. The grammar is
  provisional.
- `relations`: optional, and present only on the subject's `diagnose`
  operation. Relations are a property of the subject, so declaring them once is
  enough. Rise reads them from that job.
- `criticality`: either `"required"` or `"optional"`. It has no default in the
  schema. RiseKit's authoring helper may default it to `required`; a
  hand-written declaration must state it (S5.7).

## C4. Capability-contract artifact

A Rise capability contract is a Rise-defined frozen value, loaded from the
`functualize.rise_contracts` entry point named by its identity:

```python
@dataclass(frozen=True)
class CapabilityContract:          # functualize_rise
    identity: str                  # "cloudflare.d1@1"
    subject_kind: str              # "d1-database"
    operations: Mapping[str, OperationContract]
    observation_fields: Mapping[str, FieldRule]   # required observation keys + type
    states: frozenset[str]         # legal observation.state values
    passing_states: frozenset[str] # assessment: status = pass iff state ∈ passing_states
                                   #             and every required field is present

@dataclass(frozen=True)
class OperationContract:
    name: str                      # "diagnose" | "provision"
    required: bool                 # must a conformant package implement it?
    mutating: bool
```

The foundation's assessment rule is deliberately the smallest one that makes
`status` *derived* rather than asserted (S8): a contract can only say which
states pass. Richer assessment waits on a second contract that needs it (the
review check carried under D-2 in `plan.md` § *Decisions for the member*).

## C5. Diagnose operation job: return value

A job implementing `diagnose` returns a JSON-serializable mapping, the
**observation**:

```json
{"state": "present", "present": true, "provider": "cloudflare",
 "resource_id": "<uuid>", "evidence": {...}}
```

Rise validates the observation against the contract's `observation_fields`
and `states`. A job that raises, or returns something non-conformant, yields a
`fail` record carrying an `observation_error` issue. It never yields an
exception in the stream.

## C6. Diagnosis record (one NDJSON line)

```json
{"rise":"1","record":"subject","id":"worker.production",
 "diagnosis_id":"<uuid4 per invocation>","observed_at":"<RFC3339 UTC>",
 "package":"acme.app","contract":"cloudflare.worker@1",
 "status":"fail","observation":{"state":"present", "...": "..."},
 "requires":[{"target":"d1.production","criticality":"required","status":"fail"}],
 "issues":[{"code":"required_dependency_failed","ref":"d1.production"}]}
```

- `record` is either `"subject"` or `"package"`. The package record comes
  last. Its `requires` lists every subject record, and its `status` is the
  aggregate.
- Issue codes in this feature: `required_dependency_failed`,
  `observation_error`, `nonconformant_observation`, `state_not_passing`,
  `relation_cycle`, `unknown_target`.
- Field order is not part of the contract. Key names and value types are.

## C7. Commands

| Command | Exit 0 | Exit non-zero | Stdout |
|---|---|---|---|
| `func rise-validate --package <id>` | no findings | one or more findings (S5) | one human line per finding |
| `func rise-diagnose --package <id> [--subject <id>]` | root `status: pass` | root `status: fail` | NDJSON (C6) |
| `func cloudflare-d1-provision --account-id … --database-name …` (token via secret) | database exists afterwards | API refusal or transport failure | one diagnosis-shaped line |

The `func` spelling is provisional. The shape intent writes `rise validate`, and
whether that becomes a group or a dedicated console script is a stage-5 surface
question. These are ordinary Functualize jobs, so they reach MCP and the TUI
through the existing surfaces with no extra code (ADR-010).

## C8. Environment for live tiers

`CLOUDFLARE_ACCOUNT_ID` and `CLOUDFLARE_API_TOKEN` are the names the
substrate probe already uses (`tests/substrate_probe/d1.py`). A live test
**skips, never fails**, when either is absent, and the skip reason names the
missing variable (the convention from the substrate probe's conftest). Live
tests create resources only under a `rise-test-` name prefix.
