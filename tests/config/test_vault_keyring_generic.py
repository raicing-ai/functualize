"""The generic adapter never reads for a run; only `vault unlock` reads, in the foreground."""

from __future__ import annotations

from functualize._config.vault_keyring import AdapterOutcome, UnlockHow
from functualize._config.vault_keyring_generic import GenericAdapter
from tests.contracts._fake_platforms import Answer, FakeUnknownBackend, Recorder, World

_SECRET = "34" * 32


def _adapter(world: World, recorder: Recorder) -> GenericAdapter:
    return GenericAdapter(
        "functualize-vault",
        "vault-key",
        backend=FakeUnknownBackend(world, _SECRET, recorder),
    )


class TestARunNeverReads:
    def test_even_an_unlocked_backend_is_not_read(self) -> None:
        """Silence cannot be proven, so the run is refused rather than risked."""
        recorder = Recorder()
        read = _adapter(World.UNLOCKED, recorder).read_silent()
        assert read.outcome is AdapterOutcome.UNVERIFIED
        assert recorder.secret_reads == 0
        assert recorder.prompts == 0


class TestUnlockReadsInTheForeground:
    def test_an_answered_prompt_finds_the_key(self) -> None:
        recorder = Recorder(answer=Answer.ACCEPT)
        read = _adapter(World.LOCKED, recorder).unlock()
        assert read.outcome is AdapterOutcome.FOUND
        assert read.secret == _SECRET
        assert recorder.prompts == 1

    def test_a_cancelled_prompt_is_cancelled(self) -> None:
        read = _adapter(World.LOCKED, Recorder(answer=Answer.CANCEL)).unlock()
        assert read.outcome is AdapterOutcome.LOCKED
        assert read.how is UnlockHow.CANCELLED

    def test_nothing_stored_is_not_stored(self) -> None:
        assert (
            _adapter(World.EMPTY, Recorder()).unlock().outcome
            is AdapterOutcome.NOT_STORED
        )
