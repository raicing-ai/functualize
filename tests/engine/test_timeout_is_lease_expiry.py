"""A step "timeout" expires a lease. It does not stop the work, and says so.

`durable-run-layer`/T10. Spec AC-12, AC-13.

The roadmap asked for per-step timeouts. `_engine/exec_policy` had already
researched and **rejected** every mechanism that could deliver one, and it was
right: Python cannot preempt a running function, so a thread-based timeout
reports `TIMEOUT` while the work carries on — *"a caller that believes the job
stopped may release a lock or delete a file the still-live job is using."* A
`SIGALRM` version works only on POSIX and only on the main thread, so it would
silently do nothing in the TUI.

So a timeout here means something narrower and true: **the runner stops
renewing, and the scope becomes claimable**. Someone else may take the workflow
forward. The original work is not stopped, and every surface that reports the
reclaim says so in those words.

This file pins both halves — that the mechanism works, and that it does not
claim more than it does.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from threading import Event, Thread
from threading import enumerate as live_threads
from time import monotonic, sleep

import pytest
from tests._support.engine_storage import port_for

from functualize._engine.frontier import FrontierWalk, GraphModel, RenewalOutcome
from functualize._primitives.lease import DEFAULT_LEASE_SECONDS, is_expired
from functualize._primitives.scope_store import ScopeStore
from functualize._primitives.substrate import JsonFileSubstrate
from functualize._types.persistence import Claimed
from functualize.app._workflow_control import reclaim_scope
from functualize.app._workflow_view import derived_state


@pytest.fixture
def store(tmp_path: Path) -> ScopeStore:
    s = ScopeStore(JsonFileSubstrate(tmp_path))
    s.ensure_scope("wf", "demo")
    s.set_scope_status("wf", "running")
    return s


def _walk(store: ScopeStore) -> FrontierWalk:
    return FrontierWalk(
        GraphModel(entry="n1"), store, "wf", runtime_store=port_for(store)
    )


def _age_the_lease(store: ScopeStore, seconds: float, *, scope_id: str = "wf") -> None:
    """Move the lease's expiry into the past by ``seconds``."""
    scope = store.get_scope(scope_id)
    past = (datetime.now(UTC) - timedelta(seconds=seconds)).isoformat()
    lease = {**scope["lease"], "expires_at": past}
    store._mutate(  # noqa: SLF001
        lambda env: env["scopes"][scope_id].__setitem__("lease", lease)
    )


def _wait_for(condition: Callable[[], bool], timeout: float = 2.0) -> bool:
    """Poll ``condition`` until it holds or ``timeout`` passes."""
    deadline = monotonic() + timeout
    while monotonic() < deadline:
        if condition():
            return True
        sleep(0.01)
    return condition()


