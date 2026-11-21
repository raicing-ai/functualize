"""Generate the parameter-contract matrix project and drive the real `func` against it.

Usage: python gen.py <func-binary> <project-dir> <out.json>
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from rows import HEADER, build  # noqa: E402

FUNC, PROJ, OUT = sys.argv[1], Path(sys.argv[2]), Path(sys.argv[3])


def module_for(row: dict) -> tuple[str, list[str]]:
    rid = row["id"].lower()
    decl = row["decl"].replace("{rid}", rid)
    extra = row["extra"].replace("{rid}", rid)
    probe = row["probe"]
    if decl.startswith("CLASS:"):
        sig = decl[len("CLASS:"):]
        src = (f"{extra}\n@job(group=\"{rid}g\")\nclass K_{rid}(BaseModel):\n"
               f"    def m(self, {sig}) -> str:\n        return _show(p=p)\n")
        return src, [f"{rid}g", "m"]
    if decl.startswith("GROUP:"):
        fld = decl[len("GROUP:"):]
        src = (f"{extra}\nclass G_{rid}(GroupOptions, group=\"{rid}g\"):\n    {fld}\n\n"
               f"JOB_GROUP = \"{rid}g\"\n\n@job\ndef run(opts: G_{rid} = None) -> str:\n"
               f"    return _show(p=opts.p)\n")
        return src, [f"{rid}g", "run"]
    if probe == "f":
        body = "_show(f=p.f)"
    elif decl.startswith("*,") or "q:" in decl:
        body = "_show(p=p)"
    else:
        body = "_show(p=p)"
    src = f"{extra}\n@job\ndef {rid}({decl}) -> str:\n    return {body}\n"
    return src, [rid]


def run(argv: list[str], cwd: Path, stdin: str | None = None) -> dict:
    env = dict(os.environ, COLUMNS="200", NO_COLOR="1", TERM="dumb",
               PYTHONPATH=str(Path(__file__).parent / "pylib"))
    env.pop("FUNCTUALIZE_CLI_OUTPUT", None)
    try:
        p = subprocess.run([FUNC, *argv], cwd=cwd, capture_output=True, text=True,
                           timeout=90, env=env,
                           input=stdin if stdin is not None else "")
        return {"argv": ["func", *argv], "rc": p.returncode,
                "stdout": p.stdout, "stderr": p.stderr}
    except subprocess.TimeoutExpired as e:
        return {"argv": ["func", *argv], "rc": "TIMEOUT",
                "stdout": str(e.stdout or ""), "stderr": str(e.stderr or "")}


def main() -> None:
    rows = build()
    if PROJ.exists():
        shutil.rmtree(PROJ)
    jobs = PROJ / ".functualize" / "jobs"
    jobs.mkdir(parents=True)
    here = Path(__file__).parent
    (PROJ / ".functualize" / "plugins").mkdir(parents=True)
    (PROJ / ".functualize" / "plugins" / "pc_probe.py").write_text(
        (here / "plugin_probe.py").read_text())
    for row in rows:
        src, path = module_for(row)
        row["path"] = path
        row["module"] = src
        (jobs / f"{row['id'].lower()}.py").write_text(
            ("from __future__ import annotations\n" if os.environ.get("PC_PEP563") == "1" else "") + HEADER + src)

    # project-wide surfaces, once
    glob = {
        "root_help": run(["--help"], PROJ),
        "bash": run(["builtin", "shell-init", "bash"], PROJ),
        "zsh": run(["builtin", "shell-init", "zsh"], PROJ),
        "info": run(["builtin", "info", "schema", "--kind", "job"], PROJ),
        "mcp": run(["mcp", "schema"], PROJ),
    }

    def per_row(row: dict) -> dict:
        path = row["path"]
        res = {"help": run([*path, "--help"], PROJ),
               "absent": run([*path], PROJ)}
        if row["flag"] is not None:
            if row["decl"].startswith("GROUP:"):
                res["flag"] = run([path[0], *row["flag"], *path[1:]], PROJ)
            else:
                res["flag"] = run([*path, *row["flag"]], PROJ)
        if row["pos"]:
            res["pos"] = run([*path, *row["pos"]], PROJ)
        if "Stdin()" in row["decl"]:
            res["stdin"] = run([*path], PROJ, stdin="piped\n")
        if "envvar" in row["decl"]:
            env_run = dict(os.environ, PYTHONPATH=str(Path(__file__).parent / "pylib"))
            env_run["R_TAG"] = "fromenv"
            env_run["R_TAGS"] = "e1 e2"
            p = subprocess.run([FUNC, *path], cwd=PROJ, capture_output=True,
                               text=True, timeout=90, env=env_run, input="")
            res["envvar"] = {"argv": ["R_TAG=fromenv R_TAGS='e1 e2' func", *path],
                             "rc": p.returncode, "stdout": p.stdout,
                             "stderr": p.stderr}
        return res

    with ThreadPoolExecutor(max_workers=6) as ex:
        results = list(ex.map(per_row, rows))
    for row, res in zip(rows, results):
        row["runs"] = res
    OUT.write_text(json.dumps({"rows": rows, "global": glob}, indent=1))


if __name__ == "__main__":
    main()
