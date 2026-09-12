"""A cycle in a step graph is refused at declaration, not run once in silence.

`workflow-graph-semantics`/T1. Spec AC-3.

**What this changes.** A declared cycle used to be *accepted*. The walk prunes
nodes it has already visited, so the second pass was dropped with no message at
all — and a loop that never looped is indistinguishable from a loop whose
condition was false. The declaration said one thing, the run did another, and
nothing said so.

Nothing validated it either: `_engine/workflow_validation.py` guards cycles
between **nested workflows**, on the grounds that *"ordinary jobs terminate a
chain and are already cycle-checked as deps"* — true of the job graph, and not
a statement about edges inside one workflow.

**The other half of this file is the legal shapes.** A cycle check that also
refuses a diamond, or a conditional whose branches rejoin, would be worse than
no check: those are the ordinary way to write a graph, and the refusal would
arrive at import time for a correct declaration. Every test below that builds a
*legal* graph is guarding against that, not padding.
"""

from __future__ import annotations

import pytest
from pydantic import BaseModel

from functualize._engine.frontier import step_key
from functualize._engine.loop_state import iteration_step_key
from functualize._engine.workflow_walker import WalkOutcome, WorkflowWalker
from functualize._primitives.scope_store import ScopeStore
from functualize._primitives.substrate import JsonFileSubstrate
from functualize._types.errors import WorkflowDeclarationError
from functualize._types.workflow import (
    END,
    ConditionalEdge,
    Edge,
    Gate,
    Loop,
    Step,
    WorkflowDeclaration,
)
from functualize.workflow._validation import _validate_workflow_graph


class _Ask(BaseModel):
    """The smallest thing a gate can await."""

    text: str


def _steps(*names: str) -> list[Step]:
    return [Step(name) for name in names]


class TestACycleIsRefused:
    def test_two_nodes_pointing_at_each_other(self) -> None:
        with pytest.raises(WorkflowDeclarationError) as exc:
            _validate_workflow_graph(
                _steps("a", "b"),
                [Edge(source="a", target="b"), Edge(source="b", target="a")],
            )
        assert "cycle" in str(exc.value)

    def test_a_node_pointing_at_itself(self) -> None:
        """The smallest cycle, and the one most likely to be a typo."""
        with pytest.raises(WorkflowDeclarationError):
            _validate_workflow_graph(_steps("a"), [Edge(source="a", target="a")])

    def test_a_longer_ring(self) -> None:
        with pytest.raises(WorkflowDeclarationError):
            _validate_workflow_graph(
                _steps("a", "b", "c", "d"),
                [
                    Edge(source="a", target="b"),
                    Edge(source="b", target="c"),
                    Edge(source="c", target="d"),
                    Edge(source="d", target="b"),
                ],
            )

    def test_a_cycle_reached_through_a_conditional(self) -> None:
        """A `ConditionalEdge` has several targets and any of them can close it.

        Checking only `Edge.target` would miss this, and a conditional is the
        natural way somebody writes a retry — so it is the shape most likely to
        be hit in practice.
        """
        with pytest.raises(WorkflowDeclarationError):
            _validate_workflow_graph(
                _steps("a", "b"),
                [
                    Edge(source="a", target="b"),
                    ConditionalEdge(
                        source="b",
                        condition=lambda: "again",
                        targets={"again": "a", "done": END},
                    ),
                ],
            )

    def test_a_cycle_that_also_has_a_way_out(self) -> None:
        """Having an exit does not make it bounded.

        This is the one a reader will argue about: the graph *can* terminate,
        so is it really unbounded? Nothing in the declaration says how many
        times it goes round, and the walk has no counter — which is exactly the
        state where it silently ran once.
        """
        with pytest.raises(WorkflowDeclarationError):
            _validate_workflow_graph(
                _steps("work", "check"),
                [
                    Edge(source="work", target="check"),
                    ConditionalEdge(
                        source="check",
                        condition=lambda: "retry",
                        targets={"retry": "work", "ok": END},
                    ),
                ],
            )

    def test_a_gate_inside_the_cycle_does_not_excuse_it(self) -> None:
        """A pause is not a bound. It stops the run, not the repetition."""
        with pytest.raises(WorkflowDeclarationError):
            _validate_workflow_graph(
                [Step("a"), Gate(name="approve", awaits=_Ask), Step("b")],
                [
                    Edge(source="a", target="approve"),
                    Edge(source="approve", target="b"),
                    Edge(source="b", target="a"),
                ],
            )


