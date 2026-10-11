"""Scoped declarations remain distinct across config files."""

from __future__ import annotations

import pytest

from functualize._config.vault_declarations import (
    VaultDeclarationError,
    parse_vault_declarations,
)
from functualize._primitives.vault_identity import VaultIdentity


def test_two_scopes_with_the_same_text_are_distinct() -> None:
    parsed = parse_vault_declarations(
        [
            (
                "config.base.toml",
                {
                    "vault_secret": [
                        {"group": "deploy", "field": "token", "source": "fake-sm://a"},
                        {"job": "deploy", "field": "token", "source": "fake-sm://b"},
                    ]
                },
            )
        ]
    )
    assert [item.identity for item in parsed] == [
        VaultIdentity("group", "deploy", "token"),
        VaultIdentity("job", "deploy", "token"),
    ]
    assert [item.chain[0].reference for item in parsed] == ["a", "b"]


@pytest.mark.parametrize(
    "block",
    [
        {"group": "deploy", "job": "deploy", "field": "token", "source": "fake-sm://a"},
        {"field": "token", "source": "fake-sm://a"},
        {"job": "deploy", "source": "fake-sm://a"},
        {"job": "deploy", "field": "token", "source": "literal"},
        {"job": "deploy", "field": "token", "source": "fake-sm://a", "value": "unsafe"},
    ],
)
def test_malformed_blocks_fail_with_location(block: dict[str, str]) -> None:
    with pytest.raises(VaultDeclarationError, match="config.base.toml"):
        parse_vault_declarations([("config.base.toml", {"vault_secret": [block]})])


def test_duplicate_across_files_fails_before_merge() -> None:
    block = {"job": "deploy", "field": "token", "source": "fake-sm://a"}
    with pytest.raises(VaultDeclarationError, match="config.base.toml") as exc:
        parse_vault_declarations(
            [
                ("config.base.toml", {"vault_secret": [block]}),
                ("config.dev.toml", {"vault_secret": [block]}),
            ]
        )
    assert "config.dev.toml" in str(exc.value)


def test_ordinary_sections_are_not_declarations() -> None:
    assert (
        parse_vault_declarations(
            [("config.base.toml", {"deploy": {"endpoint": "https://example.com"}})]
        )
        == []
    )
