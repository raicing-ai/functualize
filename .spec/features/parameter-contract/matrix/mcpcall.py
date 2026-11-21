"""Call jobs over the real `func mcp serve` stdio transport."""
import json, subprocess, sys
FUNC, PROJ = sys.argv[1], sys.argv[2]
calls = [("b053", {"p": ["a", "b"]}), ("b066", {"p": ["a", "b"]}), ("c082", {"p": {"k": "v"}}),
         ("c079", {"p": ["a", "b"]}), ("a049", {"p": "s3cr3t"}), ("b072", {"p": ["a", "b"]}),
         ("a038", {"p": "PT1H"}), ("b057", {"p": ["/tmp/x"]})]
proc = subprocess.Popen([FUNC, "mcp", "serve"], cwd=PROJ, stdin=subprocess.PIPE,
                        stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)
def send(msg):
    proc.stdin.write(json.dumps(msg) + "\n"); proc.stdin.flush()
def recv(want_id):
    while True:
        line = proc.stdout.readline()
        if not line:
            return None
        m = json.loads(line)
        if m.get("id") == want_id:
            return m
send({"jsonrpc": "2.0", "id": 0, "method": "initialize", "params": {
    "protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "matrix", "version": "0"}}})
recv(0)
send({"jsonrpc": "2.0", "method": "notifications/initialized"})
for i, (name, args) in enumerate(calls, start=1):
    send({"jsonrpc": "2.0", "id": i, "method": "tools/call", "params": {"name": name, "arguments": args}})
    r = recv(i)
    res = r.get("result") or r.get("error")
    text = ""
    if isinstance(res, dict) and "content" in res:
        text = " | ".join(c.get("text", "") for c in res["content"])[:300]
        err = res.get("isError")
    else:
        text, err = json.dumps(res)[:300], True
    print(f"tools/call {name} {json.dumps(args)}\n  isError={err} -> {text}")
proc.stdin.close(); proc.terminate()
