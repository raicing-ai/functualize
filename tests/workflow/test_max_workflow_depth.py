"""Workflow nesting is bounded, and the refusal joins the existing vocabulary.

`durable-run-layer`/T12. Spec AC-18, inherited decision C9.

A separate limit from `max_invoke_depth`, because the two bound different
things. That one counts *any* nested call; this counts **workflows inside
workflows**, and each of those costs a scope, a set of step records, an epilogue
slot and a lease. A run can invoke deeply without nesting a single workflow.

Unbounded nesting is not hypothetical: a workflow that names itself as a step
type-checks, boots, and produces one scope per level until the disk or the
recursion limit gives out — and every one of those scopes is a record somebody
has to clean up afterwards.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from functualize._engine.workflow_validation import (
    DEFAULT_MAX_WORKFLOW_DEPTH,
    check_workflow_depth,
    workflow_depth,
)
from functualize._engine.workflow_walker import WorkflowWalker
from functualize._primitives.fresh_store import FreshStore
from functualize._primitives.substrate import JsonFileSubstrate
from functualize._types.errors import WorkflowDepthExceededError
from functualize._types.workflow import END, Edge, Step, WorkflowDeclaration


def _graph() -> WorkflowDeclaration:
    return WorkflowDeclaration(
        nodes=(Step("a"),), edges=(Edge(source="a", target=END),)
    )


@pytest.fixture
def store(tmp_path: Path) -> FreshStore:
    return FreshStore(JsonFileSubstrate(tmp_path))


class TestDepthComesFromTheScopeId:
    """Read from where the nesting already lives, not threaded through the walk.

    A nested workflow's scope is `f"{parent}::{step}"`, so the separators *are*
    the depth. A resumed walk in a fresh process has the id and nothing else,
    and a counter carried alongside could disagree with it.
    """

    @pytest.mark.parametrize(
        ("scope_id", "expected"),
        [
            ("top", 0),
            ("top::child", 1),
            ("top::child::grandchild", 2),
            ("a::b::c::d::e::f", 5),
        ],
    )
    def test_separators_are_the_depth(self, scope_id: str, expected: int) -> None:
        assert workflow_depth(scope_id) == expected

    def test_a_top_level_scope_is_depth_zero(self) -> None:
        """Not one. The limit counts *nesting*, so an unnested workflow has none."""
        assert workflow_depth("plain-scope-id") == 0


class TestTheLimitRefuses:
    def test_within_the_limit_passes(self) -> None:
        check_workflow_depth("a::b", limit=2)  # must not raise

    def test_exactly_at_the_limit_passes(self) -> None:
        """The limit is a ceiling, not an exclusive bound.

        `max_workflow_depth=2` means two levels of nesting are allowed; a reader
        who sets 2 and gets one level would have to discover the off-by-one from
        behaviour.
        """
        check_workflow_depth("a::b::c", limit=2)

    def test_past_the_limit_refuses(self) -> None:
        with pytest.raises(WorkflowDepthExceededError) as exc:
            check_workflow_depth("a::b::c::d", limit=2)
        assert exc.value.depth == 3
        assert exc.value.limit == 2

    def test_the_refusal_says_what_to_do(self) -> None:
        """A limit a reader cannot change is a wall, not a guard."""
        with pytest.raises(WorkflowDepthExceededError) as exc:
            check_workflow_depth("a::b::c::d", limit=2)
        message = str(exc.value)
        assert "max_workflow_depth" in message
        assert "a::b::c::d" in message

    def test_the_default_is_used_when_none_is_given(self) -> None:
        deep = "::".join("n" for _ in range(DEFAULT_MAX_WORKFLOW_DEPTH + 2))
        with pytest.raises(WorkflowDepthExceededError) as exc:
            check_workflow_depth(deep)
        assert exc.value.limit == DEFAULT_MAX_WORKFLOW_DEPTH


class TestTheWalkRefusesBeforeItWrites:
    """The check runs before any work, because the cost it bounds is the scope."""

    def test_a_too_deep_walk_raises(self, store: FreshStore) -> None:
        walker = WorkflowWalker(
            _graph(),
            store,
            "a::b::c::d",
            run_step=lambda name: name,
            max_workflow_depth=2,
        )
        with pytest.raises(WorkflowDepthExceededError):
            walker.run()

    def test_it_leaves_no_step_records_behind(self, store: FreshStore) -> None:
        """Checking after the first node would already have written one.

        The point of the limit is that each level costs a scope; a guard that
        pays that cost before refusing has bounded nothing.
        """
        executed: list[str] = []
        walker = WorkflowWalker(
            _graph(),
            store,
            "a::b::c::d",
            run_step=lambda name: executed.append(name) or name,
            max_workflow_depth=2,
        )
        with pytest.raises(WorkflowDepthExceededError):
            walker.run()

        assert executed == [], "a step ran before the depth was checked"
        scope = store.get_scope("a::b::c::d")
        assert not (scope or {}).get("steps"), "a step record was written"

    def test_a_walk_within_the_limit_runs(self, store: FreshStore) -> None:
        walker = WorkflowWalker(
            _graph(), store, "a::b", run_step=lambda name: name, max_workflow_depth=2
        )
        assert walker.run().outcome.value == "completed"

    def test_a_top_level_walk_is_unaffected(self, store: FreshStore) -> None:
        """The overwhelmingly common case must not pay for the guard."""
        walker = WorkflowWalker(
            _graph(), store, "plain", run_step=lambda name: name, max_workflow_depth=0
        )
        assert walker.run().outcome.value == "completed"


class TestNoSecondVocabulary:
    """Inherited C9: no new exit code, no parallel error family."""

    def test_it_is_an_ordinary_exception(self) -> None:
        """Not a `SystemExit`, not a sentinel return.

        A guard that exits the process cannot be caught by a caller that wants
        to handle deep nesting itself, and the CLI already has one place that
        turns a raised failure into an exit code.
        """
        assert issubclass(WorkflowDepthExceededError, Exception)
        assert not issubclass(WorkflowDepthExceededError, SystemExit)

    def test_it_carries_the_numbers_rather_than_only_a_message(self) -> None:
        """So a surface can render it without parsing prose."""
        with pytest.raises(WorkflowDepthExceededError) as exc:
            check_workflow_depth("a::b::c", limit=1)
        assert (exc.value.scope_id, exc.value.depth, exc.value.limit) == (
            "a::b::c",
            2,
            1,
        )

    def test_the_limit_lives_in_one_place(self) -> None:
        """`None` means "the default", resolved in the validation module.

        The walker stores `None` rather than substituting the default itself,
        so the number is not written twice and cannot drift.
        """
        walker = WorkflowWalker(_graph(), None, "x", run_step=lambda n: n)
        assert walker._max_workflow_depth is None
