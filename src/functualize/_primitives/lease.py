"""A lease with a fencing token — who may write to a scope, and under which generation.

`durable-run-layer`/T5. Spec AC-7, schema §4.

0.3.0 shipped a known limitation: two `resume` invocations both walk one scope,
each believing it is the only one. This is the mechanism that closes it.

## A lease without a fencing token is a suggestion

The tempting design is an owner and an expiry: *I hold this until 12:00.* It
does not work, and the reason is worth stating because it is the whole point of
this module.

Two runners disagree about the time — clock skew, a VM suspended and resumed, an
NTP step. Runner A believes its lease is live; runner B believes A's lease
expired and takes it. Now both are walking, and **nothing in an owner-plus-expiry
scheme can tell them apart**, because each one's evidence is its own clock.

A **monotonically increasing generation** fixes it without trusting any clock.
Every claim increments it, including a reclaim of an expired lease. A write
carries the generation it was acquired under, and the store refuses a write
whose generation is not the current one. So when B reclaims at generation 7, A's
writes at generation 6 are refused — *even though A still believes it holds the
lease*. A is wrong and finds out at its next write, which is the earliest moment
anything could have told it.

> The generation is the mechanism. The expiry is only how a dead runner's claim
> eventually becomes claimable — it decides *when* someone may take over, never
> *who wins* once they have.

## The lock is not the mechanism either

`file_lock` is advisory. It proceeds unlocked after its 10-second timeout, and it
is a no-op on a platform with neither `fcntl` nor `msvcrt`. A design that relied
on it would be correct only where locking happens to work, and silently wrong on
a network filesystem — which is exactly where two runners are most likely.

So the fencing check is a **comparison of a recorded number**, and holds with
locking disabled entirely. `tests/primitives/test_lease_fencing.py` asserts that
directly (risk R-a), because a test that runs with locking working cannot tell
the two designs apart.

## What this module is not

Pure functions over a lease dict, and nothing else. It does no I/O, holds no
lock, and reads no clock it is not given — `now` is a parameter. That is what
lets the fencing rule be tested for what it is: arithmetic on a number, not a
property of a filesystem.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

__all__ = [
    "DEFAULT_LEASE_SECONDS",
    "Lease",
    "LeaseHeldError",
    "StaleGenerationError",
    "claim",
    "is_expired",
    "read_lease",
    "release",
    "renew",
    "write_lease",
]

#: How long a claim is good for without a renewal.
#:
#: Long enough that an ordinary step does not have to renew mid-work, short
#: enough that a killed runner's scope becomes claimable while someone is still
#: watching. It is **not** a step timeout: a step that outlives it renews, and a
#: runner that stops renewing has stopped, not slowed down.
DEFAULT_LEASE_SECONDS = 300


class LeaseHeldError(RuntimeError):
    """Someone else holds this scope, and their lease has not expired.

    Names the holder and when the claim becomes available, because the question
    on hitting this is always *who, and how long do I wait* — and an opaque
    refusal sends the reader to a log to find out.

    **A count, never content.** A scope record holds gate payloads a human
    deposited; the holder's identity is not a reason to print what they are
    working on.
    """

    def __init__(self, scope_id: str, owner: str, expires_at: str) -> None:
        super().__init__(
            f"Scope '{scope_id}' is held by {owner} until {expires_at}. "
            f"Wait for it to expire, or reclaim it explicitly."
        )
        self.scope_id = scope_id
        self.owner = owner
        self.expires_at = expires_at


class StaleGenerationError(RuntimeError):
    """A write arrived under a generation that is no longer current.

    The fencing refusal. It means someone else claimed this scope after you did
    — so your view of the walk is from before their claim, and merging your
    write would interleave two runners' decisions into one record.

    Refused rather than merged, deliberately: a merge here produces a record
    that neither runner would recognise, and no reader could tell it had
    happened.
    """

    def __init__(self, scope_id: str, held: int, offered: int, owner: str) -> None:
        super().__init__(
            f"Scope '{scope_id}' has moved on: generation {held} is current, "
            f"this write carries {offered}. It is now held by {owner}."
        )
        self.scope_id = scope_id
        self.held = held
        self.offered = offered
        self.owner = owner


@dataclass(frozen=True)
class Lease:
    """One claim on a scope.

    Frozen: a renewal produces a new lease rather than mutating one, so a caller
    holding an old value cannot be surprised by it changing underneath.
    """

    owner: str
    generation: int
    expires_at: str

    def as_record(self) -> dict[str, Any]:
        """The shape stored inside the scope record (schema §4)."""
        return {
            "owner": self.owner,
            "generation": self.generation,
            "expires_at": self.expires_at,
        }


def read_lease(scope: dict[str, Any] | None) -> Lease | None:
    """The lease on a scope record, or None if it has never been claimed.

    Tolerant of a malformed lease — it reads as *absent*, which makes the scope
    claimable. The alternative is a scope nobody can ever take, which is worse
    than one taken twice: the second is refused at the next write, the first
    needs a human with a text editor.
    """
    if not isinstance(scope, dict):
        return None
    raw = scope.get("lease")
    if not isinstance(raw, dict):
        return None
    owner, generation = raw.get("owner"), raw.get("generation")
    expires_at = raw.get("expires_at")
    if not isinstance(owner, str) or not isinstance(generation, int):
        return None
    if not isinstance(expires_at, str):
        return None
    return Lease(owner=owner, generation=generation, expires_at=expires_at)


def write_lease(scope: dict[str, Any], lease: Lease | None) -> None:
    """Put ``lease`` into a scope record in place, or remove it when None."""
    if lease is None:
        scope.pop("lease", None)
    else:
        scope["lease"] = lease.as_record()


def is_expired(lease: Lease | None, now: datetime) -> bool:
    """Has ``lease`` run out as of ``now``?

    An absent lease is expired — nobody holds the scope. An **unparseable**
    expiry is also expired, for `read_lease`'s reason: a claim nobody can
    evaluate must not become permanent.
    """
    if lease is None:
        return True
    try:
        expires = datetime.fromisoformat(lease.expires_at)
    except ValueError:
        return True
    if expires.tzinfo is None:
        expires = expires.replace(tzinfo=UTC)
    return expires <= now


def _expiry(now: datetime, seconds: float) -> str:
    return (now + timedelta(seconds=seconds)).isoformat()


def claim(
    scope_id: str,
    existing: Lease | None,
    *,
    owner: str,
    now: datetime,
    seconds: float = DEFAULT_LEASE_SECONDS,
    force: bool = False,
) -> Lease:
    """Take the scope, returning the lease at its **new** generation.

    The generation increments on every claim — including a reclaim of an expired
    lease, and including a re-claim by the same owner. That is what makes it a
    fencing token rather than a label: a runner that lost the scope and got it
    back is, from the store's point of view, a different holder than it was, and
    its own earlier in-flight writes are refused.

    Args:
        force: Take it even from a live holder. For an explicit `reclaim`, where
            a human has decided the holder is gone — never for ordinary
            acquisition, which is why it is not the default.

    Raises:
        LeaseHeldError: Someone else holds it and their claim has not expired.
    """
    if existing is not None and not is_expired(existing, now) and not force:
        # A live holder. The same owner re-claiming is still refused here: a
        # second walk in the same process is the concurrent-resume bug, not a
        # renewal, and `renew` is the verb for extending a claim you hold.
        raise LeaseHeldError(scope_id, existing.owner, existing.expires_at)
    generation = (existing.generation if existing else 0) + 1
    return Lease(owner=owner, generation=generation, expires_at=_expiry(now, seconds))


def renew(
    scope_id: str,
    existing: Lease | None,
    *,
    owner: str,
    generation: int,
    now: datetime,
    seconds: float = DEFAULT_LEASE_SECONDS,
) -> Lease:
    """Extend a claim you already hold. The generation does **not** move.

    Moving it on renewal would fence the renewer's own in-flight writes — every
    heartbeat would invalidate the work it exists to protect.

    Raises:
        StaleGenerationError: The scope has been claimed by someone since. Note
            this fires **even if the lease has expired**: expiry decides when
            another runner *may* claim, and this says one already has.
    """
    check_generation(scope_id, existing, generation)
    return Lease(owner=owner, generation=generation, expires_at=_expiry(now, seconds))


def release(
    scope_id: str, existing: Lease | None, *, generation: int, now: datetime
) -> Lease:
    """Give up a claim you hold. Returns the **released** lease.

    **Releasing does not delete the lease, it expires it.** Deleting looks
    tidier and is wrong: the generation would reset to 0, so the next claim
    would be generation 1 again — and this runner's own in-flight writes,
    carrying generation 1, would be accepted by a *different* holder. Releasing
    would hand out the fence it exists to raise.

    So the record stays, with its generation and an expiry of now. The scope is
    immediately claimable (an expired lease is), the next claim increments past
    this one, and `get_lease` still answers "who held it last" — which is the
    question asked right after something goes wrong.

    Raises:
        StaleGenerationError: Someone else holds it now, so there is nothing of
            yours to release — and clearing theirs would hand the scope to a
            third runner while the second is still walking it.
    """
    check_generation(scope_id, existing, generation)
    assert existing is not None  # `check_generation` raises otherwise
    return Lease(
        owner=existing.owner, generation=generation, expires_at=now.isoformat()
    )


def check_generation(scope_id: str, existing: Lease | None, generation: int) -> None:
    """The fencing check. Raise unless ``generation`` is the current one.

    **This is the whole mechanism**, and it is a comparison of two integers. It
    does not read a clock, take a lock, or ask the filesystem anything — which
    is why it still holds when locking is disabled, and why it survives two
    runners whose clocks disagree.

    An absent lease is not current: a write fenced under generation 3 against a
    scope with no lease means the lease was released or the record was reset,
    and either way this writer's view is from before that.

    Raises:
        StaleGenerationError: ``generation`` is not the lease's generation.
    """
    if existing is None:
        raise StaleGenerationError(scope_id, held=0, offered=generation, owner="nobody")
    if existing.generation != generation:
        raise StaleGenerationError(
            scope_id,
            held=existing.generation,
            offered=generation,
            owner=existing.owner,
        )
