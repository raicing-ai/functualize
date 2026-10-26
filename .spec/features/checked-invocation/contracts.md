# checked-invocation — External contracts

What a user can name, call or read after this change. The behaviour is in
`spec.md`; decisions D1–D5 were confirmed 2026-10-26, and each contract below
is authorised. Original planning base `b3e624bd`; execution base `11ed0e82`.

## C1 — `JobResult.raise_for_status()` (FOSS-106)

```python
# functualize.types.JobResult   (defined in src/functualize/_types/descriptors.py)
@dataclass(frozen=True)
class JobResult:
    status: RunStatus
    return_value: Any
    duration_ms: float
    metadata: dict[str, Any] = field(default_factory=dict)
    exception: BaseException | None = field(default=None, compare=False, hash=False)
    job_name: str = ""

    def raise_for_status(self) -> Self:
        """Return this result if the job did its work; raise JobFailedError if not.

        "Did its work" is ``not is_failure(self.status, family=Family.TOOL)``:
        SUCCESS, SKIPPED and BLOCKED return ``self``; every other status raises.
        The same predicate decides ``Invoke.parallel``'s default raise and the
        INVOKE_FAILURE hook.

        Raises:
            JobFailedError: carrying this result, raised ``from self.exception``
                when the result has one.
        """
```

- **Fields: unchanged.** The same six, in the same order, with the same
  `field()` flags. No `__eq__`, `__hash__` or `__post_init__` is added.
- **Returns `self`**, so the check and the binding are one expression:
  `report = inv("report").raise_for_status().return_value`. This is the
  issue's "impossible to miss at the point the value is bound". A caller who
  ignores the return value gets the plain no-op of MCH-178 AC1.
- `Self` comes from `typing` (Python ≥ 3.11, the project floor).

## C2 — `JobFailedError` (FOSS-106; D1, D2)

```python
# functualize.types.JobFailedError   (defined in src/functualize/_types/errors.py)
class JobFailedError(Exception):
    """Raised by JobResult.raise_for_status() for a job that did not do its work.

    Carries the whole result, the way ShellError carries its ShellResult.

    Attributes:
        result: The JobResult that was checked.
        job_name: ``result.job_name``.
        status: ``result.status``.
        exception: ``result.exception`` — also ``__cause__`` when not None.
    """

    def __init__(self, result: JobResult) -> None: ...
```

- **Message:** `job '<job_name>' did not succeed (<status.value>)`, plus
  `: <ExcClass>: <message>` when `result.exception` is set. The CLI boundary
  prints `str(exc)` on one line (ADR-032 §3), so the child's error is visible at
  the default log level. Example:
  `job 'boom' did not succeed (Failure): RuntimeError: boom failed`.
- **Chaining:** `raise_for_status()` executes
  `raise JobFailedError(self) from self.exception`. With no exception it raises
  without a cause.
- **Public home:** exported from `functualize.types` beside `JobResult`, and
  only there. `functualize.job` does **not** re-export it.
- **Not** re-exported from `functualize._engine.errors`. That module exists for
  `JobNotFoundError` and `RecursionLimitError`, and this is not an engine error.

## C3 — `inv(..., capture=True)` (FOSS-107; D4, D5)

```python
# functualize.job.Invoke.__call__   (stub and WiredInvoke, _engine/capabilities/invoke.py)
def __call__(
    self,
    job_or_fn: str | Callable[..., Any],
    *,
    config: BaseModel | None = None,
    awaits_input: type[BaseModel] | None = None,
    available_tools: list[str] | None = None,
    force_gate: bool = False,
    gate_strategy: GateStrategy | str | list[GateStrategy | str] | None = None,
    timeout: float | None = None,
    group_option_values: Mapping[str, Any] | None = None,
    capture: bool = False,                       # NEW
    **kwargs: Any,
) -> JobResult: ...
```

- `capture` is a **control input**, like `group_option_values`. It never reaches
  the child as a job argument: a child parameter literally named `capture` is
  still supplied only by an explicit keyword, which the framework now claims.
  This is the same rule `group_option_values`, `timeout` and `config` already
  live under. It is stated in the docstring.
- `rc.invoke(job_name, *, timeout=None, **kwargs)` forwards `capture`
  unchanged. Its signature does not change.
- `Invoke.parallel(...)`: **no** `capture` parameter.

**Return shape under `capture=True`** — one `JobResult`, and two metadata
keys alongside whatever the child's result already carried:

| Key | Type | Content |
|---|---|---|
| `"emitted"` | `tuple[Any, ...]` | the values passed to `out.emit()`, in order, as passed (`None` included) |
| `"writes"` | `tuple[str \| bytes, ...]` | the payloads passed to `out.write()`, in order, as passed |

Both are always present under capture, and both are absent without it. When
`awaits_input=` is also given, the `_awaits_input` keys and these two keys sit
side by side.

**Output routing:** under capture the child's `emit` and `write` are recorded
**and not written** to the stream (D4). This holds at any `--emit-format`,
including `none`.

The two key strings are a **documented contract**, not module-level names.
They are pinned by a behaviour test (`tasks.md` 3.2), not by the export set.
That is consistent with the shape page, which pins *names* in
`tests/test_public_api_surface.py`, and that file pins `__all__` and nothing
else (`tests/test_public_api_surface.py:369-558`, five classes, all over
`__all__`).

## C4 — the pinned public surface: the test diff Execute owes

One name, one module, one line, measured against `EXPECTED_EXPORTS` at
`tests/test_public_api_surface.py:253-299`:

```diff
     "functualize.types": {
         # The outcome authority (run-outcome-authority F2 T1/T2).
         "ExitCode",
         "exit_code_for_status",
         "Family",
         "is_failure",
         "report_line",
         "status_from_wire",
         "wire_value",
+        # Raised by JobResult.raise_for_status(), the checked lane for a
+        # child a parent invoked; public beside the result it carries.
+        "JobFailedError",
         # The request a run is made from (run-request-entry F1 T1).
```

…and the matching `"JobFailedError"` in `src/functualize/types/__init__.py`
`__all__` and its import from `functualize._types.errors`.

**Why one name and not two.** The dispatch expected "both new names" pinned.
Capture adds a keyword and two metadata **key strings**, and no module-level
name. The surface test asserts `__all__` membership only, so it has nothing to
pin for capture. FOSS-107 says the same (*"`tests/test_public_api_surface.py`
… does not move"*). The capture contract is pinned behaviourally instead (C3).
The FOSS-106 ticket said the method needed no surface change. That premise
assumed the error would not be a new public name, and under D2 it is.

## C5 — internal seam (not public; listed because it touches a public type)

`RunRequest` (`functualize.types.RunRequest`, `_types/run_request.py:178-266`)
gains one field, which no door sets:

```python
#: Where an invoked child's Stdout records instead of writing (capture=True).
#: Set only by WiredInvoke; reset by nested_request, so capture is not
#: transitive. A live object, so it is outside equality and the hash.
capture: EmissionRecord | None = field(default=None, compare=False)
```

`EmissionRecord` is a plain `@dataclass` in `_types/stdout.py`, holding
`emitted: list[Any]` and `writes: list[str | bytes]`. It is **not** exported.
`request_from_envelope` never sets the field, so HTTP, Lambda and MCP requests
cannot capture. It is recorded in `plan.md` → `## Surviving smells` for
maintainer review.
