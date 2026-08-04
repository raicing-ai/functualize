"""C1b.1 — `InputMode` + `InputModeRegistry`.

Type-only: no widget work, no shell mode. Pulled ahead of C1.6 because C1.6
restructures completion dispatch *onto* this registry (the ordering the Phase-C
scrutiny corrected).
"""

from __future__ import annotations

import pytest

from functualize.plugin import DEFAULT_SIGIL, InputMode, InputModeRegistry


def _mode(sigil: str, name: str) -> InputMode:
    return InputMode(
        sigil=sigil,
        name=name,
        candidate_source=lambda text, cursor: [f"{name}:{text}@{cursor}"],
        is_ready=lambda text: bool(text),
        submit=lambda text: None,
        history_namespace=name,
    )


@pytest.fixture
def registry() -> InputModeRegistry:
    reg = InputModeRegistry()
    reg.register(_mode(DEFAULT_SIGIL, "command"))
    reg.register(_mode("!", "shell"))
    return reg


class TestResolve:
    def test_plain_text_is_the_default_mode(self, registry) -> None:
        assert registry.resolve("deploy --env prod").name == "command"

    def test_sigil_selects_its_mode(self, registry) -> None:
        assert registry.resolve("!ls -la").name == "shell"

    def test_empty_text_is_the_default_mode(self, registry) -> None:
        assert registry.resolve("").name == "command"

    def test_unregistered_sigil_falls_back_to_default(self, registry) -> None:
        """`?` is not registered here, so it is ordinary command text."""
        assert registry.resolve("?what").name == "command"

    def test_no_default_registered_returns_none(self) -> None:
        reg = InputModeRegistry()
        reg.register(_mode("!", "shell"))
        assert reg.resolve("plain") is None
        assert reg.resolve("!ls").name == "shell"


class TestSigilUniqueness:
    def test_duplicate_sigil_is_rejected(self, registry) -> None:
        with pytest.raises(ValueError, match="already registered"):
            registry.register(_mode("!", "other"))

    def test_duplicate_default_is_rejected(self, registry) -> None:
        with pytest.raises(ValueError, match="already registered"):
            registry.register(_mode(DEFAULT_SIGIL, "other-command"))

    def test_multichar_sigil_is_rejected(self) -> None:
        """Dispatch reads exactly one character, so two would never match."""
        reg = InputModeRegistry()
        with pytest.raises(ValueError, match="single character"):
            reg.register(_mode("!!", "bad"))

    def test_error_names_both_modes(self, registry) -> None:
        with pytest.raises(ValueError) as exc:
            registry.register(_mode("!", "other"))
        assert "shell" in str(exc.value)
        assert "other" in str(exc.value)


class TestStripSigil:
    def test_sigil_is_removed(self) -> None:
        assert _mode("!", "shell").strip_sigil("!ls -la") == "ls -la"

    def test_default_mode_is_a_noop(self) -> None:
        assert _mode(DEFAULT_SIGIL, "command").strip_sigil("deploy") == "deploy"

    def test_text_without_the_sigil_is_untouched(self) -> None:
        assert _mode("!", "shell").strip_sigil("ls") == "ls"


class TestDeclaredSlot:
    """A mode may be registered without a widget — the "declared slot".

    Contracts §6: `?` is reserved by registering a mode whose behavior raises,
    so the sigil is claimed and visible in `resolve()` before anything is built.
    """

    def test_reserved_mode_resolves_but_refuses_to_run(self) -> None:
        def _unbuilt(*args: object) -> None:
            raise NotImplementedError("the '?' mode is reserved, not implemented")

        reg = InputModeRegistry()
        reg.register(_mode(DEFAULT_SIGIL, "command"))
        reg.register(
            InputMode(
                sigil="?",
                name="ask",
                candidate_source=_unbuilt,  # type: ignore[arg-type]
                is_ready=lambda text: False,
                submit=_unbuilt,
                history_namespace="ask",
            )
        )

        mode = reg.resolve("?what is this")
        assert mode is not None
        assert mode.name == "ask"
        with pytest.raises(NotImplementedError):
            mode.submit("what is this")

    def test_reserving_a_sigil_blocks_a_later_claim(self) -> None:
        reg = InputModeRegistry()
        reg.register(_mode("?", "ask"))
        with pytest.raises(ValueError, match="already registered"):
            reg.register(_mode("?", "something-else"))


class TestRegistryIntrospection:
    def test_sigils_lists_default_first(self, registry) -> None:
        assert registry.sigils[0] == DEFAULT_SIGIL

    def test_contains_and_len(self, registry) -> None:
        assert "!" in registry
        assert DEFAULT_SIGIL in registry
        assert "?" not in registry
        assert len(registry) == 2

    def test_get_returns_the_mode(self, registry) -> None:
        assert registry.get("!").name == "shell"
        assert registry.get("?") is None


class TestModeCarriesItsOwnBehavior:
    """The point of the type: three answers travel together."""

    def test_candidates_readiness_and_history_are_per_mode(self, registry) -> None:
        shell = registry.resolve("!ls")
        command = registry.resolve("deploy")

        assert shell.candidate_source("ls", 2) == ["shell:ls@2"]
        assert command.candidate_source("deploy", 6) == ["command:deploy@6"]
        assert shell.history_namespace != command.history_namespace
        assert shell.is_ready("ls") is True
        assert shell.is_ready("") is False
