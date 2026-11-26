"""Build the parity test's project from the declaration matrix, and boot it.

One project holds every row of ``tests/_support/parameter_matrix.py`` as its
own job module, the probe plugin (``_parity_probe.SOURCE``) and a ``provlib``
package providing ``ProvWidget``. :func:`dump` runs the real ``func`` in a
subprocess — the first run after :func:`write_project` is a cold boot, the
second reads the cache — and returns what every surface did for every row.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

from tests._support.parameter_matrix import ROWS, module_source
from tests.surfaces._parity_probe import SOURCE as PROBE_SOURCE

PROVLIB = """
class ProvWidget:
    def __init__(self, v: str = "") -> None:
        self.v = v
"""

#: One JSON value per element type: what a wire caller sends for a row.
_WIRE = {
    "str": "x",
    "int": 7,
    "float": 1.5,
    "bool": True,
    "Path": "/tmp/x",
    "UUID": "12345678-1234-5678-1234-567812345678",
    "date": "2026-01-02",
    "datetime": "2026-01-02T03:04:05",
    "time": "03:04:05",
    "timedelta": "PT1H",
    "Decimal": "1.25",
    "Color": "red",
    "Enum": "red",
    "Secret[str]": "s3cr3t",
}
#: Rows whose value the label cannot imply.
_OVERRIDE: dict[str, Any] = {
    "B071": [["a"], ["b"]],
    "C081": ["a", 1],
    "C082": {"k": "v"},
    "C083": {"k": "v"},
    "C085": "w",
    "C086": "w",
    "C087": {"x": 1, "y": 2},
    "D104": {"k": "v"},
    "D105": "w",
    "D107": 2,
    "F144": 7,
    "F150": {"k": "v"},
    "F151": {"x": 5},
}


def wire_value(row: dict[str, Any]) -> Any:
    """The JSON value a wire caller sends for ``row``'s probed parameter."""
    if row["id"] in _OVERRIDE:
        return _OVERRIDE[row["id"]]
    label = row["label"]
    container = re.search(
        r"\b[pf]: (?:Annotated\[)?(?:Optional\[)?(list|tuple|set)\[([A-Za-z]+(?:\[str\])?)",
        label,
    )
    if container:
        element = container.group(2)
        if element in ("Color", "Enum"):
            return ["red", "blue"]
        return [_WIRE.get(element, "a"), _WIRE.get(element, "b")]
    scalar = re.search(r"\b[pf]: (?:Optional\[)?([A-Za-z]+(?:\[str\])?)", label)
    if scalar and scalar.group(1) in _WIRE:
        return _WIRE[scalar.group(1)]
    return "x"


def is_group_row(row: dict[str, Any]) -> bool:
    return row["declaration"].startswith("GROUP:")


def spec_row(row: dict[str, Any]) -> dict[str, Any]:
    """What the probe drives for ``row``: the job, the text, the arguments."""
    path, probe = list(row["path"]), row["probe"]
    value = wire_value(row)
    group = {probe: value} if is_group_row(row) else None
    given = {} if group else {probe: value}
    if row["id"] == "G157":  # its other required parameter, on every surface
        given = {"p": "x", "q": ["a", "b"]}
    argv = list(row["flag_argv"])
    if row["id"] == "D107":  # the matrix's argv probes the `ge=1` refusal
        argv = ["--p", "2"]
    if group:
        flag_text = " ".join([path[0], *argv, *path[1:]])
    else:
        flag_text = " ".join([*path, *argv])
    if row["expected_verdict"] == "ACCEPTED_POSITIONAL":
        flag_text = " ".join([*path, *row["pos_argv"]])
    if row["id"] == "G157":  # p positionally, then its required list q
        flag_text = " ".join([*path, "x", "--q", "a", "--q", "b"])
    return {
        "id": row["id"],
        "job": ".".join(path),
        "path": path,
        "bar": (f"{path[0]} --" if group else " ".join(path) + " --"),
        "tui": {"given": flag_text, "absent": " ".join(path)},
        "args": {"given": given, "absent": {}},
        "mcp": {"given": {**given, **(group or {})}, "absent": {}},
        "group": group,
    }


#: Rows per project. One process runs every surface for each row it holds,
#: and the default file store rewrites itself on every run, so one project
#: for all 166 rows costs minutes; groups of this size run in seconds each
#: and in parallel under xdist.
GROUP_SIZE = 21
GROUPS: tuple[tuple[dict[str, Any], ...], ...] = tuple(
    tuple(ROWS[start : start + GROUP_SIZE]) for start in range(0, len(ROWS), GROUP_SIZE)
)


def write_project(
    root: Path, *, future: bool, rows: tuple[dict[str, Any], ...] = ROWS
) -> Path:
    jobs = root / "jobs"
    jobs.mkdir(parents=True)
    (root / "pyproject.toml").write_text(
        '[project]\nname = "parity"\nversion = "0"\n\n'
        '[tool.functualize]\njobs_directories = ["jobs"]\n',
        encoding="utf-8",
    )
    for row in rows:
        source = module_source(row, future_annotations=future)
        (jobs / f"{row['id'].lower()}.py").write_text(source, encoding="utf-8")
    plugins = root / ".functualize" / "plugins"
    plugins.mkdir(parents=True)
    (plugins / "parity_probe.py").write_text(PROBE_SOURCE, encoding="utf-8")
    (root / "pylib").mkdir()
    (root / "pylib" / "provlib.py").write_text(PROVLIB, encoding="utf-8")
    (root / "spec.json").write_text(
        json.dumps([spec_row(row) for row in rows]), encoding="utf-8"
    )
    return root


def environment(project: Path) -> dict[str, str]:
    home = project / ".home"
    return {
        **os.environ,
        "HOME": str(home),
        "XDG_CONFIG_HOME": str(home / "config"),
        "XDG_CACHE_HOME": str(home / "cache"),
        "XDG_STATE_HOME": str(home / "state"),
        "XDG_DATA_HOME": str(home / "data"),
        "PYTHONPATH": str(project / "pylib"),
    }


def func(
    project: Path, *argv: str, timeout: int = 240
) -> subprocess.CompletedProcess[str]:
    """Run the real ``func`` in ``project``, as a separate process."""
    return subprocess.run(  # noqa: S603
        [sys.executable, "-m", "functualize", *argv],
        cwd=project,
        env=environment(project),
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
        stdin=subprocess.DEVNULL,
    )


def dump(project: Path, label: str) -> dict[str, Any]:
    """Boot ``func`` once and return every surface's observations per row."""
    out = project / f"{label}.json"
    # The run history is not under test, and the default file store rewrites
    # itself on every run: starting each boot without it keeps a boot's cost
    # linear in its own runs. The discovery cache (`cache.json`) stays, so the
    # second boot is still the warm one.
    (project / ".functualize" / "runs.json").unlink(missing_ok=True)
    done = func(
        project, "parity", "dump", "--spec", "spec.json", "--out", str(out), timeout=480
    )
    assert done.returncode == 0, done.stdout[-3000:] + done.stderr[-3000:]
    data: dict[str, Any] = json.loads(out.read_text(encoding="utf-8"))
    return data
