"""Reduce surfaces.json (+ out.json) to one cell per row × surface call.

Cell grammar:  ok:<type>[=<value>] | refused:<why> | fail:<ExcType>: <msg> | — (not run)
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

OBS = re.compile(r"OBS [pf]=(.*?) type=(\w+)")


def obs(text: str | None) -> tuple[str, str] | None:
    if not text:
        return None
    m = OBS.search(text)
    return (m.group(2), m.group(1)) if m else None


def short(s: str, n: int = 90) -> str:
    s = " ".join(str(s).split())
    return s if len(s) <= n else s[: n - 1] + "…"


def cell_exec(d: dict | None) -> str:
    """lambda / tui / http-body style record."""
    if d is None:
        return "—"
    if "raised" in d:
        return f"fail:{short(d['raised'])}"
    if d.get("resolved", "x") is None:
        return "refused:not resolved"
    rv = d.get("return_value", d.get("body"))
    o = obs(rv if isinstance(rv, str) else None)
    st = str(d.get("status", ""))
    if o and st.lower() == "success":
        return f"ok:{o[0]}={short(o[1], 40)}"
    err = d.get("exception") or d.get("error") or (rv if isinstance(rv, str) else "")
    return f"fail:{short(err)}" if err else f"{st}"


def cell_http(d: dict | None) -> str:
    if d is None:
        return "—"
    if d.get("code") is None:
        return f"fail:{short(d.get('error'))}"
    body = d.get("body") or {}
    if isinstance(body, str):
        return f"{d['code']}:{short(body)}"
    c = cell_exec({**body, "status": body.get("status")})
    return f"{d['code']} {c}"


def cell_mcp(d: dict | None) -> str:
    if d is None:
        return "—"
    r = d.get("response") or {}
    if "content" not in r:
        return f"rpc-error:{short(json.dumps(r))}"
    text = " | ".join(c.get("text", "") for c in r["content"])
    if r.get("isError"):
        first = text.splitlines()
        msg = next((ln.strip() for ln in first[1:] if ln.strip() and not ln.startswith("    For")), first[0] if first else "")
        if "validation error" in text:
            return f"refused:{short(msg, 70)}"
        return f"fail:{short(text)}"
    sc = r.get("structuredContent") or {}
    rv = sc.get("return_value")
    if rv is None:
        try:
            rv = json.loads(text).get("return_value")
        except Exception:
            rv = text
    o = obs(rv if isinstance(rv, str) else None)
    st = (sc.get("status") or "").lower()
    if o and st == "success":
        return f"ok:{o[0]}={short(o[1], 40)}"
    err = sc.get("error") or text
    return f"fail:{short(err)}"


def cell_cli(run: dict | None) -> str:
    if run is None:
        return "—"
    o = obs(run["stdout"])
    if run["rc"] == 0 and o:
        return f"ok:{o[0]}={short(o[1], 40)}"
    err = [ln for ln in (run["stderr"] + run["stdout"]).splitlines() if ln.strip()]
    last = err[-1].strip() if err else ""
    if "Traceback" in run["stderr"] or re.search(r"^Error: \w+(Error|Exception):", run["stderr"], re.M):
        return f"fail:{short(last)}"
    return f"refused(rc={run['rc']}):{short(last, 60)}"


def smartbar(d: dict | None) -> str:
    if d is None:
        return "—"
    c = d.get("candidates")
    if isinstance(c, dict):
        return f"fail:{short(c.get('raised'))}"
    words = sorted({m.group(0) for s in c for m in re.finditer(r"(?<![\w-])-{1,2}[\w-]+", s)})
    return " ".join(words) or "(none)"


def load():
    import os

    out = json.loads(Path(os.environ.get("MCH_OUT", "out.json")).read_text())
    s = json.loads(Path(os.environ.get("MCH_SURF", "surfaces.json")).read_text())
    return out, s


def table() -> list[dict]:
    out, s = load()
    rows = []
    for row in out["rows"]:
        rid = row["id"]
        pr = s["probe"].get(rid, {})
        http = s["http"].get(rid, {})
        mcp = s["mcp"].get(rid, {})
        cli_given = row["runs"].get("flag")
        if cli_given is None or cell_cli(cli_given).startswith("refused"):
            cli_given = row["runs"].get("pos") or cli_given
        rows.append({
            "id": rid, "label": row["label"].replace("{rid}", rid.lower()),
            "cli_absent": cell_cli(row["runs"].get("absent")),
            "cli_given": cell_cli(cli_given),
            "tui_absent": cell_exec(pr.get("tui_absent")),
            "tui_given": cell_exec(pr.get("tui_flag")),
            "tui_pos": cell_exec(pr.get("tui_pos")),
            "mcp_absent": cell_mcp(mcp.get("absent")) if rid != "G156" else "server down (F-12)",
            "mcp_given": cell_mcp(mcp.get("given")) if rid != "G156" else "server down (F-12)",
            "http_absent": cell_http(http.get("absent")),
            "http_given": cell_http(http.get("given")),
            "lambda_absent": cell_exec(pr.get("lambda_thin_absent")),
            "lambda_given": cell_exec(pr.get("lambda_thin_given")),
            "lambda_fat_kwargs": cell_exec(pr.get("lambda_fat_kwargs")),
            "smartbar": smartbar(pr.get("smartbar_flags")),
            "smartbar_job": smartbar(pr.get("smartbar_after_job")),
            "wire_value": s["plan"][rid]["value"],
        })
    return rows


if __name__ == "__main__":
    for r in table():
        print(f"{r['id']} {r['label'][:55]}")
        for k, v in r.items():
            if k not in ("id", "label"):
                print(f"   {k:17} {v}")