class TestTheRefusalIsUsable:
    def test_it_names_the_cycle_it_found(self) -> None:
        """The reader's next act is to go and look at it."""
        with pytest.raises(WorkflowDeclarationError) as exc:
            _validate_workflow_graph(
                _steps("a", "b", "c"),
                [
                    Edge(source="a", target="b"),
                    Edge(source="b", target="c"),
                    Edge(source="c", target="b"),
                ],
            )
        message = str(exc.value)
        assert "b -> c -> b" in message, message

    def test_it_does_not_name_the_path_that_reached_the_cycle(self) -> None:
        """`a` leads to the loop but is not in it.

        Reporting the whole traversal would send a reader to the wrong edge —
        the one to delete is inside the ring.
        """
        with pytest.raises(WorkflowDeclarationError) as exc:
            _validate_workflow_graph(
                _steps("a", "b", "c"),
                [
                    Edge(source="a", target="b"),
                    Edge(source="b", target="c"),
                    Edge(source="c", target="b"),
                ],
            )
        assert "a ->" not in str(exc.value)

    def test_it_says_what_to_do(self) -> None:
        """A refusal with no remedy is a wall."""
        with pytest.raises(WorkflowDeclarationError) as exc:
            _validate_workflow_graph(_steps("a"), [Edge(source="a", target="a")])
        message = str(exc.value)
        assert "remove the edge" in message
        assert "bound" in message

    def test_it_explains_what_used_to_happen(self) -> None:
        """Because the reader's graph worked yesterday.

        Without this the message reads as a new restriction rather than a
        defect being surfaced, and the obvious response is to look for a way to
        turn it off.
        """
        with pytest.raises(WorkflowDeclarationError) as exc:
            _validate_workflow_graph(_steps("a"), [Edge(source="a", target="a")])
        assert "run once" in str(exc.value)


class TestALoopIsWhatMakesACycleLegal:
    """The mechanism, which nothing tested until a sabotage said so.

    `Loop` works by being **excluded from the cycle search**: what is left must
    be acyclic. Every other test in this file either builds a graph out of
    plain `Edge`s and checks it is refused, or drives the walker directly with
    a `WorkflowDeclaration` — which bypasses validation entirely. So making
    `Loop` count as a cycle edge again broke nothing, and the one line the
    feature rests on was unverified.
    """

    def test_a_loop_bounded_cycle_is_accepted(self) -> None:
        _validate_workflow_graph(
            _steps("work", "check"),
            [
                Edge(source="work", target="check"),
                Loop(source="check", target="work", max_iterations=3),
                Edge(source="check", target=END),
            ],
        )

    def test_the_same_graph_with_a_plain_edge_is_refused(self) -> None:
        """The falsifier, beside it — otherwise the test above passes for a
        graph that was never cyclic in the first place."""
        with pytest.raises(WorkflowDeclarationError):
            _validate_workflow_graph(
                _steps("work", "check"),
                [
                    Edge(source="work", target="check"),
                    Edge(source="check", target="work"),
                    Edge(source="check", target=END),
                ],
            )

    def test_a_self_loop_is_accepted_when_bounded(self) -> None:
        _validate_workflow_graph(
            _steps("work"),
            [
                Loop(source="work", target="work", max_iterations=2),
                Edge(source="work", target=END),
            ],
        )

    def test_a_second_unbounded_cycle_is_still_refused(self) -> None:
        """One `Loop` does not make the whole graph exempt.

        The bound applies to the edge that carries it, not to the declaration —
        otherwise adding a legitimate loop anywhere would silence the check
        everywhere else in the same workflow.
        """
        with pytest.raises(WorkflowDeclarationError) as exc:
            _validate_workflow_graph(
                _steps("work", "check", "x", "y"),
                [
                    Edge(source="work", target="check"),
                    Loop(source="check", target="work", max_iterations=3),
                    Edge(source="x", target="y"),
                    Edge(source="y", target="x"),
                ],
            )
        assert "x" in str(exc.value) and "y" in str(exc.value)

    def test_a_loop_target_must_name_a_node(self) -> None:
        """Same check every other edge gets. A `Loop` is not a way past it."""
        with pytest.raises(ValueError, match="Loop target"):
            _validate_workflow_graph(
                _steps("work"),
                [Loop(source="work", target="nowhere", max_iterations=2)],
            )


