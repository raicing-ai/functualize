# Doc Audit Reference — Identifying Verifiable Content

When auditing `docs/*.md` for scenario candidates, use this guide.

## What is verifiable?

A code block is **verifiable** if it satisfies ALL three:

1. **Executable**: Contains a shell, bash, console, or sh command
2. **Deterministic**: Output is predictable and repeatable
3. **Isolatable**: Can run without affecting the host or requiring external services

## What to skip

| Type | Reason |
|---|---|
| Configuration file examples (.toml, .ini, .yaml) | Not executable; syntax errors caught by linters |
| Python code blocks (```python) | Go in pytest, not doc verification |
| Reference-only snippets | Not meant to be copy-pasted |
| `curl` to external APIs | Non-deterministic; requires network + API keys |
| Commands with random/test data | Non-deterministic output |
| `git clone` + `cd` examples | Users run these interactively; test in a different way |
| `docker run` examples inside docs | Nesting containers is fragile |

## Priority — which docs to audit first

Docs are ranked by **user-facing impact** × **likelihood of drift**:

### Tier 1 — Must verify (high-impact + high-drift)
| Doc | Why |
|---|---|
| `docs/getting-started/installation.md` | First thing a new user runs. If broken, they leave. |
| `docs/getting-started/quickstart.md` | Step-by-step onboarding. Every step must work. |
| `docs/cli/scaffold.md` | Code generation. If output format drifts, docs are wrong. |
| `docs/guides/modes.md` | Library/Adapter/Directory mode code. High surface area. |

### Tier 2 — Should verify (medium-impact)
| Doc | Why |
|---|---|
| `docs/cli/config.md` | Config resolution examples change with defaults |
| `docs/guides/configuration.md` | Layered config; env var behavior |
| `docs/cli/inline-tui.md` | TUI keybindings and SmartBar behavior |
| `docs/guides/plugins.md` | Plugin registration patterns |
| `docs/guides/mcp.md` | MCP serve commands; tool registration |

### Tier 3 — Nice to verify (nice-to-have)
| Doc | Why |
|---|---|
| `docs/guides/workflows.md` | Workflow gate interaction; needs PTY |
| `docs/guides/job-config.md` | Pydantic model examples |
| `docs/guides/jobs-discovery.md` | Discovery filter examples |
| `docs/guides/group-options.md` | Group option patterns |
| `docs/guides/task-runner.md` | Task runner examples |
| `docs/examples/` pages | Mostly reference; examples have their own tests |

## How to audit a single doc page

For each doc page:

1. **Read the page** from top to bottom
2. **Find all fenced code blocks** with `bash`, `sh`, `console`, or `shell` language tags
3. **For each block**, ask:
   - Is it executable as-is? (No `${PLACEHOLDER}`, no `...`)
   - Is it deterministic? (No `curl`, no `git clone`, no random data)
   - Can it be isolated? (No `sudo`, no system packages)
4. **If all three yes**, create a scenario candidate:

```yaml
# Candidate: docs/guides/configuration.md:85-90
# Block: "Base + environment overlay"
# Commands:
#   ENVIRONMENT=prod func data-sync
# Dependencies: needs a project with config.base.toml + config.prod.toml
# Verdict: VERIFIABLE — create scenario
```

5. **If borderline**, note the concern:

```yaml
# Candidate: docs/guides/mcp.md:45-52
# Block: "func mcp serve"
# Commands: func mcp serve
# Dependencies: needs functualize-mcp plugin
# Concern: serve runs forever; need to start as daemon + kill after verify
# Verdict: SKIP — not suitable for automated scenario (needs process mgmt)
```

## Example audit output

After auditing all Tier 1 docs:

```
docs/getting-started/installation.md:
  Block L22-24: pip install + --version              → ✅ VERIFIABLE
  Block L26-33: minimal install (no CLI extras)       → ✅ VERIFIABLE
  Block L40-41: func --version                        → ✅ VERIFIABLE (dup of L22)

docs/getting-started/quickstart.md:
  Block L17-23: func jobs.py deploy                   → ✅ VERIFIABLE
  Block L53-55: func jobs.py                          → ✅ VERIFIABLE
  Block L84-91: scaffold, add job, run               → ✅ VERIFIABLE
  Block L103-106: func deploy, func migrate           → ⚠️ Needs CWD setup
  Block L153-158: uv run my-platform ...              → ⚠️ Needs scaffold first

docs/cli/scaffold.md:
  Block L18-23: scaffold init my-project             → ✅ VERIFIABLE
  Block L29-34: scaffold add job X                   → ✅ VERIFIABLE
  Block L42-48: scaffold add plugin X                → ✅ VERIFIABLE

Total candidates: 12 verifiable, 3 borderline, 5 skipped
```

## Determining line numbers

Line numbers must be precise. The runner's report references them directly.

1. Read the doc file
2. Find the code block
3. Note the **first line** of the opening fence (```bash) through the
   **closing fence** (```)
4. If the block spans lines 22-24, write: `lines = "22-24"`
5. If it's a single line: `lines = "42"`

**Important**: line numbers change when docs are edited. The scenario file
must be updated when the doc moves its code blocks. This is intentional —
if a scenario's source reference becomes stale, it fails, and a human must
verify that the new line numbers still reference the same content.

## When to split vs combine

**Split into separate scenarios** when:
- Code blocks are in different doc pages
- Blocks have different dependencies (one needs wheel, one doesn't)
- Blocks test different features (installation vs config vs TUI)

**Combine into one scenario** when:
- Multiple code blocks in the same doc form a tutorial flow
- Each block depends on the output of the previous
- You want to fail the whole sequence if any step breaks

## Getting started — audit command

The runner has a built-in audit mode:

```bash
python .agents/skills/doc-verify/scripts/run-scenario --audit docs/
```

This scans all `docs/*.md`, lists code blocks, and prints which are candidates.
It does NOT execute anything — just identifies verifiable blocks.
