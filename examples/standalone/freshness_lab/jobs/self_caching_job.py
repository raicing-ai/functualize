"""A job that caches its own artifact — and decides its own freshness.

The framework decides whether your declared inputs changed. What to *do* about
that is domain knowledge it does not have: only this job knows that its artifact
is JSON, that it lives in ``build/report.json``, and that a rebuild costs more
than a re-read. So the framework hands over the verdict and this job decides.

That is the shape below, and it is two declarations:

* ``Fingerprint(..., decides=True)`` — *when I am fresh, run my body anyway and
  let me decide*. Without it the engine returns before the body
  (``_engine/executor.py``), and the job cannot act on its own freshness at all.
* a ``fresh: Freshness`` parameter — the verdict, bound after the pre-flight and
  before the body, whether or not the framework used it to skip.

Everything else here is ordinary: the artifact is written where this job wants
it, in the format this job wants, and **the framework never reads it**. It is
declared as a ``generates`` output so the verdict can ask "is it there?" — and
that is the whole of the framework's interest in it. Proving that is
``tests/test_self_caching_job.py``, which hand-edits the artifact and watches
the job stay fresh.

``baseline`` beside it is the same work with the same declaration and no
opt-in: the body never runs when it is fresh. That is what every job does today,
and what ``decides=True`` moves.
"""

from __future__ import annotations

import json
import uuid
from pathlib import Path

from functualize.job import Fingerprint, Freshness, Log, Sources, job

JOB_GROUP = "lab"

#: This job's choice of format and location. The framework knows the path only
#: because it is declared below, and it never opens the file.
ARTIFACT = Path("build/report.json")


def _counts(sources: Sources) -> dict[str, int]:
    """Words per declared input — read through ``Sources``, not re-globbed."""
    return {
        path: len(Path(path).read_text().split())
        for path in sorted(sources.keys())
    }


def _write(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n")


@job(
    group=JOB_GROUP,
    extra_description="Build a word-count report, or return the one it already built.",
    cache=Fingerprint(
        sources=["inputs/*.md"],
        generates=["build/report.json"],
        decides=True,
    ),
)
def report(fresh: Freshness, sources: Sources, log: Log) -> None:
    """Hand back the artifact this job built, instead of having been skipped."""
    verdict = fresh.verdict()
    if verdict is not None and verdict.is_fresh:
        cached = json.loads(ARTIFACT.read_text())
        log(f"up to date under {verdict.key} — returning the artifact")
        print(f"CACHED built={cached['built']} state={verdict.state.value}")
        return

    built = uuid.uuid4().hex[:8]
    counts = _counts(sources)
    _write(ARTIFACT, {"built": built, "inputs": counts, "total": sum(counts.values())})
    state = verdict.state.value if verdict is not None else "no-verdict"
    log(f"rebuilt {ARTIFACT} from {len(counts)} declared inputs")
    print(f"BUILT built={built} state={state}")


@job(
    group=JOB_GROUP,
    extra_description="The same work without the opt-in — the framework skips it.",
    cache=Fingerprint(sources=["inputs/*.md"], generates=["build/baseline.json"]),
)
def baseline(sources: Sources, log: Log) -> None:
    """No ``decides``: when this is fresh the engine never enters the body."""
    built = uuid.uuid4().hex[:8]
    counts = _counts(sources)
    _write(Path("build/baseline.json"), {"built": built, "total": sum(counts.values())})
    log(f"rebuilt build/baseline.json from {len(counts)} declared inputs")
    print(f"BUILT-BASELINE built={built}")
