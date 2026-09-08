# 14 — Risks & Decisions

## 1. Risks

**R1 — Instantiation at binding runs `__init__`.** The adapter constructs each
class once at boot. Mitigated by the checked constructor contract (`02` §7):
no-arg construction and stable identity are mechanical; side-effect freedom is
docstring + template + lint, and the AST-vs-live equality test catches computed
declarations.

**R2 — Group collisions in the guest delivery.** A host project with a
top-level `rise` group, or with colliding job names, breaks in a way rise
cannot fix — and `StaticProvider` makes collisions *total* rather than local
(`03` §3a). Mitigated three ways: the namespace is configurable
(`[risekit] namespace`), binding check 8 tests the composed group against the
host's existing names and rejects the *module* rather than the boot, and
`rise doctor` reports the mount point and near-collisions (`04` §6).

**R3 — Two deliveries drifting.** The whole "one binding" claim rests on the
plugin being the only integration point. Mitigated by running every acceptance
test parameterized over both deliveries (`04` §7) — a divergence shows up as a
failure in exactly one parameterization.

**R4 — No discovery cache for rise modules.** Every boot imports every module
class (`03` §6). At project scale that is milliseconds. If it stops being so:
keep module bodies import-light, measure with functualize's own perf timeline,
and take upstream ask 3 rather than building a rise-owned cache with its own
invalidation rules — the drift class this design exists to avoid.

**R5 — `runtime_checkable` under-promises.** `isinstance` checks method
presence only, not signatures or non-method members. A class with
`def backup(self, extra)` passes and fails at call time. Mitigated by mypy as
layer 1, mandatory in the project template's CI (`02` §6).

**R6 — The AST reader can diverge.** A dynamically built base list or computed
tag is invisible to it. Forbidden by the constructor contract and caught by the
equality property test, which names the module.

**R7 — Audit log has no rotation or locking.** Append-only JSONL at CLI scale,
per the intent. Concurrent short appends are safe in practice on POSIX and not
guaranteed elsewhere. Accepted for v1; recorded so it is a decision, not an
omission.

**R8 — Reserved namespaces may grow.** `builtin` is reserved today
(`_types/naming.py:207`) and `!`/`?` are reserved sigils. Binding check 8 asks
functualize's own rules rather than hard-coding a list, so a future reservation
surfaces as a rise binding error naming the class rather than a whole-CLI
failure.

**R9 — The vocabulary reframe is unproven.** Three axes are argued, not built.
Mitigated by build order: `Repository` first (`11` §2 step 7), because it
exercises substrate, action and target at once. If the axes prove awkward
there, one substrate's work is lost rather than a vocabulary.

## 2. Settled by probing

Four things v2 listed as unknown are now answered, and one of the answers
reshaped the architecture:

| Question | Answer |
|---|---|
| Is there a stable boot hook for wiring providers? | **Yes — the plugin seam.** Not the constructor, not `JobSources` **[probed]** |
| Do provider-registered jobs publish real parameters? | **Yes** — unlike `register_dynamic_job` **[probed]** |
| Does `GroupOptions` binding survive off the scan path? | **No** — binding yes, collection no |
| Do MCP/TUI render adapter-registered jobs like scanned ones? | CLI help, options, `why` and `info schema` are identical **[probed]**; the MCP plugin itself is still unprobed (§3) |

## 3. Still open

**The MCP and TUI plugins were not probed directly** — only the CLI adapter and
`builtin info`, which share the `job_schema` renderer. A one-hour probe
installing `functualize-mcp` and listing tools over a rise group would close
it. It is `11` §2's step-2 proof; nothing else depends on the answer.

## 4. Deferred deliberately

- **Group-level flags** (`rise tools jsonschema --variant pip install`). Needs
  a change to the group-options cache contract (`13`, "not asked for"). Values
  already resolve from config/env/per-job flags.
