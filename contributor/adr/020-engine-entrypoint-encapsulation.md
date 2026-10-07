# ADR-020: Engine Entrypoint Encapsulation — One Request, One Resolution, One Outcome

**Status**: proposed
**Date**: 2026-09-08
**Deciders**: proposed by the engine-encapsulation depth audit (`refactor/engine-encapsulation-audit`); awaiting maintainer review

## Context

Two maintainer gripes, verbatim intent:

- "There are a lot of ways a job can be invoked and the entry points may diverge inconsistently."
- "It feels like an encapsulation problem within the engine, being too loose (open for modification)."

The evidence base is the companion audit, `contributor/architecture/audit-engine-encapsulation.md`
(all `file:line` below verified there at `c0c921f`). Four load-bearing causes:

1. **The engine's entry contract is a 12-parameter procedure that takes the resolved function as
   an argument** (`_engine/executor.py:656`). Eight production sites resolve name→function
   themselves (`app/core.py:620`, `app/adapters/click_params.py:1141`, `lazy_command.py:141`,
   `cli.py:698`, `_cli/main.py:1470` and `_dispatch_group`, `_app/impl.py:861`,
   `_engine/capabilities/invoke.py:401,597`), while the engine already resolves by name for its
   own workflow steps and dependencies (`executor.py:1215,1794`). Every feature adds a parameter;
   every surface independently decides whether to pass it — the exact mechanism behind the
   `--scope-id` gate-resume defect.
2. **The engine is white-box mutable state.** `_app/boot.py:286,498,701,1586` and
   `app/core.py:514` write engine private attributes after construction; `RunContext` reads them
   back through `engine._app` message chains (`runcontext.py:698`); the kernel self-wires from
   `Path.cwd()` (`executor.py:1093-1096`). Construction is duplicated across boot paths
   (`boot.py:270-288` vs `482-500`).
3. **Delivery is a per-surface act.** The number tables are single authorities
   (`_types/exit_codes.py:50-68`, `_types/http_status.py:78`), but the failure-set rule is spelled
   in three places (`job_execution.py:274-285`, the exit table, `func builtin parallel`, coordinated
   by comment citations), and BLOCKED/REFUSED reporting lives only in the click-side
   `deliver_job_result` (`click_params.py:1156-1241`). Three shipped divergences (cold/warm exit
   codes, Lambda 200-for-everything, HTTP line/body disagreement) were each fixed at the table
   level; the delivery act remains scattered.
4. **`func`'s pre-boot layer is a permanent second CLI** (`_cli/dispatch.py:62-626` tokenizer,
   `_cli/tui/cli_arg_parser.py:16-71` a third parser), and the "one rule, two surfaces" fixes
   (`negative_flag_for`, seven call sites in four modules) are per-rule hand extractions, not a
   mechanism — STATUS.md:834: "five flag-rendering sites, not the four the plan named."

Supporting: the god-object guards are breached and unenforced — `RunContext` 781 LOC (≤500),
`FunctualizeApp` 1,265 LOC (≤300), `JobExecutionEngine` 2,401 LOC — and the layer contract is
blind to `TYPE_CHECKING` imports (`_config/chain.py:22`, `_config/sources.py:36`).

Precedent: this codebase collapsed surface proliferation twice — ADR-001 (five interactivity
concepts → Surface + PromptCollector + TTY) and ADR-004 (namespace re-derived in ~7 places → one
GroupTrie). Each time: find the single authority, collapse the re-derivations, seal the boundary.
This ADR is the third application of that move, aimed at the structure the first two left in place.

## Decision

Four consolidations, no new layers, no new registries. Build on existing authorities
(`GroupTrie`, `negative_flag_for`, `exit_code_for_status`, `CapabilitySpec`, `HookRegistry`/
`EventBus`, the 20-step lifecycle).

1. **`RunRequest` — one frozen value object for everything a run needs**
   (`_types/run_request.py`, stdlib-only, same placement logic as `exit_codes.py`). Fields:
   job *name* (not function), kwargs, group-option values, scope id, force flags, invoke depth,
   paths, surface provenance. The engine signature stops being the extension point; a new
   engine-level feature is a request field plus a lifecycle step.

