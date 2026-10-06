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

    def __post_init__(self) -> None:
        if self.scope not in ("group", "job"):
            raise ValueError(f"Unknown vault scope: {self.scope!r}")
        if not self.target or not self.field:
            raise ValueError("Vault target and field must both be nonempty")

    def encode(self) -> str:
        """Return the SQLite key and AES-GCM associated data spelling."""
        return json.dumps(
            [self.scope, self.target, self.field],
            ensure_ascii=False,
            separators=(",", ":"),
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
            or len(parts) != 3
            or not all(isinstance(part, str) for part in parts)
        ):
            raise ValueError("Invalid scoped vault identity")
        return cls(parts[0], parts[1], parts[2])
