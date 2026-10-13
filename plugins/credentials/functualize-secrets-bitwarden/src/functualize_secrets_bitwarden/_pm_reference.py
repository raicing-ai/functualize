"""The ``bwpm://`` reference grammar.

::

    bwpm://<item>/<field>
    bwpm://<item-uuid>/<field>
    bwpm://<item>/field:<custom-name>

One item, one field, and a field that is never defaulted
--------------------------------------------------------

``<item>`` is a Password Manager item addressed by its **uuid** — one
``bw get item`` call — or by its **exact name**, which lists the vault and
matches. ``<field>`` is one of the five built-in slots (``password``,
``username``, ``totp``, ``notes``, ``uri``) or ``field:<name>`` for a custom
field by exact name. There is no default field: ``bwpm://deploy-token`` does
not mean the password, it means nothing — an item alone does not say which of
its values a config file wants, and guessing the obvious one would resolve a
config file differently from what its author read on the screen when they
wrote it.

An unknown field is an error, not a no-op. A caller who writes
``bwpm://item/api-key`` has stated an intent; quietly resolving under a
different one is the defect this rule exists to remove. A bare custom name
gets a close-match suggestion pointing at the ``field:`` prefix, because the
two spellings differ by six characters a reader can unsee once shown.

No query string
---------------

The sibling ``bws://`` grammar carries ``?project=``/``?organization=``
overrides because a Secrets Manager key name under-specifies where to search.
An item name here is unambiguous within the vault the session can see, and
the shape decision fixes server selection to the ``bw`` CLI's own
configuration — so there is nothing for a query to override, and any ``?`` is
refused rather than ignored. A query-looking suffix that sat in a config file
doing nothing is the same silent no-op the unknown-field rule exists to
prevent, and it is worse for being spelled correctly.

No percent-decoding
-------------------

Same reasoning as the ``bws`` grammar's override block: decoding could only
ever corrupt one identifier into another. An item name holding a space or a
slash is addressed by its uuid; the error for a field that failed to parse
says so.

This mirrors the shape of ``_reference`` rather than importing its machinery.
The two grammars agree on the uuid test (imported) and the refusal
philosophy, and disagree on almost everything else — path segments against
query overrides — so only the one shared predicate is shared.
"""

from __future__ import annotations

import difflib
from dataclasses import dataclass

from functualize_secrets_bitwarden._reference import InvalidReferenceError, _is_uuid

__all__ = [
    "PM_FIELDS",
    "CUSTOM_FIELD_PREFIX",
    "PmReference",
    "parse_pm_reference",
]

#: The built-in slots a reference may name directly.
PM_FIELDS: tuple[str, ...] = ("notes", "password", "totp", "uri", "username")

#: Prefix that addresses a custom field by exact name.
CUSTOM_FIELD_PREFIX = "field:"

_FIELD_SEGMENT = "/"


@dataclass(frozen=True)
class PmReference:
    """A parsed reference: which item, and which of its values."""

    item_id: str | None = None
    """Set when the reference was a uuid. Resolves in one ``bw get item``."""

    item_name: str | None = None
    """Set when the reference was a name. Lists the vault and matches exactly."""

    field: str | None = None
    """The built-in slot, when the reference named one."""

    custom_field: str | None = None
    """The custom field's exact name, when the reference used ``field:``."""

    @property
    def label(self) -> str:
        """How to name this reference in an error. Never a value."""
        item = self.item_id or self.item_name or "<empty>"
        if self.custom_field is not None:
            slot = f"{CUSTOM_FIELD_PREFIX}{self.custom_field}"
        else:
            slot = self.field or "<no field>"
        return f"{item}/{slot}"


def _fail(reference: str, detail: str) -> InvalidReferenceError:
    return InvalidReferenceError(f"{detail}\n  in reference: {reference!r}")


def _suggest(field: str) -> str:
    if field.startswith(CUSTOM_FIELD_PREFIX):
        return ""
    close = difflib.get_close_matches(field, PM_FIELDS, n=1, cutoff=0.6)
    hinted = f"{CUSTOM_FIELD_PREFIX}{field}"
    if close:
        return f" Did you mean '{close[0]}', or '{hinted}' for a custom field?"
    return f" Custom fields are addressed as '{hinted}'."


def parse_pm_reference(reference: str) -> PmReference:
    """Parse a ``bwpm://`` reference into its parts.

    Args:
        reference: Everything after ``bwpm://``, exactly as core passed it.

    Returns:
        The parsed reference, addressed by uuid or by exact item name, with
        either a built-in field or a custom field name.

    Raises:
        InvalidReferenceError: No item, no field, a second ``/`` before the
            field, an unknown field, an empty ``field:`` name, or any query
            string — all decided before any subprocess spawns.
    """
    if "?" in reference:
        raise _fail(
            reference,
            "This grammar takes no query: an item name is unambiguous within "
            "the vault the session can see, and server selection belongs to "
            "the bw CLI's own configuration.",
        )

    # The split is on the *first* slash, so a `field:` name may itself
    # contain one — everything after the prefix is the name. An item name
    # holding a slash cannot be spelled through this grammar; addressing
    # such an item by uuid is the way, and the unknown-field error below is
    # where a mistyped attempt lands.
    item, _, field = reference.partition(_FIELD_SEGMENT)
    if not item:
        raise _fail(reference, "No item before the '/'.")
    if not field:
        raise _fail(
            reference,
            "No field after the '/'. A field is never defaulted: name one of "
            f"{' , '.join(PM_FIELDS)}, or a custom field as "
            f"'{CUSTOM_FIELD_PREFIX}<name>'.",
        )

    if field in PM_FIELDS:
        return PmReference(
            item_id=item if _is_uuid(item) else None,
            item_name=None if _is_uuid(item) else item,
            field=field,
        )

    if field.startswith(CUSTOM_FIELD_PREFIX):
        name = field[len(CUSTOM_FIELD_PREFIX) :]
        if not name:
            raise _fail(
                reference,
                f"'{CUSTOM_FIELD_PREFIX}' names a custom field, and no name "
                f"followed it.",
            )
        return PmReference(
            item_id=item if _is_uuid(item) else None,
            item_name=None if _is_uuid(item) else item,
            custom_field=name,
        )

    raise _fail(
        reference,
        f"Unknown field '{field}'.{_suggest(field)} Honoured fields: "
        f"{' , '.join(PM_FIELDS)}, or a custom field as "
        f"'{CUSTOM_FIELD_PREFIX}<name>'.",
    )
