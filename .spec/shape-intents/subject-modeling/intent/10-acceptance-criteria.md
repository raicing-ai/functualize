# 10 — Acceptance Criteria

> **Status: carried forward — current. This file is the measure of success.**
> The 69 criteria below are numbered to match
> [`../12-acceptance-mapping.md`](../12-acceptance-mapping.md), which scores each
> one against the v3 design (met / reduced / partial / unmet). Numbering follows
> this document's order: A 1–8, B 9–17, C 18–25, D 26–35, E 36–43, F 44–48,
> G 49–56, H 57–62, I 63–67, J 68–69.
>
> Where a criterion's *wording* uses the superseded vocabulary (kinds,
> interfaces, `invoke`), the mapping row records the substitution and its
> verdict. The criteria themselves were not rewritten to fit the design — that
> is the point of keeping them.

The observable behavior a re-implementation must exhibit. This is the test
matrix: every item is verifiable by running the system, not by reading code.

## A. Vocabulary & declaration

- [ ] **1.** A module file declares kind, interfaces, and tags in a single
      machine-readable block at its top.
- [ ] **2.** Kinds are a closed enum of eight: `base`, `meta`, `program`, `library`,
      `service`, `host`, `registry`, `workflow`.
- [ ] **3.** Interfaces are a closed enum of five abstract names: `daemon`, `git`,
      `backup`, `version`, `continuous-integration`.
- [ ] **4.** Interface claims are kind-scoped: `daemon` only on `program`; `git`,
      `backup`, `version` on `service`; `continuous-integration` on
      `workflow`; claiming an interface illegal for the kind is rejected.
- [ ] **5.** A program declares an empty interface list by default; declaring
      `program` or `service` as an interface name is rejected.
- [ ] **6.** Strategy names (`pip`, `brew`, `mise`, `systemd`…) never appear in
      interface lists; the strategy identity is the module's placement
      (namespace) plus its `variant` tag. Dot-notation like `program.mise`
      in an interface list is rejected.
- [ ] **7.** Adding a new variant requires no schema change.
- [ ] **8.** Program modules must declare an isolation tag (`host` | `project` |
      `process`); a program without one is rejected.

## B. Validation pipeline

- [ ] **9.** `validate` on any module runs two checks: (1) the module file's
      structure against the contract for its kind; (2) the record emitted by
      its `diagnose` operation against the diagnosis contract for its kind.
- [ ] **10.** A module claiming an unknown kind is rejected (no schema exists).
- [ ] **11.** A module missing a required capability, required configuration entry, or
      required tag is rejected.
- [ ] **12.** A module claiming an interface but missing any interface-required
      capability or configuration entry is rejected.
- [ ] **13.** A diagnosis record missing kind, interfaces, tags, or the fixed status
      value is rejected.
- [ ] **14.** A diagnosis record containing a field the contract doesn't declare is
      rejected.
- [ ] **15.** Validation is recursive: validating a root module validates the whole
      composed tree, each node against its own kind's contracts.
- [ ] **16.** The validation pipeline has exactly two runtime prerequisites: a YAML
      parser and a standard schema validator.
- [ ] **17.** Both check steps use standard, draft-stable schema documents; any
      conformant validator produces identical results.

## C. Diagnosis record

- [ ] **18.** `diagnose` emits one JSON-lines record per module: kind, interfaces,
      tags, fixed status `"N/A"`, plus a kind-appropriate runtime block.
- [ ] **19.** Static kinds (`base`, `meta`, `host`, `registry`, `workflow`) emit no
      runtime block.
- [ ] **20.** A program's record carries platform, isolation, and an `installed`
      block (status, version, path, origin, detection method) plus a
      `capabilities` block (can install/update/uninstall/run, runs correctly,
      verification method).
- [ ] **21.** `runs_correctly` is verified by actually executing a benign probe, never
      assumed.
- [ ] **22.** A library's record proves installation by language import, not path
      lookup.
- [ ] **23.** A service's record carries a detected status (running/stopped/unknown).
- [ ] **24.** The record is the single source of truth: install/uninstall/verify
      operations consult it rather than re-deriving state.
- [ ] **25.** Declaration extraction for validation reads the module's own file
      (immune to include-variable override quirks of the runner).

## D. Registry & routing

- [ ] **26.** The registry is itself a module (kind `registry`) — no custom index
      format.
- [ ] **27.** Tools are organized tool → variant; each variant is a fully
      self-describing module.
- [ ] **28.** Each tool has a router module exposing `install`, `uninstall`, `test`,
      `lock`, `invoke`.
- [ ] **29.** `install` auto-detects the best variant by ordered preference
      (host strategies before project strategies), first available package
      manager wins.
- [ ] **30.** Auto-detection is recorded in a per-tool lockfile (format version, tool,
      selected variant, isolation, resolution time, resolved-by auto/user,
      install state with version/path/time).
