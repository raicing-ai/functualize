"""The contract every keyring adapter keeps, on every platform (spec B9, A15).

One suite, parametrized over :data:`~tests.contracts._fake_platforms.HARNESSES`,
so a new adapter is held to the same rules the day it is registered. The rule
that matters most is the first: **a silent read never requests an unlock
prompt**, in any world. A run reads silently; a prompt a run later abandons can
crash the keyring daemon and re-lock every keyring the user has. Storing is
held to the same rule, so ``unlock()`` is the only call that may prompt.
"""

from __future__ import annotations

import time

import pytest

from functualize._config.vault_keyring import (
    AdapterOutcome,
    KeyringAdapter,
    UnlockHow,
)
from functualize._types.enums import KeyAvailability
from tests.contracts._fake_platforms import (
    HARNESSES,
    Answer,
    Harness,
    Recorder,
    World,
)

_SECRET = "ab" * 32
_OTHER = "cd" * 32

#: Product names a user-facing name must not carry (spec A18).
_PRODUCTS = ("gnome", "kwallet", "keychain", "credential manager", "secret service")


def _cases(*worlds: World) -> list[object]:
    return [
        pytest.param(harness, world, id=f"{harness.name}-{world.value}")
        for harness in HARNESSES
        for world in worlds
        if world in harness.worlds
    ]


def _build(
    harness: Harness, world: World, answer: Answer = Answer.ACCEPT
) -> tuple[KeyringAdapter, Recorder]:
    recorder = Recorder(answer=answer)
    return harness.build(world, _SECRET, recorder), recorder


@pytest.mark.parametrize("harness", HARNESSES, ids=lambda h: h.name)
class TestTheShape:
    def test_it_satisfies_the_port(self, harness: Harness) -> None:
        adapter, _ = _build(harness, World.UNLOCKED)
        assert isinstance(adapter, KeyringAdapter)

    def test_its_name_is_neutral(self, harness: Harness) -> None:
        adapter, _ = _build(harness, World.UNLOCKED)
        assert adapter.name
        assert not any(product in adapter.name.lower() for product in _PRODUCTS)


class TestASilentReadNeverPrompts:
    @pytest.mark.parametrize(
        ("harness", "world"),
        _cases(World.UNLOCKED, World.LOCKED, World.EMPTY, World.ABSENT),
    )
    def test_no_prompt_in_any_world(self, harness: Harness, world: World) -> None:
        adapter, recorder = _build(harness, world)
        adapter.read_silent()
        assert recorder.prompts == 0

    @pytest.mark.parametrize(("harness", "world"), _cases(World.LOCKED))
    def test_a_locked_keyring_is_reported_not_opened(
        self, harness: Harness, world: World
    ) -> None:
        adapter, recorder = _build(harness, world)
        read = adapter.read_silent()
        expected = (
            AdapterOutcome.LOCKED
            if harness.proves_silence
            else AdapterOutcome.UNVERIFIED
        )
        assert read.outcome is expected
        assert read.secret is None
        assert recorder.secret_reads == 0

    @pytest.mark.parametrize(("harness", "world"), _cases(World.UNLOCKED))
    def test_an_unlocked_keyring_is_read(self, harness: Harness, world: World) -> None:
        adapter, _ = _build(harness, world)
        read = adapter.read_silent()
        if harness.proves_silence:
            assert read.outcome is AdapterOutcome.FOUND
            assert read.secret == _SECRET
        else:
            assert read.outcome is AdapterOutcome.UNVERIFIED
            assert read.secret is None

    @pytest.mark.parametrize(("harness", "world"), _cases(World.EMPTY))
    def test_nothing_stored_is_not_stored(self, harness: Harness, world: World) -> None:
        adapter, _ = _build(harness, world)
        expected = (
            AdapterOutcome.NOT_STORED
            if harness.proves_silence
            else AdapterOutcome.UNVERIFIED
        )
        assert adapter.read_silent().outcome is expected

    @pytest.mark.parametrize(("harness", "world"), _cases(World.ABSENT))
    def test_no_backend_is_no_keyring(self, harness: Harness, world: World) -> None:
        adapter, _ = _build(harness, world)
        assert adapter.read_silent().outcome is AdapterOutcome.NO_KEYRING

    @pytest.mark.parametrize(("harness", "world"), _cases(World.UNLOCKED))
    def test_the_secret_never_appears_in_the_repr(
        self, harness: Harness, world: World
    ) -> None:
        adapter, _ = _build(harness, world)
        assert _SECRET not in repr(adapter.read_silent())


