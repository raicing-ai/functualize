"""Cold-boot pass (pitfalls.md #23: "run every end-to-end assertion twice").

Each row gets its own one-module project; `.functualize/cache.json` is deleted
before every command, so every call below is a cold boot. Compared field by field
against the warm matrix (out.json) with analyze.facts().

Usage: python cold.py <func> <root-dir> <out-cold.json>
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

FUNC, ROOT, OUT = str(Path(sys.argv[1]).resolve()), Path(sys.argv[2]).resolve(), Path(sys.argv[3])
HERE = Path(__file__).parent
warm = json.loads((HERE / "out.json").read_text())
HEADER = __import__("rows").HEADER


def run(proj: Path, argv: list[str]) -> dict:
    cache = proj / ".functualize" / "cache.json"
    if cache.exists():
        cache.unlink()
    env = dict(os.environ, COLUMNS="200", NO_COLOR="1", TERM="dumb", PYTHONPATH=str(HERE / "pylib"))
    p = subprocess.run([FUNC, *argv], cwd=proj, capture_output=True, text=True, timeout=120,
                       env=env, input="")
    return {"argv": ["func", *argv], "rc": p.returncode, "stdout": p.stdout, "stderr": p.stderr}


def per_row(row: dict) -> tuple[str, dict, dict]:
    rid = row["id"].lower()
    proj = ROOT / rid
    if proj.exists():
        shutil.rmtree(proj)
    (proj / ".functualize" / "jobs").mkdir(parents=True)
    (proj / ".functualize" / "plugins").mkdir(parents=True)
    (proj / ".functualize" / "plugins" / "pc_probe.py").write_text((HERE / "plugin_probe.py").read_text())
    (proj / ".functualize" / "jobs" / f"{rid}.py").write_text(HEADER + row["module"])
    path = row["path"]
    runs = {"help": run(proj, [*path, "--help"]), "absent": run(proj, [*path])}
    if row["flag"] is not None:
        argv = [path[0], *row["flag"], *path[1:]] if row["decl"].startswith("GROUP:") else [*path, *row["flag"]]
        runs["flag"] = run(proj, argv)
    if row["pos"]:
        runs["pos"] = run(proj, [*path, *row["pos"]])
    glob = {"bash": run(proj, ["builtin", "shell-init", "bash"]),
            "zsh": run(proj, ["builtin", "shell-init", "zsh"]),
            "info": run(proj, ["builtin", "info", "schema", "--kind", "job"]),
            "mcp": run(proj, ["mcp", "schema"])}
    return row["id"], runs, glob


def main() -> None:
    ROOT.mkdir(parents=True, exist_ok=True)
    with ThreadPoolExecutor(max_workers=6) as ex:
        res = list(ex.map(per_row, warm["rows"]))
    OUT.write_text(json.dumps({rid: {"runs": r, "global": g} for rid, r, g in res}, indent=1))
    print(f"cold: {len(res)} rows")


if __name__ == "__main__":
    main()
