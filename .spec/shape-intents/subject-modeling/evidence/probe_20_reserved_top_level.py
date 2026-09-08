"""D2 — `builtin` is protected; the rest of the first-party top level is not.

`00` fact 5 and `09` §1 pin the reserved-name story on one name: claiming
`builtin` aborts CLI construction. That was accurate when the only first-party
top-level command was `builtin`.

At `c0c921f` (#33, plugin visibility) a second one appeared — `mcp` — and it is
**not** protected. A rise module declaring `group = "mcp"` collides with it
silently, which is the same failure class as defect #32 one layer up.

The consequence for rise: binding check 10 (`03` §4, "reserved names") must
derive the protected set from the adapter rather than hardcoding `builtin`,
because the set grew upstream once and can grow again.
"""

from functualize.app import FunctualizeApp, JobSources
from functualize.app.adapters.cli import CliAdapter


def _top_level_without_rise() -> list[str]:
    """What functualize itself puts at the top level, with no rise jobs."""
    app = FunctualizeApp("rise", job_sources=JobSources(directories=[], lazy=False))
    a = CliAdapter()
    a(app)
    return sorted(a.cli_command.commands)


def _claim(group: str) -> str:
    def probe() -> str:
        """A rise module method."""
        return "x"

    try:
        app = FunctualizeApp("rise", job_sources=JobSources(directories=[], lazy=False))
        app.register_dynamic_job(name=f"{group}.probe", function=probe, group=group)
        a = CliAdapter()
        a(app)
        return f"ACCEPTED  top-level={sorted(a.cli_command.commands)}"
    except Exception as exc:  # noqa: BLE001 - the refusal is the measurement
        return f"REFUSED   {type(exc).__name__}: {str(exc)[:88]}"


first_party = _top_level_without_rise()
print("first-party top level (no rise jobs):", first_party)
print()

for group in first_party:
    print(f"group={group!r:10} -> {_claim(group)}")

print()
print("A rise module may therefore claim:",
      [g for g in first_party if _claim(g).startswith("ACCEPTED")])
