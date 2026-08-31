# Project Constitution

Non-negotiables. Violating these requires explicit user approval.

## Architecture Rules

### Layer Dependency Rules

The internal package structure follows a strict dependency order. Each layer may only import from layers above it in this chain:

```
_types (shared vocabulary, zero logic)
  → _primitives (zero-dep utilities)
    → _events (cross-cutting concerns)
      → _discovery / _config / _engine / _plugins (peer layers, independent of each other)
        → _app (composition root — sole cross-layer wiring point)
          → _cli (delivery — public API only)
```

| Layer | May Import From | Must NOT Import From |
|-------|----------------|---------------------|
| `_types/` | stdlib only | Any `_`-prefixed package |
| `_primitives/` | `_types/`, stdlib | `_events`, `_discovery`, `_config`, `_engine`, `_plugins`, `_app`, `_cli` |
| `_events/` | `_types/`, `_primitives/` | `_discovery`, `_config`, `_engine`, `_plugins`, `_app`, `_cli` |
| `_discovery/`, `_config/`, `_engine/`, `_plugins/` | `_types/`, `_primitives/`, `_events/` | Each other, `_app`, `_cli` |
| `_app/` | All internal layers except `_cli` | `_cli`, public folders |
| `_cli/` | Public folders only (`app/`, `job/`, `plugin/`, `types/`, `testing/`) | Any `_`-prefixed package |
| Internal (`_types` through `_app`) | — | Public folders (`app/`, `job/`, `plugin/`, `types/`, `testing/`) |

### Audience Separation

The package is split into **public** (user-facing) and **internal** (contributor-facing) directories:

**Public folders** (stable API contract, `__all__`-guarded):
- `app/` — Application construction: `FunctualizeApp`, config objects, presets, adapters
- `job/` — Job authoring: `RunContext`, capability protocols (`Log`, `Invoke`, `Prompt`, `Perf`, `State`)
- `plugin/` — Plugin authoring: `EventBus`, `JobProvider`, `AdapterPlugin`, protocols
- `types/` — Shared vocabulary: `JobResult`, `JobDescriptor`, `FieldDescriptor`, enums
- `testing/` — Test utilities: `TestRunContext`, `CapturingLog`, `MockInvoke`

**Internal folders** (underscore-prefixed, off-limits to users):
- `_types/`, `_primitives/`, `_events/`, `_discovery/`, `_config/`, `_engine/`, `_plugins/`, `_app/`, `_cli/`

Users import from public folders. Contributors work in internal folders. The `_cli/` layer proves public API completeness by dogfooding it.

### Kernel / Delivery Separation
- `FunctualizeApp` is the **kernel** — orchestration only. No delivery surface (CLI, HTTP, TUI) lives in the kernel.
- Delivery surfaces are implemented as `AdapterPlugin` Protocol implementations (e.g., `CliAdapter` is built-in).
- The kernel stays synchronous. Async is the adapter's responsibility (wrap with `asyncio.run()` or `to_thread()`).

### DI + RunContext Duality
- The DI registry and RunContext resolve from the **same underlying capability map** — they are two access paths, not competing systems.
- Jobs may declare dependencies via type-annotated params (DI) OR receive `RunContext` (facade) OR both (hybrid). All three are first-class.
- The DI registry is **populated at boot and frozen before execution** (`REGISTRY_FROZEN` event). No runtime mutations.
- Framework capabilities (`Log`, `Invoke`, `Prompt`, `Perf`, `State`, `JobContext`) are per-invocation. Plugin capabilities are app-scoped singletons or per-invocation factories.

### Ports
- All ports are `@runtime_checkable Protocol` — no ABC, no forced inheritance.
- Adapters depend on ports. The domain never imports adapter code. Dependencies point inward.

### Boot & Config
- Boot order is fixed: core_infra → DI registry → observability → plugins → config_resolution → job_registration → children → `REGISTRY_FROZEN` → `APP_READY` → adapter.run()
- `ResolutionChain` is built once at boot and reused for all config lookups — zero per-invocation file I/O.
- Every I/O-bearing boot step has a static bypass via grouped constructor config objects. Discovery is the default; explicit wiring is the fast path.

### Execution
- `execution/engine.py` (`JobExecutionEngine`) is the single path for all job execution — no parallel paths.
- Engine resolves job function signatures via cached `ResolutionPlan` (computed once per function).
- DI resolution failures are loud and early: `MissingProviderError` / `AmbiguousProviderError` at boot or first invocation, never silent `None`.

