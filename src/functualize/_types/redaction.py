"""Shared secret-redaction utility (proposal §B.6).

One redaction module, consumed by every layer that echoes user-supplied values
back into logs, perf reports, event payloads, or the TUI. The Shell capability
is its first consumer (S2); the core remote-source-activation work consumes the
same module (maintainer direction, 2026-07-19) — so it lives in ``_types``, the
lowest layer, importable by ``_engine``, ``_config``, and the public re-exports
alike.

Two mechanisms mark a value as secret, and :func:`is_secret_field` is the single
answer that reconciles them:

- **:class:`Secret`** — an explicit wrapper (``Secret("token")`` or the
  ``Secret[str]`` annotation) whose ``str``/``repr`` render as :data:`MASK`, so
  it cannot leak through an accidental f-string. Call
  :meth:`Secret.get_secret_value` to obtain the real value at the point of use.
  As a Pydantic annotation it validates a plain ``str`` into a ``Secret`` and
  serializes back to :data:`MASK`, so the wrapping happens in the model rather
  than in a config consumer.
- **``Field(json_schema_extra={"secret": True})``** — for a field that must stay
  a plain ``str``. The declaration masks it in every *display* sink; the
  executor additionally feeds its resolved value to output redaction, so the
  marker is not merely cosmetic.

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

    ``Secret[str]`` is a usable Pydantic field type: it accepts a plain ``str``
    from any source (config file, environment, CLI) and wraps it, so a config
    author writes ``token: Secret[str]`` and gets a value that is masked
    everywhere without needing ``arbitrary_types_allowed``.
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

    # ── Pydantic integration ────────────────────────────────────────────────
    # Both hooks import pydantic *inside* the method. This module sits in the
    # lowest layer and is imported by nearly everything; a module-level pydantic
    # import would put it on every cold-start path for a hook that only ever
    # runs while Pydantic is building a schema.

    @classmethod
    def __get_pydantic_core_schema__(cls, source: Any, handler: Any) -> Any:
        """Accept a plain ``str`` (or an existing ``Secret``) and wrap it.

        Without this, ``token: Secret[str]`` on a plain ``BaseModel`` raises
        ``PydanticSchemaGenerationError`` at class-definition time, and the job
        declaring it disappears from ``func`` with only a warning on stderr —
        so the framework's own public secret type could not be used in the
        framework's own config models.

        The serializer is as load-bearing as the validator: it makes
        ``model_dump()`` mask by default, so a resolved config cannot leak
        through a JSON path that never reaches :func:`redacted_snapshot`.
        """
        from pydantic_core import core_schema

        return core_schema.no_info_after_validator_function(
            cls._validate,
            core_schema.union_schema(
                [
                    core_schema.is_instance_schema(cls),
                    core_schema.str_schema(),
                ]
            ),
            serialization=core_schema.plain_serializer_function_ser_schema(
                lambda _: MASK,
                return_schema=core_schema.str_schema(),
            ),
        )

    @classmethod
    def __get_pydantic_json_schema__(cls, schema: Any, handler: Any) -> Any:
        """Emit ``{"secret": true}`` so the marker survives into the cache.

        The TUI panels mask from the *cached* ``FieldDescriptor``, which is
        built by reading ``model_json_schema()`` — a warm boot never imports the
        config model. Without this hook, ``Secret[str]`` would mask in
        ``info --job`` (which has the live ``FieldInfo``) and leak in the TUI
        (which does not). This is what keeps the annotation and the
        ``json_schema_extra`` flag one mechanism rather than two that happen to
        agree in :func:`is_secret_field`.
        """
        from pydantic_core import core_schema

        json_schema = handler(core_schema.str_schema())
        json_schema["secret"] = True
        return json_schema

    @classmethod
    def _validate(cls, value: Any) -> Secret:
        """Normalize an accepted value to a ``Secret`` instance."""
        return value if isinstance(value, cls) else cls(value)


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


def is_secret_annotation(annotation: Any) -> bool:
    """True when ``annotation`` is :class:`Secret` or ``Secret[T]``.

    Split out of :func:`is_secret_field` so the two callers that hold a bare
    annotation rather than a Pydantic ``FieldInfo`` — the signature-scanning
    discovery path, and anything unwrapping ``Annotated`` — ask the same
    question in the same words. A second hand-rolled ``is X or origin is X``
    check elsewhere is how the answers start to differ.
    """
    return annotation is Secret or getattr(annotation, "__origin__", None) is Secret


def is_secret_field(field_info: Any) -> bool:
    """True when a Pydantic field is marked secret by annotation or by flag.

    Public because more than one sink has to agree on it: this decides both
    whether a recorded value is masked and whether a *prompt* for that value is
    masked (T45). Two independent answers to "is this a secret" is how a field
    gets redacted in state.json and then echoed to the screen while being typed.
    """
    if is_secret_annotation(getattr(field_info, "annotation", None)):
        return True
    extra = getattr(field_info, "json_schema_extra", None)
    return bool(isinstance(extra, dict) and extra.get("secret"))
