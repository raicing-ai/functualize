"""Diff the per-surface cells of another Python version against 3.13."""
import json, os, re, subprocess, sys

def cells(out, surf):
    env = dict(os.environ, MCH_OUT=out, MCH_SURF=surf)
    code = "import json,surf_analyze;print(json.dumps(surf_analyze.table()))"
    return {r["id"]: r for r in json.loads(subprocess.check_output([sys.executable, "-c", code], env=env))}

def norm(v):
    return re.sub(r"0x[0-9a-f]+", "0x…", re.sub(r"\d+\.\d+ms|duration_ms\":[\d.]+", "", str(v)))

base = cells("out.json", "surfaces.json")
for out, surf in zip(sys.argv[1::2], sys.argv[2::2]):
    other = cells(out, surf)
    diffs = [(rid, k, base[rid][k], other[rid][k]) for rid in base for k in base[rid]
             if k not in ("label",) and norm(base[rid][k]) != norm(other[rid][k])]
    n = sum(1 for rid in base for k in base[rid] if k != "label")
    print(f"{surf}: {len(base)} rows × {len(base['A001']) - 2} surface cells = {n} cells compared; {len(diffs)} differ")
    for d in diffs:
        print("  ", d[0], d[1], "\n      3.13:", d[2], "\n      other:", d[3])
