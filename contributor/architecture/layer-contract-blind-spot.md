# The layer contract's blind spot

**Setting**: `pyproject.toml:234` — `exclude_type_checking_imports = true`. **Unchanged,
deliberately.**
**Measured**: 2026-09-10, on a tree of 333 source files.
**Why this file exists**: `contributor/reference/pitfalls.md` §5 — *a fingerprint is only worth
the number of construction sites that supply it*. The same shape applies to a rule: a contract is
only worth the imports it can see. This one has a measured hole rather than a footnote.

`import-linter` builds its graph from imports it can evaluate. With this flag on, an import
inside `if TYPE_CHECKING:` is not an edge, so it crosses a boundary the six
`[tool.importlinter]` contracts refuse and CI stays green. Nothing about that is a bug in
`import-linter` or in the flag — the flag exists for good reasons. It *is* a gap between the
rule as written (`CONSTITUTION.md` → *Layer Dependency Rules*) and the rule as enforced, and a
reviewer who does not know its size will trust the gate more than it deserves.

## 1. What the six contracts do enforce

| Contract | Type | Refuses |
|---|---|---|
| `Peer layers are independent` | independence | `_discovery`, `_config`, `_engine`, `_plugins`, `_gate` importing one another |
| `Events depends on foundation only` | forbidden | `_events` → anything but `_types`, `_primitives` |
| `Primitives import nothing internal` | forbidden | `_primitives` → anything but `_types` |
| `Types import nothing internal` | forbidden | `_types` → any internal package |
| `Internal never imports public` | forbidden | any `_*` package → `app`, `job`, `plugin`, `types`, `testing`, `workflow` |
| `_cli uses public API only` | forbidden | `_cli` → any `_*` package |

Every one of these catches a **runtime** import. That is not a small thing: it is how
`_events/adapter.py`'s runtime `_config` import was found (the file that motivated the events
contract — see the comment above `Events depends on foundation only`), and it is the reason the
`_cli` contract can be trusted to keep the dogfooding rule honest.

## 2. What the flag hides — measured

Counted with an AST walk, not a regex: every `import` / `from … import …` statement inside an
`if TYPE_CHECKING:` guard (any nesting), resolving relative imports to their absolute module.

| Target of the hidden import | Statements | Imported names |
|---|---|---|
| an internal package (`functualize._*`) | **155** | 174 |
| a public package, from an internal source | 27 | 33 |
| a public package, from a public source | 11 | 11 |
| stdlib / third party (allowed anywhere) | 92 | 119 |

`functualize._cli` (42 statements), `functualize._engine` (39) and `functualize.app` (27) are the
largest sources; `functualize._types` (48) and `functualize._cli` (39) the largest targets.

**Only 8 of the 155 cross a boundary the contracts would refuse as a direct edge** — five package
pairs: `_cli → _types` (3), `_engine → _gate` (2), `_cli → _events`, `_engine → _config`,
`_types → _events`. The rest are intra-package (a module importing a sibling) or point at a layer
the contract allows (`_engine → _types`, `app → _any internal`). The blind spot is therefore not
"155 violations waiting to be found": it is **155 invisible edges, 8 of them direct violations,
and the indirect chains those edges create** (§3).

## 3. The measurement: what happens if the flag is flipped

Method — a temporary copy of the `[tool.importlinter]` section outside the tree, so nothing in
the repository changes:

```bash
python3 - <<'PY'
import pathlib
text = pathlib.Path("pyproject.toml").read_text()
section = text[text.index("[tool.importlinter]"):]
pathlib.Path("/tmp/blind-spot/importlinter.toml").write_text(
    section.replace("exclude_type_checking_imports = true",
                    "exclude_type_checking_imports = false"))
PY
uv run lint-imports --config /tmp/blind-spot/importlinter.toml --no-cache
```

Result on this tree (333 files, 1030 dependencies): **1 kept, 5 broken.**

```
Peer layers are independent          BROKEN
Events depends on foundation only    KEPT
Primitives import nothing internal   BROKEN
Types import nothing internal        BROKEN
Internal never imports public        BROKEN
_cli uses public API only            BROKEN

Contracts: 1 kept, 5 broken.
```

20 import chains over 22 distinct module → module pairs. The table is the *whole* expose; the
interesting part is the last column.

