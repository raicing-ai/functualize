"""Driving the ``bw`` CLI as a subprocess, under the session already there.

The ambient session is the whole feature
----------------------------------------

The Password Manager API has no official SDK (the ``bitwarden-sdk``
dependency of this package speaks Secrets Manager only), so this provider
drives the ``bw`` CLI the way an operator would: it detects the state the
user has already put the CLI in, and it consumes it. It never logs in, never
prompts for a master password, never handles 2FA, and never creates or
persists a session.

The session key travels exactly one way: inherited through the environment,
because that is where ``bw unlock`` told the user to put it. It is **never**
passed as a ``--session`` argument — argv is world-readable on every host via
``ps`` — and it is never written anywhere by this module. CLI output is
untrusted and never included in an exception, even when it is malformed.

Four states, four refusals
--------------------------

The vault keyring read distinguishes its refusal cases rather than raising
one generic failure, and this module does the same, because the recoveries
differ:

* binary missing — install the ``bw`` CLI;
* ``unauthenticated`` — ``bw login`` is a human step with a human's
  credentials; this provider never performs it;
* ``locked`` — the human runs ``bw unlock`` and sync re-runs; this is the
  operational reality of ambient state, which is less durable than a BWS
  token;
* anything else — ``BwCommandError`` with a fixed, value-free message.

Each fetch probes the current state, so a long-lived process observes a
changed session or CLI path rather than reusing a stale module cache.

No prompt can hang a sync
-------------------------

Every invocation runs with ``--nointeraction`` and ``stdin=DEVNULL``, so a
locked vault produces a fast refusal instead of a prompt nobody can answer
inside ``vault sync``. The 20-second timeout sits under core's 30-second
per-value fetch wrapper, so on a hung ``bw`` the child is killed first and
the wrapper's accounting still holds.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from functualize_secrets_bitwarden._pm_reference import PmReference

__all__ = [
    "BW_BINARY",
    "AmbiguousFieldError",
    "AmbiguousItemError",
    "BwBinaryMissingError",
    "BwCommandError",
    "BwNotLoggedInError",
    "BwSessionLockedError",
    "FieldNotFoundError",
    "ItemNotFoundError",
    "fetch_item",
    "session_state",
]

BW_BINARY = "bw"

#: Below core's 30-second per-value wrapper, so a hung child is killed before
#: the wrapper's own timeout turns it into an unkillable future.
_SUBPROCESS_TIMEOUT = 20.0

_UNLOCKED = "unlocked"
_LOCKED = "locked"
_UNAUTHENTICATED = "unauthenticated"


class BwBinaryMissingError(RuntimeError):
    """No ``bw`` executable on PATH. Install the Bitwarden CLI."""


class BwNotLoggedInError(RuntimeError):
    """``bw status`` reports ``unauthenticated``. ``bw login`` is a human step."""


class BwSessionLockedError(RuntimeError):
    """``bw status`` reports ``locked``. A human re-unlocks; sync re-runs."""


class BwCommandError(RuntimeError):
    """A ``bw`` invocation failed otherwise, without exposing CLI output.

    Named apart from the Secrets Manager transport's ``BitwardenRequestError``
    on purpose: the two names appear side by side in this package's public
    surface, and they report failures of two different products.
    """


class ItemNotFoundError(LookupError):
    """The reference is well-formed and the vault holds no such item."""


class AmbiguousItemError(LookupError):
    """An item name matches more than one item. Names the candidate ids."""


class FieldNotFoundError(LookupError):
    """The item is there and the named field holds no value."""


class AmbiguousFieldError(LookupError):
    """One item carries more than one custom field of the same name."""


def _run(*args: str) -> subprocess.CompletedProcess[str]:
    # The binary is resolved from PATH by name; stdin is DEVNULL so no
    # invocation can wait on a prompt nobody can answer inside a sync.
    try:
        return subprocess.run(
            [BW_BINARY, "--nointeraction", *args],
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            timeout=_SUBPROCESS_TIMEOUT,
            check=False,
        )
    except subprocess.TimeoutExpired:
        # TimeoutExpired retains stdout/stderr, which may hold item values.
        raise BwCommandError("`bw` timed out.") from None


def session_state() -> str:
    """The CLI's current state, probed for this fetch.

    Returns:
        ``"unlocked"``, ``"locked"`` or ``"unauthenticated"`` — bw's own word
        for the state found, which is what a refusal should name.

    Raises:
        BwBinaryMissingError: No ``bw`` on PATH.
        BwCommandError: The probe failed, or its output is not the JSON
            shape this module understands.
    """
    if shutil.which(BW_BINARY) is None:
        raise BwBinaryMissingError(
            "No 'bw' executable on PATH. Install the Bitwarden CLI and "
            "sign in with `bw login`."
        )

    completed = _run("status", "--raw")
    if completed.returncode != 0:
        raise BwCommandError("`bw status` failed; CLI output was withheld.")
    try:
        status = json.loads(completed.stdout).get("status")
    except (json.JSONDecodeError, AttributeError):
        raise BwCommandError("`bw status` did not return the expected JSON.") from None
    if status not in (_UNLOCKED, _LOCKED, _UNAUTHENTICATED):
        raise BwCommandError("`bw status` returned an unknown state.")
    return str(status)


def _unlocked_or_raise() -> None:
    state = session_state()
    if state == _UNAUTHENTICATED:
        raise BwNotLoggedInError(
            f"`{BW_BINARY}` reports the vault is not signed in. Sign in "
            f"yourself with `bw login`; this provider never logs in, never "
            f"prompts for a master password, and never handles 2FA."
        )
    if state == _LOCKED:
        raise BwSessionLockedError(
            f"`{BW_BINARY}` reports the session is locked. Run `bw unlock` "
            f"and export $BW_SESSION as it instructs, then re-run the sync. "
            f"The session key is read from the environment only: it is never "
            f"stored, never logged, and never placed on a command line."
        )


def fetch_item(ref: PmReference) -> dict[str, Any]:
    """Return the referenced item's JSON as a dict.

    Raises:
        BwCommandError: A ``bw`` invocation failed.
        ItemNotFoundError: A name matched nothing.
        AmbiguousItemError: A name matched more than one item.
    """
    _unlocked_or_raise()
    if ref.item_id is not None:
        return _get_item(ref.item_id)
    return _get_item(_match_name(ref.item_name or ""))


def _get_item(item_id: str) -> dict[str, Any]:
    completed = _run("get", "item", item_id, "--raw")
    if completed.returncode != 0:
        if completed.stderr.strip().casefold().startswith("not found."):
            raise ItemNotFoundError(f"No Password Manager item with id {item_id}.")
        raise BwCommandError("`bw get item` failed; CLI output was withheld.")
    try:
        item = json.loads(completed.stdout)
    except json.JSONDecodeError:
        raise BwCommandError("`bw get item` did not return JSON.") from None
    if not isinstance(item, dict):
        raise BwCommandError(
            f"`{BW_BINARY} get item {item_id}` returned {type(item).__name__}, "
            f"not an item object."
        )
    return item


def _match_name(item_name: str) -> str:
    completed = _run("list", "items", "--raw")
    if completed.returncode != 0:
        raise BwCommandError("`bw list items` failed; CLI output was withheld.")
    try:
        items = json.loads(completed.stdout)
    except json.JSONDecodeError:
        raise BwCommandError("`bw list items` did not return JSON.") from None
    # Exact match on purpose. `bw list items --search` fuzzes, and a fuzzy
    # hit that is not the item the config file named is a *working* run with
    # the wrong credential.
    matches = [i for i in items if isinstance(i, dict) and i.get("name") == item_name]
    if not matches:
        raise ItemNotFoundError(
            f"No Password Manager item named {item_name!r} in the vault this "
            f"session can see."
        )
    if len(matches) > 1:
        ids = ", ".join(sorted(str(i.get("id")) for i in matches))
        raise AmbiguousItemError(
            f"Item name {item_name!r} matches {len(matches)} items: {ids}.\n"
            f"Bitwarden does not require item names to be unique across "
            f"folders and organizations. Address the one you mean by its uuid."
        )
    return str(matches[0].get("id"))


def extract_field(item: dict[str, Any], ref: PmReference) -> str:
    """The item's value for the reference's field, or the refusal why not.

    Values never appear in an error: every message names the item and the
    field, and stops there.
    """
    label = ref.label
    if ref.field is not None:
        if ref.field == "notes":
            # `notes` sits on the item itself, not under `login` — the one
            # built-in slot that is not login-shaped.
            value: Any = item.get("notes")
        else:
            login = item.get("login")
            if not isinstance(login, dict):
                raise FieldNotFoundError(
                    f"Item behind {label!r} has no login block — 'login' "
                    f"fields live on login items (this item's type may be a "
                    f"note, card or identity)."
                )
            if ref.field == "uri":
                return _first_uri(login, label)
            value = login.get(ref.field)
    else:
        assert ref.custom_field is not None
        value = _custom_field(item, ref.custom_field, label)

    if value is None or str(value) == "":
        raise FieldNotFoundError(
            f"Item behind {label!r} stores no value for that field. An empty "
            f"value would sit in the vault pretending to be a credential."
        )
    return str(value)


def _first_uri(login: dict[str, Any], label: str) -> str:
    """The first URI — ``bw get uri``'s own convention."""
    uris = login.get("uris")
    if not isinstance(uris, list):
        raise FieldNotFoundError(f"Item behind {label!r} stores no uri.")
    for entry in uris:
        if isinstance(entry, dict) and entry.get("uri"):
            return str(entry["uri"])
    raise FieldNotFoundError(f"Item behind {label!r} stores no uri.")


def _custom_field(item: dict[str, Any], name: str, label: str) -> Any:
    fields = item.get("fields")
    if not isinstance(fields, list):
        raise FieldNotFoundError(
            f"Item behind {label!r} has no custom field named {name!r}."
        )
    matches = [
        entry
        for entry in fields
        if isinstance(entry, dict) and entry.get("name") == name
    ]
    if not matches:
        raise FieldNotFoundError(
            f"Item behind {label!r} has no custom field named {name!r}."
        )
    if len(matches) > 1:
        # Bitwarden allows duplicate field names within one item. Picking a
        # winner would make the value depend on which field a colleague
        # added last.
        raise AmbiguousFieldError(
            f"Item behind {label!r} carries {len(matches)} custom fields "
            f"named {name!r}. Rename one in the vault, or address a "
            f"built-in slot instead."
        )
    return matches[0].get("value")
