# CLAUDE.md

See [AGENTS.md](AGENTS.md) for project context, commands, architecture, and constraints.

## Contributor Documentation

Consult the "Mandatory reading by task" table in [AGENTS.md](AGENTS.md) before layer changes, TUI work, test authoring, or architectural decisions in `src/functualize/`.

For any work in `src/functualize/_cli/tui/`, additionally read `contributor/guides/steering_textual_tui.md` (Textual architecture + testing steering with a compliance audit; HARD rules on key bindings, workers, and modality) and `contributor/guides/tui-panels.md` (panel enforcement rules). Claims in the steering docs are proven by `tests/tui_audit/` — re-run `uv run pytest tests/tui_audit/ -v` before changing key handling, workers, or overlay behavior.

To *see* what the live TUI/CLI renders while debugging or verifying a change (e.g. trying the examples one by one), use the `observe-tui` skill (`.agents/skills/observe-tui/SKILL.md`). It is for manual/agent verification only — never use it in automated tests.

## Spec-driven workflow

This project uses spec-driven development. For non-trivial work, use the `spec-driven-developer` subagent:

```
claude --agent spec-driven-developer
```

Or invoke phase commands directly: `/agentic-execute`, `/agentic-plan`, `/agentic-specify`, `/agentic-verify`, `/agentic-explore`.

Key files:
- `.spec/STATE.md` — current in-flight work (read first if present; generated per-session, gitignored)
- `.spec/CONSTITUTION.md` — non-negotiable rules
- `.spec/ARCHITECTURE.md` — implementation-level architectural details
- `.spec/TESTING.md` — test commands and conventions

## Documentation sync

After completing a feature or before a release, run the `/sync-docs` skill to reconcile
README, CHANGELOG, contributor docs, and `contributor/architecture/codemaps/` with the code.
