"""All config-class detection sites answer identically (A10).

There were three copies of the "which parameter is this job's config class"
rule — cold (`_discovery/registry`), warm (`_discovery/lazy_wrapper`) and the
single-file peer path (`_cli/main`) — and they had drifted three ways:

- the warm copy iterated the hints mapping's *values*, so a pydantic **return**
  annotation was taken as the config class;
- the warm copy resolved hints without ``include_extras=True``, so
  ``Annotated[Envelope, FromJob(...)]`` collapsed to bare ``Envelope`` and was
  taken as the config class too;
- the peer copy had no ``GroupOptions`` guard, so a group's flags leaked into
  the job's own ``--help`` on that path alone.

Each divergence was invisible from any single path — a job that ran cold failed
warm. So the assertion that matters is not "each site is correct" but "the
sites agree, on a matrix wide enough to have caught all three". This test is
parameterized over the entry points rather than the rule, which is what makes
re-copying the rule fail here.
"""

from __future__ import annotations

from typing import Annotated

import pytest
from pydantic import BaseModel

from functualize._cli.main import _detect_config_class as detect_single_file
from functualize._discovery.lazy_wrapper import _detect_config_class as detect_warm
from functualize._discovery.registry import JobRegistry
from functualize.job import FromJob, GroupOptions, Log

detect_cold = JobRegistry._detect_job_config_class

DETECTORS = pytest.mark.parametrize(
    "detect",
    [
        pytest.param(detect_cold, id="cold-registry"),
        pytest.param(detect_warm, id="warm-lazy-wrapper"),
        pytest.param(detect_single_file, id="single-file-peer"),
    ],
)


class Cfg(BaseModel):
    x: int = 1


class Envelope(BaseModel):
    n: int = 0


class Opts(GroupOptions, group="detection-matrix"):
    flag: bool = False


def s_config(cfg: Cfg) -> None: ...
def s_capability(log: Log) -> None: ...
def s_config_capability(cfg: Cfg, log: Log) -> None: ...
def s_return_annotated(log: Log) -> Envelope: ...  # type: ignore[empty-body]
def s_from_job(p: Annotated[Envelope, FromJob("u")]) -> None: ...
def s_group_options(o: Opts) -> None: ...
def s_no_parameters() -> None: ...
def s_base_model_itself(m: BaseModel) -> None: ...


def s_everything(  # type: ignore[empty-body]
    cfg: Cfg,
    log: Log,
    o: Opts,
    p: Annotated[Envelope, FromJob("u")],
) -> Envelope: ...


# (function, expected config class). `contracts.md` §3.1 is the source of the
# first six rows; the last three close the edges.
MATRIX = [
    pytest.param(s_config, Cfg, id="config-only"),
    pytest.param(s_capability, None, id="capability-only"),
    pytest.param(s_config_capability, Cfg, id="config+capability"),
    pytest.param(s_return_annotated, None, id="return-annotation-is-never-config"),
    pytest.param(s_from_job, None, id="annotated-is-never-config"),
    pytest.param(s_group_options, None, id="group-options-is-never-config"),
    pytest.param(s_everything, Cfg, id="all-of-the-above"),
    pytest.param(s_no_parameters, None, id="no-parameters"),
    pytest.param(s_base_model_itself, None, id="base-model-itself"),
]


@DETECTORS
@pytest.mark.parametrize(("func", "expected"), MATRIX)
def test_every_site_returns_the_documented_answer(detect, func, expected) -> None:
    assert detect(func) is expected


@pytest.mark.parametrize(("func", "expected"), MATRIX)
def test_all_sites_agree(func, expected) -> None:
    """The invariant the three copies violated: same function, same answer."""
    answers = {
        "cold": detect_cold(func),
        "warm": detect_warm(func),
        "single-file": detect_single_file(func),
    }
    assert set(answers.values()) == {expected}, answers
