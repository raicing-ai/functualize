"""Frozen value objects for the ``@job`` declaration model.

These grouped, typed value objects replace what would otherwise be a ~25-kwarg
flat ``@job`` signature (proposal §A.3). Each object validates its own
invariants at construction (``__post_init__``) so misuse fails loudly at import
time with an object-scoped message, and each is JSON-serializable via
``to_dict()`` so the aggregate ``JobDeclaration`` (added by the decorator) nests
cleanly into the discovery cache.

Defined here in ``_types`` — not in the public ``functualize.job`` package — so
internal discovery (``_discovery``) can read them without importing the public
API. ``functualize.job`` re-exports them for job authors.

Reference resolution note: ``Deps`` refs, ``Precondition`` callables, and
``Retry.on`` exception types cannot round-trip through the cache. ``to_dict()``
serializes strings verbatim and represents callables/types by name, marking
them opaque; discovery performs the authoritative callable-to-registered-name
resolution at scan time (proposal §A.4, schema §2).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Literal

# A dependency/precondition reference: a registered-job name, a callable
# resolved to a name at discovery, or a parameterized ``call(...)``.
DepRef = "str | Callable[..., Any] | Call"


def _ref_name(ref: str | Callable[..., Any]) -> str:
    """The registered name a string-or-callable reference denotes.

    Strings pass through verbatim. A callable reports the name it will be
    *registered* under — its ``group`` prefixed to its Python ``__name__`` —
    not the bare ``__name__``.

    The group prefix is load-bearing. This name is what survives into the
    discovery cache, and a warm boot has nothing else: the function is a
    deferred-import stand-in, so identity matching is unavailable. Dropping
    the group meant a grouped job referenced as ``Deps(compile_it)`` cached as
    ``"compile_it"`` while it registered as ``"build.compile_it"`` — boot
    validated and the run failed.

    ``@job(name=)`` used to sit between the declaration and ``__name__`` and
    was its own source of divergence. It is gone: normalization derives the
    addressable name from ``__name__``, which is the only thing a warm boot
    and a cold boot both see.
    """
    from functualize._types.naming import normalize_name, normalize_segment

    if isinstance(ref, str):
        # A string reference is an address too, so it canonicalizes like any
        # other. Passing it through verbatim left workflow graph nodes spelled
        # `travel_plan` while every resolved name was `travel-plan`, and the
        # ordering check compares those two sets directly.
        return normalize_name(ref) or ref
    declared = getattr(ref, "__name__", None)
    if not isinstance(declared, str):
        return repr(ref)
    # Normalized, because this *is* an address — the same string the job
    # registers under. Emitting the raw `__name__` made workflow graph nodes
    # read `travel_plan` while every resolved name read `travel-plan`, so an
    # ordering check comparing the two found no match and rejected a graph
    # that was correctly ordered.
    leaf = normalize_segment(declared)
    declaration = getattr(ref, "__functualize_job__", None)
    group = normalize_name(getattr(declaration, "group", None))
    return f"{group}.{leaf}" if group else leaf


@dataclass(frozen=True)
class Call:
    """A parameterized dependency reference — a job plus bound keyword args.

    Produced by the ``call()`` factory. Lets a dependency carry config
    overrides, which matrix selectors and parameterized deps require: e.g.
    ``call(build, target="wheel")`` is a distinct dep from
    ``call(build, target="sdist")`` (proposal §A.4).
    """

    target: str | Callable[..., Any]
    kwargs: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.target, str) and not callable(self.target):
            raise ValueError(
                "call() target must be a job-name string or a callable, "
                f"got {type(self.target).__name__}"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "ref": _ref_name(self.target),
            "opaque": not isinstance(self.target, str),
            "kwargs": dict(sorted(self.kwargs.items())),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Call:
        return cls(data["ref"], dict(data.get("kwargs", {})))


def call(fn_or_name: str | Callable[..., Any], **kwargs: Any) -> Call:
    """Build a parameterized dependency reference (proposal §A.4).

    Example::

        deps=Deps(call(build, target="wheel"))
    """
    return Call(fn_or_name, kwargs)


@dataclass(frozen=True, init=False)
class Deps:
    """A job's dependency set and its failure policy (proposal §A.4).

    Refs are positional and may each be a registered-job name string, a
    callable (resolved to a name at discovery — refactor-safe and
    IDE-navigable), or a ``call(...)`` for parameterized deps. Unknown names,
    unregistered callables, and cycles are boot errors (resolved at discovery).
    """

    refs: tuple[str | Callable[..., Any] | Call, ...]
    policy: Literal["fail-fast", "keep-going"]

    def __init__(
        self,
        *refs: str | Callable[..., Any] | Call,
        policy: Literal["fail-fast", "keep-going"] = "fail-fast",
    ) -> None:
        object.__setattr__(self, "refs", tuple(refs))
        object.__setattr__(self, "policy", policy)
        self.__post_init__()

    def __post_init__(self) -> None:
        if self.policy not in ("fail-fast", "keep-going"):
            raise ValueError(
                f"Deps.policy must be 'fail-fast' or 'keep-going', got {self.policy!r}"
            )
        for ref in self.refs:
            if not isinstance(ref, (str, Call)) and not callable(ref):
                raise ValueError(
                    "Deps refs must be job-name strings, callables, or call(...), "
                    f"got {type(ref).__name__}"
                )

    def to_dict(self) -> dict[str, Any]:
        refs: list[Any] = []
        for ref in self.refs:
            if isinstance(ref, Call):
                refs.append(ref.to_dict())
            else:
                refs.append({"ref": _ref_name(ref), "opaque": not isinstance(ref, str)})
        return {"refs": refs, "policy": self.policy}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Deps:
        """Reconstruct from cache form. Opaque callable refs materialize as
        their recorded name string (the live callable is unavailable off-cache)."""
        refs: list[str | Call] = []
        for r in data["refs"]:
            if "kwargs" in r:
                refs.append(Call(r["ref"], dict(r.get("kwargs", {}))))
            else:
                refs.append(r["ref"])
        return cls(*refs, policy=data["policy"])


@dataclass(frozen=True)
class Fingerprint:
    """Up-to-date-checking inputs and outputs for a job (proposal §A.3, §D.3).

    ``sources`` are glob patterns whose content/timestamps prove staleness;
    ``generates`` are the outputs the job produces. ``method`` selects the
    staleness test.
    """

    sources: tuple[str, ...] = ()
    generates: tuple[str, ...] = ()
    method: Literal["checksum", "timestamp", "none"] = "checksum"

    def __post_init__(self) -> None:
        object.__setattr__(self, "sources", tuple(self.sources))
        object.__setattr__(self, "generates", tuple(self.generates))
        if self.method not in ("checksum", "timestamp", "none"):
            raise ValueError(
                f"Fingerprint.method must be 'checksum', 'timestamp', or 'none', "
                f"got {self.method!r}"
            )
        for label, seq in (("sources", self.sources), ("generates", self.generates)):
            for item in seq:
                if not isinstance(item, str):
                    raise ValueError(
                        f"Fingerprint.{label} items must be strings, "
                        f"got {type(item).__name__}"
                    )
        if self.method == "timestamp" and not self.generates:
            raise ValueError(
                "Fingerprint(method='timestamp') requires 'generates' — "
                "timestamp comparison needs output targets to check against."
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "sources": list(self.sources),
            "generates": list(self.generates),
            "method": self.method,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Fingerprint:
        return cls(
            sources=tuple(data["sources"]),
            generates=tuple(data["generates"]),
            method=data["method"],
        )


@dataclass(frozen=True)
class Precondition:
    """A pre-flight check plus an optional human-facing failure message.

    The check is a shell-command string (run, non-zero = refuse) or a callable
    (falsy return = refuse) — proposal §A.3, §D.2.
    """

    cmd_or_callable: str | Callable[..., Any]
    msg: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.cmd_or_callable, str) and not callable(
            self.cmd_or_callable
        ):
            raise ValueError(
                "Precondition check must be a shell-command string or a callable, "
                f"got {type(self.cmd_or_callable).__name__}"
            )
        if self.msg is not None and not isinstance(self.msg, str):
            raise ValueError("Precondition.msg must be a string or None")

    def to_dict(self) -> dict[str, Any]:
        is_str = isinstance(self.cmd_or_callable, str)
        return {
            "check": _ref_name(self.cmd_or_callable),
            "opaque": not is_str,
            "msg": self.msg,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Precondition:
        return cls(data["check"], data.get("msg"))


# A precondition item may be a bare shell string, a callable, or a Precondition.
PreconditionItem = "str | Callable[..., Any] | Precondition"


@dataclass(frozen=True)
class Guards:
    """Pre-flight and up-to-date guards for a job (proposal §A.3, §D.2).

    ``preconditions`` refuse the run when unmet; ``status`` checks report the
    job already up-to-date (skip). Precondition items may be shell strings,
    callables, or ``Precondition`` objects; status items are shell strings or
    callables.
    """

    preconditions: tuple[str | Callable[..., Any] | Precondition, ...] = ()
    status: tuple[str | Callable[..., Any], ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "preconditions", tuple(self.preconditions))
        object.__setattr__(self, "status", tuple(self.status))
        for item in self.preconditions:
            if not isinstance(item, (str, Precondition)) and not callable(item):
                raise ValueError(
                    "Guards.preconditions items must be shell strings, callables, "
                    f"or Precondition objects, got {type(item).__name__}"
                )
        for item in self.status:
            if not isinstance(item, str) and not callable(item):
                raise ValueError(
                    "Guards.status items must be shell strings or callables, "
                    f"got {type(item).__name__}"
                )

    def to_dict(self) -> dict[str, Any]:
        preconditions: list[Any] = []
        for item in self.preconditions:
            if isinstance(item, Precondition):
                preconditions.append(item.to_dict())
            else:
                preconditions.append(
                    {
                        "check": _ref_name(item),
                        "opaque": not isinstance(item, str),
                        "msg": None,
                    }
                )
        status = [
            {"check": _ref_name(item), "opaque": not isinstance(item, str)}
            for item in self.status
        ]
        return {"preconditions": preconditions, "status": status}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Guards:
        """Reconstruct from cache form. Precondition items materialize as
        ``Precondition`` objects; status items as their recorded check strings."""
        preconditions = tuple(
            Precondition(p["check"], p.get("msg")) for p in data["preconditions"]
        )
        status = tuple(s["check"] for s in data["status"])
        return cls(preconditions=preconditions, status=status)


@dataclass(frozen=True)
class Retry:
    """Retry policy for a job (proposal §A.5).

    ``on`` narrows retries to specific exception types; ``on_exit_codes``
    narrows to specific ``ShellError`` exit codes. Empty means "retry on any
    failure".
    """

    attempts: int
    backoff: Literal["exponential", "linear", "constant"] = "exponential"
    on: tuple[type[BaseException], ...] = ()
    on_exit_codes: tuple[int, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "on", tuple(self.on))
        object.__setattr__(self, "on_exit_codes", tuple(self.on_exit_codes))
        if not isinstance(self.attempts, int) or isinstance(self.attempts, bool):
            raise ValueError("Retry.attempts must be an int")
        if self.attempts < 1:
            raise ValueError(f"Retry.attempts must be >= 1, got {self.attempts}")
        if self.backoff not in ("exponential", "linear", "constant"):
            raise ValueError(
                f"Retry.backoff must be 'exponential', 'linear', or 'constant', "
                f"got {self.backoff!r}"
            )
        for exc in self.on:
            if not (isinstance(exc, type) and issubclass(exc, BaseException)):
                raise ValueError(f"Retry.on items must be exception types, got {exc!r}")
        for code in self.on_exit_codes:
            if not isinstance(code, int) or isinstance(code, bool):
                raise ValueError(
                    f"Retry.on_exit_codes items must be ints, got {code!r}"
                )

    def to_dict(self) -> dict[str, Any]:
        return {
            "attempts": self.attempts,
            "backoff": self.backoff,
            "on": [exc.__name__ for exc in self.on],
            "on_exit_codes": list(self.on_exit_codes),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Retry:
        """Reconstruct from cache form. ``on`` exception types cannot round-trip
        (recorded by name only) and materialize empty off-cache."""
        return cls(
            attempts=data["attempts"],
            backoff=data["backoff"],
            on=(),
            on_exit_codes=tuple(data["on_exit_codes"]),
        )


@dataclass(frozen=True)
class Exec:
    """Execution policy for a job (proposal §A.5).

    ``run`` selects dedup behavior: ``"always"``, ``"once"`` (per session,
    ignoring args), or ``"when_changed"`` (per session, keyed on identical
    resolved args).

    **There is no job-level ``timeout``**, deliberately. Python cannot preempt
    a running function, so any such field could only *report* an overrun while
    the work continued — and a caller believing the job stopped may release a
    lock or delete a file the still-live job is using. The two mature runners
    in this space reached the same conclusion: `invoke` has no task-level
    timeout (only ``run(cmd, timeout=)``, a ``threading.Timer`` that
    ``SIGKILL``s a *subprocess*), and `doit` has none at all — its
    ``doit.tools.timeout`` is an ``uptodate`` checker, a freshness TTL, which
    is what `Fingerprint` does here. Bound the work where the OS can enforce
    it: ``sh(..., timeout=N)`` kills the process group (§B.4).
    """

    retry: Retry | None = None
    platforms: tuple[str, ...] | None = None
    run: Literal["always", "once", "when_changed"] = "always"
    silent: bool = False

    def __post_init__(self) -> None:
        if self.platforms is not None:
            object.__setattr__(self, "platforms", tuple(self.platforms))
        if self.retry is not None and not isinstance(self.retry, Retry):
            raise ValueError("Exec.retry must be a Retry or None")
        if self.platforms is not None:
            for plat in self.platforms:
                if not isinstance(plat, str):
                    raise ValueError("Exec.platforms items must be strings")
        if self.run not in ("always", "once", "when_changed"):
            raise ValueError(
                f"Exec.run must be 'always', 'once', or 'when_changed', "
                f"got {self.run!r}"
            )
        if not isinstance(self.silent, bool):
            raise ValueError("Exec.silent must be a bool")

    def to_dict(self) -> dict[str, Any]:
        return {
            "retry": self.retry.to_dict() if self.retry is not None else None,
            "platforms": list(self.platforms) if self.platforms is not None else None,
            "run": self.run,
            "silent": self.silent,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Exec:
        return cls(
            retry=Retry.from_dict(data["retry"]) if data["retry"] else None,
            platforms=tuple(data["platforms"])
            if data["platforms"] is not None
            else None,
            run=data["run"],
            silent=data["silent"],
        )


@dataclass(frozen=True)
class JobDeclaration:
    """The frozen, aggregate declaration attached by ``@job`` (proposal §A.3).

    Identity/description fields stay flat (they are what ``@job`` *is about*);
    operational concerns are the grouped value objects. ``name``/``group`` are
    stored as declared (``None`` means "fall back to convention"): discovery
    resolves ``group`` against the module-level ``JOB_GROUP`` and ``name``
    against ``__name__`` (proposal §A.3). Serializes to/from the discovery cache
    via ``to_dict``/``from_dict``; opaque callables/exception-types do not
    round-trip (see module docstring).
    """

    group: str | None = None
    extra_description: str | None = None
    category: str | None = None
    examples: tuple[str, ...] = ()
    tags: tuple[str, ...] = ()
    visibility: Literal["external", "internal"] = "external"
    config_section: str | None = None
    deps: Deps | None = None
    cache: Fingerprint | None = None
    guards: Guards | None = None
    exec: Exec | None = None
    matrix: dict[str, list[Any]] | None = None

    def __post_init__(self) -> None:
        # None is accepted as "none of these" and normalized to an empty tuple.
        object.__setattr__(self, "examples", tuple(self.examples or ()))
        object.__setattr__(self, "tags", tuple(self.tags or ()))
        if self.group is not None and not isinstance(self.group, str):
            raise ValueError("@job group must be a string or None")
        for label, seq in (("examples", self.examples), ("tags", self.tags)):
            for item in seq:
                if not isinstance(item, str):
                    raise ValueError(f"@job {label} items must be strings")
        if self.visibility not in ("external", "internal"):
            raise ValueError(
                f"@job visibility must be 'external' or 'internal', "
                f"got {self.visibility!r}"
            )
        for label, obj, typ in (
            ("deps", self.deps, Deps),
            ("cache", self.cache, Fingerprint),
            ("guards", self.guards, Guards),
            ("exec", self.exec, Exec),
        ):
            if obj is not None and not isinstance(obj, typ):
                raise ValueError(
                    f"@job {label} must be a {typ.__name__} or None, "
                    f"got {type(obj).__name__}"
                )
        if self.matrix is not None:
            if not isinstance(self.matrix, dict):
                raise ValueError("@job matrix must be a dict[str, list] or None")
            for key, vals in self.matrix.items():
                if not isinstance(key, str) or not isinstance(vals, list):
                    raise ValueError(
                        "@job matrix must map string axis names to value lists"
                    )

    def to_dict(self) -> dict[str, Any]:
        return {
            "group": self.group,
            "extra_description": self.extra_description,
            "category": self.category,
            "examples": list(self.examples),
            "tags": list(self.tags),
            "visibility": self.visibility,
            "config_section": self.config_section,
            "deps": self.deps.to_dict() if self.deps is not None else None,
            "cache": self.cache.to_dict() if self.cache is not None else None,
            "guards": self.guards.to_dict() if self.guards is not None else None,
            "exec": self.exec.to_dict() if self.exec is not None else None,
            "matrix": self.matrix,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> JobDeclaration:
        return cls(
            group=data["group"],
            extra_description=data["extra_description"],
            category=data["category"],
            examples=tuple(data["examples"]),
            tags=tuple(data["tags"]),
            visibility=data["visibility"],
            config_section=data["config_section"],
            deps=Deps.from_dict(data["deps"]) if data["deps"] else None,
            cache=Fingerprint.from_dict(data["cache"]) if data["cache"] else None,
            guards=Guards.from_dict(data["guards"]) if data["guards"] else None,
            exec=Exec.from_dict(data["exec"]) if data["exec"] else None,
            matrix=data["matrix"],
        )
