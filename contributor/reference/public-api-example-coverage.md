# Every public API is exercised by an example

**Rule** (maintainer, 2026-09-17): a symbol in a public package's `__all__`, and
every public member of a public class, must have at least one caller in
`examples/`.

**Measured**: 2026-09-17, against `79545ef`. The rule is new; the backlog below
is what it inherits.

## Why this is a rule and not a nicety

Two things it buys, and the second is the one that motivated it.

**1. Examples are collected by pytest.** `examples/conftest.py` puts every
standalone example directory on `sys.path`, and `examples/` runs as its own
suite (`spec.md` AC-12 in any feature that touches it). So an example that
calls a public API is an **end-to-end integration test** of that API, through
the same door a user comes in. No separate test tier has to be invented.

**2. It makes "no callers" mean something.** A dead-code audit asks serena for
references and reads zero as evidence. For public API that inference is
invalid — the callers are in other people's repositories — so the honest
verdict on a public symbol with no internal reference is *unknown*, not *dead*.
That is a bad place to leave a hygiene process: the audit either produces false
positives or has to exempt the whole public surface and see nothing.

This rule collapses the ambiguity. Once every public symbol has an example
caller, **zero callers means dead again**, including for public API, because the
example is the caller that should exist and doesn't.

It happened: `.spec/plans/dead-code-audit/SUMMARY.md` W4 reported
`FunctualizeApp.cache_stats` and `.domain_registry` as dead on serena's zero
references. Both are public members of a public class, so the audit's own
`CONTRACT.md` excluded them by design — *"public folders are stable API even if
unreferenced internally"* — and the finding was withdrawn
(`.spec/features/plugin-host-protocol/spec.md` §G). Under this rule the right
finding would have been available instead: *these two public members have no
example, so nothing in this repository demonstrates them.*

## The gate for new public API

`contributor/guides/adding-public-api.md` step 8. A new public symbol without an
example is not finished. This is the cheap half of the rule — it applies at the
moment the surface is added, when writing the example costs one file.

## The backlog, measured

| Population | Total | Has an `examples/` reference | Has none |
|---|---:|---:|---:|
| Symbols in public `__all__`, at `79545ef` | 161 | 53 | **108** (67%) |
| Symbols in public `__all__`, after `plugin-host-protocol` | 162 | 57 | **105** (65%) |
| `FunctualizeApp` members, at `79545ef` | 41 defs / **38 distinct** | 10 | **31 defs / 29 distinct** |
| `FunctualizeApp` members, after `plugin-host-protocol` | **40 distinct** | 19 | **21** |

The 21 still unexercised:

```
cache_stats, cli_command, collector, domain_registry, execute_parallel,
explain, explain_data, explain_verdicts, get_descriptor, live_zone,
max_invoke_depth, middleware, perf_timeline, pop_surface, push_surface,
registered_jobs, replace_job, resolution_chain, run_log, scope_for, workflows
```

**What moved, and why it is worth reading.** The original list opened with the
observation that *"`di`, `gates`, `extensions` and `configuration` — the six
typed facades are the headline of the post-#39 plugin surface, and no example
touches four of them."* `examples/standalone/plugin_host/` is that example:
`di`, `extensions` and `hooks` are called, `configuration` and `gates` are
named, and `execute`, `get_jobs`, `get_job`, `fresh_root`, `substrate` and
`install_substrate` came with the rest of the feature. Eight members left the
list; the total rose by two, because T3 split one name into three.

`cache_stats` and `domain_registry` remain, and they are the pair the
dead-code audit reported as dead on zero references — the case that produced
this rule (see above). They are still the most valuable two to write next,
for exactly that reason.

**This is a baseline, not a pass/fail.** 108 is the number to compare against
next time; a change that grows it is a change a reviewer should be able to see.
The same instrument-and-bound approach as
`contributor/architecture/layer-contract-blind-spot.md`, and for the same
reason: a rule enforced retroactively over 108 items lands red, and a red gate
is one people learn to scroll past.

## Re-measuring

```python
import ast, pathlib, re

SRC = pathlib.Path("src/functualize")
symbols = {}
for pkg in ["app", "job", "plugin", "types", "testing", "workflow", "ui"]:
    f = SRC / pkg / "__init__.py"
    if not f.exists():
        continue
    for node in ast.walk(ast.parse(f.read_text())):
        if isinstance(node, ast.Assign) and any(
            getattr(t, "id", None) == "__all__" for t in node.targets
        ):
            if isinstance(node.value, (ast.List, ast.Tuple)):
                for el in node.value.elts:
                    if isinstance(el, ast.Constant) and isinstance(el.value, str):
                        symbols.setdefault(el.value, set()).add(pkg)

ex = " ".join(
    p.read_text(errors="ignore")
    for p in pathlib.Path("examples").rglob("*")
    if p.is_file() and p.suffix in (".py", ".md", ".toml", ".j2")
)
missing = sorted(s for s in symbols if not re.search(rf"\b{re.escape(s)}\b", ex))
print(f"public symbols={len(symbols)} uncovered={len(missing)}")
```

**Read the limitation before trusting the number.** This census is a
word-boundary text search, so a symbol merely *named in an example's prose*
counts as covered. The true gap is therefore **at least** the number shown,
never fewer —
the same lesson as counting annotations with `rg` instead of `ast`
(`.claude/rules/spec-workflow.md` → *Retrieval discipline*). Tightening it to
"imported and called in a `.py` file under `examples/`" would raise the number;
do that when the backlog is being worked, not to make the baseline look worse
than it is being acted on.

## What this rule is not

- **Not a replacement for unit tests.** `tests/` still owns edge cases, error
  paths and properties. An example demonstrates the *supported* use.
- **Not a demand for one example per symbol.** One example may exercise many
  symbols; `app.di`, `app.gates` and `app.extensions` would naturally share a
  plugin example.
- **Not applicable to internal packages.** `_`-prefixed layers have their
  callers in this repository, so serena's zero really is zero there.
- **Not the docs-parity pass.** `contributor/guides/docs-example-parity.md`
  checks that what the docs *claim* still holds. This checks that what the API
  *offers* is demonstrated at all. A symbol can pass one and fail the other.