class TestSilenceIsWhatExpires:
    def test_a_lapsed_lease_makes_the_scope_claimable(self, store: ScopeStore) -> None:
        walk = _walk(store)
        walk.claim()
        _age_the_lease(store, 60)

        assert is_expired(store.get_lease("wf"), datetime.now(UTC))
        assert derived_state(store.get_scope("wf")) == "abandoned"

    def test_renewing_keeps_the_scope(self, tmp_path: Path) -> None:
        """The heartbeat, and the reason the lease is not a step time limit.

        Without renewal a step slower than `DEFAULT_LEASE_SECONDS` would watch
        its own scope go claimable while it was still working, and another
        runner could take it. Renewing says "still here", so the lease measures
        **silence**, not duration. The step below ages its own lease until the
        scope reads `abandoned`; the walk, not this test, brings it back.
        """
        from functualize._engine.workflow_walker import WorkflowWalker
        from functualize._types.workflow import END, Edge, Step, WorkflowDeclaration

        store = ScopeStore(JsonFileSubstrate(tmp_path))
        aged_until: list[datetime] = []
        entered = Event()
        finish = Event()

        def run_step(name: str) -> str:
            _age_the_lease(store, 60, scope_id="kept")
            aged = store.get_lease("kept")
            assert aged is not None
            aged_until.append(datetime.fromisoformat(aged.expires_at))
            entered.set()
            assert finish.wait(5), "the blocked step was never released"
            return name

        walker = WorkflowWalker(
            WorkflowDeclaration(
                nodes=(Step("a"),), edges=(Edge(source="a", target=END),)
            ),
            store,
            "kept",
            run_step=run_step,
            runtime_store=port_for(store),
            _heartbeat_interval_seconds=0.02,
        )
        reports = []
        runner = Thread(target=lambda: reports.append(walker.run()))
        try:
            runner.start()
            assert entered.wait(5)
            assert _wait_for(
                lambda: (
                    derived_state(store.get_scope("kept")) == "running"
                    and not is_expired(store.get_lease("kept"), datetime.now(UTC))
                )
            ), "the walk never renewed the lease its step let lapse"
            renewed = store.get_lease("kept")
            assert renewed is not None
            assert datetime.fromisoformat(renewed.expires_at) > aged_until[0]
        finally:
            finish.set()
            runner.join(5)

        assert not runner.is_alive()
        assert reports[0].outcome.value == "completed"

    def test_renewal_does_not_move_the_generation(self, store: ScopeStore) -> None:
        """Or every heartbeat would fence the work it exists to protect."""
        walk = _walk(store)
        claimed = walk.claim()
        assert isinstance(claimed, Claimed)
        assert walk.renew() is RenewalOutcome.RENEWED
        assert store.get_lease("wf").generation == claimed.generation

    def test_renewing_after_being_superseded_does_not_raise(
        self, store: ScopeStore
    ) -> None:
        """The next *write* reports it, with the holder named.

        Raising from the heartbeat would surface the problem in the middle of a
        step that is still running perfectly well, and at a point where the walk
        has nothing useful to do about it.
        """
        walk = _walk(store)
        walk.claim()
        store.claim_scope("wf", owner="someone-else", force=True)

        assert walk.renew() is RenewalOutcome.SUPERSEDED

        from functualize._primitives.lease import StaleGenerationError

        with pytest.raises(StaleGenerationError):
            store.record_step("wf", "n1", {"status": "success"})

    def test_renewing_without_a_claim_is_harmless(self, store: ScopeStore) -> None:
        assert _walk(store).renew() is RenewalOutcome.NO_CLAIM

    def test_renewing_after_expiry_distinguishes_a_takeover(
        self, store: ScopeStore
    ) -> None:
        walk = _walk(store)
        walk.claim()
        _age_the_lease(store, 60)
        store.claim_scope("wf", owner="new-runner")

        assert walk.renew() is RenewalOutcome.SUPERSEDED

    def test_storage_failure_is_not_a_takeover(
        self, store: ScopeStore, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        walk = _walk(store)
        walk.claim()

        def fail_renewal(*args: object, **kwargs: object) -> None:
            raise OSError("storage unavailable")

        monkeypatch.setattr(store, "renew_scope", fail_renewal)
        assert walk.renew() is RenewalOutcome.TRANSIENT_ERROR


class TestTheWalkActuallyRenews:
    """The walker must renew while a node is still running."""

    def test_a_walk_renews_during_a_blocked_step(self, tmp_path: Path) -> None:
        from functualize._engine.workflow_walker import WorkflowWalker
        from functualize._types.workflow import (
            END,
            Edge,
            Step,
            WorkflowDeclaration,
        )

        store = ScopeStore(JsonFileSubstrate(tmp_path))
        declaration = WorkflowDeclaration(
            nodes=(Step("a"),), edges=(Edge(source="a", target=END),)
        )
        entered = Event()
        finish = Event()
        aged_until: list[datetime] = []

        def run_step(name: str) -> str:
            _age_the_lease(store, 60, scope_id="long-step")
            aged = store.get_lease("long-step")
            assert aged is not None
            aged_until.append(datetime.fromisoformat(aged.expires_at))
            entered.set()
            assert finish.wait(5), "the blocked step was never released"
            return name

        walker = WorkflowWalker(
            declaration,
            store,
            "long-step",
            run_step=run_step,
            runtime_store=port_for(store),
            _heartbeat_interval_seconds=0.02,
        )
        reports = []
        runner = Thread(target=lambda: reports.append(walker.run()))
        try:
            runner.start()
            assert entered.wait(5)

            def renewed_past_the_aged_expiry() -> bool:
                current = store.get_lease("long-step")
                return current is not None and (
                    datetime.fromisoformat(current.expires_at) > aged_until[0]
                )

            assert _wait_for(renewed_past_the_aged_expiry), (
                "the walk did not renew during its live step"
            )
            assert runner.is_alive(), "the step returned before the renewal"
            assert not is_expired(store.get_lease("long-step"), datetime.now(UTC))
        finally:
            finish.set()
            runner.join(5)

        assert not runner.is_alive()
        assert reports[0].outcome.value == "completed"
        assert not any(t.name == "lease-heartbeat:long-step" for t in live_threads())

    @pytest.mark.parametrize("exit_case", ["completion", "exception", "timeout"])
    def test_heartbeat_thread_stops_on_each_exit(
        self, tmp_path: Path, exit_case: str, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from functualize._engine.workflow_walker import WorkflowWalker
        from functualize._types.workflow import END, Edge, Step, WorkflowDeclaration

        store = ScopeStore(JsonFileSubstrate(tmp_path))
        scope_id = f"exit-{exit_case}"

        def run_step(name: str) -> str:
            if exit_case == "timeout":
                raise TimeoutError("step failed after waiting")
            return name

        walker = WorkflowWalker(
            WorkflowDeclaration(
                nodes=(Step("a"),), edges=(Edge(source="a", target=END),)
            ),
            store,
            scope_id,
            run_step=run_step,
            runtime_store=port_for(store),
            _heartbeat_interval_seconds=0.02,
        )
        if exit_case == "exception":

            def raise_outside_step() -> None:
                raise RuntimeError("walk setup failed")

            monkeypatch.setattr(
                walker, "_check_the_graph_has_not_changed", raise_outside_step
            )

        if exit_case == "exception":
            with pytest.raises(RuntimeError, match="walk setup failed"):
                walker.run()
        else:
            report = walker.run()
            assert report.outcome.value == (
                "failed" if exit_case == "timeout" else "completed"
            )

        assert not any(t.name == f"lease-heartbeat:{scope_id}" for t in live_threads())

    def test_a_taken_scope_has_no_normal_walk_end(self, tmp_path: Path) -> None:
        from functualize._engine.workflow_walker import WalkOutcome, WorkflowWalker
        from functualize._types.workflow import END, Edge, Step, WorkflowDeclaration

        store = ScopeStore(JsonFileSubstrate(tmp_path))
        entered = Event()
        finish = Event()
        renewal_saw_takeover = Event()
        events: list[str] = []

        def run_step(name: str) -> str:
            entered.set()
            assert finish.wait(5)
            return name

        walker = WorkflowWalker(
            WorkflowDeclaration(
                nodes=(Step("a"),), edges=(Edge(source="a", target=END),)
            ),
            store,
            "taken-step",
            run_step=run_step,
            runtime_store=port_for(store),
            emit=lambda action, **kwargs: events.append(action),
            _heartbeat_interval_seconds=0.02,
        )
        real_renew = walker._walk.renew

        def observe_takeover() -> RenewalOutcome:
            outcome = real_renew()
            if outcome is RenewalOutcome.SUPERSEDED:
                renewal_saw_takeover.set()
            return outcome

        walker._walk.renew = observe_takeover  # type: ignore[method-assign]
        reports = []
        runner = Thread(target=lambda: reports.append(walker.run()))
        try:
            runner.start()
            assert entered.wait(5)
            store.claim_scope("taken-step", owner="other", force=True)
            assert renewal_saw_takeover.wait(2)
        finally:
            finish.set()
            runner.join(5)

        assert not runner.is_alive()
        assert reports[0].outcome is WalkOutcome.SUPERSEDED
        assert "workflow.walk.end" not in events
        assert not any(t.name == "lease-heartbeat:taken-step" for t in live_threads())

    def test_the_lease_is_still_live_when_the_walk_ends(self, tmp_path: Path) -> None:
        """End to end, without reaching into the walker.

        A walk that renewed correctly and then released leaves an *expired*
        lease with its generation intact — released, not abandoned mid-flight.
        """
        from functualize._engine.workflow_walker import WorkflowWalker
        from functualize._types.workflow import (
            END,
            Edge,
            Step,
            WorkflowDeclaration,
        )

        store = ScopeStore(JsonFileSubstrate(tmp_path))
        declaration = WorkflowDeclaration(
            nodes=(Step("a"),), edges=(Edge(source="a", target=END),)
        )
        WorkflowWalker(
            declaration,
            store,
            "done",
            run_step=lambda name: name,
            runtime_store=port_for(store),
        ).run()

        lease = store.get_lease("done")
        assert lease is not None, "the walk deleted its lease instead of expiring it"
        assert lease.generation == 1


class TestItDoesNotClaimToStopTheWork:
    """AC-12. The part that makes this honest rather than a renamed lie."""

    def test_reclaim_reports_that_the_old_runner_was_not_stopped(
        self, store: ScopeStore
    ) -> None:
        walk = _walk(store)
        walk.claim(owner="the-slow-one")
        _age_the_lease(store, 60)

        result = reclaim_scope(store, "wf")

        assert result["work_not_stopped"] is True
        assert result["previous_owner"] == "the-slow-one"
        assert "not** stopped" in result["message"] or "not stopped" in result[
            "message"
        ].replace("**", "")

    def test_the_message_names_who_may_still_be_running(
        self, store: ScopeStore
    ) -> None:
        """ "Something may still be running" is not actionable; a name is."""
        walk = _walk(store)
        walk.claim(owner="host-7/pid-99")
        _age_the_lease(store, 60)

        assert "host-7/pid-99" in reclaim_scope(store, "wf")["message"]

    def test_reclaiming_a_never_claimed_scope_claims_nothing_about_work(
        self, store: ScopeStore
    ) -> None:
        """No previous holder means there is no live runner to warn about."""
        result = reclaim_scope(store, "wf")
        assert result["work_not_stopped"] is False
        assert "not stopped" not in result["message"]


class TestTheRejectedMechanismsStayRejected:
    """AC-13, asserted against the source.

    `exec_policy` researched these and refused them; a later change that
    quietly reintroduced one would restore exactly the failure this design
    exists to avoid — and a behavioural test cannot see the difference between
    "no timeout" and "a timeout implemented the forbidden way but not exercised
    here".
    """

    #: Names that must not be *called*. Matched against parsed code, never
    #: against the file's text — `exec_policy`'s own docstring explains why each
    #: was rejected, and a grep over source would flag the explanation as the
    #: violation. The first version of this test did exactly that and failed on
    #: the paragraph arguing for it.
    FORBIDDEN = {"alarm", "setitimer", "wait_for", "_async_raise"}

    def _calls_in(self, path: Path) -> set[str]:
        """Every attribute or function *called* in ``path``.

        AST, not text: a mention in prose is not a call, and the distinction is
        the whole difficulty here — this design is documented by describing the
        mechanisms it refuses.
        """
        import ast

        tree = ast.parse(path.read_text())
        names: set[str] = set()
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            if isinstance(func, ast.Attribute):
                names.add(func.attr)
            elif isinstance(func, ast.Name):
                names.add(func.id)
        return names

    def test_the_engine_calls_none_of_them(self) -> None:
        engine = Path(__file__).resolve().parents[2] / "src" / "functualize" / "_engine"
        offenders: dict[str, set[str]] = {}
        for path in engine.rglob("*.py"):
            hit = self._calls_in(path) & self.FORBIDDEN
            if hit:
                offenders[str(path.relative_to(engine))] = hit
        assert not offenders, (
            f"a rejected preemption mechanism is called: {offenders}. Python "
            f"cannot preempt a running function — a timeout built on one of "
            f"these reports that the work stopped while it continues, and a "
            f"caller who believes it may release a lock the still-live job is "
            f"using. See `_engine/exec_policy` §1."
        )

    def test_the_check_would_notice(self) -> None:
        """Guards the test above against matching nothing.

        An AST walk that silently found no calls would pass for every input.
        This asserts it sees a call that is definitely there.
        """
        engine = Path(__file__).resolve().parents[2] / "src" / "functualize" / "_engine"
        calls = self._calls_in(engine / "exec_policy.py")
        assert calls, "the AST walk found no calls at all in exec_policy.py"

    def test_the_lease_kills_nothing(self) -> None:
        """The lease module ends no process and stops no thread."""
        from functualize._primitives import lease

        assert DEFAULT_LEASE_SECONDS > 0
        calls = self._calls_in(Path(lease.__file__))
        assert not (calls & {"kill", "terminate", "killpg", "join", "cancel"}), (
            f"the lease module calls {calls & {'kill', 'terminate', 'killpg'}} "
            f"— an expired lease makes a scope claimable; it stops nothing"
        )
