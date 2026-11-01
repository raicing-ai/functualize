"""Hand a working environment over: which entries to share, and what a
redeemed bundle becomes in the receiver's vault.

This module is local materialisation policy. It decides; it does not speak the
wire or do cryptography — that is :mod:`functualize.app.vault_remote`, vendored
from the funccloud reference and kept behaviour-faithful — and it never reaches
the store directly: every read and write goes through :mod:`functualize.app.vault`
(spec A3, plan *AFTER*).

Two flows, each in the order the spec fixes:

* **share** — :func:`parse_selector` → :func:`select_for_share` (rows from
  :func:`shareable_entries`) → :func:`share`.
* **redeem** — :func:`check_before_redeem` (every refusal that can precede the
  burn) → ``vault_remote.redeem_link`` (the burn) → :func:`plan_import` →
  :func:`apply_import`.

Nothing here prints, prompts or knows about Click: the CLI is one caller.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Any

from functualize.app.vault import (
    VaultIdentity,
    VaultOrigin,
    VaultPathError,
    resolve_vault_identity,
    vault_put,
    vault_require_key,
    vault_supersede_synced,
)
from functualize.app.vault_remote import (
    RedeemedBundle,
    ShareMeta,
    ShareReport,
    VaultRedeemError,
    fetch_share_meta,
    parse_link,
)
from functualize.app.vault_remote import share as _send_share

__all__ = [
    "ALL",
    "ENV_LABEL_PREFIX",
    "ImportPlan",
    "ImportReport",
    "ImportRow",
    "Materialize",
    "RowStatus",
    "Selector",
    "ShareCandidate",
    "ShareSelection",
    "apply_import",
    "check_before_redeem",
    "export_name",
    "parse_selector",
    "plan_import",
    "select_for_share",
    "share",
    "shareable_entries",
]

#: The label every share carries: the sender's active environment (spec A11).
ENV_LABEL_PREFIX = "env:"

_SHARED_LABEL = "base"
_SELECTOR_KEYS = ("group", "job", "field")


# ── selectors ─────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class Selector:
    """One ``--entry`` / ``--only`` value (spec A4 grammar).

    With ``field`` it names exactly one entry. Without it, it is *wide*:
    ``group=G`` is everything under ``G``; ``group=G,job=J`` or ``job=J`` is
    every field of that job.
    """

    group: str | None = None
    job: str | None = None
    field: str | None = None

    @property
    def exact(self) -> bool:
        return self.field is not None

    def __str__(self) -> str:
        return ",".join(
            f"{key}={value}"
            for key in _SELECTOR_KEYS
            if (value := getattr(self, key)) is not None
        )


class _All:
    """The ``--all`` marker, so a selection cannot be ``None`` by accident."""

    def __repr__(self) -> str:
        return "ALL"


ALL = _All()


def parse_selector(text: str) -> Selector:
    """``group=deploy.infra,job=app,field=api_token`` → a :class:`Selector`.

    Refusals use :class:`VaultPathError` and the ``vault put`` reason codes
    where one exists (``dotted_job``, ``scope_required``); a malformed value
    is ``bad_selector``.
    """
    values: dict[str, str] = {}
    for part in text.split(","):
        key, sep, value = part.partition("=")
        if (
            not sep
            or not key
            or not value
            or key != key.strip()
            or any(c.isspace() for c in value)
        ):
            raise VaultPathError(
                "bad_selector",
                f"{text!r} is not a selector. Expected comma-separated "
                f"key=value with keys group, job, field and no spaces, e.g. "
                f"group=deploy.infra,job=app,field=api_token.",
                path=text,
            )
        if key not in _SELECTOR_KEYS:
            raise VaultPathError(
                "bad_selector",
                f"{key!r} is not a selector key; use group, job or field.",
                path=text,
            )
        if key in values:
            raise VaultPathError(
                "bad_selector", f"{key!r} is given twice in {text!r}.", path=text
            )
        values[key] = value
    if "group" not in values and "job" not in values:
        raise VaultPathError(
            "scope_required",
            f"{text!r} names no group or job; add group=… or job=….",
            path=text,
        )
    job = values.get("job")
    if job is not None and "." in job:
        group_part, _, leaf = job.rpartition(".")
        raise VaultPathError(
            "dotted_job",
            f"job= takes one job name, not a path: use "
            f"group={group_part},job={leaf} instead of job={job}.",
            path=text,
        )
    return Selector(values.get("group"), job, values.get("field"))


def _in_subtree(group: str | None, root: str) -> bool:
    return group is not None and (group == root or group.startswith(root + "."))


def _matches(
    selector: Selector,
    *,
    scope: str,
    group: str | None,
    job: str | None,
    field_name: str,
) -> bool:
    """Whether one addressed entry falls under a selector (spec A4 table)."""
    if selector.field is not None and selector.field != field_name:
        return False
    if selector.job is not None:
        return scope == "job" and job == selector.job and group == selector.group
    if selector.group is None:  # pragma: no cover - parse_selector refuses it
        return False
    if selector.exact:
        return scope == "group" and group == selector.group
    return _in_subtree(group, selector.group)


# ── addressing an identity against this project ───────────────────────────


@dataclass(frozen=True)
class _Address:
    """Where an identity sits in *this* project, for matching and display.

    ``group``/``job`` come from the job's own descriptor — a registered job
    name is never split apart (SD/12779576).
    """

    scope: str
    group: str | None
    job: str | None
    field: str
    problem: str | None = None
    """Why the identity does not resolve here, or ``None`` when it does."""


def _address(app: Any, identity: VaultIdentity) -> _Address:
    if identity.scope == "group":
        group: str | None = identity.target
        job: str | None = None
    else:
        descriptor = app.get_job(identity.target)
        if descriptor is None:
            return _Address(
                "job",
                None,
                None,
                identity.field,
                problem=f"no job {identity.target!r} in this project",
            )
        group = getattr(descriptor, "group", None)
        name = str(descriptor.name)
        job = name[len(group) + 1 :] if group and name.startswith(group + ".") else name
    try:
        resolve_vault_identity(app, group=group, job=job, field=identity.field)
    except VaultPathError as exc:
        return _Address(identity.scope, group, job, identity.field, problem=str(exc))
    return _Address(identity.scope, group, job, identity.field)


def _label(identity: VaultIdentity, address: _Address) -> str:
    env = identity.environment or _SHARED_LABEL
    parts = []
    if address.group is not None:
        parts.append(f"--group {address.group}")
    if address.job is not None:
        parts.append(f"--job {address.job}")
    elif identity.scope == "job":
        parts.append(f"--job {identity.target}")
    parts.append(f"--field {identity.field}")
    return f"{env}: {' '.join(parts)}"


def _active_slot(app: Any) -> str | None:
    """The stored slot of the active environment; ``None`` is the shared one."""
    return VaultIdentity(
        "group", "x", "x", app.configuration.active_environment()
    ).environment


def _env_label(slot: str | None) -> str:
    return f"{ENV_LABEL_PREFIX}{slot or _SHARED_LABEL}"


# ── share ─────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class ShareCandidate:
    """One stored entry as the share picker sees it. Never carries a value."""

    identity: VaultIdentity
    label: str
    group: str | None
    job: str | None
    shareable: bool
    reason: str | None = None
    """Why it cannot be shared, when it cannot."""
    synced_from: str | None = None


@dataclass(frozen=True)
class ShareSelection:
    """What a share will send, and what a wide selector skipped (with why)."""

    chosen: tuple[ShareCandidate, ...]
    skipped: tuple[ShareCandidate, ...] = ()


def shareable_entries(
    app: Any, *, cwd: str | Path | None = None
) -> list[ShareCandidate]:
    """Every entry the active environment could offer, shareable or not.

    Built from entry metadata alone (no key). Entries stored for *another*
    environment are not listed at all. Listed but not shareable: shared
    entries while a named environment is active (spec A12) and entries that
    no longer resolve here (orphans, fields no longer secret).
    """
    from functualize.app.utils import vault_entries

    slot = _active_slot(app)
    rows: list[ShareCandidate] = []
    for entry in vault_entries(cwd):
        try:
            identity = VaultIdentity.decode(entry.key)
        except ValueError:
            continue
        if identity.environment not in (slot, None):
            continue
        address = _address(app, identity)
        synced = entry.annotation if entry.origin is VaultOrigin.PROVIDER else None
        reason = address.problem
        if reason is None and identity.environment != slot:
            reason = "shared entry; sharing shared entries is not supported yet"
        rows.append(
            ShareCandidate(
                identity=identity,
                label=_label(identity, address),
                group=address.group,
                job=address.job,
                shareable=reason is None,
                reason=reason,
                synced_from=synced,
            )
        )
    rows.sort(key=lambda c: (c.group or "", c.job or "", c.identity.field))
    return rows


def select_for_share(
    app: Any,
    selectors: Sequence[Selector] | _All,
    *,
    cwd: str | Path | None = None,
) -> ShareSelection:
    """Resolve ``--entry`` selectors (or ``--all``) to the entries to send.

    Every selector must match at least one shareable entry, so a typo never
    silently shares less. An exact selector naming an entry that cannot be
    shared refuses with its reason; a wide one, or ``--all``, skips it and
    lists it in :attr:`ShareSelection.skipped`.
    """
    candidates = shareable_entries(app, cwd=cwd)
    if isinstance(selectors, _All):
        chosen = [c for c in candidates if c.shareable]
        if not chosen:
            raise VaultRedeemError(
                "no_items", "nothing in this environment's vault can be shared."
            )
        return ShareSelection(
            tuple(chosen), tuple(c for c in candidates if not c.shareable)
        )

    if not selectors:
        raise VaultRedeemError("no_items", "no entries were selected to share.")
    chosen_keys: dict[str, ShareCandidate] = {}
    skipped_keys: dict[str, ShareCandidate] = {}
    for selector in selectors:
        if selector.exact:
            # Validated like `vault put`, so a typo is named precisely.
            resolve_vault_identity(
                app, group=selector.group, job=selector.job, field=str(selector.field)
            )
        hits = [
            c
            for c in candidates
            if _matches(
                selector,
                scope=c.identity.scope,
                group=c.group,
                job=c.job,
                field_name=c.identity.field,
            )
        ]
        usable = [c for c in hits if c.shareable]
        if selector.exact and hits and not usable:
            raise VaultRedeemError("not_shareable", f"{selector}: {hits[0].reason}.")
        if not usable:
            raise VaultRedeemError(
                "no_match",
                f"{selector} matches nothing stored for this environment; "
                f"nothing was shared. `func builtin vault list` shows what is.",
            )
        for c in usable:
            chosen_keys.setdefault(c.identity.encode(), c)
        for c in hits:
            if not c.shareable:
                skipped_keys.setdefault(c.identity.encode(), c)
    return ShareSelection(tuple(chosen_keys.values()), tuple(skipped_keys.values()))


def share(
    app: Any,
    selection: ShareSelection,
    *,
    labels: Sequence[str] = (),
    redemptions: int = 1,
    expires_in_hours: int = 24,
    origin: str | None = None,
    cwd: str | Path | None = None,
    timeout: float = 30.0,
) -> ShareReport:
    """Seal the selected entries into one link, labelled with the environment.

    Each item's name is the entry's canonical ``VaultIdentity.encode()``
    spelling (spec A10). Values are read through the vault seam and go
    straight into the envelope; none is returned or reported.
    """
    from functualize.app.vault import _read_value

    if not selection.chosen:
        raise VaultRedeemError("no_items", "no entries were selected to share.")
    reserved = [label for label in labels if label.startswith(ENV_LABEL_PREFIX)]
    if reserved:
        raise VaultRedeemError(
            "bad_label",
            f"labels starting {ENV_LABEL_PREFIX!r} are reserved for the "
            f"environment, which is set from FUNCTUALIZE_ENV: {reserved[0]!r}.",
        )
    items = [
        {
            "name": c.identity.encode(),
            "kind": "secret",
            "value": _read_value(app, c.identity, cwd=cwd),
        }
        for c in selection.chosen
    ]
    return _send_share(
        items,
        labels=[*labels, _env_label(_active_slot(app))],
        redemptions=redemptions,
        expires_in_hours=expires_in_hours,
        origin=origin,
        timeout=timeout,
    )


# ── redeem ────────────────────────────────────────────────────────────────


class Materialize(StrEnum):
    """What a redeem does with the bundle."""

    STORE = "store"
    """Into this project's vault, after a confirmation (the default, D3)."""
    PRINT = "print"
    """Export lines only; nothing persisted."""
    DOTENV = "dotenv"
    """A 0600 dotenv file; nothing persisted in the vault."""


