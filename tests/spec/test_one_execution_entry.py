"""One way into execution, asserted rather than reviewed.

`run-request-entry` AC-4: *"No file outside `src/functualize/_engine/` passes a
job function for execution. **Asserted by a test, not by review.**"* The
criterion says so in bold, and the AC→test table then named an `rg` command as
its keeper — which is review with a shell in front of it. This is the test.

The invariant it protects is the feature's whole thesis. `execute()` used to
take the resolved **function** as one of thirteen parameters, so eight
production sites resolved a name to a function themselves and each got to
decide what "the job" meant. `run(request)` takes a `RunRequest` and resolves by
*name*, inside the kernel, once. A caller that hands over a function has
re-acquired that decision, and the divergence starts again there.

Three properties, because "one entry" is three separate things that can each
break on their own:

1. the entry takes a request and nothing else;
2. nobody outside the kernel calls anything else on the engine to run a job;
3. no caller passes a callable where the request goes.

Structural, deliberately. The alternative — asserting behaviour at each of the
callers — is what the feature replaced, and it is how eight sites came to
disagree in the first place.
"""

from __future__ import annotations

import ast
import inspect
from pathlib import Path

from functualize._engine.executor import JobExecutionEngine
from functualize._types.run_request import RunRequest

_SRC = Path(__file__).resolve().parents[2] / "src" / "functualize"
_ENGINE = _SRC / "_engine"

#: The name of the one entry. Held as a string so the tests below read as
#: claims about *a* name rather than about whichever method happens to exist.
_ENTRY = "run"


def test_the_entry_takes_a_request_and_nothing_else() -> None:
    """Thirteen parameters became one. A fourteenth cannot arrive by default."""
    sig = inspect.signature(getattr(JobExecutionEngine, _ENTRY))
    params = [p for name, p in sig.parameters.items() if name != "self"]

    assert [p.name for p in params] == ["request"], (
        "`engine.run` grew a parameter. Whatever it carries belongs on "
        f"`RunRequest`, where every door states it the same way: {sig}"
    )
    assert params[0].default is inspect.Parameter.empty, (
        "the request is the run; a default would let a caller omit it"
    )


def test_no_public_method_takes_a_job_function() -> None:
    """`execute(name, function, ...)` was deleted, not deprecated.

    The precise shape AC-4 forbids: a public method that accepts *the resolved
    function*. That parameter is what let eight production sites each resolve a
    name themselves and each decide what "the job" meant.

    Resolution methods are **not** entries and are deliberately not flagged —
    `materialize_job(job_name)` hands back a job and runs nothing, and the
    adapters legitimately call it. What matters is that nobody can hand a
    callable back to the engine and say "run this".
    """
    survivors = []
    for name in dir(JobExecutionEngine):
        if name.startswith("_"):
            continue
        member = getattr(JobExecutionEngine, name, None)
        if not callable(member):
            continue
        try:
            params = set(inspect.signature(member).parameters)
        except (TypeError, ValueError):
            continue
        if {"function", "job_function"} & params:
            survivors.append(f"{name}{inspect.signature(member)}")

    assert not survivors, (
        "a public engine method takes a job function. Resolution belongs "
        "inside the kernel, keyed by name:\n  " + "\n  ".join(survivors)
    )


#: Method names that *run* a job, as opposed to resolving, registering or
#: describing one. Only these are entries; everything else on the engine is
#: ordinary API the adapters are entitled to call.
_EXECUTING = {"run", "execute", "invoke", "call", "dispatch", "run_job", "execute_job"}


def _engine_calls_outside_the_kernel() -> list[str]:
    """Every call on an engine, outside the kernel, that *runs* something.

    Resolution and registration calls are excluded by `_EXECUTING`: the
    adapters call `materialize_job` and `register_job` by design, and flagging
    those would make this test a list of exceptions rather than an invariant.
    """
    hits: list[str] = []
    for path in sorted(_SRC.rglob("*.py")):
        if _ENGINE in path.parents or path == _ENGINE:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            if not isinstance(func, ast.Attribute):
                continue
            receiver = ast.unparse(func.value)
            if "engine" not in receiver.lower() or func.attr not in _EXECUTING:
                continue
            hits.append(
                f"{path.relative_to(_SRC).as_posix()}:{node.lineno} "
                f"{receiver}.{func.attr}"
            )
    return hits


def test_nothing_outside_the_kernel_calls_anything_but_the_entry() -> None:
    offenders = [
        hit
        for hit in _engine_calls_outside_the_kernel()
        if not hit.endswith(f".{_ENTRY}")
    ]
    assert not offenders, (
        "something outside `_engine/` calls an engine method other than "
        f"`{_ENTRY}` to run a job:\n  " + "\n  ".join(offenders)
    )


def test_the_scan_finds_the_callers_that_do_exist() -> None:
    """The falsifier. An empty scan would pass the test above for free, and an
    empty scan is exactly what a typo in the receiver check would produce."""
    hits = _engine_calls_outside_the_kernel()
    assert hits, "the scan found no engine calls at all, so it proves nothing"
    assert any("core.py" in hit for hit in hits), (
        "`app/core.py` is the façade every embedder reaches; if the scan "
        f"cannot see its call, it cannot see anyone's: {hits}"
    )


def test_the_request_carries_the_name_not_the_function() -> None:
    """The other half of AC-4, at the type rather than at the call site.

    A `RunRequest` whose `job_name` accepted a callable would let every caller
    go back to resolving jobs itself while this file stayed green.
    """
    annotation = RunRequest.__annotations__["job_name"]
    assert "str" in str(annotation), (
        f"`RunRequest.job_name` is {annotation!r}; the kernel resolves names, "
        "and a caller that can pass a function resolves them itself"
    )
