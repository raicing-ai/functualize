"""Shared secret-redaction utility (proposal §B.6).

One redaction module, consumed by every layer that echoes user-supplied values
back into logs, perf reports, event payloads, or the TUI. The Shell capability
is its first consumer (S2); the core remote-source-activation work consumes the
same module (maintainer direction, 2026-07-19) — so it lives in ``_types``, the
lowest layer, importable by ``_engine``, ``_config``, and the public re-exports
alike.

Two mechanisms mark a value as secret:

- **:class:`Secret`** — an explicit wrapper (``Secret("token")`` or the
  ``Secret[str]`` annotation) whose ``str``/``repr`` render as :data:`MASK`, so
  it cannot leak through an accidental f-string. Call
  :meth:`Secret.get_secret_value` to obtain the real value at the point of use.
- Config fields declared secret (handled by the config consumer, which wraps
  their resolved values in :class:`Secret`).

The redaction primitives are pure and stdlib-only: :func:`reveal` unwraps a
value for actual use, :func:`collect_secret_values` gathers the real strings to
hide, and :func:`redact` masks every occurrence of them in arbitrary text.
"""

from __future__ import annotations

import types
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Iterable

MASK = "•••"
"""The placeholder that replaces a secret in any rendered text (§B.6)."""


class Secret:
    """A string value marked secret — masked in every string rendering (§B.6).

    ``str(secret)`` and ``repr(secret)`` return :data:`MASK`; the real value is
    only reachable through :meth:`get_secret_value`, so a secret dropped into an
    f-string, a log line, or a traceback shows ``•••`` rather than leaking.

    ``Secret[str]`` is accepted as a type annotation (via ``__class_getitem__``)
    so config authors can write ``token: Secret[str]``.
    """

    __slots__ = ("_value",)

    def __init__(self, value: Any) -> None:
        self._value = str(value)

    def get_secret_value(self) -> str:
        """Return the real, unmasked value for use at a trusted call site."""
        return self._value

    def __str__(self) -> str:
        return MASK

    def __repr__(self) -> str:
        return f"Secret({MASK!r})"

    def __eq__(self, other: object) -> bool:
        if isinstance(other, Secret):
            return self._value == other._value
        return NotImplemented

    def __hash__(self) -> int:
        return hash(self._value)

    def __class_getitem__(cls, item: Any) -> types.GenericAlias:
        return types.GenericAlias(cls, item)


def reveal(value: Any) -> str:
    """Return the real string for ``value`` — unwrapping a :class:`Secret`.

    Use this at the trusted boundary where a value is actually consumed (e.g.
    building an argv or an env dict); pair it with :func:`redact` on whatever
    text is rendered back to a human.
    """
    if isinstance(value, Secret):
        return value.get_secret_value()
    return str(value)


def collect_secret_values(values: Iterable[Any]) -> set[str]:
    """Gather the real strings of every :class:`Secret` in ``values``.

    Non-secret and empty values are skipped. The result feeds :func:`redact`.
    """
    secrets: set[str] = set()
    for value in values:
        if isinstance(value, Secret):
            real = value.get_secret_value()
            if real:
                secrets.add(real)
    return secrets


def redact(text: str, secrets: Iterable[str]) -> str:
    """Replace every occurrence of each secret in ``text`` with :data:`MASK`.

    Longer secrets are masked first so a secret that contains another is not
    partially exposed. Empty secrets are ignored (they would match everywhere).
    """
    for secret in sorted((s for s in secrets if s), key=len, reverse=True):
        text = text.replace(secret, MASK)
    return text


#: Nesting depth beyond which a snapshot stops descending.
_MAX_DEPTH = 6


def redacted_snapshot(value: Any, *, _depth: int = 0) -> Any:
    """A JSON-safe view of ``value`` with every secret replaced by :data:`MASK`.

    Used for anything that records what a job was *actually given* — step
    records in the state store, and from there the workflow state an external
    agent reads over MCP. Both are written to disk and handed to a third
    party, so a resolved config that still held a token would leak it twice
    over.

    Two secret markers are honored (§B.6, contracts §2): a :class:`Secret`
    value anywhere, and a model field flagged
    ``Field(json_schema_extra={"secret": True})``. The second marker has no
    other implementation yet; it is checked here anyway, because the cost is
    two lines and the failure mode is a silently leaked credential.

    Anything not JSON-representable degrades to ``repr`` rather than raising —
    a record that cannot be written is worse than one that says
    ``<Connection object at 0x…>``.
    """
    if isinstance(value, Secret):
        return MASK
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if _depth >= _MAX_DEPTH:
        return repr(value)

    dump = getattr(value, "model_dump", None)
    fields = getattr(type(value), "model_fields", None)
    if callable(dump) and isinstance(fields, dict):
        return {
            name: (
                MASK
                if is_secret_field(fields[name])
                else redacted_snapshot(getattr(value, name, None), _depth=_depth + 1)
            )
            for name in fields
        }

    if isinstance(value, dict):
        return {
            str(key): redacted_snapshot(item, _depth=_depth + 1)
            for key, item in value.items()
        }
    if isinstance(value, (list, tuple, set, frozenset)):
        return [redacted_snapshot(item, _depth=_depth + 1) for item in value]
    return repr(value)


def is_secret_field(field_info: Any) -> bool:
    """True when a Pydantic field is marked secret by annotation or by flag.

    Public because more than one sink has to agree on it: this decides both
    whether a recorded value is masked and whether a *prompt* for that value is
    masked (T45). Two independent answers to "is this a secret" is how a field
    gets redacted in state.json and then echoed to the screen while being typed.
    """
    annotation = getattr(field_info, "annotation", None)
    if annotation is Secret or getattr(annotation, "__origin__", None) is Secret:
        return True
    extra = getattr(field_info, "json_schema_extra", None)
    return bool(isinstance(extra, dict) and extra.get("secret"))