### Event Systems (Non-Overlapping)
- **HookRegistry** = interceptors that can *control* lifecycle (block, modify). Synchronous, ordered.
- **EventBus** = observers that *observe* without modifying. Fire-and-forget notification.
- These two MUST NOT overlap in responsibility. No pub/sub in HookRegistry. No lifecycle control in EventBus.

## Naming Conventions
- Source files use `snake_case`; classes use `PascalCase`; constants `UPPER_SNAKE_CASE`
- Error classes are suffixed `Error` (e.g., `MissingProviderError`)
- Test files mirror src layout: `tests/<module>/test_<submodule>.py`
- Property-based tests use Hypothesis; integration tests go under `tests/integration/`
- Capability types (DI-injectable) use short nouns: `Log`, `Invoke`, `Prompt`, `Perf`, `State`

## Forbidden Patterns
- Circular imports between subpackages — reason: causes import errors, breaks lazy loading
- Peer-layer cross-imports (`_discovery` ↔ `_config` ↔ `_engine` ↔ `_plugins`) — reason: violates independence contract, creates hidden coupling. Use `_app/` composition root to wire peers together.
- Runtime CLI imports in kernel layers (`typer`, `click`, `rich`, `textual`, `trogon`, `jinja2` in `_types/`, `_primitives/`, `_events/`, `_discovery/`, `_config/`, `_engine/`, `_plugins/`, `_app/`) — reason: bloats Lambda/HTTP deployments with unused CLI deps. Only permitted in `app/adapters/cli.py`, `app/adapters/tui.py`, and `_cli/scaffold/cli.py`.
- `_cli/` importing internals (any `_`-prefixed package) — reason: `_cli/` dogfoods the public API to prove completeness. If `_cli/` can't do something via public API, the capability must be added to a public folder first.
- Importing `textual` or `trogon` at module top-level outside permitted adapter files — reason: heavy optional deps; lazy-import them
- Hard-coding config file paths — reason: `ResourceLocator` handles discovery; use it
- God-object growth — if a class exceeds ~500 LOC, decompose it
- ABC for ports — reason: forces inheritance, leaks framework into adapter code. Use Protocol.
- Global mutable state / module-level singletons — reason: breaks testability and DI
- Implicit `Callable` conventions for ports — reason: untyped, no IDE support. Define a Protocol.
- `DeprecationWarning` / backward-compat shims — reason: pre-release, no users to deprecate toward. Remove old code.
- Committing a proposal, scrutiny, or review report **to master** — reason: an argument at a moment goes stale the day it lands and then contradicts the code. They are session documents under `.spec/proposals/` and `.spec/scrutiny-reports/`, both gitignored. Migrate the *decision* to an ADR and any *working rule* to `contributor/guides/` before deleting; see `.spec/README.md`. No committed file may link to those paths.

  **Exception — `.spec/features/` (approved 2026-08-29).** A feature's `spec.md`, `contracts.md`, `plan.md`, `schema.md`, `research.md`, and `tasks.md` **are** tracked, on the branch, for the life of the branch. This is not a weakening of the rule above: it is conditional on the `spec-artifacts-cleared` CI check (`VCS.2`), which blocks merge while `git ls-files .spec/features/` is non-empty, so **master still accumulates none of it** and the stated reason cannot occur. The artifacts stay recoverable after merge via `git fetch origin refs/pull/<N>/head`.

  The exception buys three things the gitignored arrangement could not: a reviewer can see the wave graph and the acceptance gates the diff claims to satisfy; `agentic-verify` step 2b's walk of `contracts.md` is auditable rather than private; and the artifacts travel across worktrees with the branch. Withdrawing the `VCS.2` check withdraws the exception with it — the two are one decision, not two.

## Quality Gates
- All changes must pass: `uv run ruff check src/ tests/`, `uv run ruff format --check src/ tests/`, `uv run mypy src/`, `uv run pytest`
- `uv run lint-imports` must pass with zero contract violations (enforces layer dependency rules)
- Mypy is strict; `ignore_missing_imports` only for `textual.*`
- Line length 88 (ruff default); E501 is suppressed
- **Reachability**: no task closes without naming the production call path that
  reaches the code it added. "A test calls it" is not a call path. Verify by
  removing the call and confirming a test fails — passing gates never detected
  three separate built-but-unwired capabilities
  (`contributor/guides/wiring-discipline.md`)