class TestLegalGraphsStillPass:
    """The half that stops the check from being worse than nothing."""

    def test_a_straight_line(self) -> None:
        _validate_workflow_graph(
            _steps("a", "b"),
            [Edge(source="a", target="b"), Edge(source="b", target=END)],
        )

    def test_a_diamond(self) -> None:
        """Two branches rejoining is not a cycle.

        `d` is reached twice by the traversal and both arrivals are legal. A
        check using a plain visited-set instead of three states would call this
        a cycle and refuse the most common non-linear graph there is.
        """
        _validate_workflow_graph(
            _steps("a", "left", "right", "d"),
            [
                Edge(source="a", target="left"),
                Edge(source="a", target="right"),
                Edge(source="left", target="d"),
                Edge(source="right", target="d"),
                Edge(source="d", target=END),
            ],
        )

    def test_a_conditional_whose_branches_rejoin(self) -> None:
        _validate_workflow_graph(
            _steps("check", "fast", "slow", "finish"),
            [
                ConditionalEdge(
                    source="check",
                    condition=lambda: "fast",
                    targets={"fast": "fast", "slow": "slow"},
                ),
                Edge(source="fast", target="finish"),
                Edge(source="slow", target="finish"),
                Edge(source="finish", target=END),
            ],
        )

    def test_two_nodes_both_ending(self) -> None:
        """END is not a vertex.

        Treating it as one would make every terminating graph share a sink,
        and two branches both ending would look like a join — harmless here,
        but it is the kind of thing that becomes a false cycle later.
        """
        _validate_workflow_graph(
            _steps("a", "b"),
            [Edge(source="a", target=END), Edge(source="b", target=END)],
        )

    def test_a_long_chain_does_not_hit_the_recursion_limit(self) -> None:
        """Iterative on purpose.

        A recursive walk turns a graph that is merely long into a
        `RecursionError` at decoration time — an unrelated failure, reported
        against a declaration that is perfectly legal.
        """
        names = [f"n{i}" for i in range(2000)]
        edges: list[Edge] = [
            Edge(source=a, target=b) for a, b in zip(names, names[1:], strict=False)
        ]
        edges.append(Edge(source=names[-1], target=END))

        _validate_workflow_graph(_steps(*names), edges)

    def test_a_disconnected_second_component_is_still_checked(self) -> None:
        """The search starts from every node, not from an entry point.

        A graph's entry is decided elsewhere, so a cycle in a component nothing
        reaches is still a cycle in the declaration — and a check that only
        walked from one root would miss it.
        """
        with pytest.raises(WorkflowDeclarationError):
            _validate_workflow_graph(
                _steps("a", "x", "y"),
                [
                    Edge(source="a", target=END),
                    Edge(source="x", target="y"),
                    Edge(source="y", target="x"),
                ],
            )


# ---------------------------------------------------------------------------
# T2 — the walk itself
# ---------------------------------------------------------------------------


class _Recorder:
    """Counts how many times each step ran."""

    def __init__(self) -> None:
        self.calls: list[str] = []

    def __call__(self, name: str) -> str:
        self.calls.append(name)
        return name

    def count(self, name: str) -> int:
        return self.calls.count(name)


@pytest.fixture
def store(tmp_path) -> ScopeStore:
    return ScopeStore(JsonFileSubstrate(tmp_path))


class TestTheIterationKeyingIsRightBothWays:
    """**Both failure modes are silent**, so they are asserted in one body.

    Key `visited` by node alone and a loop's second pass is pruned — which
    looks exactly like a loop condition that was false. Key it by iteration
    alone and a diamond join runs once per branch — which looks exactly like a
    flaky step. Two separate tests can both pass while the keying is wrong in a
    third way, so the graph below is a loop **containing** a diamond and the
    assertions are made together.

        entry ──► fan ──┬─► left ──┐
                        └─► right ─┴─► join ──(Loop ×3)──► fan
    """

    @staticmethod
    def _graph() -> WorkflowDeclaration:
        return WorkflowDeclaration(
            nodes=(Step("fan"), Step("left"), Step("right"), Step("join")),
            edges=(
                Edge(source="fan", target="left"),
                Edge(source="fan", target="right"),
                Edge(source="left", target="join"),
                Edge(source="right", target="join"),
                Loop(source="join", target="fan", max_iterations=3),
                Edge(source="join", target=END),
            ),
        )

    def test_the_loop_repeats_and_the_join_still_runs_once_per_pass(
        self, store: ScopeStore
    ) -> None:
        runner = _Recorder()

        report = WorkflowWalker(self._graph(), store, "s1", run_step=runner).run()

        assert report.outcome is WalkOutcome.COMPLETED, report
        assert runner.count("join") == 3, (
            f"the join ran {runner.count('join')} times for 3 iterations — "
            f"once per branch means `visited` lost the node half of its key; "
            f"once in total means it lost the iteration half and the loop "
            f"never looped. Calls: {runner.calls}"
        )
        assert runner.count("fan") == 3, (
            f"the loop body ran {runner.count('fan')} times, not 3 — a second "
            f"pass was pruned, which is indistinguishable from a condition "
            f"that was false. Calls: {runner.calls}"
        )
        assert runner.count("left") == runner.count("right") == 3