def check_before_redeem(
    app: Any,
    link: str,
    *,
    materialize: Materialize,
    interactive: bool,
    confirmed_without_prompt: bool,
    only: Sequence[Selector] = (),
    cwd: str | Path | None = None,
    timeout: float = 30.0,
) -> ShareMeta:
    """Every refusal that can precede the burn, in the spec's order (A11).

    Sends at most the non-burning ``meta`` read; on any refusal the link is
    still usable. Order: project → confirmation mode → ``--only`` selectors →
    share state (gone/expired/unknown, from meta) → environment label → vault
    key. Only store mode needs a project, a confirmation, a matching
    environment and a key.

    Args:
        interactive: A terminal is attached, so a prompt can be shown.
        confirmed_without_prompt: ``-y`` or ``--only`` was given.
        only: Parsed ``--only`` selectors; exact ones are validated against
            this project now, so a typo cannot cost the redemption.
    """
    origin, share_id, _key = parse_link(link)
    store = materialize is Materialize.STORE
    if store and not app.get_jobs():
        raise VaultRedeemError(
            "no_project",
            "no functualize project here, so nothing could be checked or "
            "stored. cd into the project, or use --print-only / --dotenv. "
            "Nothing was redeemed.",
        )
    if store and not interactive and not confirmed_without_prompt:
        raise VaultRedeemError(
            "no_tty_confirmation",
            "redeeming into the vault needs a confirmation and there is no "
            "terminal to ask on. Pass -y (all storable entries), --only "
            "SELECTOR, or --print-only. Nothing was redeemed.",
        )
    for selector in only:
        if selector.exact:
            resolve_vault_identity(
                app, group=selector.group, job=selector.job, field=str(selector.field)
            )
    meta = fetch_share_meta(origin, share_id, timeout=timeout)
    env_labels = [x for x in meta.labels if x.startswith(ENV_LABEL_PREFIX)]
    if len(env_labels) != 1:
        raise VaultRedeemError(
            "not_a_vault_share",
            "this share carries no environment label, so it was not made by "
            "`func builtin vault share`. Nothing was redeemed.",
        )
    if store:
        wanted = env_labels[0][len(ENV_LABEL_PREFIX) :]
        active = _env_label(_active_slot(app))[len(ENV_LABEL_PREFIX) :]
        if wanted != active:
            raise VaultRedeemError(
                "environment_mismatch",
                f"this share was made for {wanted!r} and the active environment "
                f"is {active!r}. Run FUNCTUALIZE_ENV={wanted} func builtin vault "
                f"redeem … to store it. Nothing was redeemed.",
            )
        vault_require_key(app, cwd=cwd)
    return meta


