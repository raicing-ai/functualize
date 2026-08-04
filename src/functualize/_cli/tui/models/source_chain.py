"""Shared model for "a key resolved through an ordered source chain".

Job config and TUI settings are the same abstract shape: a set of keys, each
resolved through an ordered chain of sources, where exactly one source wins.
Modelling that once lets the Config Files panel and the Settings panel share a
single Detail view instead of each growing its own.

The key distinction from the kernel's own chain model is **specificity**: a
``source_id`` here is always concrete (``"file:/etc/config.dev.toml"``,
``"env:FUNCTUALIZE_TUI_THEME"``, ``"default"``), never a generic bucket like
``"File"``. Without that, a Detail view cannot say *which* file contributed a
value, which is the entire point of the screen.

This module is in the ``_cli/`` layer — stdlib only, no kernel imports.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from functualize._cli.data.config_target import ConfigTarget

__all__ = [
    "NOT_SET",
    "ResolvedKey",
    "SourceChainProvider",
    "SourceEntry",
]


class _NotSet:
    """Sentinel: this source has no opinion about this key.

    Distinct from the empty string, which is a real value a user can set.
    """

    _instance: _NotSet | None = None

    def __new__(cls) -> _NotSet:
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __bool__(self) -> bool:
        return False

    def __repr__(self) -> str:
        return "NOT_SET"


NOT_SET = _NotSet()


@dataclass(frozen=True)
class SourceEntry:
    """One source's contribution to one key."""

    source_id: str
    """Concrete identity, e.g. ``"file:/p/config.dev.toml"``, ``"default"``."""

    label: str
    """Human-facing name for the Detail view, e.g. ``"config.dev.toml"``."""

    value: str | _NotSet = NOT_SET
    """The value this source contributes, or ``NOT_SET`` if it defines none."""

    writable: bool = False
    """Whether the Detail view may stage edits against this source."""

    precedence: int = 0
    """Higher wins. Ordering only — the absolute numbers carry no meaning."""

    @property
    def is_set(self) -> bool:
        """Whether this source actually contributes a value."""
        return not isinstance(self.value, _NotSet)

    @property
    def display_value(self) -> str:
        """The value as text, or an em-dash placeholder when unset."""
        return str(self.value) if self.is_set else "—"


@dataclass
class ResolvedKey:
    """A single key and every source that has an opinion about it."""

    name: str
    chain: list[SourceEntry] = field(default_factory=list)
    """All sources, ordered lowest precedence first."""

    description: str = ""
    type_hint: str = "str"
    """Declared type, used to emit correctly-typed TOML on save."""

    choices: list[str] | None = None
    """Valid values, if constrained — drives INSERT-mode autocomplete."""

    @property
    def winning(self) -> SourceEntry | None:
        """The highest-precedence source that actually sets a value."""
        candidates = [e for e in self.chain if e.is_set]
        if not candidates:
            return None
        return max(candidates, key=lambda e: e.precedence)

    @property
    def effective_value(self) -> str:
        """The value that actually takes effect, or empty if nothing sets it."""
        winner = self.winning
        return str(winner.value) if winner is not None else ""

    @property
    def winning_source_id(self) -> str:
        """The ``source_id`` of the winning source, or empty if none."""
        winner = self.winning
        return winner.source_id if winner is not None else ""

    def entry_for(self, source_id: str) -> SourceEntry | None:
        """Look up one source's entry by its concrete id."""
        for entry in self.chain:
            if entry.source_id == source_id:
                return entry
        return None

    def is_overridden(self, source_id: str) -> bool:
        """Whether this source sets a value but loses to a higher one."""
        entry = self.entry_for(source_id)
        if entry is None or not entry.is_set:
            return False
        return entry.source_id != self.winning_source_id


@runtime_checkable
class SourceChainProvider(Protocol):
    """What the Detail view needs from a domain to render and save it.

    Implemented by ``JobConfigChainProvider`` (job config, backed by the
    kernel's chain plus per-file provenance) and ``FuncSettingsChainProvider``
    (`func`'s settings, backed by ``FuncSettingsStore`` over the real config
    files). The Detail view knows only this Protocol, which is what lets one
    widget serve every panel.

    Writes are addressed by ``source_id`` rather than by a ``ConfigTarget``:
    a ``source_id`` already names a concrete destination, so the provider can
    map it to a path itself. Carrying a second identity for the same thing
    only creates a way for the two to disagree. ``target_for`` exists for the
    cases that genuinely need the richer display object.
    """

    def resolve(self) -> list[ResolvedKey]:
        """Re-read every source and return the current resolution."""
        ...

    def target_for(self, source_id: str) -> ConfigTarget | None:
        """Describe the destination behind ``source_id``, if it is writable."""
        ...

    def write(
        self,
        source_id: str,
        edits: dict[str, str],
        removals: set[str],
    ) -> None:
        """Persist staged changes to ``source_id``'s destination atomically."""
        ...

    def apply_live(self, edits: dict[str, str]) -> None:
        """Apply saved values to the running app.

        A no-op for job config (nothing is live until the job runs); for TUI
        settings this is where a new theme actually takes effect.
        """
        ...
