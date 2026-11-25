#!/usr/bin/env bash
# Supplementary probes for parameter-contract findings; same project, same func.
script_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
export PYTHONPATH="$script_dir/pylib${PYTHONPATH:+:$PYTHONPATH}"
F=$1; P=$2; cd "$P"
q(){ echo "\$ func $*"; "$F" "$@" > /tmp/pc.out 2>&1; rc=$?; grep -v -e "e142.py not loaded" -e "took .*ms to load" -e "registered but cannot run" /tmp/pc.out | awk 'BEGIN{n=0} {a[n++]=$0} END{s=(n>14 && a[0] ~ /Traceback/)?n-12:0; if(s>0) print "[… " s " earlier traceback lines elided …]"; for(i=s;i<n;i++) print a[i]}'; echo "# exit $rc"; echo; }
echo '## timedelta: three spellings, all refused with a traceback (F-05)'; q a039 --p PT1H; q a039 --p 3600; q a039 --p 1:00:00
echo '## completion-advertised spellings vs the CLI (F-06)'; q d097 --p x; q d097 --tags x; q d097 -t x; q d103 --p x; q d103 -a x; q d103 -b x; q b078 --p a
echo '## group-level list option keeps the last value (F-10, F-18)'; q g160g --help; q g160g --p a --p b run
echo '## MCP server start with row G156 present (F-12)'
echo '$ printf "%s\n" "<initialize request>" | func mcp serve'
printf '%s\n' '{"jsonrpc":"2.0","id":0,"method":"initialize","params":{"protocolVersion":"2025-06-18","capabilities":{},"clientInfo":{"name":"m","version":"0"}}}' '{"jsonrpc":"2.0","method":"notifications/initialized"}' '{"jsonrpc":"2.0","id":1,"method":"tools/list","params":{}}' | timeout 60 "$F" mcp serve > /tmp/pc.out 2>&1; rc=$?
grep -v -e "e142.py not loaded" -e "took .*ms to load" -e "registered but cannot run" /tmp/pc.out | python3 -c '
import json, sys
lines = []
for line in sys.stdin:
    try:
        message = json.loads(line)
    except json.JSONDecodeError:
        lines.append(line.rstrip("\n"))
        continue
    if isinstance(message, dict) and message.get("id") == 1:
        tools = message.get("result", {}).get("tools", [])
        print("tools/list g156:", next((tool["name"] for tool in tools if "g156" in tool["name"]), "MISSING"))
    else:
        lines.append(line.rstrip("\n"))
print("\n".join(lines[-8:]))
'; echo "# exit $rc"
