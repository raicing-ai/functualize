"""R2: in-process engine calls that pass a value for a parameter the engine injects.

Walks every call to RunRequest(...), *.execute(...), invoke(...)/Invoke(...) in src/, plugins/*/*/src,
tests/, plugins/*/*/tests and examples/, and reports keyword arguments (directly, or inside a
literal `kwargs={...}` dict) whose value is a known capability test double or whose key is a
conventional capability parameter name.
"""
import ast, sys
from pathlib import Path
DOUBLES = {"FakeShell", "CapturingLog", "MockInvoke", "TestRunContext", "AutoPrompt", "NoopPerf", "FakeStdout"}
NAMES = {"rc", "run_context", "log", "sh", "shell", "tty", "prompt", "perf", "stdout", "state", "vault", "live", "invoke", "sources"}
CALLEES = {"RunRequest", "execute", "invoke", "run"}
hits = []
for root in ("src", "tests", "examples", *map(str, Path("plugins").glob("*/*/src")), *map(str, Path("plugins").glob("*/*/tests"))):
    for f in Path(root).rglob("*.py"):
        try:
            tree = ast.parse(f.read_text())
        except Exception:
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            fn = node.func
            name = fn.attr if isinstance(fn, ast.Attribute) else getattr(fn, "id", "")
            if name not in CALLEES:
                continue
            pairs = []
            for kw in node.keywords:
                if kw.arg == "kwargs" and isinstance(kw.value, ast.Dict):
                    pairs += [(k.value if isinstance(k, ast.Constant) else None, v) for k, v in zip(kw.value.keys, kw.value.values)]
                elif kw.arg:
                    pairs.append((kw.arg, kw.value))
            for k, v in pairs:
                dbl = isinstance(v, ast.Call) and getattr(v.func, "id", getattr(v.func, "attr", "")) in DOUBLES
                if dbl or (k in NAMES and name in ("RunRequest",)):
                    hits.append(f"{f}:{node.lineno} {name}(... {k}={ast.unparse(v)[:50]})")
print(len(hits)); print("\n".join(hits[:40]))
