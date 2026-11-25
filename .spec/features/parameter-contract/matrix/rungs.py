"""Config ladder rungs: CLI → env → config file → default, per config-field row.

Usage: python rungs.py <func> <project> <out.json>

Five scenarios, each run over every row in parallel:
  none      no env var, no config file
  env       <SECTION>_<FIELD> set
  file      ./config.base.toml carries the value
  env+file  both (env must win, per docs/guides/job-config.md)
  cli+all   flag given as well (CLI must win)
Controls: a002 (plain signature parameter: must ignore env and file, per
SD/17137691 Outcome) and g160g/g161g (GroupOptions fields).
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

FUNC, PROJ, OUT = str(Path(sys.argv[1]).resolve()), Path(sys.argv[2]).resolve(), Path(sys.argv[3])

# id: (argv path, env var, env value, toml section, toml line, cli argv)
CASES = {
    "F143": (["f143"], "F143_F", "fromenv", "f143", 'f = "fromfile"', ["--f", "fromcli"]),
    "F144": (["f144"], "F144_F", "8", "f144", "f = 9", ["--f", "7"]),
    "F145": (["f145"], "F145_F", "e1,e2", "f145", 'f = "f1, f2"', ["--f", "c1", "--f", "c2"]),
    "F145a": (["f145"], "F145_F", "e1,e2", "f145", 'f = ["f1", "f2"]', ["--f", "c1"]),
    "F146": (["f146"], "F146_F", "fromenv", "f146", 'f = "fromfile"', ["--f", "fromcli"]),
    "F147": (["f147"], "F147_F", "e1,e2", "f147", 'f = ["f1", "f2"]', ["--f", "c1", "--f", "c2"]),
    "F148": (["f148"], "F148_F", "envsecret", "f148", 'f = "filesecret"', ["--f", "clisecret"]),
    "F149": (["f149"], "F149_F", "fromenv", "f149", 'f = "fromfile"', ["--f", "fromcli"]),
    "F150": (["f150"], "F150_F", '{"k": "env"}', "f150", 'f = {k = "file"}', ["--f", "k=v"]),
    "F151": (["f151"], "F151_F", '{"x": 5}', "f151", "f = {x = 6}", ["--f", "x"]),
    "F152": (["f152"], "F152_F", "e1,e2", "f152", 'f = ["f1", "f2"]', ["-t", "c1", "-t", "c2"]),
    "A002": (["a002"], "A002_P", "fromenv", "a002", 'p = "fromfile"', ["--p", "fromcli"]),
    "G161": (["g161g", "run"], "G161G__P", "fromenv", "g161g", 'p = "fromfile"', ["--p", "fromcli"]),
    "G160": (["g160g", "run"], "G160G__P", "e1,e2", "g160g", 'p = ["f1", "f2"]', ["--p", "c1"]),
}


def run(argv, env_extra, rid):
    env = dict(os.environ, COLUMNS="200", NO_COLOR="1", TERM="dumb",
               PYTHONPATH=str(Path(__file__).parent / "pylib"))
    env.update(env_extra)
    p = subprocess.run([FUNC, *argv], cwd=PROJ, capture_output=True, text=True, timeout=120,
                       env=env, input="")
    foreign_refusal = re.compile(
        r"/jobs/([a-z]\d+)\.py: job '([^']+)' parameter .* is refused\."
    )
    # Keep this row's own refusal and the original stdout/stderr join: a required
    # field's stdout prefix has no newline before its stderr error message.
    stderr = "".join(
        line for line in p.stderr.splitlines(keepends=True)
        if "e142.py not loaded" not in line and not (
            (match := foreign_refusal.search(line))
            and (match.group(1) != rid.lower() or match.group(2) != rid.lower())
        )
    )
    keep = [ln for ln in (p.stdout + stderr).splitlines()
            if "took " not in ln and "e142.py not loaded" not in ln
            and "registered but cannot run" not in ln]
    return {"argv": " ".join(f"{k}={v!r}" for k, v in env_extra.items()) + (" " if env_extra else "")
            + "func " + " ".join(argv), "rc": p.returncode, "out": "\n".join(keep[-6:])}


def main() -> None:
    cfg = PROJ / "config.base.toml"
    toml = "".join(f"[{c[3]}]\n{c[4]}\n\n" for k, c in CASES.items() if k != "F145a")
    toml_a = "".join(f"[{c[3]}]\n{c[4]}\n\n" for k, c in CASES.items() if k not in ("F145",))
    results: dict = {"config.base.toml": toml, "config.base.toml (F145a pass)": toml_a}

    def scenario(name, with_env, with_file, with_cli, cases, file_text):
        if with_file:
            cfg.write_text(file_text)
        elif cfg.exists():
            cfg.unlink()

        def one(item):
            rid, (path, ev, evv, _s, _l, cli) = item
            if path[0].startswith("g16") and with_cli:
                argv = [path[0], *cli, *path[1:]]
            else:
                argv = [*path, *(cli if with_cli else [])]
            return rid, run(argv, {ev: evv} if with_env else {}, rid)

        with ThreadPoolExecutor(max_workers=6) as ex:
            for rid, r in ex.map(one, cases.items()):
                results.setdefault(rid, {})[name] = r

    main_cases = {k: v for k, v in CASES.items() if k != "F145a"}
    alt = {"F145a": CASES["F145a"]}
    for name, e, f, c in (("none", 0, 0, 0), ("env", 1, 0, 0), ("file", 0, 1, 0),
                          ("env+file", 1, 1, 0), ("cli+all", 1, 1, 1)):
        scenario(name, e, f, c, main_cases, toml)
        scenario(name, e, f, c, alt, toml_a)
    if cfg.exists():
        cfg.unlink()
    OUT.write_text(json.dumps(results, indent=1))
    for rid in CASES:
        print(rid)
        for sc in ("none", "env", "file", "env+file", "cli+all"):
            r = results[rid][sc]
            last = r["out"].splitlines()[-1] if r["out"] else ""
            print(f"   {sc:9} rc={r['rc']} {last[:150]}")


if __name__ == "__main__":
    main()
