# Gate interactions, evidence, and the transactional outbox — contracts

Every interface that changes at a boundary. Names marked **(binding)** are fixed by the
approved Shape Intent; everything else is settled by `spec.md` §5.

## 1. Vocabulary — `functualize._types.gate_resolution`

```python
GATE_ACCEPTED_TOPIC: Final = "gate.accepted"

@dataclass(frozen=True)
class EvidenceRef:
    ref: str                 # where the bytes live; never the bytes
    digest: str              # "sha256:<64 hex>"
    media_type: str | None = None
    size: int | None = None

@dataclass(frozen=True)
class GateCandidate:         # (binding) — fields added, all defaulted
    ...existing fields...
    resolver_class: str = ""             # human | agent | program | policy
    channel: str = ""
    schema_id: str = ""
    schema_version: str = ""             # "sha256:<hex>"
    payload_hash: str = ""               # "sha256:<hex>"
    supersedes_candidate_id: str | None = None
    evidence_refs: tuple[EvidenceRef, ...] = ()

@dataclass(frozen=True)
class GateDecision:
    request_id: str
    accepted_id: str
    policy_id: str
    policy_version: str
    observed_candidate_ids: tuple[str, ...]
    decided_at: datetime

@dataclass(frozen=True)
class GateResolution:        # (binding) — one field added
    ...existing fields...
    decision: GateDecision | None = None
```

`CandidateEvaluation` **(binding)** is unchanged.

## 2. Ports — `functualize._types.persistence`

```python
@dataclass(frozen=True)
class InputRequest:          # (binding) — causal identity added, defaulted
    ...existing fields...
    run_id: str | None = None
    position: str | None = None

@dataclass(frozen=True)
class SuspendAtGate:         # run_id added, defaulted
    ...existing fields...
    run_id: str | None = None

@dataclass(frozen=True)
class SupersedeRequest:      # new — reopen through the port (D-4)
    scope_id: str
    gate_name: str
    request_id: str          # the accepted request being withdrawn
    new_request_id: str      # minted by the recorder
    now: datetime

@dataclass(frozen=True)
class EffectIntent:          # new — what a recorder hands EffectWriter.append
    namespace: str
    topic: str
    payload: Any
    idempotency_key: str

class InputWriter(Protocol):          # two members added
    def append(self, candidate: GateCandidate) -> None: ...
    def consume(self, cmd: ConsumeInput) -> None: ...
    def decide(self, decision: GateDecision) -> None: ...
    def supersede(self, cmd: SupersedeRequest) -> None: ...

class InputReader(Protocol):          # one member added
    ...
    def decision(self, request_id: str) -> GateDecision | None: ...

@dataclass(frozen=True)
class EffectView:            # new — one outbox row as a dispatcher sees it
    effect_id: str
    topic: str
    aggregate_type: str
    aggregate_id: str
    payload: Any
    idempotency_key: str | None
    status: str              # pending | claimed | published
    attempts: int
    available_at: datetime
    claimed_at: datetime | None = None
    published_at: datetime | None = None
    last_error: str | None = None
    claim_token: str | None = None

class EffectQueue(Protocol):          # new — outside any transaction
    def claim(self, topics: Sequence[str], *, now: datetime,
              lease_seconds: float, limit: int) -> Sequence[EffectView]: ...
    def published(self, effect: EffectView, *, now: datetime) -> None: ...
    def failed(self, effect: EffectView, *, error: str, retry_at: datetime) -> None: ...
    def effect(self, effect_id: str) -> EffectView | None: ...

class OutboxStore(RuntimeStore, Protocol):   # new — durable_outbox=True stores
    effects: EffectQueue

class EffectReceiver(Protocol):       # new — a consumer of one topic
    topic: str
    def receive(self, effect: EffectView) -> None: ...
```

`RuntimeStore` itself is unchanged, so the document store and every existing fake still
satisfy it. A store whose profile declares `durable_outbox=True` must satisfy
`OutboxStore`; boot refuses a store where the two disagree.

## 3. Lifecycle — `functualize._types.lifecycle`

- `INPUT_REQUEST` gains `("accepted", "cancelled")` — reopen supersedes an accepted
  request (member decision D-4).
- New `OutboxStatus` (`pending`, `claimed`, `published`) and `OUTBOX` machine:
  `None→pending`, `pending→claimed`, `claimed→claimed` (an expired claim retaken),
  `claimed→published`, `claimed→pending` (a failure scheduled for retry);
  `published` absorbing.

## 4. Plugin host and public API

- `PluginHost.register_effect_receiver(receiver: EffectReceiver) -> None` — new, on the
  host protocol (`_types/host.py`) and the app's extensions facade. One receiver per
  topic; a second for the same topic raises `ValueError`; registration after boot
  selected the store raises `SubstrateInstallError`; a non-conforming object raises
  `TypeError`.
- `functualize.plugin.__all__` gains `EffectReceiver`, `EffectView`, `EvidenceRef`,
  `GateDecision`, `GATE_ACCEPTED_TOPIC`. `tests/test_public_api_surface.py` and an
  `examples/` caller move with them; the decision is ADR-034.
- `functualize.app.utils.answer_gate(..., evidence=...)` gains a keyword-only
  `evidence: Sequence[EvidenceRef] = ()`.

## 5. SQLite schema — revision `0003_gate_interactions.sql`

```sql
ALTER TABLE input_requests   ADD COLUMN run_id   TEXT;
ALTER TABLE input_requests   ADD COLUMN position TEXT;
ALTER TABLE input_candidates ADD COLUMN resolver_class TEXT;
ALTER TABLE input_candidates ADD COLUMN channel TEXT;
ALTER TABLE input_candidates ADD COLUMN schema_id TEXT;
ALTER TABLE input_candidates ADD COLUMN schema_version TEXT;
ALTER TABLE input_candidates ADD COLUMN payload_hash TEXT;
ALTER TABLE input_candidates ADD COLUMN supersedes_candidate_id TEXT;
ALTER TABLE artifact_refs    ADD COLUMN candidate_id TEXT REFERENCES input_candidates (id) ON DELETE CASCADE;
ALTER TABLE outbox           ADD COLUMN claim_token TEXT;
CREATE TABLE input_decisions (...);   -- append-only by trigger, one row per request
```

Additive only: a revision-`0002` file migrates forward with every existing row intact
and every new column `NULL`, which reads back as the defaulted field.

## 6. Command line and MCP

No command, flag or tool is added or renamed. Behaviour changes (spec §3.5):
`answer`/`resume` and the MCP gate tools address the selected store; on a relational
store `--no-commit` is refused with `draft_requires_commit` and `--retry-epilogue` with
`epilogue_retry_unsupported`, both exit `2` (usage) on the CLI.

## 7. Import-linter contracts

No contract changes. `_primitives/outbox.py` imports `_types` only; `_app` composes it;
`app/` already imports `_engine.recording` and `_primitives`.

## 8. Backward compatibility

Pre-release; no obligation. What changes for a user:

- A relational project's `answer`/`resume` now work (they addressed an empty scope
  document before). A document project sees the same commands behave as before, plus
  the new provenance keys in `--format json`.
- A project that registers an `EffectReceiver` on the document store no longer boots.
- Falsified by: `uv run pytest tests/app tests/cli tests/workflow plugins/adapters/functualize-mcp/tests plugins/substrates/functualize-substrate-sqlite/tests`.
