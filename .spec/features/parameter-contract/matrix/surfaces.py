"""Drive the non-click surfaces for every row of the generated project.

Usage: python surfaces.py <func> <project> <out.json> <surfaces.json>

- Lambda, inline-TUI door, SmartBar: one `func probe surfaces` run (plugin).
- HTTP: a real `func serve` on a free port; POST /jobs/<name>/execute per row.
- MCP: one real `func mcp serve` stdio session; tools/call per row. The G156
  module stops that server at startup (F-12), so the session runs on a copy of
  the project without it, and the crash itself is recorded with it present.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import signal
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

FUNC, PROJ, OUT, SURF = str(Path(sys.argv[1]).resolve()), Path(sys.argv[2]).resolve(), Path(sys.argv[3]), Path(sys.argv[4])
os.environ["PYTHONPATH"] = str(Path(__file__).parent / "pylib")

WIRE = {
    "str": "x", "int": 7, "float": 1.5, "bool": True, "Path": "/tmp/x",
    "UUID": "12345678-1234-5678-1234-567812345678", "date": "2026-01-02",
    "datetime": "2026-01-02T03:04:05", "time": "03:04:05", "timedelta": "PT1H",
    "Decimal": "1.25", "Enum": "red", "Color": "red", "Secret[str]": "s3cr3t",
}
OVERRIDE = {
    "B071": [["a"], ["b"]], "C081": ["a", 1], "C082": {"k": "v"}, "C083": {"k": "v"},
    "C085": "w", "C086": "w", "C087": {"x": 1, "y": 2}, "D104": {"k": "v"},
    "D105": "w", "D107": 0, "F144": 7, "F150": {"k": "v"}, "F151": {"x": 5},
}


def wire_for(row: dict) -> object:
    rid, label = row["id"], row["label"]
    if rid in OVERRIDE:
        return OVERRIDE[rid]
    m = re.search(r"\b[pf]: (?:Annotated\[)?(?:Optional\[)?(list|tuple|set)\[([A-Za-z]+(?:\[str\])?)", label)
    if m:
        elem = m.group(2)
        return [WIRE.get(elem, "a"), WIRE.get(elem, "b")] if elem != "Color" else ["red", "blue"]
    m = re.search(r"\b[pf]: (?:Optional\[)?([A-Za-z]+(?:\[str\])?)", label)
    if m and m.group(1) in WIRE:
        return WIRE[m.group(1)]
    if "Field(ge=1)" in label:
        return 0
    return "x"


def free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def main() -> None:
    d = json.loads(OUT.read_text())
    rows = d["rows"]
    registered = {tuple(x["path"]) for x in json.loads(d["global"]["info"]["stdout"])}
    spec, plan = [], {}
    for row in rows:
        rid, path, probe = row["id"], row["path"], row["probe"]
        job = ".".join(path)
        val = wire_for(row)
        is_group = row["decl"].startswith("GROUP:")
        given_args = {} if is_group else {probe: val}
        if rid == "G157":
            given_args = {"p": "x", "q": ["a", "b"]}
        gov = {probe: val} if is_group else None
        plan[rid] = {"job": job, "value": val, "given_args": given_args, "gov": gov,
                     "registered": tuple(path) in registered}
        if not plan[rid]["registered"]:
            continue
        flag = row["flag"] or []
        pos = row["pos"] or []
        flag_text = (f"{path[0]} {' '.join(flag)} {' '.join(path[1:])}" if is_group
                     else " ".join([*path, *flag]))
        tui = {"absent": " ".join(path), "flag": flag_text}
        if pos and not is_group:
            tui["pos"] = " ".join([*path, *pos])
        lam = {"absent": {"arguments": {}}, "given": {"arguments": given_args}}
        if gov:
            lam["given"]["group_option_values"] = gov
        spec.append({
            "id": rid, "job": job, "tui": tui, "lambda": lam,
            "lambda_fat": {"job": job, "arguments": given_args, **({"group_option_values": gov} if gov else {})},
            "smartbar_flag_text": (f"{path[0]} --" if is_group else " ".join(path) + " --"),
            "smartbar_job_text": " ".join(path) + " ",
        })
    work = SURF.resolve().parent
    spec_path = work / "probe-spec.json"
    spec_path.write_text(json.dumps(spec))
    res: dict = {"plan": plan}

    # ── Lambda / TUI door / SmartBar
    probe_out = work / "probe-out.json"
    p = subprocess.run([FUNC, "probe", "surfaces", "--spec", str(spec_path), "--out", str(probe_out)],
                       cwd=PROJ, capture_output=True, text=True, timeout=1800, input="")
    res["probe_cmd"] = {"argv": ["func", "probe", "surfaces", "--spec", "probe-spec.json", "--out",
                                 "probe-out.json"], "rc": p.returncode,
                        "stdout_tail": p.stdout[-2000:], "stderr_tail": p.stderr[-3000:]}
    res["probe"] = json.loads(probe_out.read_text()) if probe_out.exists() else {}

    # ── HTTP: real `func serve`
    port = free_port()
    log = open(work / "http-serve.log", "w")
    srv = subprocess.Popen([FUNC, "serve", "--host", "127.0.0.1", "--port", str(port)], cwd=PROJ,
                           stdout=log, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
                           start_new_session=True)
    res["http_server"] = {"argv": f"func serve --host 127.0.0.1 --port {port}", "pid": srv.pid}
    base = f"http://127.0.0.1:{port}"
    for _ in range(120):
        try:
            urllib.request.urlopen(base + "/health", timeout=1).read()
            break
        except Exception:
            time.sleep(0.5)
    http: dict = {}

    def post(job: str, body: dict) -> dict:
        req = urllib.request.Request(f"{base}/jobs/{job}/execute", data=json.dumps(body).encode(),
                                     headers={"Content-Type": "application/json"}, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                return {"code": r.status, "body": json.loads(r.read() or b"null")}
        except urllib.error.HTTPError as e:
            raw = e.read()
            try:
                body_ = json.loads(raw)
            except Exception:
                body_ = raw.decode(errors="replace")
            return {"code": e.code, "body": body_}
        except Exception as e:  # noqa: BLE001
            return {"code": None, "error": f"{type(e).__name__}: {e}"}

    for rid, pl in plan.items():
        if not pl["registered"]:
            continue
        given = {"arguments": pl["given_args"]}
        if pl["gov"]:
            given["group_option_values"] = pl["gov"]
        http[rid] = {"absent": {"body": {"arguments": {}}, **post(pl["job"], {"arguments": {}})},
                     "given": {"body": given, **post(pl["job"], given)}}
    res["http"] = http
    # stop exactly the server we started (its own session/process group)
    os.killpg(srv.pid, signal.SIGTERM)
    try:
        srv.wait(timeout=20)
    except subprocess.TimeoutExpired:
        os.killpg(srv.pid, signal.SIGKILL)
    log.close()

    # ── MCP: crash with G156 present, then a full session without it
    init = {"jsonrpc": "2.0", "id": 0, "method": "initialize", "params": {
        "protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "m", "version": "0"}}}
    c = subprocess.run([FUNC, "mcp", "serve"], cwd=PROJ, input=json.dumps(init) + "\n",
                       capture_output=True, text=True, timeout=120)
    res["mcp_with_g156"] = {"rc": c.returncode, "stderr_tail": c.stderr[-1500:], "stdout": c.stdout[-500:]}
    mproj = PROJ.parent / (PROJ.name + "_mcp")
    if mproj.exists():
        shutil.rmtree(mproj)
    (mproj / ".functualize").mkdir(parents=True)
    for sub in ("jobs", "plugins"):
        shutil.copytree(PROJ / ".functualize" / sub, mproj / ".functualize" / sub,
                        ignore=shutil.ignore_patterns("__pycache__"))
    (mproj / ".functualize" / "jobs" / "g156.py").unlink()
    proc = subprocess.Popen([FUNC, "mcp", "serve"], cwd=mproj, stdin=subprocess.PIPE,
                            stdout=subprocess.PIPE, stderr=open(work / "mcp-serve.log", "w"),
                            text=True, start_new_session=True)

    def send(msg):
        proc.stdin.write(json.dumps(msg) + "\n")
        proc.stdin.flush()

    def recv(want):
        while True:
            line = proc.stdout.readline()
            if not line:
                return None
            try:
                m = json.loads(line)
            except json.JSONDecodeError:
                continue
            if m.get("id") == want:
                return m

    send(init)
    recv(0)
    send({"jsonrpc": "2.0", "method": "notifications/initialized"})
    send({"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
    tl = recv(1)
    tool_names = {t["name"] for t in (tl or {}).get("result", {}).get("tools", [])}
    mcp: dict = {"_tool_names": sorted(tool_names)}
    i = 10
    for rid, pl in plan.items():
        if rid == "G156" or not pl["registered"]:
            continue
        out = {}
        given = dict(pl["given_args"])
        if pl["gov"]:
            given.update(pl["gov"])
        for k, args in (("absent", {}), ("given", given)):
            i += 1
            send({"jsonrpc": "2.0", "id": i, "method": "tools/call",
                  "params": {"name": pl["job"], "arguments": args}})
            r = recv(i)
            out[k] = {"arguments": args, "response": (r or {}).get("result", (r or {}).get("error"))}
        mcp[rid] = out
    res["mcp"] = mcp
    proc.stdin.close()
    os.killpg(proc.pid, signal.SIGTERM)
    try:
        proc.wait(timeout=20)
    except subprocess.TimeoutExpired:
        os.killpg(proc.pid, signal.SIGKILL)
    SURF.write_text(json.dumps(res, indent=1, default=repr))
    print("surfaces done:", {k: len(v) for k, v in res.items() if isinstance(v, dict)})


if __name__ == "__main__":
    main()
