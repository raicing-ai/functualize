"""Workflow-graph validation against the live registry (§A.7).

Lives in ``_engine`` rather than ``_app`` because the *engine* must run it:
boot is not the only door. `register_dynamic_job` never called the boot
validator, so a dynamically registered workflow reached a live walk unchecked
— the same "guard on N entry points" shape SG closed for the job graph. A
guard belongs on the thing every path needs, and every walk needs a validated
declaration.

Keeping it here also keeps the layering honest: `_engine` may not import
`_app` (the composition root sits above the peer layers), which lint-imports
caught the moment the executor reached for it.
"""

from __future__ import annotations

from typing import Any


def _validate_workflow_from_job_refs(
    registered: dict[str, Any], nesting: dict[str, list[str]], resolve: Any
) -> None:
    """A workflow step may only consume values its graph already ordered.

    Outside a workflow a ``FromJob`` reference *is* the dependency edge, and
    resolving it may run the upstream. Inside one that would be wrong: the
    graph already declares the order and the walk already recorded the value,
    so running the upstream again would execute it outside the scope, twice,
    and defeat the walk's determinism.

    So inside a workflow the reference is a **read**, and reaching for a node
    the graph never ordered is a bug in the graph. Caught here rather than
    mid-walk, when a scope is already open and half its steps have run.
    """
    from functualize._primitives.graph import descendants
    from functualize._types.errors import WorkflowDeclarationError
    from functualize._types.from_job import from_job_refs

    for workflow_name, step_names in nesting.items():
        entry = registered.get(workflow_name)
        declaration = getattr(
            getattr(entry, "function", None), "__functualize_workflow__", None
        )
        if declaration is None:
            continue

        # `descendants(m, [x])` yields every node that depends on x under m.
        # Feeding it the *successors* map therefore yields every node that
        # reaches x — x's ancestors, which is what "ordered before it" means.
        successors: dict[str, list[str]] = {node.name: [] for node in declaration.nodes}
        for node in declaration.nodes:
            for target in declaration.successors(node.name):
                successors.setdefault(node.name, []).append(target)
                successors.setdefault(target, [])

        in_graph = set(successors)
        for step_name in step_names:
            step_fn = getattr(registered.get(step_name), "function", None)
            if step_fn is None:
                continue
            ancestors = set(descendants(successors, [step_name]))
            for param, ref in from_job_refs(step_fn).items():
                if not ref.run:
                    continue  # a read-only reference orders nothing
                target = resolve(ref.job, workflow_name)
                short = target.rsplit(".", 1)[-1]
                if short in ancestors or target in ancestors:
                    continue
                if short in in_graph or target in in_graph:
                    raise WorkflowDeclarationError(
                        f"Step '{step_name}' of workflow '{workflow_name}' consumes "
                        f"'{target}' via FromJob (parameter '{param}'), but the graph "
                        f"does not order '{target}' before it. Add an edge, or use "
                        f"FromJob(..., run=False) to read a value without ordering."
                    )
                raise WorkflowDeclarationError(
                    f"Step '{step_name}' of workflow '{workflow_name}' consumes "
                    f"'{target}' via FromJob (parameter '{param}'), which is not a "
                    f"node in the graph. Inside a workflow the graph declares the "
                    f"order; add '{target}' as a Step, or use "
                    f"FromJob(..., run=False) to read a recorded value."
                )

            # The same rule for `Deps` naming a node of this graph (Part I
            # cell D×W). A dependency says "before"; if the graph says "after"
            # the two declarations contradict each other, and the run resolved
            # it by executing the node twice — once as a dependency, once as a
            # node. Deps on jobs *outside* the graph are untouched: they are
            # ordinary dependencies and keep following their own `Exec.run`.
            step_declaration = getattr(step_fn, "__functualize_job__", None)
            step_deps = getattr(step_declaration, "deps", None)
            for ref in getattr(step_deps, "refs", ()) or ():
                target = resolve(getattr(ref, "target", ref), workflow_name)
                short = target.rsplit(".", 1)[-1]
                if short in ancestors or target in ancestors:
                    continue
                if short in in_graph or target in in_graph:
                    raise WorkflowDeclarationError(
                        f"Step '{step_name}' of workflow '{workflow_name}' declares "
                        f"Deps('{target}'), and '{target}' is also a node of this "
                        f"graph, but the graph does not order it before "
                        f"'{step_name}'. The dependency says 'before' and the graph "
                        f"says 'after'. Add an edge "
                        f"'{target}' -> '{step_name}', or remove one of the two."
                    )


