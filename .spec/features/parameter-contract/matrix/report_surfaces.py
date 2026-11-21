"""Render the extended-surface measurement as pc-surfaces.md."""

from __future__ import annotations

import json
from pathlib import Path

from surf_analyze import load, table


def esc(s: object) -> str:
    return str(s).replace("|", "\\|").replace("\n", " ")


def main() -> None:
    out, s = load()
    rows = table()
    L: list[str] = []
    w = L.append
    w("# parameter-contract extended surfaces — TUI door, SmartBar, MCP tools/call, HTTP, Lambda\n")
    w("Same 166-row project and commit as `pc-matrix.md` (`master` @ `da912d76`, CPython "
      "3.13.15). Every surface below is the real code path, booted by the real `func`:\n")
    w("- **MCP** — one `func mcp serve` stdio session; `tools/call` per row with no arguments "
      "(`absent`) and with the row's JSON value (`given`). G156 stops that server at startup "
      "(F-12), so the session ran on the same project without `g156.py`; the crash itself is in "
      "§ *Server start with G156*.")
    w("- **HTTP** — `functualize_http.HttpServerPlugin` registered by a project plugin, started as "
      "`func serve --host 127.0.0.1 --port <free>`; `POST /jobs/<job>/execute` with the envelope "
      "`{\"arguments\": …}` (group options in `group_option_values`). The PID started is the PID "
      "stopped.")
    w("- **Lambda** — `functualize_lambda.LambdaAdapter` on the booted app: the thin handler "
      "(`make_handler(job)(event, None)`, envelope event) and the fat handler with the event "
      "shape its own docstrings document (`{\"job\": …, \"kwargs\": …}`).")
    w("- **TUI door** — the inline TUI's own functions in its own order: `tokenize_bar_text` → "
      "`resolve_tui_command` → `parse_cli_args_to_kwargs(args, fields)` (fields from "
      "`get_descriptor_fields`, group-option injection parameters removed as `_get_job_fields` "
      "does) → `RunRequest(surface=\"tui.inline\")` → `app.execute`. Not measured: Textual "
      "rendering and key handling.")
    w("- **SmartBar** — `SmartBarAutoComplete(app, CompletionProvenanceClassifier(app))."
      "get_candidates()` for `\"<job> --\"`; the cell lists the flag words it offers.\n")
    w("Cell grammar: `ok:<type>=<value>` the job ran and received that; `refused:<why>` a clean "
      "refusal; `fail:<message>` the run failed (raw exception text); HTTP cells carry the status "
      "code. Raw request/response for every cell follows the table.\n")
    cols = ["cli_given", "tui_given", "mcp_given", "http_given", "lambda_given", "cli_absent",
            "tui_absent", "mcp_absent", "http_absent", "lambda_absent", "lambda_fat_kwargs",
            "smartbar"]
    w("| id | declaration | wire value | " + " | ".join(cols) + " |")
    w("|" + "---|" * (len(cols) + 3))
    for r in rows:
        w(f"| {r['id']} | `{esc(r['label'])}` | `{esc(json.dumps(r['wire_value']))}` | "
          + " | ".join(esc(r[c]) for c in cols) + " |")

    w("\n## Server start with G156 present\n")
    m = s["mcp_with_g156"]
    w("```console\n$ printf '%s\\n' '<initialize request>' | func mcp serve    # exit "
      f"{m['rc']}\n{m['stderr_tail'].strip()}\n```\n")
    w(f"Tools registered in the G156-free session: {len(s['mcp']['_tool_names'])}.\n")

    w("## Raw records, per row\n")
    probe, http, mcp, plan = s["probe"], s["http"], s["mcp"], s["plan"]
    for row in out["rows"]:
        rid = row["id"]
        w(f"### {rid} — `{row['label'].replace('{rid}', rid.lower())}`\n")
        if not plan[rid]["registered"]:
            w("Not registered (see `pc-matrix.md`); no surface call possible.\n")
            continue
        w("```text")
        pr = probe.get(rid, {})
        for k in ("tui_absent", "tui_flag", "tui_pos"):
            if k in pr:
                w(f"TUI  {pr[k].get('text')!r} -> {json.dumps({x: y for x, y in pr[k].items() if x != 'text'}, default=str)}")
        for k in ("smartbar_flags", "smartbar_after_job"):
            if k in pr:
                c = pr[k]["candidates"]
                c = [x.split("'")[1] if x.startswith("Content(") else x for x in c] if isinstance(c, list) else c
                w(f"SMARTBAR {pr[k]['text']!r} -> {c}")
        if rid in mcp:
            for k in ("absent", "given"):
                rec = mcp[rid][k]
                resp = rec["response"] or {}
                text = " | ".join(x.get("text", "") for x in resp.get("content", [])) if isinstance(resp, dict) else resp
                w(f"MCP  tools/call {plan[rid]['job']} {json.dumps(rec['arguments'])} -> isError={resp.get('isError') if isinstance(resp, dict) else '?'} {text}")
        if rid in http:
            # surfaces.py stored the response under "body"; the request is rebuilt from the plan
            req_given = {"arguments": plan[rid]["given_args"]}
            if plan[rid]["gov"]:
                req_given["group_option_values"] = plan[rid]["gov"]
            for k, req in (("absent", {"arguments": {}}), ("given", req_given)):
                rec = http[rid][k]
                w(f"HTTP POST /jobs/{plan[rid]['job']}/execute {json.dumps(req)} -> {rec.get('code')} {json.dumps(rec.get('body', rec.get('error')))}")
        for k in ("lambda_thin_absent", "lambda_thin_given", "lambda_fat_kwargs"):
            if k in pr:
                rec = pr[k]
                w(f"LAMBDA {k.replace('lambda_', '')} event={json.dumps(rec.get('event'))} -> {json.dumps({x: y for x, y in rec.items() if x != 'event'}, default=str)}")
        w("```\n")
    Path("pc-surfaces.md").write_text("\n".join(L) + "\n")


if __name__ == "__main__":
    main()
