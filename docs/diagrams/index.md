# Architecture diagrams

Interactive diagrams of the paths that are hard to hold in your head from prose
alone. Each one has **guided views** — pick one from the sidebar and it walks
you through a specific question rather than dumping the whole picture at once.

Pan and zoom work inside each diagram; use the Export button for a static copy.

## The diagrams

### [Layer Dependency Contract](layer-dependencies.html)

The six `import-linter` contracts from `pyproject.toml`, drawn. Arrows are
*permitted* imports. Shows the five peer layers (including `_gate`, the one
most often forgotten), the foundation stack, and the one direction that is
still ungoverned because `exclude_type_checking_imports = true` hides it.

### [System Data Flow](system-data-flow.html)

Four delivery surfaces — CLI, HTTP, Lambda, TUI — collapsing through adapters
into a single core pipeline. The point of the diagram is that below the adapter
line there is only one execution path, so a job behaves identically whichever
surface launched it.

### [Application Boot Sequence](boot-sequence.html)

The six ordered phases in `_app/boot.py`, ending at the `REGISTRY_FROZEN` point
after which no further `provide()` calls are accepted, and `APP_READY` before
the adapter takes over delivery.

### [Job Execution Lifecycle](job-execution-lifecycle.html)

`JobExecutionEngine`'s ordering contract: config resolution, argument
validation and the workflow prelude all complete *before* `PRE_EXECUTE` fires,
and a validation or dependency failure exits through one path where
`AFTER_FAILURE` fires but the job body never runs.

### [Job & Config Resolution](discovery-and-resolution.html)

Two independent pipelines — `Provider → Transform → Registry` for job
discovery, and `ResolutionChain`'s ordered source lookup for configuration —
and where the two converge at the execution engine.

## Regenerating them

The JSON spec is the source of truth; the HTML is a reproducible build product
(`deliver` is a pure compiler — the same spec renders byte-identically).

```bash
node ~/.claude/skills/archify/bin/archify.mjs deliver <type> \
  contributor/architecture/diagrams/<name>.json \
  docs/diagrams/<name>.html --quality showcase
```

Specs live in `contributor/architecture/diagrams/`. Where a diagram and the
code disagree, the code wins and the diagram is the bug.