2. **One resolution authority.** `engine.run(request)` resolves and materializes the job
   internally (the engine already owns `get_job`/`materialize_job` and does this for steps and
   deps). The config-field/kwargs split and stdin-marker resolution move in from the click
   callback (`click_params.py:1099-1124`). No production code outside `_engine` passes a function
   to the engine. `execute(name, function, ...)` is deleted — clean cutover, pre-release.
   `FunctualizeApp.execute` becomes the single surface-facing Facade; adapters (including the
   click family, which currently bypasses it) build requests and go through it.

3. **Sealed construction.** An `EngineHost` protocol in `_types/protocols.py` (job lookup, config
   resolution, gate resolution, state-store root, surface stack) wired once by a single
   `build_engine(host)` in `_app/boot.py`.
   *(Amended twice since. `store-substrate` added a storage member; and
   `plugin-host-protocol`/T3 renamed it `substrate_override`, because
   `substrate` had come to mean two things — the slot a plugin installs into,
   which is normally `None`, and the storage in effect, which never is. The
   engine reads the slot; everyone else reads `PluginHost.substrate`.
   `plugin-host-protocol` also gave this port a peer for the plugin boundary,
   `PluginHost` in `_types/host.py` — see `dependency-graph.md` → *The Two
   Ports in `_types/`*.)* All post-hoc private-attribute writes are deleted;
   `refresh()` re-resolves through a sanctioned host method; `Path.cwd()` leaves the kernel;
   `RunContext`'s `engine._app` chains become host accesses.

4. **One outcome module.** The `RunStatus → family` mappings (exit codes — existing; HTTP status —
   existing; a new failure-set rule and BLOCKED/REFUSED report lines) live in one `_types` module.
   Delivery surfaces become Adapters that choose a family and render; they stop deciding. The TUI's
   in-panel BLOCKED→0 may remain correct — but as an explicit family choice against a shared
   mapping, not a comment citing `parallel`.

Plus two structural repairs: the flag vocabulary (`dispatch.py` tables, alias/negative matchers,
`negative_flag_for`) consolidates into `_types/flag_grammar.py` consumed by click builders, the
pre-boot parser, the TUI, and completions; and the facade LOC guards (RunContext ≤500,
FunctualizeApp ≤300) become executable tests.

The 20-step `_execute_lifecycle` Template Method is **unchanged** — `tests/engine/test_lifecycle_order.py` stays the proof of order at every commit. `WorkflowOrchestrator` and
`DependencyRunner` are extracted as engine-owned collaborators (Extract Class), not as peers.

Migration is ordered, incremental, and specified in the audit's §4 (nine steps, each with its
invariant, verification suite, and named sabotage; the resolution move is the highest-risk step
and is gated by the dual-surface `cli_run` harness and warm-boot parity tests).

**Regrowth resistance** (the reviewer's first question): ADR-001/004 collapsed rules but left the
protocol that demands per-surface re-derivation — so every later feature re-entered through the
same door. This decision removes the door: after it lands there is no API by which a surface can
resolve a job, restate the failure set, or re-spell a flag rule; divergence in those classes
requires adding a new authority, which the absence-tests (no private writes, LOC limits,
panel≡table parity) and the `cli_run` harness make visible as a failing test rather than a
convention drift.

## Consequences

### Positive

- A job-author-declared feature works on every surface *by construction* — surfaces pass opaque
  requests and receive a `JobResult`; there is nothing per-surface to forget (surface-boundary §4
  becomes structural rather than aspirational).
- Engine features stop being parameter additions: one field, one lifecycle step, inherited by all
  surfaces.
- The engine becomes a sealed object with a single construction point; the "open for
  modification" complaint becomes structurally impossible for the four audited divergence classes.
- Exit semantics (failure set, reporting, family mappings) become importable data beside
  `RunStatus`; a new status or delivery family is one edit plus adapter translations.
- CONSTITUTION's facade limits become tests; the layer contract's TYPE_CHECKING hole is measured
  and either closed or explicitly owned.
- `boot_static`/`boot_standard` engine construction collapses to one builder.

### Negative

- **Breaking, broadly.** Every production call site of `engine.execute` and every job author using
  `RunContext`'s observability/discovery re-exposures must change once (pre-release: free, but one
  release note each for job authors and plugin authors).
