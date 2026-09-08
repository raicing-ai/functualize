# 11 — Executable Architecture

## 1. Package layout

```
risekit/
├── pyproject.toml
│     [project.scripts]                  rise = risekit._cli:main
│     [project.entry-points."functualize.plugins"]   rise = risekit.plugin:RISE
├── src/risekit/
│   ├── __init__.py                # the public vocabulary re-export
│   ├── plugin.py                  # ★ RisePlugin + the RISE entry-point instance (04)
│   ├── _cli/main.py               # ★ the standalone `rise` app (04 §1B)
│   ├── core/                      # vocabulary — pydantic + stdlib ONLY
│   │   ├── substrates.py          # Executable Package Process Repository Machine
│   │   │                          #   Endpoint Artifact Nothing  (+ supports tuples)
│   │   ├── protocols.py           # Installable Runnable Controllable Loggable
│   │   │                          #   Backupable Updatable Syncable
│   │   ├── targets.py             # Target, RepositoryTarget
│   │   ├── resource.py            # Resource: inherited diagnose/validate/audit
│   │   ├── models.py              # Declaration, Presence, per-substrate Diagnosis,
│   │   │                          #   Verdict, AuditEvent, Lockfile
│   │   ├── declaration.py         # declaration_of (live) + declaration_of_source (AST)
│   │   └── probes.py              # default probes per substrate
│   ├── binding/
│   │   ├── adapter.py             # ★ ClassBinding: 10 checks → Job list (03 §4)
│   │   ├── discovery.py           # module-class discovery (config + entry points)
│   │   └── naming.py              # method → surface name, subgroups, namespace
│   ├── registry/                  # router, lockfile, variant availability
│   ├── audit/                     # the JSONL appender
│   ├── schema/                    # export, listing
│   ├── modules/                   # risekit's own rise classes (meta, registry, doctor)
│   ├── generator/                 # `rise new`
│   ├── templates/
│   ├── tui/displays.py            # ★ RiseProjectDisplay — the [tui] extra only (18)
│   └── _skills/                   # force-included in the wheel
├── risekit-registry/              # default tool + repo registry
└── tests/
```

Two structural rules, enforced by import-linter contracts:

- **`risekit.core` imports pydantic and stdlib only** — not functualize. The
  vocabulary must be checkable without the runtime; this is what makes the
  "two prerequisites" substitution honest (`12` row 16) and what would let
  `core` become the shared kernel that the scrill/rise scenario-D analysis
  called for — see `17` §1, which settled that no separate kernel package is
  needed.
- **Only `risekit.binding`, `risekit.plugin`, `risekit._cli` and `risekit.tui`
  import functualize**, and only its public surfaces (`functualize.app`,
  `functualize.job`, `functualize.plugin`, `functualize.ui`).

  `risekit.tui` is the only one of the four that also imports **textual**, and
  it is the `[tui]` extra: the import must stay inside `risekit.tui.displays`
  so a headless install neither imports nor fails on it (`18` §3). The
  entry-point layout above also means `pyproject.toml` carries a third
  entry point — `[project.entry-points."functualize.displays"]` — beside the
  console script and the plugin.

Note what is *not* in the layout: no compatibility shim. v2 needed one for the
`parameters=[]` defect; the plugin binding path makes it unnecessary
(`03` §1).

## 2. Build order

Each step ends with a runnable proof, so the design cannot drift from the
evidence.

**Upstream first.** All five asks in `13` are being taken, and two of them
change what rise builds: ask 4 (a discovery pre-filter hook) makes rise modules
findable on disk, and ask 5 (public install detection) removes a chunk of the
registry. Both land before the steps that would otherwise work around them.

