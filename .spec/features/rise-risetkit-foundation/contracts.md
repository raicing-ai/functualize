# Rise / RiseKit foundation — external contracts

These are the surfaces that a provider author, a consumer, or a CI script
depends on. Every name is **provisional** in the sense of the 1.0 promise
decision: it becomes stable only once it is listed. Anything that waits on the
open boundary decision is marked **[D-2]**.

## C1. Distributions and import packages

| Distribution | Import package | Directory | Depends on | Role |
|---|---|---|---|---|
| `functualize-rise` | `functualize_rise` | `plugins/domains/functualize-rise/` | `functualize` (public API only) | the judge |
| `functualize-risekit` | `functualize_risekit` | `plugins/domains/functualize-risekit/` | `functualize-rise`, `functualize` (public API only) | the authoring toolkit; **no provider inside** (B5) |
| `functualize-rise-cloudflare` | `functualize_rise_cloudflare` | `plugins/substrates/functualize-rise-cloudflare/` | `functualize-risekit`, `functualize-rise`, `functualize` (public API only) | a provider package authored with RiseKit; owns the `cloudflare` namespace |

- None of the three goes into `functualize[all]` in this feature. `[all]` is
  what the standalone binary bakes in, and all three are experimental.
- All three distributions use the monorepo's `functualize-*` naming.
  Decision 15's `from risekit.javascript import Npm` is illustrative ("The exact
  API remains open"), so the import names follow this repository's convention.
- The provider sits under `plugins/substrates/` because the North Star names
  the Worker and D1 the "execution substrate" and the persistence. The directory
  groups are an organizing convention, not a loading mechanism:
  `tests/spec/test_every_declared_group_has_a_reader.py:72` globs
  `plugins/*/*`. The directory name is provisional.
- The provider lives in this repository only because FUN-8 needs its proof in
  this repository's CI. It uses nothing a third-party author could not use: the
  same public API, and RiseKit as an ordinary dependency (gate G8).

## C2. Entry points

Every group below is already read by core (`READ_GROUPS`,
`src/functualize/_primitives/entry_point_groups.py`). **This feature declares no
new group** (B6). A new group would also fail
`tests/spec/test_every_declared_group_has_a_reader.py`, which refuses any
shipped manifest declaring a `functualize.*` group that nothing in `src/` reads.

| Group | Name | Value | Distribution |
|---|---|---|---|
| `functualize.plugins` | `rise` | `functualize_rise:RisePlugin` | `functualize-rise`. Owns metadata namespace `rise` (`functualize_ext_namespaces = ("rise",)`) |
| `functualize.jobs` | `rise-validate` | `functualize_rise.jobs:rise_validate` | `functualize-rise` |
| `functualize.jobs` | `rise-diagnose` | `functualize_rise.jobs:rise_diagnose` | `functualize-rise` |
| `functualize.jobs` | `cloudflare-d1-diagnose`, `cloudflare-d1-provision`, `cloudflare-worker-diagnose` | `functualize_rise_cloudflare.jobs:<fn>` | `functualize-rise-cloudflare` |

`functualize-risekit` declares **no** entry point. It is a library that authors
import; nothing is discovered from it.

The `rise` plugin prints as `ADAPTER` in `func builtin plugin`, because
`functualize.plugins` classifies that way. This label is **inherited**, not
introduced. The maintainer accepted it in writing on 2026-09-17
(`.spec/STATUS.md:2930-2933`), and the Jev plugin already carries it
(`plugins/domains/functualize-decision-jev/pyproject.toml:23-24`).

## C3. Job metadata (Rise metadata on a Functualize job)

The job carries the attribute `__functualize_ext_rise__`. Discovery places its
value at `JobDescriptor.metadata["plugins"]["rise"]`. The value must be
JSON-serializable:

```json
{
  "rise": "1",
  "package": "acme.app",
  "contract": "cloudflare.d1@1",
  "contract_ref": "functualize_rise_cloudflare.contracts:D1",
  "operation": "diagnose",
  "subject": "d1.production",
  "relations": [
    {"kind": "binds", "target": "d1.production", "criticality": "required"}
  ]
}
```

- `rise`: schema generation, currently `"1"`.
- `contract`: the canonical string identity, of the form
  `<namespace>.<name>@<major>`. The namespace is dot-separated lowercase and the
  name is lowercase. The grammar is provisional.
