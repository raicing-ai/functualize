# Schema: workflow-state-durability

On-disk formats and internal types. External surface is `contracts.md`.

---

## 1. `scopes.json` — the new file

Beside `state.json`, in whichever of the two modes
`resolve_state_location` picked (`project` → `.functualize/scopes.json`;
`standalone` → `$XDG_CACHE_HOME/functualize/<project_id>/scopes.json`). The path
is **derived** from the state path, never resolved separately:

```python
SCOPES_FILENAME = "scopes.json"
SCOPES_VERSION = 1

def resolve_scopes_path(start: Path | str) -> Path:
    return resolve_state_location(Path(start))[0].with_name(SCOPES_FILENAME)
```

Envelope:

```json
{
  "format_version": 1,
  "scopes": {
    "<scope_id>": { … scope record … }
  }
}
```

Two keys, no more. `format_version` is **independent of `STATE_VERSION`** (AC-2):
bumping one says nothing about the other, which is the entire point of the split.

### 1.1 Scope record — unchanged

Byte-for-byte what `_blank_scope()` produces today. No field is added, renamed or
removed by this feature (`contracts.md` §4).

```json
{
  "workflow":   "release-pipeline" | null,
  "status":     "running" | "blocked" | "completed" | "failed" | "cancelled",
  "steps":      { "<job_name>::<args_hash>": { … step record … } },
  "branches":   { "<source_node>": "<chosen_target>" },
  "gates":      { "<gate_name>":   { … gate record … } },
  "position":   "<node_name>" | null,
  "epilogue":   { … } | null,
  "tool_calls": [ { … }, … ]
}
```

`scopes` stays a flat `{str: record}` mapping — the shape
`StateBackend`'s KV protocol (`get`/`set`/`delete`/`keys`) addresses, so
`functualize-state-sqlite` can back this store later without a record-format
change (`state_store.py:13-19`). That seam is preserved, not built.

## 2. `state.json` — what leaves it

```diff
  {
    "format_version": 1,
    "fingerprints": {},
-   "scopes": {},
    "history": [],
    "session": {"preconditions": {}}
  }
```

`_SECTIONS` becomes `("fingerprints", "history", "session")`. `STATE_VERSION` is
**not** bumped: the removal is what this feature is for, and bumping it would
discard every fingerprint for no reason. A `state.json` still carrying a `scopes`
key is simply ignored — `normalize_state` copies only the sections it knows.

The header comment at `state_format.py:41-48` currently reads:

> *A version mismatch discards the file (runtime state is derived, never a source
> of truth — the worst case is one extra run).*

That becomes true only once `scopes` is gone, and the comment must say so
explicitly — naming the split, so the next person to add a section to this file
has to decide which of the two it belongs in (spec.md §5, third bullet).

## 3. Read behaviour, side by side

The one table that has to be right. `state.json` is a cache; `scopes.json` is a
record.

| Condition | `state.json` (today, unchanged) | `scopes.json` (new) |
|---|---|---|
| file absent | empty envelope | empty — "no scopes" (AC-5) |
| unparseable JSON | empty envelope | **raise**, file untouched (AC-6) |
| not a dict | empty envelope | **raise**, file untouched (AC-6) |
| `format_version` mismatch | empty envelope | **raise**, file untouched (AC-4) |
| unknown extra keys | ignored | ignored |
| `scopes` not a dict | — | **raise** (AC-6) |

The right-hand column is a deliberate divergence from
`_discovery/cached_provider.py:285-367`, whose silent-recovery-and-delete
`load_state` copied. That is correct for a cache — derived, cheap to rebuild,
deleting the stale file is a feature — and wrong for the only record of a run
holding a human's approval.

**The file is never renamed by a read** (`plan.md` §1.2). Refusing is a stable,
repeatable state; renaming would make the *second* run find nothing and start over
silently, which is the defect this feature removes.

## 4. `ScopeStoreUnreadableError`

`_types/errors.py`, `Error`-suffixed per `CONSTITUTION.md` naming.

| Attribute | Type | Meaning |
|---|---|---|
| `path` | `Path` | the file that could not be read |
| `scope_count` | `int \| None` | scopes visible in it, or `None` when unparseable |
| `found_version` | `int \| None` | the version on disk, when that is the cause |
| `expected_version` | `int` | `SCOPES_VERSION` |

`scope_count` is a **count, never content**. Scope records hold gate payloads and
step return values, which may be secrets; `_events`' history section already stores
`args_hash` only, for the same reason
(`.serena/memories/execution-ordering-contract.md`). The message names how many
runs are at stake and the command that discards them — nothing about what they say.

## 5. Internal types

```python
class ScopeStore:
    def __init__(self, path: Path | str) -> None: ...
    @classmethod
    def for_project(cls, start: Path | str) -> ScopeStore: ...
    @property
    def path(self) -> Path: ...

    # the 16 accessors moved verbatim from StateStore
    def get_scope(...); def ensure_scope(...); def set_scope_status(...)
    def record_step(...); def get_step(...)
    def record_branch(...); def get_branch(...)
    def put_gate(...); def get_gate(...); def deposit_gate_payload(...)
    def set_position(...); def get_position(...)
    def record_epilogue(...); def get_epilogue(...)
    def record_tool_call(...); def get_tool_calls(...)
    def scope_ids(self) -> list[str]: ...

    @contextmanager
    def batch(self) -> Iterator[ScopeStore]: ...
    def clear(self) -> Path | None: ...   # → where the old file was moved
```

`StateStore` gains one attribute and one rule:

```python
self._scopes = ScopeStore(self._path.with_name(SCOPES_FILENAME))
```

— derived from its own path, so `StateStore(tmp_path / "state.json")` in a test
finds `tmp_path / "scopes.json"` with no extra wiring, and the two files cannot
land in different directories.

`StateStore.batch()` is **removed** and `StateStore.scope_batch()` added, forwarding
to `self._scopes.batch()`. `batch()` had zero production call sites while the module
docstring instructed callers to use it; `scope_batch()` is called by the walk at four
sites (AC-18).
