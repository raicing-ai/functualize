"""``FromJob`` — declare a parameter that is another job's return value (§D.5).

A job that needs what another job produced says so in its signature::

    @job
    def publish(wheel: FromJob[build_wheel]) -> None: ...

That single annotation is both the dependency edge and the injection: the
declaration *is* the wiring, so there is no second place to keep in sync. It is
the same move `@workflow` makes — a graph whose nodes name jobs that already
exist — pushed down to one parameter.

**One shape, two kinds of reference** (ratified 2026-07-20, resolved question
18, amended same day)::

    def publish(wheel: Annotated[Path, FromJob(build_wheel)]) -> None: ...
    def publish(wheel: Annotated[Path, FromJob("pkg.build_wheel")]) -> None: ...

Pass the function where you can import it — existence is checked by the import,
renames are caught by tooling, completion works. Pass a name for a cross-group
reference where importing would create a cycle, which is exactly when a string
earns its place. That is the same ``str | Callable`` pair `Step`, `Deps`, and
`Tool` already accept, so the vocabulary has one rule for "point at a job".

**Why not ``FromJob[build_wheel]``?** It was the ratified primary form until it
was built and measured: a function object cannot appear in a type position
under PEP 484, so mypy rejects it in *user* code
(``Function "build_wheel" is not valid as a type``). No runtime trick reaches
that — annotations are resolved statically. The metadata slot of ``Annotated``
holds a *value*, so the same object reference type-checks there cleanly. The
cost is writing ``Path`` yourself instead of inferring it from the upstream's
return annotation; the benefit is that a typed framework does not ship a
headline syntax that makes its users' type checkers fail.

**Resolution is deliberately not done here.** This module produces a *reference*
— a name and how it was written. Turning that into a value (is the upstream
fingerprint-fresh? is the cached value reusable? must it run first?) is the
engine's job, because only the engine knows the run.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Annotated, Any, get_args, get_origin

from functualize._types.annotations import resolved_hints
from functualize._types.job_declaration import _ref_name

if TYPE_CHECKING:
    from collections.abc import Callable

__all__ = [
    "FromJob",
    "FromStep",
    "from_job_types",
    "declared_dependency_names",
    "from_job_names",
    "from_job_refs",
]


class FromJob:
    """A reference to another job, used in a parameter annotation.

    See the module docstring for the two accepted forms. Instances are the
    metadata carried inside ``Annotated``; ``FromJob[...]`` builds that
    ``Annotated`` for you.

    **``run=False`` reads without causing work.** The default is that
    referencing a value declares the dependency — the idiom every comparable
    system follows (doit's ``getargs`` "creates an implicit setup-task";
    Dagster infers upstreams "from the arguments to the decorated function").
    ``run=False`` opts out: use the recorded value if there is one, never
    trigger execution, and contribute no dependency edge. That is what a
    reporting job wants — read the last build's result, do not cause a build.

    With ``run=False`` and nothing recorded, the parameter falls back to its
    default; a parameter with no default raises, because silently injecting
    ``None`` would make "never ran" indistinguishable from "returned nothing".

    Args:
        job: The upstream job — its registered name, or the decorated function.
            Positional-only, matching :class:`~functualize._types.workflow.Tool`.
        run: Whether a missing or stale value may trigger the upstream.
    """

    __slots__ = ("_job", "_run")

    _job: str | Callable[..., Any]
    _run: bool

    def __init__(self, job: str | Callable[..., Any], /, *, run: bool = True) -> None:
        if isinstance(job, str):
            if not job.strip():
                raise ValueError("FromJob reference must not be empty")
        elif not callable(job):
            raise TypeError(
                f"FromJob must reference a registered job name or a callable, "
                f"got {type(job).__name__}"
            )
        object.__setattr__(self, "_job", job)
        object.__setattr__(self, "_run", bool(run))

    def __setattr__(self, name: str, value: Any) -> None:
        raise AttributeError("FromJob is immutable")

    @property
    def job(self) -> str | Callable[..., Any]:
        """The referenced job, as written."""
        return self._job

    @property
    def run(self) -> bool:
        """Whether resolving this reference may execute the upstream."""
        return self._run

    @property
    def name(self) -> str:
        """The upstream job's name."""
        from functualize._types.workflow import _job_ref_name

        return _job_ref_name(self._job)

    def __class_getitem__(cls, job: Any) -> Any:
        """Reject the subscript form with the syntax that actually works.

        ``X[...]`` is the conventional way to parameterize a Python generic, so
        it is the first thing a reader will try. Without this they would get
        either a bare "not subscriptable" or — worse — a working runtime object
        that their type checker rejects, with nothing pointing at the fix.
        """
        name = getattr(job, "__name__", job)
        raise TypeError(
            f"FromJob[...] is not a type. Write "
            f"Annotated[<return type>, FromJob({name!r})] instead — a function "
            f"object is not valid in a type position (PEP 484), so the "
            f"subscript form cannot type-check."
        )

    def __repr__(self) -> str:
        suffix = "" if self._run else ", run=False"
        return f"FromJob({self.name!r}{suffix})"

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, FromJob):
            return NotImplemented
        return self.name == other.name and self._run == other._run

    def __hash__(self) -> int:
        return hash(("FromJob", self.name, self._run))


def from_job_refs(func: Callable[..., Any]) -> dict[str, FromJob]:
    """Every ``FromJob`` parameter of ``func``, as ``{param name: reference}``.

    Hints are resolved rather than read raw. Under
    ``from __future__ import annotations`` the annotation is the *string*
    ``"Annotated[Path, FromJob('build')]"``, whose ``get_origin`` is None — so
    a raw read would find no references at all, in a module that declared
    them, silently. That failure has already been shipped once in this
    codebase and is not worth shipping twice.
    """
    refs: dict[str, FromJob] = {}
    for name, annotation in resolved_hints(func).items():
        if name == "return":
            continue
        if get_origin(annotation) is not Annotated:
            continue
        for meta in get_args(annotation)[1:]:
            if isinstance(meta, FromJob):
                refs[name] = meta
                break
    return refs


