# Contributor Documentation

This folder contains internal documentation for functualize contributors — people working on the framework itself, not just using it.

## Structure

```
contributor/
├── README.md                       ← You are here
├── architecture/
│   ├── overview.md                 — Mental model, layer diagram, audience separation
│   ├── dependency-graph.md         — Layer rules, import-linter contracts, allowed imports
│   ├── boot-sequence.md            — FunctualizeApp initialization flow
│   ├── execution-flow.md           — Job execution lifecycle, DI resolution
│   ├── interactivity-model.md      — Input/output axis, escalation levels
│   ├── developer-modes.md          — The six bootstrap/entry-point modes (A–F)
│   ├── tui-architecture.md         — Inline TUI: layout, focus model, keybindings, panel rings
│   ├── tui-command-panel.md        — Command panel ring (Ctrl+R) UX: Config Table/Files/Diff View
│   └── codemaps/                   — Machine-assisted maps: overview, modules,
│                                     dependencies (measured fan-in), entry-points, data-flow
├── adr/                            — Architecture Decision Records
│   └── 000-template.md            — ADR template
├── guides/
│   ├── adding-internal-module.md   — How to add code to an internal layer
│   ├── adding-public-api.md        — How to expose a new symbol publicly
│   ├── writing-property-tests.md   — Hypothesis conventions and patterns
│   ├── tui-development.md          — TUI panel height/deferred-population patterns (human-facing)
│   ├── tui-panels.md               — TUI panel widget hard rules (min-height, deferred population)
│   ├── steering_textual_tui.md     — Textual architecture + testing HARD rules, compliance audit
│   └── plugin-development.md       — How to develop official plugins in the monorepo
└── reference/
    ├── layer-rules.md              — Which layer can import what (quick reference)
    ├── code-map.md                 — Which classes/functions live where
    ├── performance.md              — Boot phase budgets, measurement methodology
    ├── testing-strategy.md         — Test tiers, when to run what, CI matrix
    └── pitfalls.md                 — Defects that already shipped here, and the
                                      shape of each trap so it isn't reintroduced
```

## ADR Backlog

The following Architecture Decision Records are planned but not yet authored. Each represents a key architectural decision that should be documented:

1. Audience-separated structure
2. Composition root pattern
3. Dependency injection via type annotations
4. Adapter and plugin protocol design
5. Presets as factory functions
6. CLI dependency isolation
7. Monorepo plugin packaging
8. Import-linter enforcement
9. RunContext decomposition
10. No backward compatibility guarantee

## Who Is This For?

- Framework contributors (you're modifying `src/functualize/` internals)
- Plugin authors building official plugins in `plugins/`
- Anyone trying to understand *why* the code is structured this way

## Where to Start

1. **New contributor?** Start with `architecture/overview.md`
2. **Adding a feature?** Read `guides/adding-internal-module.md` or `guides/adding-public-api.md`, then `guides/wiring-discipline.md` before you call it done — a green suite does not prove your code is reachable
3. **Want to understand a past decision?** Browse `adr/`
4. **Need a quick import rule check?** See `reference/layer-rules.md`
5. **Something resolves and displays but does nothing?** Check `reference/pitfalls.md` — that exact failure has happened here four times, and it is trap #1

## Relationship to Other Documentation

| Location | Audience | Purpose |
|----------|----------|---------|
| `docs/` (mkdocs site) | End users (job authors, plugin authors) | How to USE functualize |
| `examples/` | End users (all levels) | Working code examples with tests |
| `CONTRIBUTING.md` | First-time contributors | Dev setup, PR process, commit conventions |
| `contributor/` (this folder) | Regular contributors | Architecture understanding, design rationale |
| `.spec/` | AI-assisted development | Stable reference docs for the spec-driven workflow |

### Examples Layout

The `examples/` directory is organized by usage pattern:

| Directory | Audience | Pattern |
|-----------|----------|---------|
| `examples/standalone/` | Job authors | Single-file scripts using `func` CLI |
| `examples/project/` | App constructors | Full `FunctualizeApp` with adapters (HTTP, Lambda) |
| `examples/plugins/` | Plugin authors | Creating custom StateBackends, adapters, etc. |

Each example includes tests proving it works. A `.devcontainer` config at the examples root provides isolated execution.
