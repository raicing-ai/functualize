"""The walk, the pause, and the sign-off.

`jobs/pipeline.py` pins one combination per job. This module adds the three the
lab could not show with single jobs, because each is about a *shape* rather
than a seam between two capabilities:

* **`GroupOptions`** — one flag declared once and shared by every job beneath a
  group, rather than repeated in each job's config model.
* **A second group.** `check.signoff` is deliberately not in `lab`, so the
  workflow below crosses a group boundary and the lab has more than one.
* **`@workflow` + `Gate`** — a topology whose one interesting node is a pause:
  the point at which a person or an agent has to say yes before the release is
  signed off.

Kept apart from `jobs/pipeline.py` because the topology is a separate thing to
maintain from the stages, and a reader asking "what is the order" should not
have to read nine job bodies to find out.
"""

from __future__ import annotations

import tarfile
from pathlib import Path
from typing import Annotated

from pydantic import BaseModel, Field

from functualize import workflow
from functualize.job import (
    Deps,
    Fingerprint,
    FromJob,
    GroupOptions,
    Log,
    Stdout,
    job,
)
from functualize.workflow import END, Edge, Gate, Step
from pipeline import BUILD, Parsed

JOB_GROUP = "lab"

DIST = Path("dist")


# ── 10. GroupOptions — one flag, every job in the group ──────────────────
#
# Declared once here instead of as a field on each job's config model. It is a
# *mid-path* flag: `func lab --strict bundle`, not `func lab bundle --strict`.


class LabOptions(GroupOptions, group="lab"):
    """Flags shared by every job in the `lab` group."""

    strict: bool = Field(
        default=False,
        description="Treat an unapproved release as a blocking verdict.",
    )


# ── 11. Fingerprint(generates=[<glob>]) — a pattern, not a literal ───────
#
# `generates` entries are globs, exactly as `sources` entries are. A literal
# `dist/lab-0.1.0.tar.gz` would pin the version into the declaration; the glob
# says what the stage *produces* without restating what it will be called.


@job(
    group=JOB_GROUP,
    deps=Deps("lab.publish"),
    cache=Fingerprint(sources=["build/report.md"], generates=["dist/*.tar.gz"]),
)
def bundle(log: Log, out: Stdout, options: LabOptions) -> None:
    """Package the rendered report. Fresh once the glob matches something."""
    DIST.mkdir(exist_ok=True)
    archive = DIST / "lab-0.1.0.tar.gz"
    with tarfile.open(archive, "w:gz") as tar:
        tar.add(BUILD / "report.md", arcname="lab-0.1.0/report.md")
    log(f"bundled {archive}")
    out.emit({"archive": archive.name, "strict": options.strict})
    print(f"BUNDLED {archive.name} strict={options.strict}")


# ── 12. A gate's payload, and the second group ───────────────────────────


class Approval(BaseModel):
    """What the gate waits for before the release may be signed off."""

    note: str = Field(description="Why this release is approved.")
    author: str = Field(default="ai", description="Who approved it.")


@job(group="check", deps=Deps("lab.bundle"))
def signoff(
    log: Log,
    out: Stdout,
    parsed: Annotated[Parsed, FromJob("lab.report")],
    options: LabOptions,
) -> None:
    """Report what still blocks the release.

    Two things are pinned here. **`Deps` crosses a group boundary**: this job is
    in `check`, its dependency is in `lab`, and running it cold pulls the whole
    `lab` chain first. And it takes `LabOptions` while living outside that
    group — a `GroupOptions` subclass is a *type*, so any job may accept it;
    `group="lab"` decides only where the flag is *parsed* on the command line.
    From here the flag is not on the command line at all, and the rest of the
    ladder (config file, environment) is how it is reached.

    Note there is deliberately **no `Precondition` restating the dependency**.
    `Deps("lab.bundle")` already guarantees the archive exists, so a guard
    checking for it could never fire — a decorative refusal that reads like a
    safety net and is not one.
    """
    verdicts: list[dict[str, str]] = []
    if not (BUILD / "approved.json").exists():
        verdicts.append(
            {
                "id": "approval",
                "severity": "error",
                "verdict": "unapproved",
                "evidence": "no approval was recorded for this release",
            }
        )
    if options.strict and verdicts:
        verdicts.append(
            {
                "id": "strict",
                "severity": "error",
                "verdict": "strict-mode",
                "evidence": f"{len(verdicts)} open verdict(s) under --strict",
            }
        )
    out.emit(verdicts)
    log(f"{len(verdicts)} blocking verdict(s) over {len(parsed.items)} item(s)")
    print(f"SIGNOFF verdicts={len(verdicts)} strict={options.strict}")


# ── 13. The topology ─────────────────────────────────────────────────────
#
# Every node names a job that already exists; there is no second definition of
# what a stage does. The gate sits between the artifact and its sign-off.


@workflow(
    steps=[
        # By *name*, not by importing the function. A step points at behaviour
        # that is already declared and independently runnable, and naming it
        # keeps this module from importing four jobs it never calls.
        Step("lab.parse"),
        Step("lab.report"),
        Step("lab.publish"),
        Step(bundle),
        Gate(name="approval-gate", awaits=Approval, strategy="ai_outbound"),
        Step(signoff),
    ],
    edges=[
        Edge("lab.parse", "lab.report"),
        Edge("lab.report", "lab.publish"),
        Edge("lab.publish", "lab.bundle"),
        Edge("lab.bundle", "approval-gate"),
        Edge("approval-gate", "check.signoff"),
        Edge("check.signoff", END),
    ],
)
def release(log: Log) -> str:
    """Walk the whole lab, pausing for approval before sign-off."""
    log("walk complete")
    print("RELEASE complete")
    return "release complete"