- **The `"N/A"` sentinel** (`05` §1). Retained because criterion 13 names it; a
  candidate for diagnosis format version 2 with a migration, not a silent drop.
- **Non-Python module authoring.** `custom` variants shell out.
- **Audit rotation and locking** (R7).

## 5. Decisions, settled

**Settled, not open — the vocabulary.** v3 adopts the three-axis model
(substrate / action / target); it is what everything else here is built on.
What remains is *build order*, not a choice: `Repository` lands first, because
it is the one substrate that exercises all three axes at once (a substrate,
`Syncable` actions, and a target for `code_audit`). If the axes prove
awkward on that first real case, one substrate's work is lost rather than a
vocabulary — see R9.

**Settled — delivery and scaffold.** `rise new project` scaffolds a **func
project with rise wired in**: the project's own jobs under `jobs/`, risekit as
a dependency, so `func build` and `func rise diagnose` are one command tree.
The standalone `rise` is the bootstrapper for where no project exists yet.

This follows from a scoping decision: **`rise` is not a job runner.** It scans
no `jobs/` directory and registers nothing but rise modules, so there is
exactly one task runner (`func`) and no chance of two drifting.

**Settled — dependency coverage.** `rise diagnose` and `rise bootstrap` cover
**all three layers**:

| Layer | Declared in | Rise's role |
|---|---|---|
| tools the machine needs | rise's registry | installs them |
| the app's own packages, any language | `package.json`, `pyproject.toml`, `Cargo.toml`, … | **reads** the manifest, proves presence, shells out (`npm ci`, `uv sync`, `cargo fetch`) |
| the job code's Python imports | `pyproject.toml`, or `.functualize.toml requires` when there is no package | proves presence by import |

Two constraints that follow, and both are load-bearing:

- **Rise resolves nothing, in any language.** It reads the manifest the
  ecosystem already has and delegates installation to that ecosystem's tool.
  There is never a second place to *write* a dependency list.
- **The `Package` substrate is language-parameterized**, as the intent always
  required (`language` and `package_manager` are required tags on `library`).
  Presence dispatches on `language`; installation delegates to `manager`.

**Settled — all five upstream asks land in functualize.** Not routed around.
That changes rise's build order: asks 3 and 4 must ship before the parts of
rise that would otherwise need workarounds.

| # | Ask | Unblocks in rise |
|---|---|---|
| 1 | diagnose a failed job-module import | deletes rise's need to own that diagnostic alone |
| 2 | `register_dynamic_job` extracts parameters | removes the reason rise must bind through a provider *only* |
| 3 | honour or delete `JobSources.job_providers` | the declared surface matches the real one |
| 4 | `DiscoveryConfig(extra_pre_filters=[…])` | **rise modules become first-class on disk** — the explicit module list becomes an escape hatch rather than the mechanism |
| 5 | public `Detection` / `InstallMode` / command planners | **rise's registry reuses ~1,700 tested lines** instead of reimplementing install-mode detection and package-install planning |

Consequences worth noting now, because they simplify rise:

- With ask 4, `[risekit] module_packages` stops being the only way to find
  modules; a `RiseModulePreFilter` lets a `modules/` directory work like a
  `jobs/` directory does.
- With ask 5, the registry's variant router for packages becomes a thin call
  into functualize's planners rather than a parallel implementation — and the
  two cannot drift on what "how was this installed?" means.

**Settled — naming.** Package `risekit`, CLI `rise`, plugin namespace `rise`.
Rise's `invoke` action is **renamed `run`**, so no word means two things:
`run()` is the tool being run, `rc.invoke()` is one job calling another. The
`Runnable` protocol therefore requires `run(args)`.

A deliberate divergence from `intent/03-type-system.md`, which spells it
`invoke`; the docs note it, and it is free now and expensive after modules
exist.

## 6. Nothing open

Every decision above is settled. The one outstanding *task* is the unprobed MCP
and TUI surfaces (§3) — a check, not a choice.