| The hidden import lives in | Chain import-linter then reports | Contract |
|---|---|---|
| `_engine.capabilities.runcontext` | → `_config.job_config` | Peer |
| `_discovery.registry` | → `app.core` → `_engine.ambient`, `.capabilities.invoke`, `.executor`, `.explain`, `.guards`, `.preflight`, `.result` | Peer |
| `_discovery.registry` | → `job.context` → `job._runcontext` → `_engine.capabilities.runcontext` | Peer |
| `_discovery.registry` | → `app.core` → `_gate._registry`, `._resolver` | Peer |
| `_discovery.registry` | → `app.core` → `_plugins.domain_registry`, `.loader` | Peer |
| `_discovery.registry` | → `app.core` → `_config`, `.job_config`, `.registry` | Peer |
| `_engine.capabilities.invoke` | → `_gate._strategy`, `._registry` | Peer |
| `_discovery.filter_factory` | → `app.config` → `_config` | Peer |
| `_primitives.pre_filter` | → `_types.protocols` → `_types.interactivity` → `_events.bus` | Primitives |
| `_types.interactivity` | → `_events.bus` | Types |
| `_app.impl` | → `app.config` | Internal never imports public |
| `_discovery.filter_factory` | → `app.config` | Internal never imports public |
| `_discovery.registry` | → `app.core` | Internal never imports public |
| `_discovery.registry` | → `job.context` | Internal never imports public |
| `_engine.capabilities.invoke` | → `job._workflow_scope` | Internal never imports public |
| `_cli.tui.panel_live_zone` | → `_events.bus` | `_cli` public API only |
| `_cli.tui.live_panel_widget`, `_cli.tui.panel_live_zone` | → `_types.interactivity` | `_cli` public API only |
| `_cli.tui.panels.job_browser` | → `_types.descriptors` | `_cli` public API only |

**Why 8 direct violations break 5 of 6 contracts.** An edge added to the graph does not only
commit its own endpoints; it joins every path that passes through them. `_primitives.pre_filter
→ _types.protocols` is legal on its own, but `_types.protocols → _types.interactivity →
_events.bus` is another hidden edge, and the composed path `_primitives → _events` is what the
Primitives contract refuses. The same composition turns `_discovery.registry → app.core` — one
hidden import of a *public* module — into five separate peer-layer violations, because
`app.core` is the composition root and imports nearly every internal package at runtime. One
invisible annotation-only import of `FunctualizeApp` re-opens the whole layering question for the
package that holds it.

`Events depends on foundation only` stays green: no `_events` module has a TYPE_CHECKING import
of a peer layer today. It did not break at this commit, and would if one were added — which is
exactly the kind of import a reviewer would have no automated warning about.

## 4. Why the flag stays on

Flipping it is not a fix. The 8 direct violations are annotation-only references that would have
to become one of:

1. **runtime imports** — `_cli/tui/` importing `_types.interactivity` and `_events.bus` at module
   scope, which is what the `_cli` contract exists to prevent, and boot cost on the TUI path;
2. **a `_types` re-export or protocol** — the right answer for some of them (the `_types →
   _events.bus` annotation is the kind of reference a protocol in `_types` can carry); and a
   public-API decision for the rest, because `_discovery.registry` reaching `FunctualizeApp` under
   `TYPE_CHECKING` is a question about `_discovery`'s seam, not an import nit;
3. **contract exemptions** — six contracts carrying exception lists, which is the outcome
   `CONSTITUTION.md` → *Forbidden Patterns* calls "burying the rule".

So the hole is **documented and bounded** instead of closed: the number below is the thing to
compare against next time, and a change that grows it is a change a reviewer should be able to
see.

## 5. What a reviewer has to check by hand

No contract will tell you. Every item here passes CI.

- **A new `TYPE_CHECKING` import is a layer decision, not a typing convenience.** Ask what the
  runtime import would be. If the answer is "a violation", the annotation-only form is the same
  violation with the gate switched off — pick a layer that can hold the type (`_types`), or move
  the seam.
- **`_types` and `_primitives` are the two that look harmless and are not.** A `_types` module
  TYPE_CHECKING-importing `_primitives` or `_events` is exactly as forbidden as the runtime form
  (`_types` is stdlib-only), and `_primitives` may reach `_types` and nothing else.
- **Public modules are not a shortcut between internal layers.** `_discovery.registry →
  functualize.app.core` under `TYPE_CHECKING` is one hidden line that, on the flip, produces five
  peer-layer violations through `app.core`'s runtime fan-out (§3).
- **`_cli`'s dogfooding rule has no runtime backstop at all.** `_cli → _types.interactivity` is
  what the flag hid four times in `_cli/tui/`; the contract catches the runtime spelling only.
- Read the guard, not the grep. `rg -n -A20 'if TYPE_CHECKING' <file>` shows the imports that
  matter; a count of them tells you nothing about their targets.

## 6. Re-measuring

The census (paste as one `python3` heredoc from the repository root):

