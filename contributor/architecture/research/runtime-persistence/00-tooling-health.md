# Code-intelligence and skill health

Recorded 2026-09-20 against worktree
`feat-substrate-sqlite` at `b0148f8`.

## Retrieval tools

| Tool | MCP result | Fallback/result | Conclusion |
|---|---|---|---|
| Serena 2.0.0.dev0 | Healthy | Activated the exact worktree; resolved `StoreSubstrate`, `ScopeStore`, `RunStore`, engine and boot symbols plus references through the Python LSP | MCP is usable |
| Graphify 0.9.56 | Host rejected MCP calls because they require approval while session policy is `never` | Existing `graphify-out/graph.json` loaded through the CLI; `explain` and `path` worked | Index/CLI healthy; MCP transport blocked by host policy |
| zvec-grep 0.2.2 | Host rejected MCP calls under the same approval policy | Built a project index successfully: 813 files, 12,876 entities, zero failures; semantic CLI queries returned architecture/lifecycle evidence | Index/CLI healthy; MCP transport blocked by host policy |

The Graphify index contains 9,594 graph nodes and the committed graph file is
12,182,405 bytes. Its installed global skill copies report version 0.9.55 while
the CLI is 0.9.56. Those global locations are outside this writable workspace;
the version warning did not prevent graph queries.

This distinction matters: Graphify and zvec are not broken at their engines or
indexes. Their MCP calls are unavailable **in this session** because the product
requires an approval that the enforced policy cannot grant. The analysis used
their CLIs rather than representing that limitation as success.

## Project-level C4 skill

Skill discovery selected
[`softaworks/agent-toolkit@c4-architecture`](https://skills.sh/softaworks/agent-toolkit/c4-architecture).
The registry reported approximately 4.1K installs, and its linked repository had
approximately 2.5K stars at evaluation time. Registry security checks were green.

The intended project-level install command is:

```bash
npx skills add softaworks/agent-toolkit@c4-architecture -y --copy --json
```

It correctly targeted `.agents/skills/c4-architecture` but could not create that
directory because this session mounts `.agents/skills` read-only. `.codex` is
also read-only. Installing it into the repository's shipped `skills/` directory
would violate the repository's two-directory rule: this is contributor guidance,
not an end-user Functualize skill.

The skill's `SKILL.md` and its C4 syntax, advanced-pattern, and common-mistake
references were read from a temporary clone. Their constraints applied here:

- Context and container diagrams are always present.
- Component diagrams exist only for the container whose internals matter.
- Dynamic diagrams describe consequential flows; deployment diagrams describe
  materially different runtime topologies.
- Containers are deployable/runtime units, not Python packages.
- Relationships are one-way and action-labeled.
- Diagrams stay below roughly 15–20 elements and one diagram per file.
- Decision debate stays in prose; diagrams show the selected outcome.

Project installation remains an environment blocker, not completed work. Re-run
the command above when `.agents/skills` is writable.

## Evidence routes used

- `rg` for exhaustive literals, imports, entry-point groups, and call sites.
- Serena for symbol bodies and language-aware references.
- zvec for lifecycle, rationale, and cross-document semantic retrieval.
- Graphify for blast radius, hub degree, and paths between storage and engine
  concepts.
- Git history for PR #34, PR #39, PR #41, and the v0.3.0 baseline.
- Primary upstream documentation/source for C4, Celery, Omnigent, and Turso
  AgentFS.