class TestStateAgreesAndNeverPrompts:
    @pytest.mark.parametrize(
        ("harness", "world"),
        _cases(World.UNLOCKED, World.LOCKED, World.EMPTY, World.ABSENT),
    )
    def test_state_agrees_with_the_world(self, harness: Harness, world: World) -> None:
        adapter, recorder = _build(harness, world)
        state = adapter.state()
        assert recorder.prompts == 0
        assert recorder.secret_reads == 0
        if not harness.proves_silence or world is World.ABSENT:
            assert state is KeyAvailability.UNKNOWN
        elif world is World.LOCKED:
            assert state is KeyAvailability.LOCKED
        else:
            assert state is KeyAvailability.UNLOCKED

    @pytest.mark.parametrize(("harness", "world"), _cases(World.HUNG))
    def test_a_hung_backend_costs_at_most_its_bound(
        self, harness: Harness, world: World
    ) -> None:
        adapter, recorder = _build(harness, world)
        started = time.monotonic()
        state = adapter.state()
        assert time.monotonic() - started < 2.0
        assert state is KeyAvailability.UNKNOWN
        assert recorder.prompts == 0


class TestStoringNeverPrompts:
    """`vault init` stores through this, so creating a key cannot open a dialog."""

    @pytest.mark.parametrize(
        ("harness", "world"),
        _cases(World.UNLOCKED, World.LOCKED, World.EMPTY, World.ABSENT),
    )
    def test_no_prompt_in_any_world(self, harness: Harness, world: World) -> None:
        adapter, recorder = _build(harness, world)
        adapter.store_silent(_OTHER)
        assert recorder.prompts == 0

    @pytest.mark.parametrize(("harness", "world"), _cases(World.EMPTY))
    def test_a_stored_key_is_then_read_silently(
        self, harness: Harness, world: World
    ) -> None:
        adapter, _ = _build(harness, world)
        stored = adapter.store_silent(_OTHER)
        if harness.proves_silence:
            assert stored is AdapterOutcome.FOUND
            read = adapter.read_silent()
            assert read.outcome is AdapterOutcome.FOUND
            assert read.secret == _OTHER
        else:
            assert stored is AdapterOutcome.UNVERIFIED

    @pytest.mark.parametrize(("harness", "world"), _cases(World.LOCKED))
    def test_a_locked_keyring_is_not_written(
        self, harness: Harness, world: World
    ) -> None:
        adapter, _ = _build(harness, world)
        expected = (
            AdapterOutcome.LOCKED
            if harness.proves_silence
            else AdapterOutcome.UNVERIFIED
        )
        assert adapter.store_silent(_OTHER) is expected
        assert adapter.read_silent().secret is None

    @pytest.mark.parametrize(("harness", "world"), _cases(World.ABSENT))
    def test_no_backend_is_no_keyring(self, harness: Harness, world: World) -> None:
        adapter, _ = _build(harness, world)
        assert adapter.store_silent(_OTHER) is AdapterOutcome.NO_KEYRING


class TestUnlockIsTheOnlyPrompt:
    @pytest.mark.parametrize(("harness", "world"), _cases(World.LOCKED))
    def test_an_answered_dialog_unlocks_and_reads(
        self, harness: Harness, world: World
    ) -> None:
        adapter, recorder = _build(harness, world, Answer.ACCEPT)
        read = adapter.unlock()
        assert recorder.prompts == 1
        assert read.outcome is AdapterOutcome.FOUND
        assert read.secret == _SECRET
        if harness.proves_silence:
            assert read.how is UnlockHow.UNLOCKED_NOW
            # Unlocked now, so a later run reads silently.
            assert adapter.read_silent().outcome is AdapterOutcome.FOUND

    @pytest.mark.parametrize(("harness", "world"), _cases(World.LOCKED))
    def test_a_cancelled_dialog_stays_locked(
        self, harness: Harness, world: World
    ) -> None:
        adapter, recorder = _build(harness, world, Answer.CANCEL)
        read = adapter.unlock()
        assert recorder.prompts == 1
        assert read.outcome is not AdapterOutcome.FOUND
        assert read.secret is None
        if harness.proves_silence:
            assert read.how is UnlockHow.CANCELLED

    @pytest.mark.parametrize(
        ("harness", "world"),
        [
            case
            for case in _cases(World.LOCKED)
            if case.values[0].detects_missing_prompt  # type: ignore[attr-defined]
        ],
    )
    def test_a_dialog_that_never_appears_is_reported(
        self, harness: Harness, world: World
    ) -> None:
        adapter, _ = _build(harness, world, Answer.NO_DIALOG)
        read = adapter.unlock()
        assert read.outcome is AdapterOutcome.LOCKED
        assert read.how is UnlockHow.NO_PROMPT

    @pytest.mark.parametrize(("harness", "world"), _cases(World.UNLOCKED))
    def test_an_unlocked_keyring_needs_no_prompt(
        self, harness: Harness, world: World
    ) -> None:
        adapter, recorder = _build(harness, world)
        read = adapter.unlock()
        assert read.outcome is AdapterOutcome.FOUND
        if harness.proves_silence:
            assert recorder.prompts == 0
            assert read.how in (UnlockHow.ALREADY_UNLOCKED, UnlockHow.NOTHING_TO_UNLOCK)

    @pytest.mark.parametrize(("harness", "world"), _cases(World.ABSENT))
    def test_no_backend_has_nothing_to_unlock(
        self, harness: Harness, world: World
    ) -> None:
        adapter, recorder = _build(harness, world)
        assert adapter.unlock().outcome is AdapterOutcome.NO_KEYRING
        assert recorder.prompts == 0
