# Evidence and premise audit

WorkflowMode: REPOSITORY_NATIVE. WorkflowAuthority: `AGENTS.md`, `.claude/rules/spec-workflow.md`, `.spec/CONSTITUTION.md`. CurrentPhase: Specify → Plan. ArtifactLocations: this directory. ApprovalState: shape authority SD/19595276 v2 approved by member; task list and surviving smells still require native Plan review. ContextPolicy: fresh checkout at `91947bb4f90c611d588de9907f84e61edf2c1514`, live Multica/Jira/Confluence reads; the retired branches are prior art, not authority.

## Live authorities

- MCH-194 issue read at revision 62, updated 2026-10-19 04:55:56 UTC; its `Shape intent` property points to SD/19595276. Triggering approval and dispatch thread read, plus all root thread summaries.
- Confluence SD/19595276 read full, version 2, updated 2026-10-19 04:37:16 UTC. Field table says `Status = Approved`, `Authority = Approved`, carried by MCH-194, N1-a folds in MCH-189 and MCH-192. The stale draft sentences in its prose do not override the field table. Approval on MCH-194 says B, S2, N1-a, N2 include, N3 include.
- Jira FOSS-132 (updated 2026-10-16 12:56:28 UTC), FOSS-126 (2026-10-13 14:26:07 UTC), FOSS-129 (2026-10-13 14:26:09 UTC) read live with evidence view. FOSS-126's original either-two-rows-or-refusal expectation is superseded by the approved warning model; FOSS-129's earlier permission for dotted top-level IDs is superseded by S2.

## Base and falsifying measurements

- `git diff --name-only d1c7e40a..91947bb4` touches 23 files, with no naming, TUI, collision or help module; `app/utils.py` moved for vault behavior, so its relevant symbols were re-read.
- Fresh temp project, `uv sync --frozen --all-extras --all-packages`, `func` 0.4.0, fresh HOME and all three XDG roots: `func suite.inventori` exits 1 and prints `func suite.inventory`; `func suite.inventory` exits 0; `func suite inventory --help` exits 0 and prints `Usage: inventory [OPTIONS]`. Thus E1, E2 and E3 fail at this base.
- The same fixture's `status()` / `status_()` pair yields one `tools.status` row, runs the underscore claimant, and `func tools --help` and `builtin info jobs` show no collision. A second fixture's `info jobs --json` row has no collision field. Thus E5 fails on the visible surfaces while the discovery finding exists.
- In-process TUI SmartBar with `audit.explain` and `audit.notes`, no `GroupOptions`: both the root and `audit ` offer flat `audit.explain` / `audit.notes` plus `builtin`; E4 fails.
- Root `func --help` in a project with `hello` and grouped jobs lists only `builtin` under Commands; E7 fails. `.spec/STATUS.md:3860` records a prior deliberate decision to keep root help that way; SD/19595276 N3 explicitly supersedes it, so the pinned test must be rewritten, not discarded.
- `_types/naming.py:561-574` derives a leaf by stripping the group prefix, preserving a literal dot inside an ungrouped leaf. `dispatch.py:727` and `_types/naming.py:532` split input dots today. E6 requires rejecting *group traversal by dot*, not every token containing a dot.
- `_discovery/collisions.py:37-105` orders claimants by source and Python name; `_cli/info.py:317-360` gathers provider and pipeline findings. The older collision branch's research measured a two-file report with dropped `path` and surviving descriptor `source_file`; Plan must verify association in the current code before treating that as a contract.

## Prior art and retrieval

- `zg` indexed this checkout (912 files, 14,412 entities; absolute root confirmed by `zg status`) and queried prior reasons for group options, identity and CLI/TUI separation. ADR-009 §6 already calls out the TUI header's dotted/spaced divergence and the shell write-back rule. ADR-018 keeps discovery findings non-fatal so healthy jobs and diagnostics remain accessible. `contributor/architecture/surface-boundary.md` requires both `func` and the application CLI for program behavior.
- Serena was activated by this checkout's absolute path. It found `_job_segments` used only by `GroupTrie.from_cache`; `build_group_option_trie` is consumed by inline TUI, full TUI, SmartBar and an example. Graphify confirms the same dependency directions and shows `JobDescriptor` as a shared vocabulary hub. Its committed `graph.json` names an unavailable `built_at_commit`, so graph edges are directional leads only, checked against live source before use.
- Skills consulted: repository `python-design-patterns`, user `design-patterns-refactoring`, `graphify`, and `functualize-repo-ops`. BEFORE smells are **primitive obsession** (one string means identity and path), **shotgun surgery** (surface-specific conversions), and **divergent change** (group navigation depends on `GroupOptions`).
