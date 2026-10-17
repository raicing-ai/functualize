"""Unambiguous storage identity for one scoped vault secret."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Literal

VaultScope = Literal["group", "job"]


@dataclass(frozen=True)
class VaultIdentity:
    """A group option or job config field, independent of dotted path parsing."""

    scope: VaultScope
    target: str
    field: str
    environment: str | None = None

    def __post_init__(self) -> None:
        if self.scope not in ("group", "job"):
            raise ValueError(f"Unknown vault scope: {self.scope!r}")
        if not self.target or not self.field:
            raise ValueError("Vault target and field must both be nonempty")
        if self.environment is not None:
            if not isinstance(self.environment, str) or not self.environment.strip():
                raise ValueError("Vault environment must be a nonempty string")
            object.__setattr__(self, "environment", self.environment.strip().casefold())

    def encode(self) -> str:
        """Return the SQLite key and AES-GCM associated data spelling."""
        parts = [self.scope, self.target, self.field]
        if self.environment is not None:
            parts.append(self.environment)
        return json.dumps(
            parts,
            ensure_ascii=False,
            separators=(",", ":"),
        )

    @classmethod
    def lookup_candidates(
        cls, scope: VaultScope, target: str, field: str, environment: str | None
    ) -> tuple[VaultIdentity, ...]:
        """Try active entries before shared entries, nearest group first."""
        if scope not in ("group", "job"):
            raise ValueError(f"Unknown vault scope: {scope!r}")
        targets: tuple[str, ...] = (target,)
        if scope == "group":
            parts = target.split(".")
            targets = tuple(".".join(parts[:end]) for end in range(len(parts), 0, -1))
        slots = (environment, None) if environment is not None else (None,)
        return tuple(
            cls(scope, candidate, field, slot)
            for slot in slots
            for candidate in targets
        )

    @classmethod
    def decode(cls, key: str) -> VaultIdentity:
        """Reject malformed and pre-scope keys instead of guessing their scope."""
        try:
            parts = json.loads(key)
        except (TypeError, ValueError) as exc:
            raise ValueError("Invalid scoped vault identity") from exc
        if (
            not isinstance(parts, list)
            or len(parts) not in (3, 4)
            or not all(isinstance(part, str) for part in parts)
        ):
            raise ValueError("Invalid scoped vault identity")
        return cls(*parts)
