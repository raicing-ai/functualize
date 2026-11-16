"""Unambiguous storage identity for one scoped vault secret."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Literal

VaultScope = Literal["group", "job"]

#: The environment name that addresses **shared** entries (SD/12779576): as
#: ``config.base.*`` applies to every environment, an entry written under
#: ``FUNCTUALIZE_ENV=base`` serves every environment. Matches
#: ``_config.roles.BASE_SLOT`` by rule, not by import — ``_primitives`` imports
#: nothing internal — and a test pins the two equal.
SHARED_SLOT = "base"


def _slot(environment: str | None) -> str | None:
    """Fold an environment name to its stored slot; ``None`` is shared."""
    if environment is None:
        return None
    folded = environment.strip().casefold()
    return None if folded == SHARED_SLOT else folded


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
            # `base` is the shared slot, so it is stored as no environment —
            # the one spelling put, remove, inspect, reads and declarations use.
            object.__setattr__(self, "environment", _slot(self.environment))

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
        active = _slot(environment)
        # Under SHARED_SLOT the active slot *is* shared: consult it once.
        slots = (active, None) if active is not None else (None,)
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
