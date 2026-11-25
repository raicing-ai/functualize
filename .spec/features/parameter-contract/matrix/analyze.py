"""Reduce out.json to per-row facts and an observed verdict."""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

NOISE = (
    re.compile(r"^⚠ e142\.py not loaded.*$"),
    re.compile(r"^Plugin '.*' took \d+ms to load.*$"),
    re.compile(r"^Job '(c085|c087|e138)' is registered but cannot run.*$"),
)


def clean(text: str, keep_row: str | None = None) -> str:
    out = []
    for line in text.splitlines():
        if any(p.match(line) for p in NOISE):
            # keep a row's own boot warning
            if keep_row and keep_row in line:
                out.append(line)
            continue
        out.append(line)
    return "\n".join(out).rstrip()


def tree(script: str) -> dict[str, list[str]]:
    t = {}
    for m in re.finditer(r"_func_tree\['(:[^']*)'\]='([^']*)'", script):
        t[m.group(1)] = m.group(2).split()
    return t


def load(path: str = "out.json"):
    d = json.loads(Path(path).read_text())
    g = d["global"]
    info = {tuple(x["path"]): x for x in json.loads(g["info"]["stdout"])}
    mcp = {x["name"]: x for x in json.loads(g["mcp"]["stdout"])}
    bash, zsh = tree(g["bash"]["stdout"]), tree(g["zsh"]["stdout"])
    return d, info, mcp, bash, zsh


def obs_of(run: dict) -> str:
    lines = [ln[4:] for ln in run["stdout"].splitlines() if ln.startswith("OBS ")]
    return "; ".join(lines)


def kind_of(run: dict | None) -> str:
    if run is None:
        return "-"
    err = run["stderr"] + run["stdout"]
    if run["rc"] == "TIMEOUT":
        return "TIMEOUT"
    m = re.search(r"^Error: (\w+(Error|Exception)): (.*)$", err, re.M)
    if "Traceback" not in err and m:
        return f"UNCAUGHT rc={run['rc']}: {m.group(0)[:140]}"
    if "Traceback" in err:
        last = [ln for ln in err.splitlines() if ln.strip()][-1]
        return f"UNCAUGHT(traceback) rc={run['rc']}: {last.strip()[:110]}"
    o = obs_of(run)
    if run["rc"] == 0 and o:
        return f"ok: {o}"
    msg = [ln for ln in clean(run["stderr"]).splitlines() if ln.strip()]
    tail = msg[-1].strip()[:140] if msg else ""
    return f"rc={run['rc']}: {tail}"


def facts(row, info, mcp, bash, zsh):
    rid = row["id"].lower()
    path = row["path"]
    probe = row["probe"]
    fname = row["flagname"]
    runs = row["runs"]
    help_ = runs["help"]
    htxt = help_["stdout"]
    usage = next((ln for ln in htxt.splitlines() if ln.startswith("Usage:")), "")
    # flag present in help?
    flag_in_help = bool(re.search(rf"(^|[\s,/]){re.escape(fname)}([\s,=/]|$)", htxt, re.M))
    if not flag_in_help and fname == "--p":
        flag_in_help = bool(re.search(r"(^|\s)-p[\s,]", htxt, re.M))
    pos_tok = probe.upper()
    tail = usage.split("[OPTIONS]")[-1].strip() if "[OPTIONS]" in usage else ""
    pos_in_help = bool(re.search(rf"\b{pos_tok}\b", tail)) or tail.startswith("{") or tail.startswith("[{")
    key = ":" + " ".join(path)
    b = bash.get(key)
    z = zsh.get(key)
    info_e = info.get(tuple(path))
    mcp_e = mcp.get(".".join(path))
    ip = (info_e or {}).get("inputSchema", {}).get("properties", {}).get(probe)
    mp = (mcp_e or {}).get("inputSchema", {}).get("properties", {}).get(probe)
    ireq = probe in (info_e or {}).get("inputSchema", {}).get("required", [])
    mreq = probe in (mcp_e or {}).get("inputSchema", {}).get("required", [])
    registered = info_e is not None or help_["rc"] == 0
    loaded = help_["rc"] == 0
    return {
        "registered": registered,
        "loaded": loaded,
        "usage": usage.strip(),
        "help_flag": flag_in_help,
        "help_pos": pos_in_help,
        "bash": None if b is None else (fname in b),
        "zsh": None if z is None else (fname in z),
        "bash_words": b,
        "info": ip,
        "info_req": ireq,
        "mcp": mp,
        "mcp_req": mreq,
        "info_eq_mcp": (ip == mp and ireq == mreq),
        "k_absent": kind_of(runs.get("absent")),
        "k_flag": kind_of(runs.get("flag")),
        "k_pos": kind_of(runs.get("pos")),
        "k_stdin": kind_of(runs.get("stdin")),
        "k_env": kind_of(runs.get("envvar")),
    }


def verdict(row, f) -> str:
    if not f["registered"]:
        return "REJECTED_DISCOVERY"
    # B-2/B-8 and tests/surfaces/test_parameter_surface_parity.py:284-290:
    # refused jobs remain listed and answer --help, but every call refuses.
    # Match this job's call error, not unrelated discovery warnings at boot.
    calls = [run for name, run in row["runs"].items() if name != "help"]
    refused = re.compile(
        rf"^Error: job '{re.escape(row['path'][-1])}' cannot run: parameter .*"
        r"(?:is refused|was refused at discovery)\.",
        re.M,
    )
    if calls and all(
        run["rc"] != 0
        and not obs_of(run)
        and "Traceback" not in run["stderr"] + run["stdout"]
        and refused.search(run["stderr"] + run["stdout"])
        for run in calls
    ):
        return "REJECTED_DISCOVERY"
    if not f["loaded"]:
        return "UNRUNNABLE (registered, every call: 'could not be loaded')"
    crashed = any(k.startswith("UNCAUGHT") for k in
                  (f["k_absent"], f["k_flag"], f["k_pos"], f["k_stdin"]))
    if row["probe"] == "f":
        base = "CONFIG_FIELD" if f["help_flag"] else "NO_SURFACE"
    elif f["help_flag"]:
        base = "ACCEPTED_FLAG"
    elif f["help_pos"]:
        base = "ACCEPTED_POSITIONAL"
    elif f["info"] is not None:
        base = "INVOCATION_ONLY"
    else:
        base = "INJECTED"
    if crashed:
        base += " +UNCAUGHT"
    return base


def main():
    d, info, mcp, bash, zsh = load()
    for row in d["rows"]:
        f = facts(row, info, mcp, bash, zsh)
        v = verdict(row, f)
        print(f"{row['id']} | {row['label'][:60]:60} | {v}")
        print(f"     help={f['help_flag']}/{f['help_pos']} usage={f['usage']!r} "
              f"bash={f['bash']} zsh={f['zsh']} info={json.dumps(f['info'])} req={f['info_req']} "
              f"mcp==info={f['info_eq_mcp']}")
        print(f"     absent: {f['k_absent']}")
        print(f"     flag  : {f['k_flag']}")
        print(f"     pos   : {f['k_pos']}")
        if f["k_stdin"] != "-":
            print(f"     stdin : {f['k_stdin']}")
        if f["k_env"] != "-":
            print(f"     env   : {f['k_env']}")


if __name__ == "__main__":
    main()
