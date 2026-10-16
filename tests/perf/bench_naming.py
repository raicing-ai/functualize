"""Compare the frozen naming loop and current policy in one process.

Run from the repository root: ``uv run python tests/perf/bench_naming.py``.
"""

from __future__ import annotations

import platform
import sys
import time
from collections.abc import Callable
from pathlib import Path

from functualize._types.naming import normalize_segment

# Direct script execution puts tests/perf, rather than the repository root, on
# sys.path. The reference loop lives in the discovery test module.
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from tests.discovery.test_naming import _pre_nfkc_segment  # noqa: E402


def _round(fn: Callable[[str], str], value: str, calls: int) -> float:
    start = time.perf_counter_ns()
    for _ in range(calls):
        fn(value)
    return (time.perf_counter_ns() - start) / calls


def measure(
    value: str, *, rounds: int = 15, calls: int = 50_000
) -> tuple[float, float]:
    """Return minimum old/new nanoseconds per call from interleaved rounds."""
    before: list[float] = []
    after: list[float] = []
    for index in range(rounds):
        if index % 2:
            after.append(_round(normalize_segment, value, calls))
            before.append(_round(_pre_nfkc_segment, value, calls))
        else:
            before.append(_round(_pre_nfkc_segment, value, calls))
            after.append(_round(normalize_segment, value, calls))
    return min(before), min(after)


def main() -> None:
    print(f"python={platform.python_version()} host={platform.node()}")
    for value in ("deploy-web", "myJobName", "job_aaǆ", "naïve_x"):
        before, after = measure(value)
        print(
            f"{value}: pre={before:.1f} ns/call "
            f"post={after:.1f} ns/call ratio={after / before:.3f}x"
        )


if __name__ == "__main__":
    main()