class TestTheBound:
    @staticmethod
    def _counting(max_iterations: int) -> WorkflowDeclaration:
        return WorkflowDeclaration(
            nodes=(Step("work"),),
            edges=(
                Loop(source="work", target="work", max_iterations=max_iterations),
                Edge(source="work", target=END),
            ),
        )

    @pytest.mark.parametrize("bound", [1, 2, 5])
    def test_the_body_runs_exactly_the_bound(
        self, bound: int, store: ScopeStore
    ) -> None:
        """`max_iterations` counts the first pass, and means *at most*."""
        runner = _Recorder()
        WorkflowWalker(self._counting(bound), store, "s1", run_step=runner).run()
        assert runner.count("work") == bound

    def test_a_bound_of_one_is_a_body_that_does_not_repeat(
        self, store: ScopeStore
    ) -> None:
        """Legal, and occasionally what someone wants while switching it off."""
        runner = _Recorder()
        WorkflowWalker(self._counting(1), store, "s1", run_step=runner).run()
        assert runner.count("work") == 1

    def test_there_is_no_default(self) -> None:
        """Every value anyone would pick as a default is wrong for somebody.

        Too low truncates work silently; too high turns a runaway condition
        into an outage rather than a quick refusal. Writing the number is the
        point of the type.
        """
        with pytest.raises(TypeError):
            Loop(source="a", target="b")  # type: ignore[call-arg]

    def test_zero_is_refused(self) -> None:
        with pytest.raises(ValueError, match="at least 1"):
            Loop(source="a", target="b", max_iterations=0)

    def test_the_bound_wins_over_a_condition_that_never_stops(
        self, store: ScopeStore
    ) -> None:
        """Checked before the condition, so a runaway costs a pass, not an outage."""
        runner = _Recorder()
        graph = WorkflowDeclaration(
            nodes=(Step("work"),),
            edges=(
                Loop(
                    source="work",
                    target="work",
                    max_iterations=4,
                    condition=lambda _value: True,
                ),
                Edge(source="work", target=END),
            ),
        )
        WorkflowWalker(graph, store, "s1", run_step=runner).run()
        assert runner.count("work") == 4


class TestTheCondition:
    def test_a_false_condition_leaves_the_loop_early(self, store: ScopeStore) -> None:
        runner = _Recorder()
        graph = WorkflowDeclaration(
            nodes=(Step("work"),),
            edges=(
                Loop(
                    source="work",
                    target="work",
                    max_iterations=9,
                    condition=lambda _value: len(runner.calls) < 2,
                ),
                Edge(source="work", target=END),
            ),
        )
        WorkflowWalker(graph, store, "s1", run_step=runner).run()
        assert runner.count("work") == 2

    def test_it_is_given_the_sources_return_value(self, store: ScopeStore) -> None:
        """Same argument a `ConditionalEdge` condition receives."""
        seen: list[object] = []
        graph = WorkflowDeclaration(
            nodes=(Step("work"),),
            edges=(
                Loop(
                    source="work",
                    target="work",
                    max_iterations=2,
                    condition=lambda value: seen.append(value) or False,
                ),
                Edge(source="work", target=END),
            ),
        )
        WorkflowWalker(graph, store, "s1", run_step=lambda n: f"{n}-value").run()
        assert seen == ["work-value"]


