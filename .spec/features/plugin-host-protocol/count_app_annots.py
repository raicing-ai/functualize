"""Census the `app` parameter annotations across `plugins/*/src`.

`plugin-host-protocol` T11's gate. An `ast` walk rather than `rg`, because a
Google-style docstring line — `app: The FunctualizeApp instance` — matches the
same regex: the two disagreed by four on this repository (42 vs 40 of 44), and
`.claude/rules/spec-workflow.md` → *Retrieval discipline* says a count about
syntax is an AST question.

    uv run python .spec/features/plugin-host-protocol/count_app_annots.py
"""

import ast
import collections
import pathlib

root = pathlib.Path(".")
counts = collections.Counter()
sites = collections.defaultdict(list)

for py in sorted(root.glob("plugins/*/src/**/*.py")):
    try:
        tree = ast.parse(py.read_text(encoding="utf-8"))
    except SyntaxError:
        continue
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        a = node.args
        for arg in list(a.posonlyargs) + list(a.args) + list(a.kwonlyargs):
            if arg.arg != "app":
                continue
            ann = ast.unparse(arg.annotation) if arg.annotation else "<none>"
            counts[ann] += 1
            sites[ann].append(f"{py}:{arg.lineno} {node.name}")

total = sum(counts.values())
print(f"TOTAL `app` parameters in plugins/*/src: {total}\n")
for ann, count in counts.most_common():
    print(f"{count:4d}  app: {ann}")

anyish = sum(n for a, n in counts.items() if a.replace(" ", "").split("|")[0] == "Any")
concrete = sum(n for a, n in counts.items() if "FunctualizeApp" in a)
none_ann = counts.get("<none>", 0)
print(f"\nAny-typed:        {anyish}")
print(f"FunctualizeApp:   {concrete}")
print(f"Unannotated:      {none_ann}")
print(f"pct Any of total: {100 * anyish / total:.0f}%")
print("\n--- FunctualizeApp-annotated sites ---")
for ann in counts:
    if "FunctualizeApp" in ann:
        for site in sites[ann]:
            print(f"  [{ann}] {site}")
