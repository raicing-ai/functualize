"""Frozen parity snapshots for the click-native param builder.

Each expected tuple was captured from typer's actual ``click.Parameter`` output
(via the old schema→signature→typer→click pipeline) at the Phase 1 boundary and
verified param-for-param. Freezing them here keeps a permanent regression guard
for ``build_click_params`` that does not depend on typer being importable — the
whole-suite CLI behavior tests remain the broader guard.

Snapshot tuple layout:
    (name, param_cls, opts, secondary_opts, type_repr,
     required, default_repr, nargs, is_flag, multiple)
"""

from __future__ import annotations

import enum
import itertools
from pathlib import Path
from typing import Annotated

from pydantic import BaseModel

from functualize.app.adapters.click_params import build_click_params
from functualize.job.markers import Arg, Option, Stdin


class Color(enum.Enum):
    RED = "red"
    GREEN = "green"


class Cfg(BaseModel):
    api_url: str
    retries: int = 3
    enabled: bool = False
    opt_flag: bool = True
    color: Color = Color.RED
    maybe: str | None = None
    tags: list[str] = []


def job_args(
    target: Annotated[str, Arg(help="the target")],
    count: Annotated[int, Arg()] = 1,
    files: Annotated[list[str], Arg(help="files")] = [],  # noqa: B006 — corpus fixture
) -> str:
    return "x"


def job_options(
    verbose: Annotated[bool, Option("-v")] = False,
    target: Annotated[str, Option("-t", "--target", help="tgt")] = "prod",
    name: Annotated[str, Option("--name")] = "n",
) -> str:
    return "x"


def job_stdin(data: Annotated[str, Stdin(flag="--data", help="input")] = "") -> str:
    return "x"


def job_plain(count: int = 5, flag: bool = False, path: Path | None = None) -> str:
    return "x"


def job_nodefault(x: int, y: str = "hi") -> str:
    return "x"


def job_config(cfg: Cfg) -> str:
    return "x"


def plugin_cb(
    directory: str,
    name: str | None = None,
    port: int = 8080,
    http: bool = False,
) -> str:
    return "x"


def _snap(p: object) -> tuple:
    return (
        p.name,  # type: ignore[attr-defined]
        type(p).__name__,
        tuple(p.opts),  # type: ignore[attr-defined]
        tuple(p.secondary_opts),  # type: ignore[attr-defined]
        repr(p.type),  # type: ignore[attr-defined]
        p.required,  # type: ignore[attr-defined]
        repr(p.default),  # type: ignore[attr-defined]
        p.nargs,  # type: ignore[attr-defined]
        getattr(p, "is_flag", None),
        getattr(p, "multiple", None),
    )