class RowStatus(StrEnum):
    STORABLE = "storable"
    EXISTS = "exists"
    SYNCED = "synced"
    NO_MATCH = "no_match"
    MALFORMED = "malformed"

    @property
    def selectable(self) -> bool:
        return self in (RowStatus.STORABLE, RowStatus.EXISTS, RowStatus.SYNCED)


@dataclass(frozen=True)
class ImportRow:
    """One redeemed item as the confirmation shows it. Never carries a value."""

    index: int
    """Position of the item in the bundle — how :func:`apply_import` finds
    the value, so the plan itself never holds one."""
    status: RowStatus
    label: str
    identity: VaultIdentity | None = None
    group: str | None = None
    job: str | None = None
    reason: str | None = None
    synced_from: str | None = None

    @property
    def default_ticked(self) -> bool:
        """All storable rows ticked; collisions and synced rows unticked."""
        return self.status is RowStatus.STORABLE


@dataclass(frozen=True)
class ImportPlan:
    share_id: str
    rows: tuple[ImportRow, ...]
    names: tuple[str, ...] = field(repr=False)
    """The item names that were planned, in bundle order — what the bundle
    applied must still carry (the "payload equals plan" check)."""

    def default_selection(self) -> list[int]:
        return [row.index for row in self.rows if row.default_ticked]

    def select(self, selectors: Sequence[Selector], *, replace: bool) -> list[int]:
        """``--only``: selectable rows under any selector. Collisions need
        ``replace``; a selector matching no selectable row is refused."""
        picked: list[int] = []
        for selector in selectors:
            hits = [
                row
                for row in self.rows
                if row.status.selectable
                and row.identity is not None
                and _matches(
                    selector,
                    scope=row.identity.scope,
                    group=row.group,
                    job=row.job,
                    field_name=row.identity.field,
                )
            ]
            if not hits:
                raise VaultRedeemError(
                    "no_match", f"--only {selector} matches nothing in this share."
                )
            picked.extend(
                row.index
                for row in hits
                if (replace or row.status is RowStatus.STORABLE)
                and row.index not in picked
            )
        return picked


