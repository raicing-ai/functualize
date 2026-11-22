"""H3: what does a pydantic-TypeAdapter binder cost, per invocation?

Only the invoked job is bound, so the per-invocation cost is:
  build  — one TypeAdapter per parameter of that job (built once per process), plus
  bind   — one validate_python per supplied argument.
Compared against today's engine step, ArgValidator (create_model over Field() params).
Run with the repository's interpreter: <venv>/bin/python binder_cost.py
"""

from __future__ import annotations

import statistics
import time
from datetime import date, datetime, timedelta
from decimal import Decimal
from enum import Enum
from pathlib import Path
from typing import Annotated, Optional
from uuid import UUID

from pydantic import Field, TypeAdapter, create_model


class Color(Enum):
    RED = "red"
    BLUE = "blue"


# A deliberately wide signature: every shape class the contract admits.
SHAPES = {
    "service": (str, "api"),
    "count": (int, "7"),
    "ratio": (Optional[float], "1.5"),
    "out": (Path, "/tmp/x"),
    "rid": (UUID, "12345678-1234-5678-1234-567812345678"),
    "day": (date, "2026-01-02"),
    "at": (Optional[datetime], "2026-01-02T03:04:05"),
    "after": (timedelta, "PT1H"),
    "amount": (Decimal, "1.25"),
    "color": (Color, "red"),
    "targets": (list[str], ["eu", "us"]),
    "paths": (Optional[list[Path]], ["/a", "/b"]),
    "tags": (tuple[str, ...], ["a", "b"]),
    "patch": (dict[str, str], {"k": "v"}),
    "level": (Annotated[int, Field(ge=1)], 3),
}


def timeit(fn, n):
    samples = []
    for _ in range(n):
        t = time.perf_counter_ns()
        fn()
        samples.append(time.perf_counter_ns() - t)
    return statistics.median(samples) / 1000, max(samples) / 1000  # µs


def build():
    return {k: TypeAdapter(t) for k, (t, _) in SHAPES.items()}


def main() -> None:
    n_params = len(SHAPES)
    b_med, b_max = timeit(build, 50)
    adapters = build()
    raw = {k: v for k, (_, v) in SHAPES.items()}

    def bind():
        return {k: adapters[k].validate_python(v) for k, v in raw.items()}

    v_med, v_max = timeit(bind, 2000)
    out = bind()
    assert isinstance(out["rid"], UUID) and isinstance(out["paths"][0], Path) and out["tags"] == ("a", "b")
    assert out["after"] == timedelta(hours=1) and out["color"] is Color.RED

    # today's engine step: create_model over the Field() params only
    def argvalidator_build():
        return create_model("_Validate_x", level=(int, Field(ge=1, default=1)))
    a_med, _ = timeit(argvalidator_build, 50)

    print(f"parameters in the signature: {n_params}")
    print(f"build  (one TypeAdapter per parameter, once per process): median {b_med:,.0f} µs, max {b_max:,.0f} µs "
          f"= {b_med / n_params:,.0f} µs per parameter")
    print(f"bind   (validate every argument, per call):                median {v_med:,.1f} µs, max {v_max:,.1f} µs")
    print(f"today  ArgValidator create_model, 1 Field() param, build:  median {a_med:,.0f} µs")


if __name__ == "__main__":
    main()
