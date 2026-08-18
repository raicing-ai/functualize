<!--
  This PR will be SQUASH-MERGED, and the squash commit takes:
    - its subject from the PR title
    - its body from this description

  So the PR title must be a valid Conventional Commit, e.g.
    feat(tui): render group flags mid-path
    fix(engine): resolve Log from the registry in RunContext.log

  Types: feat fix docs refactor test perf ci build chore revert
  See CONTRIBUTING.md § Commit Message Convention.
-->

## Summary

<!-- What this PR does, and why it is the right change. The diff already says what changed. -->

## Changes

<!-- List the key changes -->

-

## Testing

<!-- How was this tested? Name the production paths the change reaches — see contributor/guides/wiring-discipline.md -->

- [ ] Tests pass locally (`uv run pytest`)
- [ ] Linting passes (`uv run ruff check src/ tests/`)
- [ ] Formatting passes (`uv run ruff format --check src/ tests/`)
- [ ] Type checking passes (`uv run mypy src/`)
- [ ] Import boundaries hold (`uv run lint-imports`)

## Related Issues

<!-- Link related issues HERE, not in the title: Fixes #123, Relates to #456 -->