def plan_import(
    bundle: RedeemedBundle, app: Any, *, cwd: str | Path | None = None
) -> ImportPlan:
    """Classify every redeemed item against *this* project (spec A13).

    Validation is ``vault put``'s; existence and provenance come from entry
    metadata (no key). A name that does not decode is ``malformed`` — after the
    burn that is a row, never a crash.
    """
    from functualize.app.utils import vault_entries

    slot = _active_slot(app)
    stored = {entry.key: entry for entry in vault_entries(cwd)}
    rows: list[ImportRow] = []
    for index, item in enumerate(bundle.items):
        try:
            sent = VaultIdentity.decode(str(item.get("name", "")))
        except ValueError:
            rows.append(
                ImportRow(
                    index,
                    RowStatus.MALFORMED,
                    f"item {index + 1}",
                    reason="unreadable item name",
                )
            )
            continue
        address = _address(app, sent)
        label = _label(sent, address)
        if sent.environment != slot:
            rows.append(
                ImportRow(
                    index,
                    RowStatus.NO_MATCH,
                    label,
                    sent,
                    address.group,
                    address.job,
                    reason=f"sent for {sent.environment or _SHARED_LABEL!r}",
                )
            )
            continue
        if address.problem is not None:
            rows.append(
                ImportRow(
                    index,
                    RowStatus.NO_MATCH,
                    label,
                    sent,
                    address.group,
                    address.job,
                    reason=address.problem,
                )
            )
            continue
        existing = stored.get(sent.encode())
        if existing is None:
            status, reason, synced = RowStatus.STORABLE, None, None
        elif existing.origin is VaultOrigin.PROVIDER:
            status = RowStatus.SYNCED
            synced = existing.annotation
            reason = (
                "replacing makes it a direct entry; vault sync will report it "
                "until it is removed"
            )
        else:
            status, reason, synced = RowStatus.EXISTS, "exists, would replace", None
        rows.append(
            ImportRow(
                index,
                status,
                label,
                sent,
                address.group,
                address.job,
                reason=reason,
                synced_from=synced,
            )
        )
    return ImportPlan(
        share_id=bundle.share_id,
        rows=tuple(rows),
        names=tuple(str(item.get("name", "")) for item in bundle.items),
    )


