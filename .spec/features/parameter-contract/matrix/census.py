"""AST census: function parameters in examples/ whose annotation is a collection or dict."""
import ast, sys
from pathlib import Path
hits = []
for f in Path("examples").rglob("*.py"):
    try:
        tree = ast.parse(f.read_text())
    except SyntaxError:
        continue
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            a = node.args
            for arg in [*a.posonlyargs, *a.args, *a.kwonlyargs]:
                if arg.annotation is None:
                    continue
                src = ast.unparse(arg.annotation)
                if any(k in src for k in ("list[", "tuple[", "dict[", "set[", "Secret[", "timedelta")):
                    hits.append(f"{f}:{arg.lineno} {node.name}({arg.arg}: {src})")
print(len(hits)); print("\n".join(hits))