# Expected click.Parameter shapes — the verified typer output, frozen.
EXPECTED: dict[str, list[tuple]] = {
    "job_args": [
        (
            "target",
            "Argument",
            ("target",),
            (),
            "STRING",
            True,
            "Sentinel.UNSET",
            1,
            None,
            False,
        ),
        ("count", "Argument", ("count",), (), "INT", False, "1", 1, None, False),
        (
            "files",
            "Argument",
            ("files",),
            (),
            "STRING",
            True,
            "Sentinel.UNSET",
            -1,
            None,
            False,
        ),
    ],
    "job_options": [
        (
            "verbose",
            "Option",
            ("--verbose", "-v"),
            (),
            "BOOL",
            False,
            "False",
            1,
            True,
            False,
        ),
        (
            "target",
            "Option",
            ("--target", "-t"),
            (),
            "STRING",
            False,
            "'prod'",
            1,
            False,
            False,
        ),
        ("name", "Option", ("--name",), (), "STRING", False, "'n'", 1, False, False),
    ],
    "job_stdin": [
        ("data", "Option", ("--data",), (), "STRING", False, "None", 1, False, False),
    ],
    "job_plain": [
        ("count", "Option", ("--count",), (), "INT", False, "5", 1, False, False),
        (
            "flag",
            "Option",
            ("--flag",),
            ("--no-flag",),
            "BOOL",
            False,
            "False",
            1,
            True,
            False,
        ),
    ],
    "job_nodefault": [
        ("x", "Argument", ("x",), (), "INT", True, "Sentinel.UNSET", 1, None, False),
        ("y", "Option", ("--y",), (), "STRING", False, "'hi'", 1, False, False),
    ],
    "job_config": [
        (
            "api_url",
            "Option",
            ("--api-url",),
            (),
            "STRING",
            False,
            "None",
            1,
            False,
            False,
        ),
        (
            "retries",
            "Option",
            ("--retries",),
            (),
            "INT",
            False,
            "None",
            1,
            False,
            False,
        ),
        (
            "enabled",
            "Option",
            ("--enabled",),
            (),
            "BOOL",
            False,
            "None",
            1,
            True,
            False,
        ),
        (
            "opt_flag",
            "Option",
            ("--opt-flag",),
            (),
            "BOOL",
            False,
            "None",
            1,
            True,
            False,
        ),
        (
            "color",
            "Option",
            ("--color",),
            (),
            "Choice(['red', 'green'])",
            False,
            "None",
            1,
            False,
            False,
        ),
        ("maybe", "Option", ("--maybe",), (), "STRING", False, "None", 1, False, False),
        ("tags", "Option", ("--tags",), (), "STRING", False, "None", 1, False, True),
    ],
    # Raw plugin callback (apply_job_filter=False): typer applies no config/CLI
    # filtering, so str | None survives as an option and no-default → argument.
    "plugin_cb": [
        (
            "directory",
            "Argument",
            ("directory",),
            (),
            "STRING",
            True,
            "Sentinel.UNSET",
            1,
            None,
            False,
        ),
        ("name", "Option", ("--name",), (), "STRING", False, "None", 1, False, False),
        ("port", "Option", ("--port",), (), "INT", False, "8080", 1, False, False),
        (
            "http",
            "Option",
            ("--http",),
            ("--no-http",),
            "BOOL",
            False,
            "False",
            1,
            True,
            False,
        ),
    ],
}


def _check(fn, cc, expected, *, raw=False):
    params, _, _ = build_click_params(fn, cc, apply_job_filter=not raw)
    got = [_snap(p) for p in params]
    for want, g in itertools.zip_longest(expected, got):
        assert want == g, f"\nexpected: {want}\ngot:      {g}"


def test_job_args():
    _check(job_args, None, EXPECTED["job_args"])


def test_job_options():
    _check(job_options, None, EXPECTED["job_options"])


def test_job_stdin():
    _check(job_stdin, None, EXPECTED["job_stdin"])


def test_job_plain():
    _check(job_plain, None, EXPECTED["job_plain"])


def test_job_nodefault():
    _check(job_nodefault, None, EXPECTED["job_nodefault"])


def test_job_config():
    _check(job_config, Cfg, EXPECTED["job_config"])


def test_raw_plugin_callback():
    _check(plugin_cb, None, EXPECTED["plugin_cb"], raw=True)


def test_custom_flag_binds_to_param_name():
    """A custom flag whose spelling differs from the param must still bind the
    param's name — else click infers a wrong name and the engine callback gets
    the wrong keyword (regression guard)."""

    def job_stdin_custom(
        payload: Annotated[str, Stdin(flag="--data")] = "",
    ) -> str:
        return "x"

    def job_opt_custom(
        target: Annotated[str, Option("--dest")] = "x",
    ) -> str:
        return "x"

    p_stdin = {p.name: p for p in build_click_params(job_stdin_custom, None)[0]}
    assert "payload" in p_stdin
    assert p_stdin["payload"].opts == ["--data"]

    p_opt = {p.name: p for p in build_click_params(job_opt_custom, None)[0]}
    assert "target" in p_opt
    assert p_opt["target"].opts == ["--dest"]
