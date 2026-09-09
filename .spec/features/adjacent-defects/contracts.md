# Contracts — adjacent-defects

External interfaces only. Most of this feature changes behaviour behind existing interfaces;
the three genuine surface changes are below.

---

## 1. `functualize.app.utils` — a changed signature

```python
def read_group_options_from_cache(
    cache_path: Path,
    discovery_hash: str | None = None,     # NEW — required of callers, defaulted for safety
) -> dict[str, GroupOptionsSpec] | None: ...
```

A `None` fingerprint means *"do not validate"* and is the current behaviour. Every in-tree
caller supplies one; the default exists so an out-of-tree caller does not break, and it is the
one place this feature accepts a shim — the alternative is an unnecessary break for a function
whose whole defect is that it could not be told the truth.

### Removed from `functualize.app.utils`

Only if §3 concludes deletion. Both are re-exported today and neither has a production caller:

- `get_missing_required_args` (STATUS #13)
- the `omit_defaults` keyword of `build_command_line` (STATUS #14)

## 2. `functualize.job` — a removed field

```python
@dataclass(frozen=True)
class JobContext:
    ...
    # deadline: float | None      ← REMOVED
```

Nothing constructs it with a non-`None` value. It documents an abort the engine has decided
not to implement (`_engine/exec_policy.py:7-22`). Removing it is a **breaking change for a job
author who reads `rc.job_context.deadline`** — it would always have been `None`. Pre-release;
one release-note line.

## 3. Event catalog

Three declared events with no producer (`_events/_catalog_entries.py`):
`job.execute.error`, `cli.parse.start`, `tui.session.start`, `tui.session.end`.

Each is **emitted** or **removed from the catalog**. The catalog is public introspection
(`app.event_bus.catalog()`), so an entry with no producer is a documented lie about what a
subscriber can receive.

If `job.execute.error` is emitted, its payload matches the existing `job.execute.end`
vocabulary — it does not invent a second shape.

## 4. Exit codes and rendering

A group-options conflict changes from **traceback + exit 1** to a rendered discovery failure.
The code comes from the existing table (`_types/exit_codes.py`) — this feature adds no new
exit code and no new vocabulary.

## 5. Unchanged, deliberately

- `pyproject.toml`'s `exclude_type_checking_imports = true` (spec §3.4).
- Every import-linter contract, at its current setting.
- The `--output` / `--prompt-gates` surfaces — F1's, not this feature's.
