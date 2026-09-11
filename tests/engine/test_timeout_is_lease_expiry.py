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

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from functualize._engine.frontier import FrontierWalk, GraphModel
from functualize._primitives.lease import DEFAULT_LEASE_SECONDS, is_expired
from functualize._primitives.scope_store import ScopeStore
from functualize._primitives.substrate import JsonFileSubstrate
from functualize.app._workflow_control import reclaim_scope
from functualize.app._workflow_view import derived_state


@pytest.fixture
def store(tmp_path: Path) -> ScopeStore:
    s = ScopeStore(JsonFileSubstrate(tmp_path))
    s.ensure_scope("wf", "demo")
    s.set_scope_status("wf", "running")
    return s


def _walk(store: ScopeStore) -> FrontierWalk:
    return FrontierWalk(GraphModel(entry="n1"), store, "wf")


def _age_the_lease(store: ScopeStore, seconds: float) -> None:
    """Move the lease's expiry into the past by ``seconds``."""
    scope = store.get_scope("wf")
    past = (datetime.now(UTC) - timedelta(seconds=seconds)).isoformat()
    lease = {**scope["lease"], "expires_at": past}
    store._mutate(  # noqa: SLF001
        lambda env: env["scopes"]["wf"].__setitem__("lease", lease)
    )


class TestSilenceIsWhatExpires:
    def test_a_lapsed_lease_makes_the_scope_claimable(self, store: ScopeStore) -> None:
        walk = _walk(store)
        walk.claim()
        _age_the_lease(store, 60)

        assert is_expired(store.get_lease("wf"), datetime.now(UTC))
        assert derived_state(store.get_scope("wf")) == "abandoned"

    def test_renewing_keeps_the_scope(self, store: ScopeStore) -> None:
        """The heartbeat, and the reason the lease is not a step time limit.

        Without renewal a step slower than `DEFAULT_LEASE_SECONDS` would watch
        its own scope go claimable while it was still working, and another
        runner could take it. Renewing says "still here", so the lease measures
        **silence**, not duration.
        """
        walk = _walk(store)
        walk.claim()
        _age_the_lease(store, 60)
        assert derived_state(store.get_scope("wf")) == "abandoned"

        walk.renew()

        assert not is_expired(store.get_lease("wf"), datetime.now(UTC))
        assert derived_state(store.get_scope("wf")) == "running"

    def test_renewal_does_not_move_the_generation(self, store: ScopeStore) -> None:
        """Or every heartbeat would fence the work it exists to protect."""
        walk = _walk(store)
        generation = walk.claim()
        walk.renew()
        assert store.get_lease("wf").generation == generation

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

        walk.renew()  # must not raise

        from functualize._primitives.lease import StaleGenerationError

        with pytest.raises(StaleGenerationError):
            store.record_step("wf", "n1", {"status": "success"})

    def test_renewing_without_a_claim_is_harmless(self, store: ScopeStore) -> None:
        _walk(store).renew()


class TestTheWalkActuallyRenews:
    """The wiring, which the rest of this file did not reach.

    Every other test here calls `walk.renew()` directly, so they all pass with
    the walker's call to it deleted — verified by sabotage, which changed
    nothing. A method that is correct and never called is the shape
    `contributor/guides/wiring-discipline.md` exists for, and the lease would
    have expired under every long workflow while the unit tests stayed green.
    """

    def test_a_walk_renews_at_each_node_boundary(self, tmp_path: Path) -> None:
        from functualize._engine.workflow_walker import WorkflowWalker
        from functualize._types.workflow import (
            END,
            Edge,
            Step,
            WorkflowDeclaration,
        )

        store = ScopeStore(JsonFileSubstrate(tmp_path))
        declaration = WorkflowDeclaration(
            nodes=(Step("a"), Step("b")),
            edges=(Edge(source="a", target="b"), Edge(source="b", target=END)),
        )
        walker = WorkflowWalker(
            declaration, store, "renewed", run_step=lambda name: name
        )

        renewals: list[str] = []
        real_renew = walker._walk.renew

        def _counting() -> None:
            renewals.append("renewed")
            real_renew()

        walker._walk.renew = _counting  # type: ignore[method-assign]
        walker.run()

        assert len(renewals) >= 2, (
            f"the walk renewed {len(renewals)} times across two nodes — a step "
            f"slower than the lease would lose its scope while still working"
        )

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
        WorkflowWalker(declaration, store, "done", run_step=lambda name: name).run()

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
