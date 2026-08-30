"""Sources capability — the resolved inputs this job's own ``Fingerprint`` declared.

A job declares the files it depends on, the pre-flight expands that glob and
records ``{path: {mtime, size, sha256}}`` for each match on **every run**, uses
it to decide freshness — and then threw it away. The body, about to read exactly
those files, had no way to reach it, so every job restated the glob its own
declaration had just run. Two statements of one intent, free to drift.

This is plumbing, not computation: nothing here resolves anything. The map comes
off the :class:`~functualize._engine.preflight.PreflightDecision`, which now
carries what it used to discard. See ADR-012.

**The ordering that makes this delicate.** DI resolution runs *before* the
pre-flight, so at injection time the data does not exist. The instance is
therefore injected empty and populated by :meth:`Sources._bind` once the
decision is in hand, before the body is called. That is exactly the shape
``contributor/guides/wiring-discipline.md`` warns about — a capability that
resolves and does nothing — which is why the binding carries a sabotage check
on both the cold and warm paths rather than a unit test alone.
"""

from __future__ import annotations

from collections.abc import ItemsView, KeysView, Mapping, Sequence
from typing import Any

from functualize._engine.capabilities.spec import CapabilitySpec


class Sources:
    """The files this job's ``Fingerprint(sources=...)`` resolved to.

    Reads as a mapping of project-relative POSIX path → ``{"mtime", "size",
    "sha256"}``::

        @job(cache=Fingerprint(sources=["src/**/*.yaml"]))
        def parse(sources: Sources) -> Parsed:
            files = {path: Path(path).read_text() for path in sources.keys()}

    ``declared`` is not the same question as emptiness, and conflating them is
    the bug this exists next to:

    ============================================ ========== =========
    Declaration                                  declared   items()
    ============================================ ========== =========
    ``sources=["src/*.yaml"]``, files present    True       populated
    ``sources=["absent/*.yaml"]``, no match      True       **empty**
    no ``Fingerprint``, or no ``sources``        False      empty
    ============================================ ========== =========

    The middle row is the R3 refusal's trigger, read here through the same
    mechanism rather than a second one.
    """

    __slots__ = ("_declared", "_generates", "_map")

    def __init__(
        self,
        source_map: Mapping[str, Any] | None = None,
        *,
        declared: bool = False,
        generates: Sequence[str] = (),
    ) -> None:
        self._map: Mapping[str, Any] = dict(source_map or {})
        self._declared = declared
        self._generates: tuple[str, ...] = tuple(generates)

    def _bind(
        self,
        source_map: Mapping[str, Any],
        *,
        declared: bool,
        generates: Sequence[str] = (),
    ) -> None:
        """Fill in the resolved map once the pre-flight has produced it.

        Private, and called from exactly one place in the executor. The
        instance is injected before the pre-flight runs, so without this call
        every job would see an empty map and no error — the silent failure this
        capability's tests are built around.
        """
        self._map = dict(source_map)
        self._declared = declared
        self._generates = tuple(generates)

    @property
    def declared(self) -> bool:
        """True when the job declares ``Fingerprint(sources=...)`` at all.

        Tells "declared, nothing matched" (True, empty) apart from "declared no
        sources" (False, empty) — which an empty mapping alone cannot.
        """
        return self._declared

    @property
    def generates(self) -> tuple[str, ...]:
        """Declared outputs, as project-relative POSIX paths."""
        return self._generates

    def items(self) -> ItemsView[str, Any]:
        return self._map.items()

    def keys(self) -> KeysView[str]:
        return self._map.keys()

    def values(self) -> Any:
        return self._map.values()

    def get(self, path: str, default: Any = None) -> Any:
        return self._map.get(path, default)

    def __len__(self) -> int:
        return len(self._map)

    def __iter__(self) -> Any:
        return iter(self._map)

    def __contains__(self, path: str) -> bool:
        return path in self._map

    def __getitem__(self, path: str) -> Any:
        return self._map[path]

    def __bool__(self) -> bool:
        """Truthy when at least one input resolved.

        Note this is emptiness, not :attr:`declared` — a job that declared
        sources which matched nothing is falsy here *and* ``declared``. That
        pair is the whole point; see the class docstring.
        """
        return bool(self._map)

    def __repr__(self) -> str:
        return (
            f"Sources(declared={self._declared}, resolved={len(self._map)}, "
            f"generates={list(self._generates)!r})"
        )


# ── Registry entry (ADR-014) ───────────────────────────────────────────────


def _bind_from_preflight(instance: Sources, decision: Any) -> None:
    """Hand the pre-flight's resolved source map to the injected instance.

    A job whose declaration has no `Fingerprint` gets `declared=False`, which
    is a different answer from an empty map (ADR-012).
    """
    if decision is None:
        # No declaration, or nothing to pre-flight. Declared nothing.
        instance._bind({}, declared=False)
        return
    instance._bind(
        decision.source_map,
        declared=bool(decision.declared_sources),
        generates=decision.declared_generates,
    )


CAPABILITY = CapabilitySpec(
    name="Sources",
    type=Sources,
    # Deliberately empty. The pre-flight has not run yet — DI resolves before
    # it, because the pre-flight's args hash reads `context.injected` — so the
    # resolved map does not exist at this point.
    factory=lambda ctx: Sources(),
    # ...which is why the second phase is declared rather than remembered. The
    # executor completes every spec that declares one, right after the
    # pre-flight decision exists. When it was one call at one line, losing it
    # gave every job an empty map and no error anywhere.
    preflight_bind=_bind_from_preflight,
)
