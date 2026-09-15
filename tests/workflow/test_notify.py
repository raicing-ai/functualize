"""A notification is a target and an effect, and nothing else.

`workflow-graph-semantics`/T6. Spec AC-13, AC-14. Decision **N8**, risk **R-f**.

Two properties, and the second is the one that keeps growing back.

**It fires at most once** (AC-13). The record that a notification fired is
committed *before* the provider is called — `Step(effecting=True)`'s outbox rule,
applied to an effect that is not a step — so a crash can lose one and can never
send one twice. The asymmetry is deliberate and it runs this way round: a
resumed workflow must not page the on-call again for a failure they have already
seen. The *crash* half of that lives in
`tests/integration/test_notify_exactly_once.py`, because only a real `kill -9`
can test it; what is here is the half a unit test can hold.

**It is not a bus** (AC-14, N8). `to` is carried from the declaration to the
provider and nothing in between reads it — no routing, no fan-out, no retry, no
dead-letter queue. Each of those is the *first field* of a broker, so
`TestToIsOpaque` asserts the one property that keeps them all out: whatever was
declared is what arrives, byte for byte, including strings nothing could parse.

And core registers **nothing**, which is why `TestAnUndeliverableNotifyIsRefused`
exists: a declaration that silently delivered nowhere is indistinguishable from
one that worked, until the day it matters.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from pydantic import BaseModel

from functualize._engine.notify import LogNotifier, NotifierRegistry
from functualize._engine.notify_providers import (
    CORE_NOTIFIERS,
    NOTIFY_PROVIDERS,
    missing_notifier_hint,
)
from functualize._engine.workflow_walker import WorkflowWalker
from functualize._primitives.scope_store import ScopeStore
from functualize._primitives.substrate import JsonFileSubstrate
from functualize._types.errors import NotifierUnavailableError
from functualize._types.protocols import Notifier
from functualize._types.workflow import (
    END,
    Edge,
    Gate,
    Notification,
    Notify,
    Step,
    WorkflowDeclaration,
)
from functualize.workflow._validation import _validate_workflow_graph


class _Ask(BaseModel):
    text: str


class _Recorder:
    """A notifier that remembers, and optionally refuses."""

    def __init__(self, name: str = "recorder", *, raises: bool = False) -> None:
        self.name = name
        self.raises = raises
        self.sent: list[Notification] = []

    def deliver(self, notification: Notification) -> None:
        self.sent.append(notification)
        if self.raises:
            raise RuntimeError("the mail server is down")


@pytest.fixture
def store(tmp_path: Path) -> ScopeStore:
    return ScopeStore(JsonFileSubstrate(tmp_path))


def _registry(*notifiers: object) -> NotifierRegistry:
    registry = NotifierRegistry()
    for notifier in notifiers:
        registry.register(notifier)
    return registry


def _graph(*notify: Notify, fail: bool = False) -> WorkflowDeclaration:
    return WorkflowDeclaration(
        nodes=(Step("first"), Step("second")),
        edges=(
            Edge(source="first", target="second"),
            Edge(source="second", target=END),
        ),
        notify=notify,
    )


def _blocking(*notify: Notify) -> WorkflowDeclaration:
    return WorkflowDeclaration(
        nodes=(Step("first"), Gate(name="approval", awaits=_Ask)),
        edges=(
            Edge(source="first", target="approval"),
            Edge(source="approval", target=END),
        ),
        notify=notify,
    )


def _walk(
    store: ScopeStore,
    declaration: WorkflowDeclaration,
    registry: NotifierRegistry | None,
    *,
    scope_id: str = "s1",
    failing: str = "",
) -> Any:
    def run_step(name: str) -> str:
        if name == failing:
            raise RuntimeError(f"{name} blew up")
        return name

    return WorkflowWalker(
        declaration,
        store,
        scope_id,
        run_step=run_step,
        notifiers=registry,
    ).run()


# ----------------------------------------------------------------------
# The declaration
# ----------------------------------------------------------------------


class TestTheDeclaration:
    def test_it_refuses_a_state_no_walk_can_end_in(self) -> None:
        with pytest.raises(ValueError, match="must be one of"):
            Notify(on="nearly-done", to="ops")

    def test_it_refuses_an_empty_target(self) -> None:
        with pytest.raises(ValueError, match="non-empty"):
            Notify(on="failed", to="   ")

    @pytest.mark.parametrize("state", ["completed", "failed", "blocked", "cancelled"])
    def test_every_status_a_walk_writes_can_be_notified_on(self, state: str) -> None:
        """The vocabulary is the one the walk writes, not the derived one.

        `_types` imports nothing internal, so the richer display set is out of
        reach — and copying it would be a fifth spelling of a list that has to
        agree exactly. These four are what a scope's `status` can hold.
        """
        assert Notify(on=state, to="ops").on == state

    def test_the_key_is_the_content_not_the_position(self) -> None:
        """A workflow that gains a second `Notify` must not make the first one
        fire again by shifting an index."""
        first = Notify(on="failed", to="ops")
        assert Notify(on="failed", to="ops").key == first.key
        assert Notify(on="failed", to="someone-else").key != first.key
        assert Notify(on="completed", to="ops").key != first.key
        assert Notify(on="failed", to="ops", provider="mail").key != first.key

    def test_the_validator_refuses_a_non_notify(self) -> None:
        """Reached directly, because every other test here hands a
        `WorkflowDeclaration` to the walker and never sees the validator at all
        — the blind spot `workflow-graph-semantics`/T2 found the hard way.
        """
        with pytest.raises(TypeError, match="must be Notify"):
            _validate_workflow_graph(
                [Step("a")], [Edge(source="a", target=END)], ["failed"]
            )


# ----------------------------------------------------------------------
# The registry
# ----------------------------------------------------------------------


class TestTheRegistry:
    def test_core_ships_a_notifier_and_registers_nothing(self) -> None:
        """The decision `_app.boot` makes for `cli-prompt`, made again.

        A default registration makes the refusal unreachable, and a workflow
        whose "page the on-call on failure" quietly became a debug line is
        worse than one that refuses to start.
        """
        assert isinstance(LogNotifier(), Notifier)
        assert NotifierRegistry().names() == ()

    def test_it_refuses_something_that_is_not_a_notifier(self) -> None:
        with pytest.raises(TypeError, match="must satisfy Notifier"):
            NotifierRegistry().register(object())

    def test_it_refuses_a_second_registration_of_one_name(self) -> None:
        registry = _registry(_Recorder())
        with pytest.raises(ValueError, match="already registered"):
            registry.register(_Recorder())

    def test_a_lone_notifier_needs_no_naming(self) -> None:
        recorder = _Recorder()
        assert _registry(recorder).resolve(Notify(on="failed", to="ops")) is recorder

    def test_two_notifiers_and_no_name_is_refused(self) -> None:
        """Nothing is guessed. Picking a deliverer the declaration did not name
        is how a page becomes a log line."""
        registry = _registry(_Recorder("a"), _Recorder("b"))
        with pytest.raises(NotifierUnavailableError, match="names no notifier"):
            registry.resolve(Notify(on="failed", to="ops"))

    def test_an_unknown_name_names_what_is_registered(self) -> None:
        registry = _registry(_Recorder("a"))
        with pytest.raises(NotifierUnavailableError, match="registered: a"):
            registry.resolve(Notify(on="failed", to="ops", provider="nope"))

    def test_a_known_provider_gets_its_install_hint(self) -> None:
        with pytest.raises(NotifierUnavailableError, match="Install functualize-http"):
            NotifierRegistry().resolve(
                Notify(on="failed", to="https://x", provider="webhook")
            )

    def test_the_table_names_core_without_an_install_hint(self) -> None:
        for name in CORE_NOTIFIERS:
            assert NOTIFY_PROVIDERS[name] == "functualize"
            assert missing_notifier_hint(name) == ""


class TestAnUndeliverableNotifyIsRefused:
    """Before the walk, which is the whole point of checking at all.

    Discovering at the end of a long run that its notification was never
    deliverable is the one moment the fault is least recoverable — the work is
    done and the person who needed telling has not been told.
    """

    def test_check_refuses_a_declaration_nothing_can_deliver(self) -> None:
        with pytest.raises(NotifierUnavailableError):
            NotifierRegistry().check(_graph(Notify(on="failed", to="ops")))

    def test_check_passes_a_declaration_that_can(self) -> None:
        _registry(_Recorder()).check(_graph(Notify(on="failed", to="ops")))

    def test_a_graph_with_no_notifications_needs_no_notifier(self) -> None:
        NotifierRegistry().check(_graph())


# ----------------------------------------------------------------------
# The walk
# ----------------------------------------------------------------------


class TestTheWalkDelivers:
    def test_a_completed_walk_notifies_on_completed(self, store: ScopeStore) -> None:
        recorder = _Recorder()
        _walk(store, _graph(Notify(on="completed", to="ops")), _registry(recorder))

        assert [n.status for n in recorder.sent] == ["completed"]
        assert recorder.sent[0].scope_id == "s1"

    def test_a_failed_walk_notifies_on_failed_and_names_the_node(
        self, store: ScopeStore
    ) -> None:
        recorder = _Recorder()
        _walk(
            store,
            _graph(Notify(on="failed", to="ops")),
            _registry(recorder),
            failing="second",
        )

        assert [n.status for n in recorder.sent] == ["failed"]
        assert recorder.sent[0].node == "second"

    def test_a_blocked_walk_notifies_on_blocked(self, store: ScopeStore) -> None:
        recorder = _Recorder()
        _walk(store, _blocking(Notify(on="blocked", to="ops")), _registry(recorder))
        assert [n.status for n in recorder.sent] == ["blocked"]

    def test_a_notification_for_another_state_stays_silent(
        self, store: ScopeStore
    ) -> None:
        recorder = _Recorder()
        _walk(store, _graph(Notify(on="failed", to="ops")), _registry(recorder))
        assert recorder.sent == []

    def test_with_no_registry_nothing_is_delivered(self, store: ScopeStore) -> None:
        """A walker built by hand — which is every other test in this suite."""
        report = _walk(store, _graph(Notify(on="completed", to="ops")), None)
        assert report.outcome.value == "completed"


class TestItFiresAtMostOnce:
    def test_a_second_walk_of_the_same_scope_does_not_repeat_it(
        self, store: ScopeStore
    ) -> None:
        """The half of AC-13 a unit test can hold. The crash half is in
        `tests/integration/test_notify_exactly_once.py`."""
        recorder = _Recorder()
        declaration = _blocking(Notify(on="blocked", to="ops"))

        _walk(store, declaration, _registry(recorder))
        _walk(store, declaration, _registry(recorder))

        assert len(recorder.sent) == 1, [n.status for n in recorder.sent]

    def test_another_scope_of_the_same_workflow_gets_its_own(
        self, store: ScopeStore
    ) -> None:
        """The guard on the test above: "fires once" must mean once **per
        scope**, not once per process."""
        recorder = _Recorder()
        declaration = _blocking(Notify(on="blocked", to="ops"))

        _walk(store, declaration, _registry(recorder), scope_id="a")
        _walk(store, declaration, _registry(recorder), scope_id="b")

        assert {n.scope_id for n in recorder.sent} == {"a", "b"}

    def test_the_record_is_written_before_the_provider_is_called(
        self, store: ScopeStore
    ) -> None:
        """The outbox rule, and the direction it fails in.

        The notifier here crashes the way a process does — by never returning
        normally — and the assertion is that the scope already carries the mark
        anyway. Written afterwards, a crash inside `deliver` would leave no mark
        and the resume would send it again.
        """
        seen: list[bool] = []

        class _Peeking:
            name = "peek"

            def deliver(self, notification: Notification) -> None:
                scope = store.get_scope(notification.scope_id) or {}
                seen.append(
                    any("notify" in key for key in (scope.get("branches") or {}))
                )
                raise RuntimeError("crashed mid-delivery")

        _walk(store, _blocking(Notify(on="blocked", to="ops")), _registry(_Peeking()))

        assert seen == [True], (
            "the delivery was attempted before the record committed, so a "
            "crash inside it would send the notification twice"
        )

    def test_a_notifier_that_raises_does_not_fail_the_walk(
        self, store: ScopeStore
    ) -> None:
        """A notification is an account *of* what happened. Letting it change
        what happened would report a workflow as failed because a mail server
        was down."""
        recorder = _Recorder(raises=True)
        report = _walk(
            store, _graph(Notify(on="completed", to="ops")), _registry(recorder)
        )

        assert report.outcome.value == "completed"
        assert store.get_scope("s1")["status"] == "completed"
        assert len(recorder.sent) == 1


class TestTheRunnerRefusesBeforeTheWalk:
    """`check` is called, not merely available.

    `TestAnUndeliverableNotifyIsRefused` calls the registry directly, which
    proves the check works and nothing about whether anybody runs it. This
    reaches `WorkflowRunner.prelude` — the one point every continuation passes
    through — for the reason that docstring already gives about the cancelled
    scope: a check a caller can skip by not calling it is not a rule.
    """

    def test_prelude_refuses_an_undeliverable_declaration(
        self, store: ScopeStore
    ) -> None:
        from functualize._engine.workflow_runner import WorkflowRunner

        runner = WorkflowRunner(
            store,
            run_step=lambda name: name,
            scope_id="s1",
            notifiers=NotifierRegistry(),
        )
        with pytest.raises(NotifierUnavailableError):
            runner.prelude("flow", _graph(Notify(on="failed", to="ops")))

    def test_prelude_runs_a_declaration_it_can_deliver(self, store: ScopeStore) -> None:
        """The guard: the refusal must be about the notifier, not about
        everything."""
        from functualize._engine.workflow_runner import WorkflowRunner

        runner = WorkflowRunner(
            store,
            run_step=lambda name: name,
            scope_id="s1",
            notifiers=_registry(_Recorder()),
        )
        assert runner.prelude("flow", _graph(Notify(on="failed", to="ops"))) is not None


class TestTheStatusComesFromTheScope:
    """Not from `WalkOutcome`, which is a different vocabulary.

    `WalkOutcome.FAILED` covers both a failure and a cancellation (T4), so a
    notification read off the report would page "failed" for a workflow somebody
    deliberately stopped — the exact confusion T4 exists to end, reintroduced
    one layer up.
    """

    @staticmethod
    def _cancelling(*notify: Notify) -> WorkflowDeclaration:
        return WorkflowDeclaration(
            nodes=(Step("first"),),
            edges=(Edge(source="first", target=END),),
            notify=notify,
        )

    def _walk_cancelled(
        self, store: ScopeStore, registry: NotifierRegistry, *notify: Notify
    ) -> None:
        from functualize._types.errors import ScopeCancelledError

        def run_step(name: str) -> str:
            raise ScopeCancelledError("s1::first", workflow="child")

        WorkflowWalker(
            self._cancelling(*notify),
            store,
            "s1",
            run_step=run_step,
            notifiers=registry,
        ).run()

    def test_a_cancelled_walk_notifies_on_cancelled(self, store: ScopeStore) -> None:
        recorder = _Recorder()
        self._walk_cancelled(
            store, _registry(recorder), Notify(on="cancelled", to="ops")
        )
        assert [n.status for n in recorder.sent] == ["cancelled"]

    def test_it_does_not_notify_on_failed(self, store: ScopeStore) -> None:
        recorder = _Recorder()
        self._walk_cancelled(store, _registry(recorder), Notify(on="failed", to="ops"))
        assert recorder.sent == [], (
            "a cancellation paged the on-call as a failure — the status was "
            "read from WalkOutcome rather than from the scope"
        )


class TestTheWiringIsReal:
    """The test that would fail if the registry reached nothing.

    Every other test here hands a `NotifierRegistry` to the walker by hand, so
    all of them pass with the engine wired to nothing — a declared `Notify`
    silently delivering nowhere on every real run, which is precisely the
    failure this port exists to make impossible. This one registers through
    `app.extensions.register_notifier` and runs a real `@workflow`.
    """

    def test_a_real_run_delivers_through_the_registered_notifier(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from functualize._app.state import AppState
        from functualize.app.core import FunctualizeApp
        from functualize.types import RunRequest
        from functualize.workflow import workflow

        project = tmp_path / "project"
        (project / ".functualize").mkdir(parents=True)
        monkeypatch.chdir(project)

        AppState.reset()
        recorder = _Recorder("recorder")
        app = FunctualizeApp(name="notified")
        app.register_dynamic_job("work", lambda: "done")

        @workflow(
            steps=[Step("work")],
            edges=[Edge(source="work", target=END)],
            notify=[Notify(on="completed", to="ops@example.com")],
        )
        def release() -> str:
            return "released"

        app.register_dynamic_job("release", release)
        app.extensions.register_notifier(recorder)
        try:
            app.execute(
                RunRequest(
                    job_name="release",
                    surface="app.execute",
                    workflow_scope_id="rel-1",
                )
            )
        finally:
            AppState.reset()

        assert [n.to for n in recorder.sent] == ["ops@example.com"]
        assert recorder.sent[0].scope_id == "rel-1"
        assert recorder.sent[0].status == "completed"

    def test_an_unregistered_notifier_refuses_the_run(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The other half: with nothing registered the run must not succeed
        quietly, because that is what a notification going nowhere looks like.

        It **raises**, like `AgentExecutorUnavailableError` does, and reaches a
        surface as a refusal: `click_params._refusals_become_exits` maps it to
        exit 3 beside the two agent-step refusals, for the same reason — the
        declaration asked for something no registration can supply, so nothing
        ran and nothing failed.
        """
        from functualize._app.state import AppState
        from functualize.app.core import FunctualizeApp
        from functualize.types import RunRequest
        from functualize.workflow import workflow

        project = tmp_path / "project"
        (project / ".functualize").mkdir(parents=True)
        monkeypatch.chdir(project)

        AppState.reset()
        app = FunctualizeApp(name="unnotified")
        app.register_dynamic_job("work", lambda: "done")

        @workflow(
            steps=[Step("work")],
            edges=[Edge(source="work", target=END)],
            notify=[Notify(on="completed", to="ops@example.com")],
        )
        def release() -> str:
            return "released"

        app.register_dynamic_job("release", release)
        try:
            with pytest.raises(NotifierUnavailableError):
                app.execute(
                    RunRequest(
                        job_name="release",
                        surface="app.execute",
                        workflow_scope_id="rel-2",
                    )
                )
        finally:
            AppState.reset()


class TestToIsOpaque:
    """N8. The one property that keeps every broker feature out.

    Whatever was declared is what arrives. Nothing splits it, matches it,
    expands it or validates its shape — so there is nowhere for a routing rule
    to attach itself later without this failing first.
    """

    @pytest.mark.parametrize(
        "target",
        [
            "ops@example.com",
            "#incidents",
            "https://hooks.example/x?a=1&b=2",
            "a,b,c",
            "{{not a template}}",
            "  spaces inside  ",
        ],
    )
    def test_whatever_was_declared_arrives(
        self, store: ScopeStore, target: str
    ) -> None:
        recorder = _Recorder()
        _walk(store, _graph(Notify(on="completed", to=target)), _registry(recorder))
        assert [n.to for n in recorder.sent] == [target]

    def test_a_comma_separated_target_is_one_target(self, store: ScopeStore) -> None:
        """Not two. The moment `to` fans out, this is a broker."""
        recorder = _Recorder()
        _walk(store, _graph(Notify(on="completed", to="a,b")), _registry(recorder))
        assert len(recorder.sent) == 1
