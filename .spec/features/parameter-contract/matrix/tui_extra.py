"""Rows where `func <job> <tokens>` exits 2 ("Got unexpected extra argument") but the
inline TUI door, given the same tokens, runs the job (tokens silently dropped)."""
import json
out = json.load(open("out.json")); s = json.load(open("surfaces.json"))
ids = []
for row in out["rows"]:
    rid, pos = row["id"], row["runs"].get("pos")
    if not pos or "unexpected extra" not in pos["stderr"]:
        continue
    t = s["probe"].get(rid, {}).get("tui_pos")
    if t and str(t.get("status", "")).lower() == "success":
        ids.append(rid)
print(f"{len(ids)} rows: {' '.join(ids)}")