- The kwargs-split/stdin move (decision 2) is the riskiest single change in the codebase's near
  term: identical behaviour must be preserved across eager/lazy click, group options, and stdin
  markers on both surfaces. Mitigated by, and only by, the existing parity and warm-boot suites.
- External plugins that reach past the `AdapterPlugin` protocol (direct engine construction,
  `engine._app` reads) break silently — not enumerable from this repo.
- The TUI's BLOCKED semantics require a maintainer decision (in-panel 0 vs process 5 when the
  inline TUI *is* the process); this ADR forces the question, it does not answer it.
- The `_types` placement keeps the request/outcome types stdlib-only — some duplication pressure
  with `_types`-resident dataclasses is accepted as the price of importability by every layer.

### Neutral

- Two CLI parsers remain (click and pre-boot) — inherent to pre-boot; they share a vocabulary, not
  a syntax. `--perf-report` stays deliberately `func`-only. *(Superseded: the lookahead
  this row used to cite was withdrawn — every pre-boot flag is boolean or value-required;
  the two-parser decision stands.)*
- `app/utils.py`'s corridor (2,021 LOC) is untouched by this ADR; recorded as the next
  surface-boundary question, with the group-options cache fingerprint gap as its open wound.

## Alternatives Considered

| Alternative | Pros | Cons | Why rejected |
|-------------|------|------|-------------|
| Keep `execute()`, add a completeness test over call sites | No churn | Tests the sites that exist, not the ones a new surface will add; the parameter-addition mechanism survives (pitfalls: ADR-014 ruled this shape out for capabilities already) |
| A `JobRunner` service between surfaces and the engine | Seams without touching the engine | A new layer with the same looseness one step removed; second authority beside the engine's own resolution |
| Mediator-structured engine (surfaces coordinate through it) | Centralizes everything | No component-to-component chatter exists to mediate; blesses god-object creep on a 2,401-LOC class (ch20's own anti-pattern); HookRegistry/EventBus already own notification |
| Command objects at the entry boundary (undo/queue/defer protocol) | Request-as-object symmetry | No deferral/queue/undo need at this boundary; `WiredInvoke.parallel` and workflow `record_body` already implement Command's intent where it is real |
| Strategy per surface for delivery | Family flexibility | One mapping per family is data, not an interchangeable algorithm; Strategy here is pattern overhead (ch24 anti-pattern) |
| Per-rule extraction only (keep applying the `negative_flag_for` pattern by hand) | Smallest diffs | The mechanism that produced "five sites, not four" — counting re-derivations is not a mechanism; the vocabulary needs a home, not more exports |
| Compatibility shims for `engine.execute` | Zero breakage | Pre-release explicitly carries no backward-compatibility obligation (AGENTS.md); shims would preserve the very door this ADR exists to close |

## References

- `contributor/architecture/audit-engine-encapsulation.md` — the evidence base (root causes,
  smell mapping, pattern justifications, migration roadmap, open questions). Its Method note
  records the verification toolchain: serena reference enumeration
  (`JobExecutionEngine.execute`, `JobExecutionEngine.get_job`), `graphify explain
  "JobExecutionEngine"` (typed dependency edges), and zvec-grep prose search (via the mounted
  MCP tool against the worktree root — the `zg` CLI is not installed on this host).
- `contributor/architecture/surface-boundary.md` — §4's rule this design makes structural
- `contributor/adr/001-surface-architecture-collapse.md`, `004-cli-shell-convergence.md`,
  `010-job-schema-in-core.md`, `014-capability-registry.md` — precedent collapses and the
  declared-beside + import-time-invariant mechanism
- `contributor/reference/execution-lifecycle.md` + `tests/engine/test_lifecycle_order.py` — the
  Template Method this decision preserves
- `.spec/STATUS.md` — case files: boolean-flag negation, 0.1.1 cache findings, standalone
  distribution defects

## Addendum — one arity per pre-boot flag (2026-10)

**Deciders**: maintainer, 2026-09-27; scope confirmed 2026-09-28 and 2026-10-05.

The *Neutral* row above used to say the `--perf-report` lookahead stays
deliberately `func`-only. That lookahead is withdrawn; this addendum records why,
and what replaced it. The two-parser decision is unchanged: pre-boot and Click
share a vocabulary but still parse separately.

### Context

`func`'s early (pre-boot) parse used to let two of its flags take a value
**optionally**. `--emit-format` and `--perf-report` were listed in
`GLOBAL_OPTIONS_OPTIONAL_VALUE`, with their accepted values in
`OPTIONAL_VALUE_VALID_SET`, and every reader of that table decided what the
token after a bare flag meant by asking whether it belonged to the flag's
accepted set. A token outside the set was left standing as a *command
candidate*: `func --emit-format greet` ran `greet` with the default format.

That lookahead made one token mean two things at once, and the two meanings
were resolved by different code at different times:

- **pre-boot** — `_cli/dispatch.py::detect_mode` consumed the flag alone and
  classified the token as the command; `_cli/dispatch.py::_extract_global_options`
  assigned the flag's *default* value and left the token at
  `first_positional_index`.
- **post-boot** — `_cli/main.py::_handle_job` re-walked the same prefix through
  `_cli/dispatch.py::refused_optional_value`, which asked the opposite question
  and re-decided the same token as the value the flag refused.

With `[aliases] shortcut = "absent"` and no `absent` job, the consequence
(PR #51 review, finding 1) was:

```
$ func --emit-format shortcut
Error: --emit-format must be one of {auto, json, ndjson, none, raw}, got 'shortcut'.
```

Exit 1. The same token in command position reports the repair the operator
actually has to make:

```
$ func shortcut
Error: Alias 'shortcut' maps to job 'absent', which was not found.
```

The token was resolved as a command pre-boot and rejected as a flag value
post-boot, so the alias diagnostic was unreachable on exactly the spelling that
needed it. An operator was sent to repair a `--emit-format` value that was not
the setting at fault.

### Decision

**In `func`'s early (pre-boot) parse a flag is either boolean, or its value is
mandatory — never optional, never defaulted.** With no optional-value flag there
is no position in which a token might be a command, so the misdiagnosis class
cannot exist rather than being re-ordered.

- **One arity per flag.** `GLOBAL_BOOL_FLAGS` consumes no token;
  `GLOBAL_OPTIONS_ALWAYS_VALUE` consumes one. `--perf-report` and
  `--emit-format` join the latter, and `GLOBAL_OPTIONS_OPTIONAL_VALUE` is
  removed. The token after a value-required flag is its value, with no command
  or alias lookup; a following known global flag means the value is missing.
- **One exit code for a wrong value.** A missing value and an invalid value are
  both usage errors, exit 2, for every value-required pre-boot flag.
  Command-position errors are unchanged, and the alias error is reachable
  wherever the alias is in command position (`func shortcut`,
  `func --emit-format json shortcut`).

### Alternatives Considered

| Alternative | Pros | Cons | Why rejected |
|-------------|------|------|-------------|
| **A-1.** Keep the optional value and move the diagnostics: recognize the command first, report the flag value only if command resolution misses | Keeps every existing spelling, including `func --emit-format greet` | It keeps the two-meaning token and would add a third place that decides what the token means | Withdrawn by the maintainer (2026-09-27): the fix is the flag contract, not the diagnostic order |
| **A-2 (chosen).** One arity per pre-boot flag: boolean or value-required | The misdiagnosis class cannot exist; one statement of the rule, held by a parity test | Breaking for spellings that relied on the lookahead | — |

The two follow-ups this change leaves open are tracked outside the repository.