def from_job_names(function: Any) -> tuple[str, ...]:
    """Upstream job names ``function`` *depends* on via ``FromJob``.

    ``run=False`` references are excluded: they read a recorded value and are
    explicitly not a reason to run anything, so treating them as edges would
    reintroduce exactly the work they exist to avoid.
    """
    if function is None or not callable(function):
        return ()
    return tuple(ref.name for ref in from_job_refs(function).values() if ref.run)


def declared_dependency_names(
    declaration: Any = None,
    function: Any = None,
    cached_from_job: Any = (),
) -> tuple[str, ...]:
    """Every job ``function``/``declaration`` depends on, as names.

    Merges the two ways a dependency can be stated — an explicit
    ``Deps(...)`` and a ``FromJob`` parameter — into one ordered, de-duplicated
    list, because they mean the same thing to the scheduler and a job that
    states both must not run its upstream twice.

    ``Deps`` survives in the cached declaration, so ``declaration`` alone
    covers it. ``FromJob`` edges live in the *signature*, which a warm boot has
    not imported — hence ``cached_from_job``, the names discovery recorded on
    the descriptor. Passing the live ``function`` when there is one keeps the
    cold path working before anything is cached.
    """
    names: list[str] = []

    deps = getattr(declaration, "deps", None)
    for ref in getattr(deps, "refs", ()) or ():
        target = getattr(ref, "target", ref)  # unwrap call(...)
        # `_ref_name` is what the cache stores, so using it here is what makes
        # the cold path and the warm path name the same job.
        resolved = _ref_name(target) if not isinstance(target, str) else target
        if isinstance(resolved, str) and resolved not in names:
            names.append(resolved)

    for name in list(from_job_names(function)) + list(cached_from_job or ()):
        if name not in names:
            names.append(name)

    return tuple(names)


def from_job_types(func: Callable[..., Any]) -> dict[str, Any]:
    """The declared ``T`` of each ``FromJob`` parameter, as ``{param: T}``.

    ``Annotated[Report, FromJob("make-report")]`` yields ``Report``. This is
    what rebuilds the recorded value into its original type: the writer stored
    JSON-compatible data and could not reliably know the full type
    (``type([Report(1)])`` is ``list``, losing the item schema), while the
    consumer's annotation states it exactly.

    Resolved rather than read raw, for the same PEP 563 reason as
    :func:`from_job_refs` — under ``from __future__ import annotations`` the
    annotation is a string and a raw read finds nothing.
    """
    types: dict[str, Any] = {}
    for name, annotation in resolved_hints(func).items():
        if name == "return" or get_origin(annotation) is not Annotated:
            continue
        args = get_args(annotation)
        if any(isinstance(meta, FromJob) for meta in args[1:]):
            types[name] = args[0]
    return types


class FromStep:
    """A read of *this walk's* recorded result for one step (resolved Q20).

    ``FromStep`` and :class:`FromJob` answer different questions, and the
    difference is why this is a separate name rather than a flag:

    ============  ===============================  =========================
                  ``FromJob`` in a signature        ``FromStep``
    ============  ===============================  =========================
    may run it    yes — it is a dependency edge     **never**
    resolves in   fingerprints, or a scope          this scope's steps only
    upstream      may not have run yet              has already run
    ============  ===============================  =========================

    Used where a value is read from inside a walk that has already produced
    it — a gate tool's bound argument, and the epilogue body::

        Gate(
            name="review",
            awaits=Decision,
            tools=[Tool(read_file, allowed=FromStep("setup-vfs"))],
        )

    The agent may call `read_file`, but `allowed` is fixed to whatever
    `setup-vfs` returned *in this scope* — so the tool is scoped to exactly
    those files and a call outside them is inexpressible rather than refused.

    **Why not ``FromJob`` here.** In a gate-tool binding ``run=True`` is not
    merely unused, it is unmeaningful: the agent invokes the tool on demand,
    outside the graph's ordering, and the referenced step has already run
    because the graph ordered it before the gate. Running it from here would
    execute it outside the walk's step recording, so the walker would not know
    it happened. Reusing ``FromJob`` would have made its natural spelling mean
    one thing in a signature and another in a binding — the "same declaration,
    different path" divergence this codebase has repeatedly paid for.

    Args:
        step: The step's registered job name, or the decorated function.
            Positional-only, matching :class:`FromJob` and
            :class:`~functualize._types.workflow.Tool`.
    """

    __slots__ = ("_step",)

    _step: str | Callable[..., Any]

    def __init__(self, step: str | Callable[..., Any], /) -> None:
        if isinstance(step, str):
            if not step.strip():
                raise ValueError("FromStep reference must not be empty")
        elif not callable(step):
            raise TypeError(
                f"FromStep must reference a step name or a callable, "
                f"got {type(step).__name__}"
            )
        object.__setattr__(self, "_step", step)

    def __setattr__(self, name: str, value: Any) -> None:
        raise AttributeError("FromStep is immutable")

    @property
    def step(self) -> str | Callable[..., Any]:
        """The referenced step, as written."""
        return self._step

    @property
    def name(self) -> str:
        """The referenced step's canonical name."""
        from functualize._types.workflow import _job_ref_name

        return _job_ref_name(self._step)

    def __repr__(self) -> str:
        return f"FromStep({self.name!r})"

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, FromStep):
            return NotImplemented
        return self.name == other.name

    def __hash__(self) -> int:
        return hash(("FromStep", self.name))
