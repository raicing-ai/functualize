# Data model and transaction boundaries

## Modeling rules

1. Normalize fields used for identity, joins, ownership, status, ordering,
   retention, leases, and operational filtering.
2. Keep opaque user/provider payloads as JSON with a schema/version field at the
   owning boundary.
3. Keep large bytes outside runtime SQL; store an artifact URI, digest, media
   type, size, and ownership reference.
4. Use stable string IDs/ULIDs at the domain boundary. Provider-specific binary
   UUID optimization stays inside the adapter.
5. Every tenant/project query includes `namespace_id` in its key/index. A
   provider must not rely on callers remembering a free-form filter.
6. Append-only evidence is inserted, not rewritten. Mutable lifecycle rows use
   explicit version/fencing predicates.

## Proposed logical schema

Names are conceptual and may be shortened by FUN-18. Constraints and ownership
are the contract.

### Schema and namespace

| Table | Essential fields | Invariants/indexes |
|---|---|---|
| `schema_migrations` | `version`, `checksum`, `applied_at`, `provider_version` | one row per applied migration; checksum mismatch refuses boot |
| `runtime_namespaces` | `id`, `project_key`, `created_at`, `metadata_json` | unique `project_key`; all runtime roots reference it |

### Workflow aggregate

| Table | Essential fields | Invariants/indexes |
|---|---|---|
| `workflow_scopes` | namespace/id, workflow, graph digest, status, position, lease owner/expiry/generation, created/updated/terminal time | PK namespace+id; resumable/status and lease-expiry indexes |
| `workflow_steps` | scope, step key, iteration, status, inputs JSON, return JSON, reusable, started/completed time | unique scope+step+iteration; status index |
| `workflow_branches` | scope, decision key, chosen target, chosen time | unique scope+decision; choices are immutable |
| `scope_state` | scope, key, value JSON, version, updated time | unique scope+key; writes require current fence |
| `scope_events` | scope, sequence, type, payload JSON, occurred time, run id | unique scope+sequence; append only; watch index |

The lease fields stay on `workflow_scopes` because there is exactly one current
claim per aggregate and every transition already locks/conditions that row.
Lease history, if required, is evidence in `scope_events` rather than a second
authority.

### Runs and evidence

| Table | Essential fields | Invariants/indexes |
|---|---|---|
| `runs` | namespace/id, scope id, parent run id, job, surface, status, args hash, runner id, invoke depth, start/end/duration, failure code | PK namespace+id; recent, job, scope, parent indexes |
| `run_events` | run, sequence, type, payload JSON, occurred time | unique run+sequence; append only |
| `tool_calls` | id, run/scope/step, tool, status, request/result/error JSON, start/end/duration | run/time and scope/step indexes; terminal fields update once |
| `artifact_refs` | id, run/scope/step, kind, URI, digest, size, media type, created time | URI/digest are metadata; bytes live in workspace/blob provider |

Run argument values remain absent by default. `args_hash` identifies equivalent
inputs without persisting secrets. Explicit evidence capture requires a separate
redaction/retention decision.

### Interactions and effects

| Table | Essential fields | Invariants/indexes |
|---|---|---|
| `interaction_requests` | id, scope/step/gate key, kind, status, schema JSON, prompt/policy JSON, created/resolved time | one active request per scope+gate generation |
| `interaction_candidates` | id, request id, source, payload JSON, score/confidence, status, created time | request/status/source index; append candidate, do not overwrite |
| `interaction_evaluations` | id, request/candidate, evaluator, verdict, reason/evidence JSON, created time | append only; stable evaluator/version |
| `outbox` | id, namespace, aggregate type/id, topic, payload JSON, idempotency key, policy, created/available/claimed/published time, attempts, last error | unique idempotency key where applicable; claim/available index |

Gate input, AI inbound candidates, human approvals, and evaluator results are
modeled as interactions rather than nested fields inside one scope JSON object.
The scope stores only the authoritative gate/request relationship and terminal
decision.

## JSON boundary

Good JSON fields:

- step inputs/return values whose shape belongs to the job;
- gate schemas and candidate payloads;
- event/evaluation details not used in core predicates;
- provider metadata explicitly documented as opaque.

Bad JSON fields:

- `status`, `position`, `parent_run_id`, timestamps, sequence numbers;
- lease owner/expiry/generation;
- job/workflow names used in filters;
- artifact digest/URI/size;
- outbox claim/attempt/published fields.

This follows the useful part of Omnigent's model: searchable/operational fields
are columns with composite tenant-aware indexes, while genuinely opaque metadata
is JSON/text and artifacts point at separately owned blobs.

## Transaction catalogue

| Transition | Atomic writes | Runs outside transaction |
|---|---|---|
| start run | claim/ensure scope, fence generation, insert run, start events | job body |
| state batch | verify fence, upsert/delete state keys, state event if enabled | caller computation before batch |
| complete step | step outcome, branch/position, scope status, evidence, outbox intents | notification/tool/network delivery |
| finish run | run outcome, terminal scope mutation when applicable, final events/outbox | EventBus notification and rendering |
| suspend gate | request row, scope blocked status/position, event | collecting human/agent input |
| resume | consume accepted request, claim with new generation, mark running, resume event | resumed job body |
| dispatch effect | claim outbox row | provider call |
| acknowledge effect | published/error/next attempt | — |

## Fencing algorithm

Claim is one conditional update:

```sql
UPDATE workflow_scopes
SET lease_owner = :runner,
    lease_expires_at = :expiry,
    lease_generation = lease_generation + 1
WHERE namespace_id = :namespace
  AND id = :scope
  AND (lease_owner = :runner OR lease_expires_at <= :now)
RETURNING lease_generation;
```

Every authoritative scope/state/step write includes
`WHERE lease_generation = :held_generation`. A stale runner cannot commit even
if its clock or lease view is wrong. SQLite may serialize the update; network
SQL may use row locks or compare-and-swap, but the semantic contract is the same.

## Retention and deletion

- Live/blocked scopes are never evicted by a cap.
- Terminal scopes and runs use policy-driven age/count retention.
- Deleting a scope cascades its state, steps, branches, interactions, and scope
  events in one transaction; referenced artifacts follow workspace retention,
  not blind SQL cascade.
- Evidence subject to legal/audit retention may outlive the operational scope;
  if enabled, it is exported or detached explicitly rather than accidentally
  retained by failed cascades.
- Freshness and shell history keep their existing discard rules outside this
  schema.

## Migration discipline

- Migrations are ordered, checksummed, idempotent at the runner level, and
  serialized by a provider migration lock.
- Explicit provider selection runs migrations before `APP_READY` and before any
  job can execute.
- SQLite migration tests start from every supported historical schema, not only
  an empty database.
- Network providers test concurrent migrators and recovery from a failed
  migration. A partially applied revision is a boot refusal with repair steps.
- ORM `create_all()` is acceptable only for a brand-new empty database; it is
  not an upgrade mechanism.
