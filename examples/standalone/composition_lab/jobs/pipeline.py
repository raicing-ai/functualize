"""The composition lab — capabilities used *together*, one combination per job.

Every other example demonstrates one feature. This one demonstrates the seams
*between* features, because that is where the questions actually are: does
`Fingerprint` still fire if I take a `Log`? Does `FromJob` work when the
upstream was skipped as fresh? Does a `Precondition` failing look like a crash?

Each job below is named for the combination it pins, and each is asserted by
`examples/docs/scenarios/n-composition.toml`, which runs them and checks what
they print. The guide that reads this file is `docs/guides/composition.md`.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated

from pydantic import BaseModel

from functualize.job import (
    Deps,
    Exec,
    Fingerprint,
    FromJob,
    Guards,
    Invoke,
    Log,
    Precondition,
    Retry,
    Shell,
    Sources,
    State,
    Stdout,
    job,
)

JOB_GROUP = "lab"

BUILD = Path("build")


# ── Value types ──────────────────────────────────────────────────────────
#
# Returned *by name* from jobs. A pydantic return annotation is not the job's
# config class — the two are told apart by whether they annotate a parameter.


class Item(BaseModel):
    name: str
    size: int


class Parsed(BaseModel):
    items: list[Item]

    @property
    def total(self) -> int:
        return sum(i.size for i in self.items)


class ReportConfig(BaseModel):
    """A *parameter* annotated with this is the job's config class."""

    title: str = "Untitled"


# ── 1. Fingerprint × Sources × Log ───────────────────────────────────────
#
# The declaration resolves the glob to decide freshness. Read that result
# instead of re-globbing: two statements of one intent drift.


@job(
    group=JOB_GROUP,
    cache=Fingerprint(sources=["inputs/*.yaml"], generates=["build/parsed.json"]),
)
def parse(log: Log, sources: Sources) -> Parsed:
    """Normalize the declared inputs. Reads them *through* the declaration."""
    items = [
        Item(
            name=Path(p).stem,
            size=int(
                next(
                    line.split(":", 1)[1]
                    for line in Path(p).read_text().splitlines()
                    if line.startswith("size:")
                )
            ),
        )
        for p in sorted(sources.keys())
    ]
    parsed = Parsed(items=items)
    BUILD.mkdir(exist_ok=True)
    (BUILD / "parsed.json").write_text(parsed.model_dump_json(indent=2))
    log(f"parsed {len(items)} inputs (declared={sources.declared})")
    print(f"PARSED n={len(items)} total={parsed.total} keys={sorted(sources.keys())}")
    return parsed


# ── 2. FromJob × a typed envelope × config class ─────────────────────────
#
# Three annotations in one signature that the framework must tell apart:
# a config *parameter*, a FromJob *parameter*, and a pydantic *return*.


@job(
    group=JOB_GROUP,
    cache=Fingerprint(sources=["build/parsed.json"], generates=["build/report.md"]),
)
def report(
    log: Log,
    config: ReportConfig,
    parsed: Annotated[Parsed, FromJob("lab.parse")],
) -> Parsed:
    """Render a report from the upstream's *value*, not a re-read of its file."""
    BUILD.mkdir(exist_ok=True)
    lines = [f"# {config.title}", ""]
    lines += [f"- {i.name}: {i.size}" for i in parsed.items]
    (BUILD / "report.md").write_text("\n".join(lines) + "\n")
    log(f"wrote build/report.md ({len(parsed.items)} items)")
    print(f"REPORT title={config.title!r} items={len(parsed.items)}")
    return parsed


# ── 3. Deps × Guards(status) ─────────────────────────────────────────────
#
# `Deps` orders the work; `Guards(status=...)` says "already done". They are
# ANDed with file staleness: a status guard cannot mask changed sources.


@job(
    group=JOB_GROUP,
    deps=Deps("lab.report"),
    guards=Guards(status=["test -f build/publish.stamp"]),
    cache=Fingerprint(sources=["build/report.md"], generates=["build/publish.stamp"]),
)
def publish(log: Log) -> None:
    """Runs after `report`, and skips once its stamp exists."""
    BUILD.mkdir(exist_ok=True)
    (BUILD / "publish.stamp").write_text("published\n")
    log("published")
    print("PUBLISHED")


# ── 4. Guards(preconditions) — refusal, not failure ──────────────────────


@job(
    group=JOB_GROUP,
    guards=Guards(preconditions=[Precondition("exit 1", msg="never satisfiable")]),
)
def gated(log: Log) -> None:
    """A failing precondition refuses (exit 3). The body never runs."""
    print("GATED BODY RAN")  # must never appear


# ── 5. Fingerprint whose sources resolve to nothing — also a refusal ──────


@job(group=JOB_GROUP, cache=Fingerprint(sources=["absent/*.json"]))
def verify(log: Log) -> None:
    """Declared inputs that resolve to no files refuse rather than report clean."""
    print("VERIFY BODY RAN")  # must never appear


# ── 6. Stdout × --output ─────────────────────────────────────────────────
#
# A job's return value is programmatic (it feeds FromJob and rc.invoke).
# Reaching stdout is explicit and honours --output.


@job(group=JOB_GROUP, deps=Deps("lab.parse"))
def emit(out: Stdout, parsed: Annotated[Parsed, FromJob("lab.parse")]) -> None:
    """`func lab emit --output json` prints the envelope as JSON."""
    out.emit({"items": [i.model_dump() for i in parsed.items], "total": parsed.total})


# ── 7. Shell × Exec(retry) × Log ─────────────────────────────────────────


@job(group=JOB_GROUP, exec=Exec(retry=Retry(attempts=2)))
def probe(sh: Shell, log: Log) -> None:
    """Shell runs the command; Exec governs the *job's* retry, not the shell's."""
    result = sh(["python", "-c", "print('probe-ok')"])
    log(f"probe said {result.stdout.strip()!r}")
    print(f"PROBE {result.stdout.strip()}")


# ── 8. Invoke.parallel × State ───────────────────────────────────────────
#
# `State` is per-invocation and in memory. The children below get their own
# State; nothing they set is visible here. That is the trap this job pins.


@job(group=JOB_GROUP)
def worker(log: Log, state: State, slot: str = "a") -> None:
    """A child job. Its `State` is its own."""
    state.set("slot", slot)
    print(f"WORKER slot={slot} state={state.get('slot')}")


@job(group=JOB_GROUP)
def fanout(inv: Invoke, state: State, log: Log) -> None:
    """Run N of the same job concurrently, then read the results."""
    results = inv.parallel(
        [("lab.worker", {"slot": "a"}), ("lab.worker", {"slot": "b"})]
    )
    statuses = sorted(r.status.value for r in results)
    print(
        f"FANOUT n={len(results)} statuses={statuses} parent_state={state.get('slot')}"
    )


# ── 9. State (runtime, across runs) — the one that persists ──────────────


@job(group=JOB_GROUP)
def counter(log: Log) -> None:
    """`State` does not persist. A file you own does.

    Three things are called "state"; only the runtime store survives a process,
    and it is reached from `functualize.app.utils`, not from the capability.
    """
    stamp = BUILD / "counter.json"
    BUILD.mkdir(exist_ok=True)
    n = json.loads(stamp.read_text())["n"] + 1 if stamp.exists() else 1
    stamp.write_text(json.dumps({"n": n}))
    print(f"COUNTER n={n}")
