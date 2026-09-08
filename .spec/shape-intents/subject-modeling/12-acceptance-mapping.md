# 12 — Acceptance Mapping

All **69** criteria from `intent/10-acceptance-criteria.md`, re-scored
under the three-axis vocabulary and the dual delivery.

**Verdicts** — **met** / **reduced** (substance delivered by a different
mechanism; the delta is in the row) / **partial** / **unmet**.

Every test runs parameterized over **both deliveries** (`04` §7).

## A. Vocabulary & declaration (1–8)

| # | Criterion | Mechanism | Verdict |
|---|---|---|---|
| 1 | declaration in one machine-readable block at the top | the class statement; AST-readable (`02` §5) | met |
| 2 | closed enum of eight kinds | **eight presets over closed substrate/action sets** (`01` §7); the presets are still eight, but no longer the only legal shapes | reduced |
| 3 | closed enum of five interfaces | seven action Protocols in `risekit.core.protocols`, closed; three intent members (`daemon`→`Controllable`+`Loggable`, `continuous-integration`→dropped per `01` §4) re-expressed | reduced |
| 4 | interface claims are kind-scoped | `supports` tuple per substrate + binding check 5 | met |
| 5 | empty interface list by default; substrate-as-action rejected | substrates are classes, not Protocols; check 1 rejects conflicting substrates | met |
| 6 | strategy names never actions; dot-notation rejected | no strategy Protocol exists — `ImportError` | met |
| 7 | a new variant needs no schema change | a variant is a subclass, discovered by import | met |
| 8 | programs must declare isolation | required `ClassVar` + binding check 3 | met |

## B. Validation pipeline (9–17)

| # | Criterion | Mechanism | Verdict |
|---|---|---|---|
| 9 | two-step validate | inherited `Resource.validate` (`05` §4) | met |
| 10 | unknown kind rejected | no such class → `ImportError` | met |
| 11 | missing action / config / tag rejected | `@abstractmethod` **[probed]** + checks 3, 7 | met |
| 12 | interface claimed but unimplemented rejected | mypy (signatures) + `isinstance` (presence) | met |
| 13 | record missing required fields rejected | required model fields + `Literal["N/A"]` | met |
| 14 | undeclared record field rejected | `ConfigDict(extra="forbid")` | met |
| 15 | validation recursive over the tree | the walk calls each module's inherited `validate` | met |
| 16 | exactly two runtime prerequisites | **substituted**: `risekit.core` imports pydantic + stdlib only (import-linter contract); the runtime adds functualize | reduced |
| 17 | standard draft-stable schema documents | `rise schema export` → JSON Schema 2020-12, so **step 2** is re-checkable by any validator; **step 1** is a property of code (`05` §5) | partial |

## C. Diagnosis record (18–25)

| # | Criterion | Mechanism | Verdict |
|---|---|---|---|
| 18 | one JSONL record per module | `Stdout.emit` + `--output ndjson` | met |
| 19 | static kinds emit no runtime block | `Nothing` substrate; dispatch by MRO | met |
| 20 | program block: platform, isolation, installed, actions | `Executable` presence block | met |
| 21 | `runs_correctly` verified by execution | the default probe runs the binary | met |
| 22 | library proves install by import | `importlib.util.find_spec` | met |
| 23 | service status detected | `Process` presence probe | met |
| 24 | record is the single source of truth | lifecycle methods call `self.diagnose()`; the overwrite check reads its block | met |
| 25 | declaration extraction reads the module's own file | `declaration_of_source()` — AST, no import, no execution | met |

## D. Registry & routing (26–35)