- [ ] **31.** An explicit variant install is recorded as a user choice and honored by
      all subsequent automatic runs.
- [ ] **32.** Re-running install on an already-installed tool is a no-op (lockfile +
      runtime truth agree).
- [ ] **33.** The registry index exposes a fixed-size command surface via wildcard
      dispatch (`<tool>:<action>`, `<tool>:<action>:<variant>`), independent of
      how many tools exist.
- [ ] **34.** Registry operations include: list (filterable), status, lock aggregate,
      audit (validate all entries), bootstrap (install prerequisites),
      scaffold (generate tool entry from templates).
- [ ] **35.** Lockfiles are re-derivable cache state: clearing one costs only a
      re-detection.

## E. Safety

- [ ] **36.** Every mutating operation is idempotent: install, uninstall, start, stop,
      restore — each check state before acting.
- [ ] **37.** Host-isolated install/uninstall prints a warning banner and requires
      confirmation interactively; anything but yes aborts with non-zero exit.
- [ ] **38.** The same operations in CI/non-interactive contexts auto-continue with a
      log record — never hang.
- [ ] **39.** Installing a program that already exists from a different origin warns
      and requires confirmation.
- [ ] **40.** Project- and process-isolated operations prompt nothing.
- [ ] **41.** Every program lifecycle event (install/uninstall/invoke) appends one
      JSON-lines record to a shared project audit log with timestamp, program,
      isolation, operation, variant, platform.
- [ ] **42.** Logging writes nothing to the console.
- [ ] **43.** The audit log directory is created on demand; location overridable.

## F. Testing

- [ ] **44.** `program`, `library`, and `service` modules each expose a `test`
      operation.
- [ ] **45.** Full `test` runs diagnose → install (twice) → invoke probe → uninstall
      (twice), proving idempotency.
- [ ] **46.** On a developer machine, `test` runs only non-destructive checks with a
      warning; the destructive cycle runs only in a container or CI.
- [ ] **47.** The framework's own suite has a fast tier (safe on host, non-mutating)
      and an isolated tier (install/uninstall cycles inside a disposable
      container).
- [ ] **48.** The suite includes rejection cases for: unknown kind, unknown/illegal
      interface, dot-notation interface, missing status, missing kind, extra
      record fields, invalid isolation, missing isolation, missing required
      capability, missing required configuration, missing declaration. Each
      must fail loudly; if any starts passing, that is a regression.

## G. Lifecycle & UX

- [ ] **49.** One-line install; only hard dependency is the task runner.
- [ ] **50.** `init <name>` scaffolds a complete self-contained project (root module,
      source subsystem, deployment subsystem, framework layer with schema,
      extensions file, local registry, templates, instruction docs, log dir).
- [ ] **51.** `init` inside an existing project adds the framework layer without
      touching existing files.
- [ ] **52.** `bootstrap` in a fresh clone installs all registered project tools.
- [ ] **53.** Root command with no arguments prints a curated menu of top-level
      commands.
- [ ] **54.** Colon-namespaced naming is used consistently for grouping; every
      operation has a human-readable description.
- [ ] **55.** `upgrade` updates the framework; per project, one command rebuilds the
      effective schema.
- [ ] **56.** The generated project works with the global install absent (fully
      self-contained).

## H. Extension model

- [ ] **57.** Projects extend the vocabulary via an extensions file; framework
      upgrades never touch it.
- [ ] **58.** `schema kind add` and `schema interface add` (project-local) validate
      names, update the extensions file, and rebuild the effective schema.
- [ ] **59.** The effective schema (base + extensions) is the single validation
      authority; absent extensions, it is the base schema.
- [ ] **60.** A malformed extensions file fails the rebuild loudly.
- [ ] **61.** A project may pin the framework version; validation then uses the
      pinned schema, immune to framework upgrades.
- [ ] **62.** New interfaces support concrete variants by naming convention
      (capability name + variant suffix) with no schema changes.

## I. Agent alignment

- [ ] **63.** Instruction documents ship per persona (maintainer / machine user /
      project member) and refresh on upgrade.
- [ ] **64.** Installer-strategy and daemon-strategy reference tables ship with the
      project docs (detection, install, remove, platforms, idempotent pattern
      for each strategy).
- [ ] **65.** Architectural decisions are recorded persistently with context →
      decision → consequences.
- [ ] **66.** An agent can determine a tool's risk profile (isolation) and current
      state (diagnosis) by reading, without executing anything.
- [ ] **67.** Generating a module from a template, then validating it, converges to a
      valid module (generate → validate → fix loop).

## J. Self-consistency (dogfooding)

- [ ] **68.** The framework repository is itself a valid project: it uses its own
      templates, validates against its own schemas, and manages its own dev
      tools through its own registry.
- [ ] **69.** The framework passes its own full validation.
