"""Explicit, scoped remote-secret declarations from parsed config files."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from functualize._config.manifest import parse_annotation
from functualize._config.roles import BASE_SLOT, parse_slot
from functualize._primitives.vault_identity import VaultIdentity

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping

    from functualize._config.manifest import SourceAnnotation


_VAULT_SECRET_SECTION = "vault_secret"
_GROUP = "group"
_JOB = "job"
_FIELD = "field"
_SOURCE = "source"
_VAULT_SECRET_FIELDS = frozenset({_GROUP, _JOB, _FIELD, _SOURCE})


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
        slot = parse_slot(path)
        environment = None if slot is None or slot.casefold() == BASE_SLOT else slot
        blocks = config.get(_VAULT_SECRET_SECTION, [])
        if not isinstance(blocks, list):
            raise VaultDeclarationError(
                f"{path}: [[vault_secret]] must be an array of tables"
            )
        for number, block in enumerate(blocks, start=1):
            location = f"{path}: [[vault_secret]] #{number}"
            if not isinstance(block, dict):
                raise VaultDeclarationError(f"{location}: expected a table")
            group, job = block.get(_GROUP), block.get(_JOB)
            field, source = block.get(_FIELD), block.get(_SOURCE)
            if group is None and job is None:
                raise VaultDeclarationError(
                    f"{location}: supply group, job, or both group and job"
                )
            if set(block) - _VAULT_SECRET_FIELDS:
                raise VaultDeclarationError(
                    f"{location}: unsupported key in declaration"
                )
            if (
                not isinstance(field, str)
                or not field
                or not isinstance(source, str)
                or not source
                or any(
                    not isinstance(value, str) or not value
                    for value in (group, job)
                    if value is not None
                )
            ):
                raise VaultDeclarationError(
                    f"{location}: target, field, and source must be nonempty strings"
                )
            if isinstance(job, str) and "." in job:
                raise VaultDeclarationError(
                    f"{location}: job must be a leaf name; use group and job separately "
                    "(for example --group deploy --job web)"
                )
            assert isinstance(field, str) and isinstance(source, str)
            target = (
                f"{group}.{job}"
                if group is not None and job is not None
                else group
                if group is not None
                else job
            )
            assert isinstance(target, str)
            try:
                identity = VaultIdentity(
                    "job" if job is not None else "group", target, field, environment
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
