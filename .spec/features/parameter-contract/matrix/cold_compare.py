"""Compare the cold pass (out_cold.json, one project per row, cache deleted before
every command) with the warm matrix (out.json), field by field via analyze.facts()."""

from __future__ import annotations

import json
import re
from pathlib import Path

from analyze import facts, tree, verdict

KEYS = ("help_flag", "help_pos", "bash", "zsh", "info", "info_req", "mcp", "mcp_req",
        "k_absent", "k_flag", "k_pos", "usage")


def norm(v):
    s = json.dumps(v, sort_keys=True, default=str)
    s = re.sub(r"0x[0-9a-f]+", "0x…", s)
    s = re.sub(r"available: \[[^\]]*\]", "available: […]", s)
    return s


def index(glob):
    def js(run):
        out = run["stdout"]
        i = out.find("[")
        return json.loads(out[i:]) if i >= 0 else []
    info = {tuple(x["path"]): x for x in js(glob["info"])}
    mcp = {x["name"]: x for x in js(glob["mcp"])}
    return info, mcp, tree(glob["bash"]["stdout"]), tree(glob["zsh"]["stdout"])


def main() -> None:
    warm = json.loads(Path("out.json").read_text())
    cold = json.loads(Path("out_cold.json").read_text())
    g = warm["global"]
    winfo = {tuple(x["path"]): x for x in json.loads(g["info"]["stdout"])}
    wmcp = {x["name"]: x for x in json.loads(g["mcp"]["stdout"])}
    wb, wz = tree(g["bash"]["stdout"]), tree(g["zsh"]["stdout"])
    diffs = []
    for row in warm["rows"]:
        rid = row["id"]
        fw = facts(row, winfo, wmcp, wb, wz)
        c = cold[rid]
        crow = dict(row, runs=c["runs"])
        ci, cm, cb, cz = index(c["global"])
        fc = facts(crow, ci, cm, cb, cz)
        vw, vc = verdict(row, fw), verdict(crow, fc)
        if vw != vc:
            diffs.append((rid, "verdict", vw, vc))
        for k in KEYS:
            if norm(fw[k]) != norm(fc[k]):
                diffs.append((rid, k, fw[k], fc[k]))
    print(f"{len(warm['rows'])} rows compared cold vs warm on {len(KEYS) + 1} fields; {len(diffs)} differences")
    for rid, k, a, b in diffs:
        print(f"   {rid} {k}\n      warm: {a}\n      cold: {b}")


if __name__ == "__main__":
    main()
