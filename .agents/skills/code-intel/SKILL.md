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
| "What depends on X? What breaks if I change it?" | **graphify `get_neighbors`** (MCP) / **`graphify explain "X"`** (CLI) | Typed, directional edges with EXTRACTED/INFERRED confidence. Nothing else produces this. |
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

- **2026-09-08** — `get_neighbors` is an **MCP tool name, not a CLI subcommand**.
  `graphify get-neighbors` exits with `unknown command`. The CLI equivalent is
  `graphify explain "X"`, which reports degree and lists every connection
  grouped by file with the same EXTRACTED/INFERRED markers (26 connections for
  `ResolutionChain`). Route to whichever surface you actually have.
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

- **2026-09-08** — When a long index build runs inside an agent session, kill
  the **agent**, not the job. Killing `graphify extract` returned control to the
  supervising omp agent, which diagnosed the timeout and relaunched it — twice,
  at successively smaller `--token-budget` values. Killing the agent process
  took its child job down with it. Three attempts and ~100 minutes were spent
  before this was understood. Corollary: an instruction like "let it run, do not
  interrupt it" makes an agent persistent through failures, so say what should
  happen *on failure* too.

- **2026-09-08** — `pgrep -f "<pattern>"` matches the shell command doing the
  searching, because that command line contains the pattern. It reported a
  killed process as still running. Filter the wrapper out
  (`ps -eo pid,args | grep <pat> | grep -v shell-snapshots`) before concluding
  anything about whether a process died.

- **2026-09-08** — Verify a claim before writing it into a commit message. A
  message here asserted a `.gitattributes` union merge driver for `graph.json`
  that had been recommended hours earlier and never implemented; there was no
  `.gitattributes` file at all. `git check-attr merge diff -- <path>` confirms
  an attribute actually applies.

- **2026-09-08** — `git count-objects -vH` reports `size-pack` for *packed*
  objects only. A freshly committed blob is loose, so the pack figure does not
  move and the repo looks unchanged. Read `size:` as well before claiming a
  commit was cheap.

- **2026-09-08** — Verified end-to-end on a real multica worker (contabo,
  issue MCH-11). A task worktree landed at
  `/home/ubuntu/multica_workspaces/<ws>/<issue>/workdir/functualize` — a
  different user and an unrelated path — and `graphify-out/graph.json` arrived
  intact with **8,608 nodes, 292 named communities, 0 absolute paths**, no
  build step, ~20 s from checkout. `.serena/memories/` and `project.yml` came
  too; `.zvec-grep/` and `.serena/cache/` were correctly absent. The
  portability rule holds across machines, not just across worktrees.

- **2026-09-08** — **The data travels; the tools do not.** That same worker had
  no `graphify`, no `zg` and no `uvx` on its PATH, so it could read `graph.json`
  as JSON but could not run any graphify command. A committed graph is warm as
  *data* on any worker, but the traversal tooling is a separate prerequisite —
  do not assume a remote agent can run the commands in this skill.

- **2026-09-08** — That diagnosis was half wrong, and the failure mode is worth
  remembering: `command -v` over a **non-interactive** SSH session searches only
  the default PATH, which excludes `~/.local/bin`. graphify *was* installed on
  the host, under `/root/.local/bin`. The real fault was a **user split** — the
  tools lived in root's home while the multica daemon had moved to the `ubuntu`
  user (uid 1000), whose `~/.local/bin` and `~/.omp/agent/mcp.json` were empty.
  Check `ls ~<user>/.local/bin` per user before concluding a tool is absent.

- **2026-09-08** — Fixed by installing **system-wide** rather than per-user, so
  the next daemon-user change cannot break it again: `uv` and `uvx` copied to
  `/usr/local/bin`, then
  `UV_TOOL_DIR=/opt/uv-tools UV_TOOL_BIN_DIR=/usr/local/bin uv tool install graphifyy`.
  Verified as the `ubuntu` user, then end-to-end on a real task (MCH-12):
  checkout → first successful `graphify query` in **~8.5 s**, query itself
  ~4.0 s, returning the same nodes as the local run.

- **2026-09-08** — Remote host upgraded to node 22.23.2 (NodeSource) and
  `@zvec/zvec-grep` installed, so both tools now work there. The upgrade removed
  133 Debian node-stack packages and moved npm's global prefix from
  `/usr/local` to `/usr` — reset it with `npm config set prefix /usr/local`
  before reinstalling globals, or the existing CLIs are orphaned at the old
  prefix. Nothing on that host ran `/usr/bin/node`, which is what made the
  upgrade safe; check that first (`readlink /proc/<pid>/exe`) rather than
  assuming.

- **2026-09-08** — **Head-to-head on a real cold worker (MCH-13)**, and the gap
  is decisive on an ephemeral worktree:

  | | setup | query | disk |
  |---|---|---|---|
  | graphify (committed graph) | **none** | 3.86 s | 0 (already in git) |
  | zvec-grep | 51.4 s index build, 566 files | 6.1 s | 62 MB |

  On a throwaway checkout that runs one or two queries, graphify wins by a wide
  margin — the committed `graph.json` *is* the index. zvec-grep earns its build
  cost only on a long-lived workspace, or when the question genuinely needs
  prose: its top hits for "how does configuration precedence work" were
  `docs/guides/configuration.md` and `docs/guides/architecture.md`, which
  graphify cannot reach at all.