| # | Criterion | Mechanism | Verdict |
|---|---|---|---|
| 26 | the registry is itself a module | `ToolRouter`, bound by the same adapter | met |
| 27 | tool → variant, each self-describing | variant subclasses | met |
| 28 | router exposes install/uninstall/test/lock/run (rise's `invoke` action is renamed `run`, `14`) | router methods + inherited | met |
| 29 | auto-detect by ordered preference | `resolve_variant` (`06` §3) | met |
| 30 | lockfile records auto/user with full state | the `Lockfile` model | met |
| 31 | explicit variant honoured forever | `resolved_by == "user"` short-circuit | met |
| 32 | re-install is a no-op | `Guards(status=…)` → exit 0 **[probed]** | met |
| 33 | fixed-size surface via wildcard dispatch | the *property* holds (tools are groups, variants are an option); the wildcard *mechanism* is replaced | reduced |
| 34 | registry ops incl. scaffold | router methods; scaffold is `rise new variant` | met |
| 35 | lockfiles re-derivable | `rise registry lock clear` → re-detect | met |

## E. Safety (36–43)

| # | Criterion | Mechanism | Verdict |
|---|---|---|---|
| 36 | every mutating operation idempotent | status guards **[probed]** | met |
| 37 | host install: banner + confirm, non-zero on refusal | `prompt_confirm(destructive=True, default=False)` in the `tty is not None` arm | met |
| 38 | non-interactive auto-continues with a log record | the `tty is None` arm + `audit(mode="auto-continue")` **[probed]** | met |
| 39 | different-origin install warns and confirms | origin comparison against the record | met |
| 40 | project/process installs prompt nothing | the `isolation is HOST` guard | met |
| 41 | one JSONL audit record per lifecycle event | inherited `Resource.audit()` | met |
| 42 | logging writes nothing to the console | the appender takes no `Log` | met |
| 43 | audit dir on demand; location overridable | `mkdir(parents=True, exist_ok=True)`; `audit.path` | met |

## F. Testing (44–48)

| # | Criterion | Mechanism | Verdict |
|---|---|---|---|
| 44 | program/library/service expose `test` | `test` in each preset's abstract set | met |
| 45 | full `test` runs each step twice | a job body driving `rc.invoke`, **asserting** `SKIPPED` (`08` §6) — not a workflow | met |
| 46 | dev machine non-destructive only | `Guards(preconditions=[in_isolated_runner])` → exit 3 | met |
| 47 | fast + isolated tiers | the same precondition; CI marker selects | met |
| 48 | rejection suite (11 named cases) | parametrized across binding checks 1–10 and the record models | met |

## G. Lifecycle & UX (49–56)

| # | Criterion | Mechanism | Verdict |
|---|---|---|---|
| 49 | one-line install; only hard dep is the task runner | `uv tool install risekit` (host) or `pip install risekit` into an existing func (guest); runtime deps are functualize + pydantic | met |
| 50 | `init` scaffolds a self-contained project | `rise new project` (`09` §3) — **minus** the extensions file and framework schema layer, both deleted by design (`10` §4) | reduced |
| 51 | `init` touches nothing existing | additive writes; dry-run diff on a non-empty target | met |
| 52 | `bootstrap` installs all declared tools | `Bootstrap.bootstrap`; **also declared repos** (`06` §6) | met |
| 53 | bare root prints a curated menu | click help / TUI root | met |
| 54 | colon-namespaced naming used consistently | space-separated groups; the discoverable-family property is identical, the spelling is not | reduced |
| 55 | `upgrade`; one command rebuilds the effective schema | **inherited** `rise builtin self update` **[probed]**. **No rebuild exists** — no effective-schema artifact | reduced |
| 56 | works with the global install absent | the project depends on risekit | met |

## H. Extension model (57–62)

| # | Criterion | Mechanism | Verdict |
|---|---|---|---|
| 57 | extensions survive upgrades | project vocabulary in project-owned files | met |
| 58 | `schema kind add` / `interface add` validate, update, rebuild | `rise new substrate` / `new action`, idempotent. **No rebuild step** | reduced |
| 59 | the effective schema is the single validation authority | **no merged artifact**; replaced by "one binding path, no second authority" (`10` §4) | reduced |
| 60 | a malformed extension fails loudly | `SyntaxError`/`TypeError` at import | met |
| 61 | a pin makes validation immune to upgrades | **step 1 unmet** — the vocabulary *is* the installed classes. **step 2 met under option 2**: committed `contracts/` + `rise validate --contracts` (`10` §6) | unmet (step 1) |
| 62 | new interfaces get variants without schema work | variant subclasses implement the Protocol directly | met |

## I. Agent alignment (63–67)

| # | Criterion | Mechanism | Verdict |
|---|---|---|---|
| 63 | per-persona docs ship, refresh on upgrade | `risekit/_skills/`, force-included, version-stamped | met |
| 64 | strategy reference tables ship | markdown in the same directory | met |
| 65 | ADRs recorded | `contributor/adr/` | met |
| 66 | agent reads risk and state **without executing** | isolation + diagnosis in `info schema` / MCP — **correct through the plugin binding path with no upstream patch [probed]** — plus `declaration_of_source()`, which answers with no import at all | met |
| 67 | generate → validate → fix converges | stubs raise, so `validate` reports each TODO (`09` §4) | met |

## J. Dogfooding (68–69)

| # | Criterion | Mechanism | Verdict |
|---|---|---|---|
| 68 | the framework repo is itself a valid project | risekit manages its own dev tools | met |
| 69 | the framework passes its own validation | CI | met |

---

## Tally

| Verdict | Count | Criteria |
|---|---|---|
| met | 58 | — |
| reduced | 9 | 2, 3, 16, 33, 50, 54, 55, 58, 59 |
| partial | 1 | 17 |
| unmet | 1 | 61 (step 1; step 2 met under option 2) |
| **total** | **69** | |

## What changed from v2's scoring

| # | v2 | v3 | Why |
|---|---|---|---|
| 2, 3 | met | **reduced** | The three-axis model makes the eight kinds presets, not the only shapes, and re-expresses two of the five interfaces (`01` §4). v2 scored these met under the eight-kind model it was simultaneously arguing against — an inconsistency v3 resolves by scoring what it actually proposes. |
| 66 | met **⚠ gated on upstream P1** | **met** | The plugin binding path publishes real parameters with no patch **[probed]** (`03` §1). |
| 55 | reduced | reduced | unchanged, but the mechanism is now the inherited `self update` rather than a rise-written verb. |

Six of the nine reductions (16, 50, 54, 55, 58, 59) are one trade taken six
times: **the intent describes a schema-document architecture, and the class
model replaces documents with code.** Two more (2, 3) are the cost of the
three-axis split — a more expressive vocabulary in exchange for a less
enumerable one. One (33) is a mechanism substitution whose observable property
is preserved.

The single unmet criterion is inherent, not incidental: when the vocabulary
*is* the installed classes, a version pin cannot select a different vocabulary.
`10` §6 offers the two honest answers rather than a warning dressed as
immunity.
