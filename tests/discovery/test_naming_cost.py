"""Bound work done by the job-name policy on its common path."""

from __future__ import annotations

import unicodedata
import warnings

import pytest

from functualize._types import naming
from tests.perf.bench_naming import measure


class _CountingUnicode:
    def __init__(self) -> None:
        self.calls = 0

    def normalize(self, form: str, value: str) -> str:
        self.calls += 1
        return unicodedata.normalize(form, value)


@pytest.fixture
def counter(monkeypatch: pytest.MonkeyPatch) -> _CountingUnicode:
    proxy = _CountingUnicode()
    monkeypatch.setattr(naming, "unicodedata", proxy)
    return proxy


@pytest.mark.parametrize(
    ("value", "calls"),
    [
        ("deploy-web", 0),
        ("myJobName", 0),
        ("HTTPServer", 0),
        ("build_wheel", 0),
        ("a", 0),
        ("", 0),
        ("job_aaǆ", 1),
        ("naïve_x", 1),
        ("ｄｅｐｌｏｙ", 1),
    ],
)
def test_segment_normalizes_once_or_not_at_all(
    counter: _CountingUnicode, value: str, calls: int
) -> None:
    naming.normalize_segment(value)
    assert counter.calls == calls


@pytest.mark.parametrize(
    ("value", "calls"),
    [
        ("web.deploy", 0),
        ("ǆ_ops.run_it", 2),
        ("ｄｅｐｌｏｙ．ｗｅｂ", 1),
        ("naïve.x", 2),
        ("a.ǆ.b", 2),
    ],
)
def test_full_name_normalizes_whole_name_then_non_ascii_segments(
    counter: _CountingUnicode, value: str, calls: int
) -> None:
    naming.normalize_name(value)
    assert counter.calls == calls


def test_ascii_resolution_does_not_enter_unicode_normalizer(
    counter: _CountingUnicode,
) -> None:
    assert naming.resolve_name("build_wheel", ["build-wheel", "x.y"]) == "build-wheel"
    assert counter.calls == 0


@pytest.mark.parametrize("value", ["deploy", "naïve_x"])
def test_stable_input_returns_the_identical_object(value: str) -> None:
    assert naming._nfkc(value) is value


@pytest.mark.slow
@pytest.mark.parametrize("value", ["deploy-web", "myJobName"])
def test_ascii_cost_ratio_reports_observation(value: str) -> None:
    before, after = measure(value)
    warnings.warn(
        f"{value}: pre={before:.1f} ns/call post={after:.1f} ns/call "
        f"ratio={after / before:.3f}x (report only)",
        stacklevel=1,
    )
