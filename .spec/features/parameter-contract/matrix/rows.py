"""parameter-contract matrix: the declaration table.

Each row declares one job whose probed parameter is named ``p`` (or, for a
config-model row, the model field ``f``). ``gen.py`` turns every row into a job
module and drives the real ``func`` against it.
"""

from __future__ import annotations

HEADER = '''\
import dataclasses, enum, datetime as _dt, decimal, pathlib, uuid
from typing import Annotated, Optional
from pydantic import BaseModel, Field
from functualize.job import (
    job, Arg, Option, Stdin, FromJob, GroupOptions,
    RunContext, Log, Invoke, Prompt, Perf, Shell, Stdout, State, Sources,
    Freshness, JobContext, JobConfigView, TTY, Live, Vault,
)
from functualize.types import Secret
from functualize._primitives import Provide
from pathlib import Path
from uuid import UUID
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from provlib import ProvWidget

class Color(enum.Enum):
    RED = "red"
    BLUE = "blue"

class Widget:
    def __init__(self, v: str = "w") -> None:
        self.v = v

@dataclasses.dataclass
class Point:
    x: int = 0
    y: int = 0

class Body(BaseModel):
    x: int = 0

def _show(**kw):
    out = []
    for k, v in kw.items():
        r = repr(v)
        if len(r) > 80:
            r = r[:77] + "..."
        out.append(f"OBS {k}={r} type={type(v).__name__}")
    for line in out:
        print(line)
    return " ; ".join(out)
'''

# type label -> (annotation, CLI sample tokens, default literal)
SCALARS: list[tuple[str, str, list[str], str]] = [
    ("str", "str", ["x"], '"d"'),
    ("int", "int", ["7"], "3"),
    ("float", "float", ["1.5"], "0.5"),
    ("bool", "bool", [], "False"),  # flag form, no value
    ("Path", "Path", ["/tmp/x"], 'Path("/tmp/d")'),
    ("UUID", "UUID", ["12345678-1234-5678-1234-567812345678"], 'UUID(int=0)'),
    ("date", "date", ["2026-01-02"], "date(2026, 1, 1)"),
    ("datetime", "datetime", ["2026-01-02T03:04:05"], "datetime(2026, 1, 1)"),
    ("time", "time", ["03:04:05"], "time(1, 2, 3)"),
    ("timedelta", "timedelta", ["PT1H"], "timedelta(seconds=1)"),
    ("Decimal", "Decimal", ["1.25"], 'Decimal("0.5")'),
    ("Enum", "Color", ["red"], "Color.RED"),
    ("Secret[str]", "Secret[str]", ["s3cr3t"], 'Secret("d")'),
]

INJECTED = [
    "RunContext", "Log", "Invoke", "Prompt", "Perf", "Shell", "Stdout",
    "State", "Sources", "Freshness", "JobContext", "JobConfigView", "TTY",
    "Live", "Vault",
]


def _row(rid, axis, decl, *, flag=None, pos=None, extra="", path=None,
         body=None, probe="p", files=None, label=None, flagname="--p"):
    return {
        "id": rid,
        "axis": axis,
        "label": label or decl,
        "decl": decl,
        "flag": flag,  # argv tail for "supply as flag"
        "pos": pos,  # argv tail for "supply positionally"
        "extra": extra,
        "path": path,
        "body": body,
        "probe": probe,
        "files": files or {},
        "flagname": flagname,
    }


