---
name: code-intel
description: >
  Route a codebase question to the right retrieval tool (serena, zvec-grep,
  graphify, ripgrep) instead of guessing, and carry this repo's institutional
  knowledge about how those indexes are built, scoped and shared. Use before
  searching or exploring this codebase, when an index seems stale or missing,
  when working in a git worktree or an ephemeral cloud checkout, or when adding
  a learning about these tools.
---

# Code intelligence: which tool, and why

Four retrieval tools are wired into this repo. They barely overlap, and picking
the wrong one wastes a lot of time. Route on the **shape of the question**, not
on which tool you used last.

## The routing rule

| The question is… | Use | Because |
|---|---|---|
| An exact string, path, flag, config key, error message | `rg` / Grep | No index needed. Fastest, exhaustive, zero cost. |
| "Where is X defined? What references X?" | **serena** | LSP-accurate. It either is a reference or it isn't — no ranking, no guessing. The only safe basis for a rename or signature change. |
| "What is this? Why is it like this?" | **zvec-grep** | The only tool that reads prose. Finds ADRs, `contributor/` guides and `docs/` alongside code. |
| "What depends on X? What breaks if I change it?" | **graphify `get_neighbors`** | Typed, directional edges with EXTRACTED/INFERRED confidence. Nothing else produces this. |
| "How does subsystem Y work?" (conceptual, no symbol anchor) | **zvec-grep** | Measured: graphify does this *badly* — see Gotchas. |

Institutional knowledge that is not derivable from code lives in
`.serena/memories/` — read those first when starting architectural work. They
are plain markdown, committed, and portable to any checkout.

## serena

Symbol-level navigation over a live language server. No build step; the cache
warms lazily on first use.

- `find_symbol` — definition, docstring, signature.
- `find_referencing_symbols` — every reference, per file. On a widely used
  symbol it will exceed the answer limit and return **per-file counts instead**,
  which is usually the more useful answer anyway.
- `write_memory` / `read_memory` — the durable, portable half of serena.

Cost: `.serena/cache/` reaches ~1.8 MB for this repo. Free, no API calls.

**Not portable.** The cache pickles absolute `file:///…` URIs, so it is
per-checkout and gitignored. `project.yml` and `memories/` are plain text and
**are** committed — that is the part that travels.

## zvec-grep

Hybrid lexical + semantic search over a local embedding index. Indexes markdown
as well as code, which is why it is the only tool that can answer "why".

```bash
# Build (or rebuild) this repo's index — scoped, see below
zg index "$(git rev-parse --show-toplevel)" \
  -g 'src/**' -g 'docs/**' -g 'contributor/**' -g 'plugins/**' -g '*.md' \
  --embedding local/potion-code-16m-v2
zg status
```

Measured on this repo: **21 s / 48 MB** scoped, versus 49 s / 128 MB unscoped.
Free — the embedding model runs locally.

**Always pass an explicit absolute root.** Without one, `zg` walks up the
directory tree and silently adopts an ancestor's index — so a worktree under
`.worktrees/` answers with the *parent checkout's* content. Convenient by
accident, wrong when you are asking about your branch. `git rev-parse
--show-toplevel` gives the right root from anywhere.

**Never share or copy an index.** Entries are keyed by absolute path. Copying
one and rewriting `manifest.json` yields 0% coverage and a full re-embed
(measured). Each workspace builds its own; at 21 s that is cheaper than any
sharing scheme.

## graphify

A persistent knowledge graph. Strong at typed relationships, weak at prose.

```bash
graphify extract . --code-only          # local AST, no API key, no cost
graphify cluster-only . --no-label      # regenerate report + graph.html
graphify label . --backend openai --model z-ai/glm-5.3-flash   # names communities
```

`graphify-out/graph.json` holds **zero absolute paths**, so it is committed and
every worktree and cloud worker gets a warm graph for free. Its `cache/`,
`manifest.json` and `.graphify_root` are machine-local and gitignored — see
`.gitignore` for the whitelist form and the reasoning.

Repo config already in place:
- `.graphifyignore` — scopes the graph to `src/`, `plugins/*/src/`, `docs/`,
  `contributor/`. Tests, fixtures and examples excluded. **Exclude-only**: a
  `!` line cannot re-include, so a whitelist is impossible.
- `mise.toml` sets `GRAPHIFY_VIZ_NODE_LIMIT=12000` and `PYTHONHASHSEED=0`.
- `.graphifyrc` carries the same viz limit for the git hook.

## Gotchas, all measured in this repo

- **graphify `query_graph` is poor at conceptual questions.** Asked "how does
  config precedence work", it returned 108 nodes truncated to 26, led with
  `di.Provide` and an autocomplete `.value()`, and never surfaced
  `_config/sources.py`. Use `get_neighbors` for relationships; use zvec-grep
  for concepts.
- **`--code-only` skips all markdown.** Indexing prose needs the semantic LLM
  path, which is dramatically slower: a doc run over ~119 files / ~248 k tokens
  exceeded 3600 s with the default `--token-budget 60000`. If you attempt it,
  use `--token-budget 12000`. Given zvec-grep already searches prose well and
  cheaply, this is usually not worth doing.
- **`GRAPHIFY_VIZ_NODE_LIMIT` is read from the environment only.**
  `.graphifyrc` is consumed solely by `graphify hook install`. Anything that
  regenerates `graph.html` without the env var collapses it to an aggregated
  community view.
- **Scoping changed label quality, not just size.** With tests included, the
  946 community labels came out as symbol and filename fragments
  (`FunctualizeApp`, `core.py`). Scoped to `src/`, the 292 labels became roles
  (`TUI Action Bindings`, `Job Execution Engine`). Test files were dragging
  clustering toward file-shaped groups.
- **Nothing depends on where a worktree lives.** Resolve roots from
  `git rev-parse --show-toplevel`; for a per-clone shared location use
  `git rev-parse --path-format=absolute --git-common-dir`, which is identical
  from the main checkout, a nested worktree and a worktree in `/tmp`. Never
  rely on a worktree sitting under the repo.

## Learnings log

Append here when a tool surprises you. Keep entries one or two lines, dated,
and factual — a measured number beats an impression. Prune anything that later
turns out to be wrong rather than leaving it to mislead.

- **2026-09-08** — Established the routing table above from a head-to-head test:
  same two questions to all three tools. serena gave exact reference counts
  across 26 files; zvec-grep surfaced `contributor/adr/008` explaining why the
  TUI keeps its own resolver; graphify gave typed `calls`/`imports`/`references`
  edges separating production callers from imports.