| # | Build | Proof |
|---|---|---|
| 0 | **functualize asks 1–5** (`13`) | functualize's own suite; a rise smoke test per ask |
| 1 | `core/substrates.py`, `protocols.py`, `models.py` | the abstract gate fires; per-substrate models round-trip |
| 2 | `binding/adapter.py` + `plugin.py` | `rise tools jsonschema install` runs a method — **probe 10 is the prototype** |
| 3 | `_cli/main.py`, and the entry point | **both deliveries** green — probe 12 |
| 4 | `core/declaration.py` (live + AST) | the equality property test over the fixture tree |
| 5 | `core/probes.py`, inherited `diagnose`/`validate` | golden NDJSON; strict + `extra="forbid"` rejections |
| 6 | `schema/export.py` | exported schemas re-validate the same records under `check-jsonschema` |
| 7 | `core/targets.py` + `Repository` | `code_audit` binds; a branch switch with identical bytes invalidates |
| 8 | `registry/` — router, lockfile, one tool + one repo, **over functualize's public planners** (ask 5) | install twice → `SUCCESS`, `SKIPPED`; clear lock → re-detect |
| 9 | `audit/` + the host guard | pexpect: prompt with a TTY; `tty is None` writes `mode="auto-continue"` |
| 10 | the destructive `test` prover | refuses (exit 3) on the host; passes in the container tier |
| 11 | `generator/` + `_skills/` | `rise new project` → `rise validate` reports only the TODOs |
| 12 | dogfooding | risekit manages its own dev tools; CI runs `rise validate` on itself |
| 13 | `tui/displays.py` + the `[tui]` extra (`18`) | the display appears in a rise project in **both** deliveries; absent outside; absent with textual uninstalled |

Step 3 before everything else substantial: if the two deliveries are going to
diverge, that is the cheapest moment to find out.

Step 13 last on purpose: it is the first thing in risekit to depend on textual,
and step 12 should prove the package works without it.

## 3. The tests that pin the probed claims

Each exists to fail loudly if a functualize upgrade moves something this design
leans on. All run parameterized over both deliveries (`04` §7).

| Test | Pins | Breaks if |
|---|---|---|
| `test_plugin_provider_registers` | a plugin's provider reaches the registry | plugin/boot ordering changes |
| `test_descriptor_parameters_present` | rise jobs publish a real `inputSchema` | provider extraction changes |
| `test_qualified_names_required` | FQ names produce two distinct runnable jobs — asserted as `len(jobs) == 2`, **not** as "the bare-name case errors": at `787035e` a bare-name collision keeps the first job and silently drops the second (defect #32; `evidence/README.md` drift table) | `StaticProvider` keying changes |
| `test_namespace_in_group` | guest mounting resolves | trie/group handling changes |
| `test_bound_method_parameters` | `self` skipped, capabilities excluded | extraction changes |
| `test_abstract_gate` | binding rejects an incomplete class | — |
| `test_status_guard_skips` | second `install` is `SKIPPED`, exit 0 | guard semantics change |
| `test_precondition_refuses` | destructive tier outside isolation exits 3 | — |
| `test_method_job_declaration` | `@job(guards=…)` on a method reaches the executor | `adopt_descriptor_declaration` changes |
| `test_no_builtin_namespace` | no rise group is named `builtin` | — |
| `test_tty_branch` | `tty is None` off a terminal; prompt defaults as measured | interactivity model changes |
| `test_declaration_source_equals_live` | AST reader == live reflection | a module violates the constructor contract |
| `test_missing_dep_is_diagnosed` | a failed import is reported, not swallowed | the `doctor` surface regresses |
| `test_display_protocol_satisfied` | `isinstance(RiseProjectDisplay(), DisplayProvider)` | `DisplayProvider` gains a member |
| `test_should_show_is_pure` | `should_show` is one `is_dir()`, imports no project code | rise grows I/O on the loop thread |
| `test_local_display_coexists` | a project `displays.py` with a distinct id registers alongside rise's | discovery order or dedupe changes (`18` §5) |
| `test_headless_import` | importing `risekit` with textual absent yields no display and no error | the textual import escapes `risekit.tui` |

## 4. Where the critiques live

| Critique | Answered in |
|---|---|
| OOP modules | `core/substrates.py` + `binding/adapter.py`; `02` |
| kinds / interfaces / validation | the three axes + the five-layer ladder; `01` |
| code reuse | inherited meta-reflected `diagnose`/`validate`; `05` |
| repositories, and modules that act on things | `Repository` substrate + `Target`; `01` §2, §5 |
| one framework or two CLIs | one plugin, two hosts; `04` |