@dataclass(frozen=True)
class ImportReport:
    """What :func:`apply_import` stored. Labels only — never values."""

    stored: tuple[str, ...]
    replaced: tuple[str, ...]
    superseded: tuple[str, ...]
    skipped: tuple[str, ...]


def apply_import(
    app: Any,
    plan: ImportPlan,
    bundle: RedeemedBundle,
    selected: Iterable[int],
    *,
    replace: bool,
    cwd: str | Path | None = None,
) -> ImportReport:
    """Store the selected rows through the vault seam.

    The bundle must be the one that was planned — same share, same item names
    in the same order — or nothing is stored. ``exists`` and ``synced`` rows
    are replaced only with ``replace`` (an interactive tick is that consent).

    Raises:
        VaultRedeemError: ``plan_mismatch`` for a different bundle, or a
            selection naming a row that cannot be stored.
    """
    names = tuple(str(item.get("name", "")) for item in bundle.items)
    if bundle.share_id != plan.share_id or names != plan.names:
        raise VaultRedeemError(
            "plan_mismatch",
            "the bundle is not the one that was confirmed; nothing was stored.",
        )
    chosen = sorted(set(selected))
    by_index = {row.index: row for row in plan.rows}
    for index in chosen:
        row = by_index.get(index)
        if row is None or not row.status.selectable:
            raise VaultRedeemError(
                "bad_selection", f"item {index + 1} cannot be stored."
            )
        if row.status is not RowStatus.STORABLE and not replace:
            raise VaultRedeemError(
                "entry_exists",
                f"{row.label} already exists; replacing it needs --replace.",
            )
    stored: list[str] = []
    replaced: list[str] = []
    superseded: list[str] = []
    for index in chosen:
        row = by_index[index]
        assert row.identity is not None  # selectable rows always carry one
        value = str(bundle.items[index]["value"])
        if row.status is RowStatus.SYNCED:
            vault_supersede_synced(app, row.identity, value, cwd=cwd)
            superseded.append(row.label)
        else:
            vault_put(
                app,
                row.identity,
                value,
                replace=row.status is RowStatus.EXISTS,
                cwd=cwd,
            )
            (replaced if row.status is RowStatus.EXISTS else stored).append(row.label)
    skipped = tuple(row.label for row in plan.rows if row.index not in chosen)
    return ImportReport(tuple(stored), tuple(replaced), tuple(superseded), skipped)


# ── export names ──────────────────────────────────────────────────────────


def export_name(identity: VaultIdentity) -> str:
    """The environment variable a run already resolves for this entry (O1).

    ``JOB_FIELD`` for a job config field, ``SCOPE__FIELD`` for a group option —
    the repository's two documented conventions, used rather than restated.
    """
    from functualize._config.resolved_field import env_name_for, group_env_name_for

    if identity.scope == "group":
        return group_env_name_for(identity.target, identity.field)
    return env_name_for(identity.target, identity.field)