def build() -> list[dict]:
    rows: list[dict] = []
    n = 0

    def nid(prefix):
        nonlocal n
        n += 1
        return f"{prefix}{n:03d}"

    # ── A. bare scalars × {required, default, Optional[T]=None, T|None=None}
    for label, ann, sample, default in SCALARS:
        flag = ["--p", *sample] if sample else ["--p"]
        pos = sample or None
        rows.append(_row(nid("A"), "scalar", f"p: {ann}", flag=flag, pos=pos,
                         label=f"p: {label}"))
        rows.append(_row(nid("A"), "scalar", f"p: {ann} = {default}", flag=flag,
                         pos=pos, label=f"p: {label} = <default>"))
        rows.append(_row(nid("A"), "scalar", f"p: Optional[{ann}] = None",
                         flag=flag, pos=pos, label=f"p: Optional[{label}] = None"))
        rows.append(_row(nid("A"), "scalar", f"p: {ann} | None = None",
                         flag=flag, pos=pos, label=f"p: {label} | None = None"))

    # ── B. lists
    for label, ann, sample, _ in SCALARS:
        two = (sample * 2) if sample else []
        flag = []
        for tok in (sample or ["x"]) * 2:
            flag += ["--p", tok]
        if not sample:  # bool element: values must be spelled
            flag = ["--p", "true", "--p", "false"]
            two = ["true", "false"]
        rows.append(_row(nid("B"), "list", f"p: list[{ann}]", flag=flag,
                         pos=two, label=f"p: list[{label}]"))
    s2 = ["--p", "a", "--p", "b"]
    for decl in [
        "p: list[str] | None = None",
        "p: Optional[list[str]] = None",
        "p: list[str] | None",
        "p: list[str] = []",
        "p: list[str] = None",
        "p: list[list[str]]",
        "p: Annotated[list[str], Option()]",
        "p: Annotated[list[str] | None, Option()] = None",
        "p: Annotated[Optional[list[str]], Option()] = None",
        "p: Annotated[list[int], Option()]",
        "p: Annotated[list[Color], Option()]",
        "p: Annotated[list[str], Arg()]",
        "p: Annotated[list[str], Option(\"-t\", \"--tags\", help=\"tags\", hidden=True, envvar=\"R_TAGS\")] = []",
    ]:
        flag = s2
        if "Color" in decl:
            flag = ["--p", "red", "--p", "blue"]
        if "int]" in decl:
            flag = ["--p", "1", "--p", "2"]
        if "--tags" in decl:
            flag = ["--tags", "a", "-t", "b"]
        rows.append(_row(nid("B"), "list", decl, flag=flag, pos=["a", "b"]))

    # ── C. other generics and custom classes
    for decl, flag in [
        ("p: tuple[str, ...]", ["--p", "a", "--p", "b"]),
        ("p: tuple[str, ...] = ()", ["--p", "a", "--p", "b"]),
        ("p: tuple[str, int]", ["--p", "a", "1"]),
        ("p: dict[str, str]", ["--p", "k=v"]),
        ("p: dict[str, str] = {}", ["--p", "k=v"]),
        ("p: set[str]", ["--p", "a", "--p", "b"]),
        ("p: Widget", ["--p", "w"]),
        ("p: Widget | None = None", ["--p", "w"]),
        ("p: Point", ["--p", "1"]),
        ("p: str | int", ["--p", "x"]),
        ("p: object", ["--p", "x"]),
        ("p", ["--p", "x"]),
        ("p = \"d\"", ["--p", "x"]),
    ]:
        rows.append(_row(nid("C"), "generic", decl, flag=flag, pos=flag[1:2]))

    # ── D. markers
    for decl, flag, pos, fname in [
        ("p: Annotated[str, Arg()]", None, ["x"], "--p"),
        ("p: Annotated[str, Arg()] = \"d\"", ["--p", "x"], ["x"], "--p"),
        ("p: Annotated[str, Option()]", ["--p", "x"], ["x"], "--p"),
        ("p: Annotated[str, Option()] = \"d\"", ["--p", "x"], ["x"], "--p"),
        ("p: Annotated[str, Option(\"-t\")] = \"d\"", ["-t", "x"], ["x"], "-t"),
        ("p: Annotated[str, Option(\"-t\", \"--tags\", help=\"the tag\", hidden=True, envvar=\"R_TAG\")] = \"d\"", ["--tags", "x"], ["x"], "--tags"),
        ("p: Annotated[str, Stdin()] = \"\"", ["--p", "x"], ["x"], "--p"),
        ("p: Annotated[str, Stdin()]", ["--p", "x"], ["x"], "--p"),
        ("p: Annotated[Optional[str], Option()] = None", ["--p", "x"], ["x"], "--p"),
        ("p: Annotated[str | None, Arg()] = None", ["--p", "x"], ["x"], "--p"),
        ("p: Annotated[str, Arg(), Option()]", ["--p", "x"], ["x"], "--p"),
        ("p: Annotated[str, Option(\"-a\"), Option(\"-b\")] = \"d\"", ["-a", "x"], ["x"], "-a"),
        ("p: Annotated[dict[str, str], Option()] = {}", ["--p", "k=v"], ["k=v"], "--p"),
        ("p: Annotated[Widget, Option()] = None", ["--p", "w"], ["w"], "--p"),
        ("p: Annotated[tuple[str, ...], Option()] = ()", ["--p", "a", "--p", "b"], ["a"], "--p"),
        ("p: Annotated[int, Field(ge=1)] = 1", ["--p", "0"], ["0"], "--p"),
    ]:
        rows.append(_row(nid("D"), "marker", decl, flag=flag, pos=pos, flagname=fname))

    # ── E. injection
    for name in INJECTED:
        rows.append(_row(nid("E"), "injected", f"p: {name}", flag=["--p", "x"], pos=["x"]))
        rows.append(_row(nid("E"), "injected", f"p: {name} | None = None", flag=["--p", "x"], pos=["x"]))
    rows.append(_row(nid("E"), "injected", "p: Annotated[Widget, Provide(\"w\")]",
                     flag=["--p", "x"], pos=["x"]))
    rows.append(_row(nid("E"), "injected", "p: Annotated[str, Provide(\"s\")]",
                     flag=["--p", "x"], pos=["x"]))
    up = "\n@job\ndef {rid}_up() -> str:\n    return \"upval\"\n"
    rows.append(_row(nid("E"), "injected", "p: Annotated[str, FromJob({rid}_up)]",
                     flag=["--p", "x"], pos=["x"], extra=up))
    rows.append(_row(nid("E"), "injected", "p: Annotated[str, FromJob(\"{rid}-up\")]",
                     flag=["--p", "x"], pos=["x"], extra=up))
    rows.append(_row(nid("E"), "injected", "p: FromJob[{rid}_up]",
                     flag=["--p", "x"], pos=["x"], extra=up))

    # ── F. config models (probe the field `f`)
    for fdecl, flag in [
        ("f: str = \"d\"", ["--f", "x"]),
        ("f: int", ["--f", "7"]),
        ("f: list[str] = Field(default_factory=list)", ["--f", "a", "--f", "b"]),
        ("f: Optional[str] = None", ["--f", "x"]),
        ("f: list[str] | None = None", ["--f", "a", "--f", "b"]),
        ("f: Secret[str] = Secret(\"d\")", ["--f", "s3cr3t"]),
        ("f: str = Field(default=\"d\", description=\"the f\")", ["--f", "x"]),
        ("f: dict[str, str] = Field(default_factory=dict)", ["--f", "k=v"]),
        ("f: Body = Field(default_factory=Body)", ["--f", "x"]),
        ("f: Annotated[list[str], Option(\"-t\")] = Field(default_factory=list)", ["-t", "a", "-t", "b"]),
    ]:
        cls = "Cfg_{rid}"
        extra = f"\nclass {cls}(BaseModel):\n    {fdecl}\n"
        rows.append(_row(nid("F"), "config", f"p: {cls}", flag=flag, pos=None,
                         extra=extra, probe="f", label=f"cfg field {fdecl}",
                         flagname=flag[0]))

    # ── G. signature shape
    rows.append(_row(nid("G"), "shape", "*, p: str", flag=["--p", "x"], pos=["x"]))
    rows.append(_row(nid("G"), "shape", "*, p: list[str]", flag=["--p", "a", "--p", "b"], pos=["a"]))
    rows.append(_row(nid("G"), "shape", "p: str, /", flag=["--p", "x"], pos=["x"]))
    rows.append(_row(nid("G"), "shape", "q: str = \"d\", *, p: str", flag=["--p", "x"], pos=["x"]))
    # The wire surfaces are given p and q, so the command line supplies both too.
    rows.append(_row(nid("G"), "shape", "p: str, q: list[str]",
                     flag=["x", "--q", "a", "--q", "b"], pos=["x", "--q", "a", "--q", "b"]))
    # class-method job
    rows.append(_row(nid("G"), "shape", "CLASS:p: list[str]", flag=["--p", "a", "--p", "b"],
                     pos=["a"], label="@job class method, p: list[str]"))
    rows.append(_row(nid("G"), "shape", "CLASS:p: str = \"d\"", flag=["--p", "x"],
                     pos=["x"], label="@job class method, p: str = \"d\""))
    # GroupOptions field reaching a job
    rows.append(_row(nid("G"), "shape", "GROUP:p: list[str] = []",
                     flag=["--p", "a", "--p", "b"], pos=None,
                     label="GroupOptions field p: list[str] = []"))
    rows.append(_row(nid("G"), "shape", "GROUP:p: str = \"d\"",
                     flag=["--p", "x"], pos=None,
                     label="GroupOptions field p: str = \"d\""))

    # ── H. DI with a REGISTERED provider (the probe plugin registers
    #    ProvWidget by type and by qualifier "w", and str by qualifier "s2")
    for decl in [
        "p: Annotated[ProvWidget, Provide(\"w\")]",
        "p: ProvWidget",
        "p: ProvWidget | None = None",
        "p: Annotated[str, Provide(\"s2\")]",
        "p: Annotated[ProvWidget, Provide(\"nope\")]",
    ]:
        rows.append(_row(nid("H"), "provider", decl, flag=["--p", "x"], pos=["x"]))
    return rows