```python
import ast, pathlib

SRC = pathlib.Path("src/functualize")
internal = public_from_internal = public_from_public = other = 0
for f in sorted(SRC.rglob("*.py")):
    mod = "functualize." + ".".join(f.relative_to(SRC).with_suffix("").parts).removesuffix(
        ".__init__")
    source_is_internal = mod.split(".")[1].startswith("_")
    pkg_parts = mod.split(".")[:-1]
    for node in ast.walk(ast.parse(f.read_text(encoding="utf-8"))):
        if not isinstance(node, ast.If):
            continue
        test = node.test
        if not (getattr(test, "id", None) == "TYPE_CHECKING"
                or getattr(test, "attr", None) == "TYPE_CHECKING"):
            continue
        for sub in node.body:
            if isinstance(sub, ast.ImportFrom):
                if sub.level:
                    base = pkg_parts[: len(pkg_parts) - (sub.level - 1)]
                    target = ".".join(base + ([sub.module] if sub.module else []))
                else:
                    target = sub.module or ""
            elif isinstance(sub, ast.Import):
                target = sub.names[0].name
            else:
                continue
            if target.startswith("functualize._"):
                internal += 1
            elif target.startswith("functualize."):
                if source_is_internal:
                    public_from_internal += 1
                else:
                    public_from_public += 1
            else:
                other += 1
print(
    f"internal={internal} public_from_internal={public_from_internal} "
    f"public_from_public={public_from_public} other={other}"
)
```

Today: `internal=155 public_from_internal=27 public_from_public=11 other=92`, over 335 files (the
same day's first run saw 333; the counts did not move, and they are what to compare — not the
file total). The flip is §3's two commands. Both are cheap; run them when a wave of work touches
import structure, and record the movement here rather than rediscovering the shape.

**What growth looks like**: `internal` rising is not automatically bad (annotation-only imports
of an allowed layer are fine). `_cli.tui → _types.*`, `_discovery → app.*`, `_engine → _gate` and
any `_types → _*` are the ones that add violations to the flip; the flip's chain count is the
number to watch.

## 7. What this file does not do

- It does not flip the flag, and it does not change a single import. `pyproject.toml`'s setting
  is untouched.
- It does not list the 155 imports. They are stable enough to measure and too volatile to
  transcribe; §6 measures the whole set in one pass.
- It is not an exemption. Nothing here legalizes a TYPE_CHECKING import across a layer the
  contracts refuse — it records that such an import is currently unenforced, so a reviewer can
  refuse it deliberately.

## 8. Recorded figures that no longer reproduce

`spec.md` §1.4 and `tasks.md` T8 were written against an earlier tree and record **125** hidden
`TYPE_CHECKING` imports of internal packages, **47** violations when the flag is flipped, **all
six** contracts broken, and a breakdown of `_cli/tui/` 18, `_engine/` 8, `_types/` 7, `_app/` 6.
Re-run at this commit, none of those four numbers survives:

| Recorded | Re-measured 2026-09-10 | Note |
|---|---|---|
| 125 hidden internal imports | **155** | the tree grew — `.serena/memories/architecture-layer-contract.md` records 318 files / 816 dependencies, this run analyses 333 / 1030 |
| 47 violations | **20 chains / 22 module pairs** | 8 direct violations; the rest of the 47 was presumably counted over indirect expansions, by a convention this file does not share |
| all six contracts broken | **5 of 6** | `Events depends on foundation only` is KEPT: no `_events` module carries such an import today |
| `_cli/tui/` 18, `_engine/` 8, `_types/` 7, `_app/` 6 | `_cli.tui` 4, `_engine.capabilities` 4, `_types.interactivity` 1, `_app.impl` 1 | per-*package* counts of the source that holds the hidden import |

The direction is unchanged and the conclusion is identical — the flag hides a real hole across
every contract, most of its hidden imports are legitimate annotation-only references, and it
stays on. The magnitude, though, had to be re-measured: this branch has already recorded three
task censuses that undercounted, all of them written by reading rather than by running.

## 9. Adjacent gap, found while measuring (not this flag's doing)

The contracts' list of public packages is six (`app`, `job`, `plugin`, `types`, `testing`,
`workflow`). `src/functualize/ui/` is a **seventh**, and no contract names it — so
`_cli/inline_tui.py:213`'s runtime `from functualize.ui import stdout_live_session` and
`_cli/tui/app.py`'s `from functualize.ui import Display` pass `_cli uses public API only` while
the identical import from `functualize._types` would fail it. Whether `functualize.ui` is public
or delivery-internal is a real question (it is absent from `CONSTITUTION.md`'s public-folder list
and from `AGENTS.md`'s), and it is not a `TYPE_CHECKING` issue. Recorded here because the
measurement that produced this file is the only place it surfaced; it needs its own decision.

`contributor/architecture/codemaps/dependencies.md:25` still says *"five contracts"*. There have
been six since `Events depends on foundation only` was added, and its list omits both that
contract and `_gate`'s membership in the independence contract.
