"""A scanned module's pydantic models must be instantiable (defect: forward refs).

`extract_module` execs a jobs module under a uniquified synthetic name. It did
so without registering the module in `sys.modules` first — skipping the step
the importlib docs call for.

That skip is not cosmetic. A pydantic model resolves its forward references by
looking its own ``__module__`` up in ``sys.modules``, and under
``from __future__ import annotations`` *every* annotation is a forward
reference. So a jobs module holding

    class Finding(BaseModel): ...
    class Findings(BaseModel):
        payload: list[Finding]

scanned fine, registered fine, and produced a `Findings` class that could not
be instantiated — the failure surfaced only when the job body finally
constructed one, as a pydantic error naming a class defined ten lines above it.

The assertion is deliberately about *instantiating* the model, not about
`sys.modules` membership: it is the behavior that broke, and an implementation
that fixed forward refs some other way should still pass.
"""

from __future__ import annotations

import sys
from pathlib import Path

from functualize._discovery.sync import extract_module

# Every element matters: the future import (making annotations strings), a
# model referenced *by name* from another model, and the job returning it.
_JOBS_MODULE = """
from __future__ import annotations

from pydantic import BaseModel

from functualize.job import job

JOB_GROUP = "fwd"


class Item(BaseModel):
    name: str


class Envelope(BaseModel):
    payload: list[Item]


@job(group=JOB_GROUP)
def produce() -> Envelope:
    return Envelope(payload=[Item(name="a")])
"""


def _write(tmp_path: Path) -> Path:
    jobs = tmp_path / "jobs"
    jobs.mkdir()
    source = jobs / "fwd.py"
    source.write_text(_JOBS_MODULE)
    return source


def test_scanned_model_with_a_forward_ref_can_be_instantiated(tmp_path) -> None:
    source = _write(tmp_path)
    before = set(sys.modules)
    try:
        extraction = extract_module(str(source), tmp_path)
        assert [d.name for d in extraction.jobs] == ["fwd.produce"]

        # Reach the executed module through the job function itself rather than
        # by guessing the synthetic name.
        produce = extraction.jobs[0].function
        assert produce is not None
        envelope_cls = sys.modules[produce.__module__].Envelope

        instance = envelope_cls(payload=[{"name": "a"}])
        assert instance.payload[0].name == "a"
    finally:
        for name in set(sys.modules) - before:
            sys.modules.pop(name, None)


def test_the_job_body_runs(tmp_path) -> None:
    """The end the defect actually broke: calling the job."""
    source = _write(tmp_path)
    before = set(sys.modules)
    try:
        extraction = extract_module(str(source), tmp_path)
        produce = extraction.jobs[0].function
        assert produce is not None
        assert produce().payload[0].name == "a"
    finally:
        for name in set(sys.modules) - before:
            sys.modules.pop(name, None)
