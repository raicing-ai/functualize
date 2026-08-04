"""The job dependency graph — one construction, one resolver, one validation.

Built lazily and rebuilt whenever a registration invalidates it, so "once" is
per stable registry rather than per process: `register_dynamic_job` after boot
correctly forces a rebuild on the next query.

Before this existed, every consumer built its own adjacency dict from the
registry with its own reference resolver at its own moment: boot validation,
the executor's dependency pass, workflow nesting checks, `func why`. Seven
construction sites and three resolvers over one set of facts, which cost
exactly what duplication always costs — they disagreed. A dependency written
as a callable to a *grouped* job resolved to ``build.compile_it`` in the
validator and to bare ``compile_it`` in the executor, so boot passed and the
run failed with ``dependencies failed for 'ship': compile_it``.

**One object now answers "what depends on what".** Consumers ask it; nobody
builds their own.

**Validation happens on build, and that is the point.** Jobs enter the registry
through three doors — discovery (`_app/boot.py`), `register_dynamic_job`
(`_app/impl.py`), and `register_module` (`_discovery/registry.py`) — and only
the first ever called the validators, so a dynamically registered job with an
unknown dependency was never checked. Adding a validate call to the other two
would be a third and fourth thing to keep in sync. Instead the check lives
where every path must pass anyway: you cannot run a dependency without building
the graph, and building it validates. A guard on N entry points is N guards; a
guard on the thing they all need is one.

**It never reads ``entry.function``.** Structure comes from
``entry.dependencies`` and from reference names that a declaration can supply
on its own, because on a warm boot the function is a deferred-import stand-in
carrying nothing. Anything read off it works cold and silently vanishes warm.

**It knows nothing about runs.** Fingerprints, scopes and recorded step
results are runtime history in the state store; this is structure. The walker
joins the two. Keeping that line hard is what lets one graph serve boot
validation, execution, and `func why` without any of them caring which of the
three registration paths — cold discovery, warm cache, or
`register_dynamic_job` — put a job in the registry.

**Ordering is not implemented here.** It comes from
``_primitives.graph.topological_order`` — the same function plugin loading and
the dependency scheduler use — so one graph cannot be walked in two orders.
That function is `graphlib.TopologicalSorter` (stdlib, 0.23 ms to import) plus
an alphabetical tie-break; `static_order()` alone emits ready nodes in
insertion order, which made this class's plans depend on dict construction
while every other consumer got a deterministic one. networkx was measured at
499 ms — a hundred times this project's entire ``<5ms`` cold-start budget — to
supply analysis algorithms nothing here calls.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping

__all__ = ["JobGraph"]


class JobGraph:
    """Resolved dependency edges over the registered jobs.

    Args:
        registry: Live ``{name: RegisteredJob}`` mapping. Held by reference,
            not copied — :meth:`invalidate` is what reacts to registrations,
            so the graph is never stale against a registry it can still see.
    """

    def __init__(self, registry: Mapping[str, Any]) -> None:
        self._registry = registry
        self._edges: dict[str, list[str]] | None = None

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def invalidate(self) -> None:
        """Forget the built graph; the next query rebuilds and revalidates."""
        self._edges = None

    @property
    def edges(self) -> dict[str, list[str]]:
        """``{job: [jobs it depends on]}``, building and validating on demand."""
        if self._edges is None:
            self._edges = self._build()
        return self._edges

    # ------------------------------------------------------------------
    # Queries
    # ------------------------------------------------------------------

    def deps_of(self, name: str) -> list[str]:
        """Direct dependencies of ``name`` — resolved names, or []."""
        return list(self.edges.get(name, ()))

    def order_for(self, name: str) -> list[str]:
        """Everything ``name`` transitively needs, in a runnable order.

        ``name`` itself is excluded: the caller runs it after the plan, and
        including it would schedule a job inside its own dependency run.
        """
        from functualize._primitives.graph import topological_order

        needed = self._reachable(name)
        if not needed:
            return []
        subgraph = {
            node: [dep for dep in self.edges.get(node, ()) if dep in needed]
            for node in needed
        }
        return topological_order(subgraph)

    def validate(self) -> None:
        """Resolve every reference and reject unknown refs and cycles."""
        self.edges  # noqa: B018 - building is validating

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _reachable(self, root: str) -> set[str]:
        """Transitive dependencies of ``root``, excluding ``root``."""
        seen: set[str] = set()
        stack = list(self.edges.get(root, ()))
        while stack:
            node = stack.pop()
            if node in seen or node == root:
                continue
            seen.add(node)
            stack.extend(self.edges.get(node, ()))
        return seen

    def _build(self) -> dict[str, list[str]]:
        """Resolve every declared reference, then check for cycles."""
        from functualize._types.errors import JobDependencyError

        edges: dict[str, list[str]] = {}
        for name, entry in self._registry.items():
            declared = getattr(entry, "dependencies", ()) or ()
            edges[name] = [self.resolve(ref, owner=name) for ref in declared]

        # Every referenced node must be a key, or TopologicalSorter treats it
        # as an isolated node and the order silently omits nothing — but a
        # missing key would also hide a typo, which `resolve` has already
        # rejected. This only normalizes shape.
        for deps in list(edges.values()):
            for dep in deps:
                edges.setdefault(dep, [])

        from functualize._primitives.graph import GraphCycleError, topological_order

        try:
            topological_order(edges)
        except GraphCycleError as exc:
            raise JobDependencyError(
                f"Dependency cycle: {' -> '.join(exc.cycle)}"
                if exc.cycle
                else "Dependency cycle detected."
            ) from exc
        return edges

    def resolve(self, ref: Any, *, owner: str = "") -> str:
        """One reference resolved to a registered job name.

        Turns a reference into a *candidate* name, then hands the naming
        question to :func:`~functualize._discovery.naming.resolve_name`.

        This class owns edges; the namespace owns names. Keeping the policy
        here would have made a fourth resolver the moment the kernel group
        trie resolves the same names for dispatch and completion.
        """
        from functualize._types.errors import JobDependencyError

        target = getattr(ref, "target", ref)  # unwrap call(...)
        if isinstance(target, str):
            candidate: str = target
        elif callable(target):
            # Deliberately *not* matched by function identity. On a warm boot
            # `entry.function` is a deferred-import stand-in, so identity
            # would resolve cold and silently fall through warm — the exact
            # divergence this class exists to remove. `_ref_name` yields the
            # registered name from the target's own declaration, which is
            # also what the cache stores, so both paths ask the same question.
            from functualize._types.job_declaration import _ref_name

            candidate = _ref_name(target)
        else:
            raise JobDependencyError(
                f"Job '{owner}' has an invalid dependency reference {ref!r}."
            )

        from functualize._types.naming import resolve_name

        try:
            return resolve_name(candidate, self._registry)
        except LookupError as exc:
            # `naming` knows names; this class knows they are jobs. Ambiguous
            # and unknown are different problems and get different sentences —
            # "unknown job 'build'" is actively misleading when two jobs match.
            message = (
                f"Job '{owner}' depends on '{candidate}', which is {exc}."
                if "ambiguous" in str(exc)
                else f"Job '{owner}' depends on unknown job '{candidate}'."
            )
            raise JobDependencyError(message) from exc

    def resolve_all(self, refs: Iterable[Any], *, owner: str = "") -> list[str]:
        """Resolve a batch of references, preserving order."""
        return [self.resolve(ref, owner=owner) for ref in refs]
