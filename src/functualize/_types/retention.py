"""One retention policy, read by every cap this wave applies.

`runtime-schema-migrations`/T5, AC7. The three caps were three module constants
in two files — `scope_format.SCOPES_LIMIT`, `scope_format.EVENTS_PER_SCOPE_LIMIT`
and `run_format.RUNS_LIMIT`, each spelled `500` — so "how long does this project
remember?" had as many answers as there were files, and a fourth answer was a
fourth constant. They read one value now, and the value is a value: a caller
that wants a smaller horizon constructs a policy rather than editing a constant.

**A cap, not a cleanup.** The document backend has no maintenance operation, so
the rings are applied where they are already written (`scope_format._trim`,
`run_format._trim`, and the per-record event rings in the two stores). The
relational statement that deletes rows on a schedule is
`sqlite-runtime-provider`'s (`schema.md` §5, D3 = B); it consumes this same
value.

**Which fields a document trim reads, and which it cannot.** `max_records` and
`evictable_only` are read by `scope_format._trim`; `run_format._trim` reads
`max_records` only, because a run log evicts oldest-first by ULID and carries no
status clause to filter on. `max_age` is not read here at all: a scope record
has no creation timestamp (`scope_store._blank_scope` writes none) and the run
log orders by id rather than by clock, so an age filter would need a field this
wave does not add. It is stated here because the relational statement applies
it, and one shape for the policy beats a second type over there.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from typing import Final


@dataclass(frozen=True)
class RetentionPolicy:
    """How much of a ring is kept, and what is allowed to leave it.

    Attributes:
        max_records: How many records a ring keeps, newest kept. The scope
            record ring and the run-log ring hold this many; the scope event
            ring uses it as its per-record depth.
        evictable_only: When true, a cap may drop only records whose status is
            in the machine's *evictable* set — `SCOPE.evictable`, which is
            `{completed, failed, cancelled}`. That default is the safety
            property, not a preference: a workflow parked at a gate is the one
            record that must survive any amount of unrelated traffic, and
            evicting it spends a human's approval on a run that no longer
            exists. Setting this false lets a cap drop a live scope as readily
            as a finished one, which is only ever what a maintenance caller
            asked for on purpose.
        max_age: How old a record may be, when a backend can tell. `None` means
            the count is the only horizon. The relational retention statement
            implements this; the document trims do not, because neither has a
            creation time to compare against (see the module docstring).
    """

    max_records: int = 500
    evictable_only: bool = True
    max_age: timedelta | None = None


#: The policy every cap applies unless a caller hands over another one.
#:
#: 500 matches the horizon the run log already had, so the two rings that can
#: be read together do not disagree about what happened: a scope outliving
#: every run that could reference it is unreachable, and a much lower count
#: would evict records a user could still resume.
DEFAULT_RETENTION: Final[RetentionPolicy] = RetentionPolicy()