- `contract_ref`: `<importable module>:<attribute>`, the **static** location of
  the contract value. It is the string form of the typed contract symbol an
  author imports (Decision 15: "Typed symbols and canonical string identities
  represent the same contract identity"). RiseKit's `@operation(<contract>, …)`
  derives both `contract` and `contract_ref` from the symbol it is given, so an
  author never writes either by hand (Decision 14: one typed source of truth). A
  hand-written package writes both strings (B2).
- `relations`: optional, and present only on the subject's `diagnose`
  operation. Relations are a property of the subject, so declaring them once is
  enough. Rise reads them from that job.
- `criticality`: either `"required"` or `"optional"`. It has no default in the
  schema. RiseKit's helper may default it to `required`; a hand-written
  declaration must state it (S7.7).

## C4. Capability-contract value  [D-2, sub-check 1]

A Rise capability contract is a frozen value of a Rise-defined type. Its
**namespace owner** constructs it in a declaration module, which may use
RiseKit's helper, and every job claiming it points at it with `contract_ref`:

```python
@dataclass(frozen=True)
class CapabilityContract:          # defined in functualize_rise
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
    mutating: bool                 # PROVISIONAL — see "Operation effects" below
```

- **Operation effects are PROVISIONAL [OS-1].** `mutating: bool` was revision
  1's placeholder. The owner asked whether operations should carry "destructive",
  "mutating" or "side-effect" markers, and whether to support opt-in
  plan/dry-run (Shape Intent 5407068 comments 11927574, 11927557). research.md
  § *R-2* lays out the candidate vocabulary, its semantics, its limits and its
  migration cost. **T2 must not freeze this field before OS-1 is answered.**
  Whatever OS-1 picks replaces the line above.

- **Resolution (S6):** Rise imports the `contract_ref` module, reads the
  attribute, and requires a `CapabilityContract` whose `identity` equals the
  declared `contract`. A declaration module holds contract values only and runs
  no operation. Importing it is the bounded cost of S4, and the no-import static
  analyzer of stage 5 can read the same string without importing.
- **Assessment:** the rule is the smallest one that makes `status` *derived*
  rather than asserted (Decision 5). A contract can say only which states pass.
  For `cloudflare.d1@1`: `states = {present, absent, error}`,
  `passing_states = {present}`, required fields `uuid` and `state`. Richer
  assessment (thresholds, a `degraded` state) waits for a second contract that
  needs it (review decision D4). Enlarging a contract later is a new major
  version, `cloudflare.d1@2`.
- **Ownership proof is not checked in this feature.** Decision 12 leaves the
  mechanism open ("registry identity, signing, domain/repository provenance, or
  another mechanism"). Rise checks identity equality only; stage 5 owns the
  proof.

## C5. Diagnose operation job: return value

A job implementing `diagnose` returns a JSON-serializable mapping, the
**observation**:

```json
{"state": "present", "present": true, "provider": "cloudflare",
 "uuid": "<uuid>", "evidence": {"...": "..."}}
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

| Command | From | Exit 0 | Exit non-zero | Stdout |
|---|---|---|---|---|
| `func rise-validate --package <id>` | `functualize-rise` | no findings | one or more findings (S7) | one human line per finding |
| `func rise-diagnose --package <id> [--subject <id>]` | `functualize-rise` | root `status: pass` | root `status: fail` | NDJSON (C6) |
| `func cloudflare-d1-provision --account-id … --database-name …` (token via secret) | `functualize-rise-cloudflare` | database exists afterwards | API refusal or transport failure | one diagnosis-shaped line |

The `func` spelling is provisional. The shape intent writes `rise validate`, and
whether that becomes a job group, a plugin command namespace
(`PluginHost.extensions.register_plugin_command`) or a console script is a
stage-5 surface question. These are ordinary Functualize jobs, so they reach MCP
and the TUI through the existing surfaces with no extra code (ADR-010).

## C8. Environment for live tiers

`CLOUDFLARE_ACCOUNT_ID` and `CLOUDFLARE_API_TOKEN` are the names the
substrate probe already uses (`tests/substrate_probe/d1.py`). A live test
**skips, never fails**, when either is absent, and the skip reason names the
missing variable (the convention from the substrate probe's conftest). Live
tests create resources only under a `rise-test-` name prefix.
