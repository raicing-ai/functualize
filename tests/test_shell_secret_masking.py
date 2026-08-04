"""Tests for secret masking (S2/T11): the shared redaction utility and its
application in the Shell capability's command echo (§B.6).
"""

from __future__ import annotations

import pytest

from functualize._engine.capabilities.shell import WiredShell
from functualize._types.redaction import (
    MASK,
    Secret,
    collect_secret_values,
    redact,
    reveal,
)
from functualize.testing import FakeShell
from functualize.types import Secret as PublicSecret


@pytest.fixture
def sh() -> WiredShell:
    return WiredShell()


class TestSecretType:
    def test_str_and_repr_are_masked(self) -> None:
        s = Secret("hunter2")
        assert str(s) == MASK
        assert MASK in repr(s)
        assert "hunter2" not in repr(s)
        assert "hunter2" not in f"the token is {s}"

    def test_get_secret_value_returns_real(self) -> None:
        assert Secret("hunter2").get_secret_value() == "hunter2"

    def test_equality_by_value(self) -> None:
        assert Secret("a") == Secret("a")
        assert Secret("a") != Secret("b")
        assert Secret("a") != "a"  # a bare str is never a Secret

    def test_hashable(self) -> None:
        assert {Secret("a"), Secret("a")} == {Secret("a")}

    def test_subscriptable_for_annotations(self) -> None:
        # Secret[str] must be usable as a type annotation at runtime.
        alias = Secret[str]
        assert alias is not None

    def test_public_export_is_same_type(self) -> None:
        assert PublicSecret is Secret


class TestRedactionPrimitives:
    def test_reveal_unwraps_secret(self) -> None:
        assert reveal(Secret("x")) == "x"

    def test_reveal_stringifies_plain(self) -> None:
        assert reveal(42) == "42"

    def test_collect_gathers_only_secrets(self) -> None:
        assert collect_secret_values([Secret("a"), "b", Secret("c")]) == {"a", "c"}

    def test_collect_skips_empty_secret(self) -> None:
        assert collect_secret_values([Secret("")]) == set()

    def test_redact_replaces_all_occurrences(self) -> None:
        assert redact("a x a x", {"x"}) == f"a {MASK} a {MASK}"

    def test_redact_longer_secret_first(self) -> None:
        # "abcd" must be masked whole, not partially via "ab".
        assert redact("abcd", {"ab", "abcd"}) == MASK

    def test_redact_ignores_empty(self) -> None:
        assert redact("abc", {""}) == "abc"

    def test_redact_no_secrets_is_identity(self) -> None:
        assert redact("abc", set()) == "abc"


class TestShellCommandMasking:
    def test_template_secret_runs_real_but_masks_echo(self, sh: WiredShell) -> None:
        r = sh("echo {token}", token=Secret("s3cr3t-value"))
        # Runs with the real value...
        assert r.stdout.strip() == "s3cr3t-value"
        # ...but the echoed command hides it.
        assert "s3cr3t-value" not in r.command
        assert MASK in r.command

    def test_list_secret_runs_real_but_masks_echo(self, sh: WiredShell) -> None:
        r = sh(["echo", Secret("topsecret")])  # type: ignore[list-item]
        assert r.stdout.strip() == "topsecret"
        assert "topsecret" not in r.command
        assert MASK in r.command

    def test_secret_with_spaces_masked(self, sh: WiredShell) -> None:
        r = sh("echo {token}", token=Secret("two words"))
        assert r.stdout.strip() == "two words"
        assert "two words" not in r.command
        assert MASK in r.command

    def test_env_secret_reaches_process_but_not_echo(self, sh: WiredShell) -> None:
        r = sh(
            'printf "%s" "$MYTOKEN"',
            shell=True,
            env={"MYTOKEN": Secret("env-secret")},  # type: ignore[dict-item]
        )
        assert r.stdout == "env-secret"  # the child saw the real value
        assert "env-secret" not in r.command

    def test_plain_value_is_not_masked(self, sh: WiredShell) -> None:
        r = sh("echo {msg}", msg="plainvalue")
        assert "plainvalue" in r.command


class TestFakeShellSecret:
    def test_fake_reveals_secret_for_matching(self) -> None:
        from functualize.job import ShellResult

        fake = FakeShell(
            {"deploy topsecret": ShellResult(0, "ok", "", "deploy topsecret", 1.0)}
        )
        r = fake(["deploy", Secret("topsecret")])  # type: ignore[list-item]
        assert r.stdout == "ok"
        assert fake.calls[0].argv == ["deploy", "topsecret"]