def validate_workflow_declarations(app: Any = None, *, registry: Any = None) -> None:
    """Resolve every ``@workflow`` graph against the registry (§A.7).

    Two checks that need the live registry, and so cannot run at decoration
    time: every `Step` must reference a registered job, and workflows that
    nest one another (a `Step` pointing at another workflow job) must not form
    a cycle. Both raise ``WorkflowDeclarationError`` at boot rather than
    halfway through a walk, when a scope is already open.

    Accepts either an app or a bare ``registry`` mapping. The registry form is
    what lets the *engine* run this before a walk, which matters because boot
    is not the only door: `register_dynamic_job` never called this, so a
    dynamically registered workflow was never checked at all. That is the same
    "guard on N entry points" shape SG closed for the job graph — a guard
    belongs on the thing every path needs, and every walk needs a validated
    declaration.
    """
    from functualize._primitives.graph import GraphCycleError, topological_order
    from functualize._types.errors import WorkflowDeclarationError
    from functualize._types.naming import resolve_name

    registered: dict[str, Any] = (
        registry if registry is not None else app.job_registry._registered_jobs
    )

    func_to_name: dict[int, str] = {}
    for name, entry in registered.items():
        fn = getattr(entry, "function", None)
        if fn is not None:
            func_to_name[id(fn)] = name

    def _resolve(ref: Any, owner: str) -> str:
        """One Step reference resolved to a registered job name.

        Identity is tried first because a *cold* boot has the real function
        here and that is the most precise answer available. Everything after
        it defers to `resolve_name`, the single naming policy — this used to
        carry its own exact-then-leaf matching, which made it the sixth
        implementation of "what job does this name mean" and, once names
        became canonical, the one that could not find `travel-plan` from a
        Step written as `travel_plan`.
        """
        if callable(ref) and not isinstance(ref, str):
            mapped = func_to_name.get(id(ref))
            if mapped is not None:
                return mapped
            candidate = getattr(ref, "__name__", None) or repr(ref)
        else:
            candidate = ref

        try:
            return resolve_name(str(candidate), registered)
        except LookupError as exc:
            detail = f" {exc}." if "ambiguous" in str(exc) else ""
            raise WorkflowDeclarationError(
                f"Workflow '{owner}' has a Step referencing unknown job "
                f"'{candidate}'.{detail}"
            ) from exc

    # workflow job name -> the workflow jobs it nests via Step refs
    nesting: dict[str, list[str]] = {}
    workflow_names: set[str] = set()

    for name, entry in registered.items():
        fn = getattr(entry, "function", None)
        declaration = getattr(fn, "__functualize_workflow__", None)
        if declaration is None:
            continue
        workflow_names.add(name)
        nesting[name] = [_resolve(ref, name) for ref in declaration.step_refs()]

    _validate_workflow_from_job_refs(registered, nesting, _resolve)

    if not workflow_names:
        return

    # Only workflow-to-workflow edges can form the cycle this guards against;
    # ordinary jobs terminate a chain and are already cycle-checked as deps.
    graph = {
        name: [t for t in targets if t in workflow_names]
        for name, targets in nesting.items()
    }
    try:
        topological_order(graph)
    except GraphCycleError as exc:
        cycle = getattr(exc, "cycle", None)
        raise WorkflowDeclarationError(
            f"Workflow nesting cycle: {' -> '.join(cycle)}"
            if cycle
            else "Workflow nesting cycle detected."
        ) from exc
