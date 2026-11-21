"""Compare per-row facts of out311.json / out312.json against out.json (3.13)."""
import json, re, sys
from analyze import facts, load, verdict

KEYS = ("help_flag", "help_pos", "bash", "zsh", "info", "info_req", "mcp", "mcp_req",
        "k_absent", "k_flag", "k_pos", "k_stdin", "k_env", "usage")


def norm(v):
    s = json.dumps(v, sort_keys=True, default=str)
    s = re.sub(r"0x[0-9a-f]+", "0x…", s)
    return s


def facts_of(path):
    d, info, mcp, bash, zsh = load(path)
    out = {}
    for row in d["rows"]:
        f = facts(row, info, mcp, bash, zsh)
        out[row["id"]] = {"verdict": verdict(row, f), **{k: f[k] for k in KEYS}}
    return out, d


base, d = facts_of("out.json")
for other in sys.argv[1:]:
    o, _ = facts_of(other)
    diffs = []
    for rid in base:
        for k, v in base[rid].items():
            if norm(v) != norm(o[rid][k]):
                diffs.append((rid, k, v, o[rid][k]))
    print(f"{other}: {len(base)} rows compared on {len(KEYS) + 1} fields; {len(diffs)} differences")
    for rid, k, a, b in diffs:
        print(f"   {rid} {k}\n      3.13: {a}\n      other: {b}")