class TestResumeContinuesTheIteration:
    """AC-4. The iteration is derived from the records, so a fresh process
    resumes where the last one stopped rather than at the first pass."""

    @staticmethod
    def _gated_loop() -> WorkflowDeclaration:
        return WorkflowDeclaration(
            nodes=(Step("work"), Gate(name="approve", awaits=_Ask)),
            edges=(
                Edge(source="work", target="approve"),
                Loop(source="approve", target="work", max_iterations=3),
                Edge(source="approve", target=END),
            ),
        )

    def test_a_resume_does_not_replay_iterations_it_has_finished(
        self, store: ScopeStore
    ) -> None:
        """The property the derivation actually provides.

        **The obvious assertion is the wrong one.** "The loop continues after a
        resume" holds whether or not the iteration is derived, because replay
        already skips finished work — measured: replacing `_resume_iteration`
        with `return 0` produced identical executions and failed no test, which
        is how this test came to be rewritten.

        What the derivation changes is how much replaying happens before the
        walk reaches live work. Resumed at 0, the walk replays every finished
        iteration first; a loop resumed at iteration 900 of 1000 would re-read
        900 iterations' records on every resume.
        """
        runner = _Recorder()
        first = WorkflowWalker(self._gated_loop(), store, "s1", run_step=runner).run()
        assert first.outcome is WalkOutcome.BLOCKED, first

        store.deposit_gate_payload("s1", "approve", {"text": "go"})
        resumed = WorkflowWalker(
            self._gated_loop(), ScopeStore(store.substrate), "s1", run_step=runner
        ).run()

        assert "work" not in resumed.replayed, (
            f"the resumed walk replayed the loop body it had already finished, "
            f"so it restarted at iteration 0: replayed={resumed.replayed}"
        )

    def test_the_loop_still_finishes_across_the_resume(self, store: ScopeStore) -> None:
        """Correctness, stated separately from the optimization above.

        Kept apart deliberately: this one passes with or without the
        derivation, and folding the two together is what hid the fact that the
        derivation was untested.
        """
        runner = _Recorder()
        WorkflowWalker(self._gated_loop(), store, "s1", run_step=runner).run()
        store.deposit_gate_payload("s1", "approve", {"text": "go"})
        resumed = WorkflowWalker(
            self._gated_loop(), ScopeStore(store.substrate), "s1", run_step=runner
        ).run()

        assert resumed.outcome is WalkOutcome.COMPLETED, resumed
        assert runner.count("work") == 3

    def test_a_gate_inside_a_loop_is_answered_once_for_every_pass(
        self, store: ScopeStore
    ) -> None:
        """**A known limitation, pinned so it is not discovered by accident.**

        Gate payloads are keyed by gate *name*, not by name and iteration. So a
        gate inside a loop is answered once and every later pass reads that
        same answer rather than pausing again — which is very likely not what
        someone writing an approval inside a retry loop expects.

        Asserted rather than fixed: iteration-keyed gates change the deposit
        vocabulary that `--wf-input`, the MCP `answer_gate` tool and the scope
        record all share, which is a wider change than T2 owns. This test is
        what will fail when that is done, and it should be *changed* then, not
        deleted.
        """
        runner = _Recorder()
        WorkflowWalker(self._gated_loop(), store, "s1", run_step=runner).run()
        store.deposit_gate_payload("s1", "approve", {"text": "go"})

        resumed = WorkflowWalker(
            self._gated_loop(), ScopeStore(store.substrate), "s1", run_step=runner
        ).run()

        assert resumed.outcome is WalkOutcome.COMPLETED, (
            "the loop paused again at the gate — which is arguably right, but "
            "it is not what this build does, and the change is bigger than T2"
        )

    def test_each_iteration_gets_its_own_record(self, store: ScopeStore) -> None:
        """Which is what makes the derivation possible.

        One record per node would make the second pass a replay of the first,
        and there would be nothing in the store to read the iteration back out
        of.
        """
        WorkflowWalker(
            TestTheBound._counting(3), store, "s1", run_step=lambda n: n
        ).run()

        assert store.get_step("s1", iteration_step_key("work", 0)) is not None
        assert store.get_step("s1", iteration_step_key("work", 1)) is not None
        assert store.get_step("s1", iteration_step_key("work", 2)) is not None

    def test_iteration_zero_is_keyed_exactly_as_before(self) -> None:
        """So a graph with no `Loop` writes the records it always wrote.

        Nothing is migrated, and a workflow that never loops cannot notice this
        feature happened.
        """
        assert iteration_step_key("work", 0) == step_key("work", "")


class TestAGraphWithNoLoopIsUntouched:
    def test_the_records_are_the_ones_it_always_wrote(self, store: ScopeStore) -> None:
        graph = WorkflowDeclaration(
            nodes=(Step("a"), Step("b")),
            edges=(Edge(source="a", target="b"), Edge(source="b", target=END)),
        )
        WorkflowWalker(graph, store, "s1", run_step=lambda n: n).run()

        for name in ("a", "b"):
            assert store.get_step("s1", step_key(name, "")) is not None

    def test_a_diamond_join_still_runs_once(self, store: ScopeStore) -> None:
        """The property the `visited` set existed for, with no loop in sight."""
        runner = _Recorder()
        graph = WorkflowDeclaration(
            nodes=(Step("fan"), Step("left"), Step("right"), Step("join")),
            edges=(
                Edge(source="fan", target="left"),
                Edge(source="fan", target="right"),
                Edge(source="left", target="join"),
                Edge(source="right", target="join"),
                Edge(source="join", target=END),
            ),
        )
        WorkflowWalker(graph, store, "s1", run_step=runner).run()
        assert runner.count("join") == 1