- **Capability coverage**: every user-declarable capability has an end-to-end test
  that declares it and observes the consequence through the public entry point
- **Commit before sabotaging**: the restore step (`git checkout -- <file>`)
  reverts *everything* uncommitted in that file, not just the damage. Commit the
  finished change first, sabotage second, restore third, then amend with the
  result. Skipping this has silently discarded completed work twice
  (`contributor/guides/wiring-discipline.md` §3)

## Transitional Changes (disclose, never disguise)

A change is **transitional** when it intentionally leaves the code in a non-final
state whose completion is planned in a later task, phase, or feature. Landing a
large change incrementally is fine; leaving an *undisclosed* half-state is not.

- **Label it in the code.** Mark the transitional site with a comment naming the
  step that resolves it: `# TRANSITIONAL(<feature/task>): <what is not final yet
  and why>`. A reviewer must be able to tell a scaffold from a settled decision
  without guessing or reading the git log.
- **Describe what the code does, not what it will do.** Spec / tasks / commit
  prose MUST match the code's *current* behavior. State the intended end-state
  and its owning step *separately, as a plan* — never assert the final state is
  already reached. (Real failure this rule exists for: a spec claimed a dispatch
  branch was "deleted" when the code had only narrowed it to a single entry, so
  the surviving vestige read as a bug rather than a planned interim step.)
- **A task is `[x]` only when its own acceptance gate is green against the code
  as it actually stands** — never on the strength of its final-state
  description. If the gate can only pass after a later step, the task is
  *partial*: leave it `[ ]` (or split it), and carry the remainder forward
  explicitly in `tasks.md` / `STATE.md`.

## Acceptance Gates (author them by running them)

An acceptance criterion that is an executable command — a grep that must come
back empty, a test selection that must be green, a count that must match — is a
**gate**, and a gate is only meaningful if it was run when it was written.

- **Run the command at authoring time and make the task's file scope equal its
  hit set.** Deriving the scope from prose and the gate from a separate reading
  produces a task that cannot pass as written: the executor does exactly what the
  scope says and still lands red.
- **Beware recursion and counts.** `src/pkg/ui/` includes `src/pkg/ui/panels/`.
  "The four X" is a claim, not a fact — write the number the command returned.
  (Real failure: a "delete the four seams" task listed three files while its own
  recursive grep matched four; the fifth seam sat in a `panels/` subdirectory.)
- A gate that is weakened to make a task pass must say so explicitly, per
  *Transitional Changes* above — narrowing the command is a scope decision, not
  a formatting one.

## Completed Invariants (do not revert)
- `Configurations` class is gone — all config access through `JobConfigView` / `ResolutionChain`
- Config files are parsed once at boot — no per-invocation file I/O
- `SignalBus` is gone — signal API (`define_signal`, `connect`, `fire`) fully removed
- `execution/engine.py` is the single execution path (CLI, `rc.invoke()`, `func`)
- Phase 4 (package separation) is archived — do not implement without explicit user decision
- `PathResolver` is gone — all path discovery uses `ResourceLocator`
- All ports use `@runtime_checkable Protocol` — no ABC base classes
- FunctualizeApp kernel is delivery-agnostic (no Typer/TUI imports)
- DI registry frozen after APP_READY hooks — no runtime mutations
- Constructor uses grouped frozen dataclass configs (`JobSources`, `ConfigSources`, `PluginSources`, `ExecutionConfig`)
- No `DeprecationWarning` / backward-compat shims remain in src/
- RunContext decomposed to ≤500 LOC facade — delegates to capability classes (`Invoke`, `WorkflowTracker`, `EventBus`)
- FunctualizeApp facade ≤300 LOC — heavy boot/wiring logic lives in `_app/boot.py` and `_app/impl.py`
- Presets are factory functions (`classic`, `twelve_factor`, `env_only`, `remote_first`) returning `ConfigSources` — no class registry
- HTTP/Lambda adapters extracted to monorepo plugin packages (`plugins/functualize-http/`, `plugins/functualize-lambda/`) — core package ships only `CliAdapter` and `TuiAdapter`

## Pre-Release Stance
- No backward compatibility obligation. Breaking changes are free.
- Remove deprecated code immediately rather than shimming.
- This stance expires at v1.0.0.
