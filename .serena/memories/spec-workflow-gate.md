# Spec-workflow gate

Writing to `src/functualize/**` or `plugins/*/src/**` requires an existing
`.spec/features/*/tasks.md` with a parseable `## Task Dependency Graph`.
A `PreToolUse` hook denies the write otherwise.

NOT gated: `.spec/`, `tests/`, `docs/`, `contributor/`, `.claude/`,
`plugins/*/tests/`, every `pyproject.toml`.

The gate fails open — a broken validator degrades to unenforced.

Escape hatch: `.spec/EXEMPT` containing `Spec-exempt: <reason, 20+ chars>`,
honoured for one hour. Using it appends to `.spec/exemptions.log`, which **is
committed** — that ledger is the entire mitigation. Bypassing is allowed;
bypassing invisibly is not.

Shell writes (`sed -i`, heredocs, `tee`) raise no Edit/Write tool call and are
NOT blocked — they are recorded as `shell-write:` entries in the same ledger.

Full contract: `.claude/rules/spec-workflow.md`
