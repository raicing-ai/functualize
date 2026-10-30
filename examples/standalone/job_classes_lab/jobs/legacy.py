"""A plain function that claims the name a class method also claims.

`JOB_GROUP` puts it in the `pg` group, so its canonical name is `pg.start` —
the same name `Postgres.start` produces. One claimant is class-derived, so the
collision is strict: neither definition may run under that name.
"""

JOB_GROUP = "pg"


def start() -> str:
    """Never runs either -- see jobs/pg.py."""
    return "legacy start ran"
