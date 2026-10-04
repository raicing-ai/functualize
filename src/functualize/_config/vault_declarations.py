"""Explicit, scoped remote-secret declarations from parsed config files."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from functualize._config.manifest import parse_annotation
from functualize._primitives.vault_identity import VaultIdentity

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping

    from functualize._config.manifest import SourceAnnotation


class VaultDeclarationError(ValueError):
    """A declaration cannot safely identify one secret and its provider."""


@dataclass(frozen=True)
class VaultSecretDeclaration:
    """One provider source and its validated storage identity."""

    identity: VaultIdentity
    source: str
    location: str
    chain: tuple[SourceAnnotation, ...]


def parse_vault_declarations(
    per_file_values: Iterable[tuple[str, Mapping[str, Any]]],
) -> list[VaultSecretDeclaration]:
    """Read every block before any provider is contacted or vault is written.

    Parsing the individual files, instead of the merged config, retains both
    locations when two files declare the same identity.
    """
    declarations: list[VaultSecretDeclaration] = []
    locations: dict[VaultIdentity, str] = {}
    for path, config in per_file_values:
        blocks = config.get("vault_secret", [])
        if not isinstance(blocks, list):
            raise VaultDeclarationError(
                f"{path}: [[vault_secret]] must be an array of tables"
            )
        for number, block in enumerate(blocks, start=1):
            location = f"{path}: [[vault_secret]] #{number}"
            if not isinstance(block, dict):
                raise VaultDeclarationError(f"{location}: expected a table")
            group, job = block.get("group"), block.get("job")
            field, source = block.get("field"), block.get("source")
            if (group is None) == (job is None):
                raise VaultDeclarationError(
                    f"{location}: choose exactly one of group or job"
                )
            if set(block) - {"group", "job", "field", "source"}:
                raise VaultDeclarationError(
                    f"{location}: unsupported key in declaration"
                )
            if not all(
                isinstance(value, str) and value
                for value in (group if group is not None else job, field, source)
            ):
                raise VaultDeclarationError(
                    f"{location}: target, field, and source must be nonempty strings"
                )
            assert isinstance(field, str) and isinstance(source, str)
            target = group if group is not None else job
            assert isinstance(target, str)
            try:
                identity = VaultIdentity(
                    "group" if group is not None else "job", target, field
                )
                chain = parse_annotation(source)
            except ValueError as exc:
                raise VaultDeclarationError(
                    f"{location}: invalid provider source"
                ) from exc
            if not chain:
                raise VaultDeclarationError(
                    f"{location}: source must use provider://reference syntax"
                )
            if identity in locations:
                raise VaultDeclarationError(
                    f"{location}: duplicate secret identity also declared in {locations[identity]}"
                )
            locations[identity] = location
            declarations.append(
                VaultSecretDeclaration(identity, source, location, tuple(chain))
            )
    return declarations
