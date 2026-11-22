"""First-use cost in a fresh process that has already imported functualize (as `func` has)."""
import sys, time
import functualize.app  # noqa: F401  — what a real `func` process has loaded before binding
from pydantic import TypeAdapter, Field, create_model
from typing import Optional
from pathlib import Path
from uuid import UUID
mode = sys.argv[1]
t = time.perf_counter()
if mode == "one":
    a = TypeAdapter(str); a.validate_python("x")
elif mode == "wide":
    for tp in (str, int, Optional[float], Path, UUID, list[str], Optional[list[Path]], tuple[str, ...], dict[str, str]):
        TypeAdapter(tp).validate_python
elif mode == "today":
    create_model("_Validate_x", level=(int, Field(ge=1, default=1))).model_validate({"level": 2})
print(f"{mode}: {(time.perf_counter() - t) * 1000:.1f} ms")
