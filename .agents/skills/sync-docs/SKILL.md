---
name: sync-docs
description: >
  Reconcile documentation with code changes. Detects doc/code drift from the
  git diff, updates contributor docs and codemaps, and refreshes README /
  CHANGELOG when the public surface changed. Use after completing a feature,
  before a release, or whenever docs feel stale.
---

# Sync Docs

Reconcile this repo's documentation with the actual state of the code. Run after a
milestone, before a release, or on request ("sync the docs").

## Modes

- **auto** (default): reconcile only docs affected by changes since the last commit
  on the main branch (`git diff master... --name-only`, plus uncommitted changes).
- **full**: audit ALL documentation against the codebase, regardless of the diff.
- **status**: read-only report of detected drift; change nothing.

## Phase 1 — Quality gate (skip in status mode)

Docs must describe working code. Run and require green:

```bash
uv run ruff check src/ tests/ plugins/ && uv run ruff format --check src/ tests/ plugins/
uv run mypy src/
uv run lint-imports
uv run pytest -x -q --no-header
```

If anything fails, stop and report — fix code before syncing docs.

## Phase 2 — Drift detection

Build the changed-file list, then map changes to their documentation owners:

| Change touches | Docs to check |
|---|---|
| `src/functualize/{app,job,plugin,types,testing,workflow}/` (public API) | `README.md` public-API table, `docs/api/`, `contributor/reference/code-map.md` |
| New module / moved package / import-rule change | `contributor/architecture/codemaps/{overview,modules,dependencies}.md`, `contributor/architecture/dependency-graph.md`, `contributor/reference/layer-rules.md` |
| `src/functualize/_cli/main.py`, `dispatch.py`, `pyproject.toml [project.scripts]` | `contributor/architecture/codemaps/entry-points.md`, `docs/cli/` |
| `_app/boot.py`, `_engine/`, hook/event surfaces | `contributor/architecture/codemaps/data-flow.md`, `contributor/architecture/{boot-sequence,execution-flow}.md` |
| `src/functualize/_cli/tui/` | `contributor/guides/tui-panels.md`, `contributor/guides/steering_textual_tui.md`, `contributor/architecture/tui-architecture.md`, `contributor/architecture/tui-command-panel.md` |
| `plugins/*/` | `README.md` plugin ecosystem table, `plugins/PUBLISHING.md`, `contributor/guides/plugin-development.md` |
| `pyproject.toml` dependencies | `contributor/architecture/codemaps/dependencies.md` external-deps section, `README.md` install instructions |
| Config keys, env vars, defaults | `docs/guides/`, `README.md` config section |
| `src/functualize/{app,job,plugin,types,testing,workflow}/` (new public feature) | `examples/` — verify the feature has at least one runnable example in the appropriate category (`quickstart/`, `standalone/`, `project/`, or `plugins/`); check `examples/README.md` index |
| Anything user-visible | `CHANGELOG.md` `[Unreleased]` section |

For each mapped doc, read the relevant section and compare against the code. Record
each mismatch as: file, section, what the code says, what the doc says.

## Phase 3 — Reconcile

Present the drift report, then apply fixes:

- Update stale sections in place — do not regenerate whole files; preserve
  human-authored prose and structure.
- Codemaps (`contributor/architecture/codemaps/`) are regenerable: when structural
  change is large (new package, dependency-graph change, module reorganization),
  re-derive the affected file from scratch:
  1. Explore the current structure (`ls src/functualize/`, imports via
     `grep -r "^from functualize" src/`, entry points from `pyproject.toml`).
  2. Measure fan-in for `dependencies.md` (count import statements per module).
  3. Rewrite only the affected codemap file, keeping the established format.
- Add an entry to `CHANGELOG.md` under `[Unreleased]` for user-visible changes.
- Never invent features: if the doc claims something the code doesn't do, fix the
  doc (or flag it if it looks like a regression instead).

### Examples coverage

When a new user-visible feature lands (new capability, config surface, workflow
pattern, CLI command, or plugin hook) and no existing example demonstrates it:

1. **Flag it** as an "example gap" in the drift report.
2. **Placement**: choose the right category based on feature scope:
   - `quickstart/` — if it extends the Quick Start escalation path
   - `standalone/` — if it's a self-contained feature reference
   - `project/` — if it requires a full `FunctualizeApp` setup
   - `plugins/` — if it demonstrates plugin authoring
3. **Draft a minimal example** for quickstart-level and standalone features. For
   complex features (full project / plugin), note the gap and suggest structure.
4. **Update all three indexes** if a new example directory was added:
   `examples/README.md`, `examples/standalone/README.md` (including its count in
   prose) and `docs/examples/index.md`. Four examples were invisible to readers
   in three indexes because only one of them was updated.
5. **Verify existing examples still pass** against the changed code (Phase 4).

## Phase 4 — Verify

```bash
uv run pytest tests/test_contributor_docs.py -q   # doc-structure invariants
uv run mkdocs build --strict                       # docs site must build clean
uv run pytest examples/ -v                         # examples still runnable

# Do the documented commands still behave as documented? A prose claim about
# runtime behaviour is invisible to every check above while being false.
PATH="$PWD/.venv/bin:$PATH" python \
    .agents/skills/doc-verify/scripts/run-scenario examples/docs/scenarios/ --engine shell
```

`/sync-docs` is one of the two moments someone reconciles docs with code, so it is
one of the two places the parity pass belongs. See
[`contributor/guides/docs-example-parity.md`](../../../contributor/guides/docs-example-parity.md)
for the drift classes it detects and how each is caught — including the rule that
before believing a doc-verify failure you run `a-core-builtins` to prove the harness
works, and the fact that `uv sync --all-packages`, `--all-extras` and `--group docs`
prune each other.

Report: files updated, drift items fixed, example gaps flagged or filled, drift
items deliberately skipped (with reason), and any regressions discovered along
the way.
