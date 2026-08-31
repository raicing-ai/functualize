---
name: functualize-skill
description: >
  Author an agent skill whose bundled scripts are functualize jobs — giving
  the skill self-contained dependencies, a discoverable --help, structured
  output, secret masking, and testable scripts. Also covers deciding where a
  skill should live and how to distribute it: personal, committed to a team
  repo, published via the skills CLI, or packaged as a Claude Code plugin
  marketplace. Use when writing a SKILL.md, when a skill needs scripts that do
  real work, or when asked how to share or publish a skill.
license: MIT
metadata:
  version: "0.1.2"
  project: functualize
---

# Authoring skills powered by functualize

A skill is a directory with a `SKILL.md` and optional `scripts/`. Most skill
scripts are ad-hoc Python or bash: undocumented, untested, and dependent on
whatever happens to be installed. Making them functualize jobs fixes all
three.

Load the **`functualize`** skill for the job-authoring contracts. This skill
covers the skill-specific parts.

---

## 1. Establish intent before writing anything

Where a skill lives determines its frontmatter, its dependency strategy, and
whether it may assume anything about the machine. Settle this first — it is
expensive to change later.

Ask, or infer from the repo, which of these applies:

| Intent | Lives at | Assume about the host |
| --- | --- | --- |
| Just me, this project | `.claude/skills/<name>/` | Anything — it is your machine |
| Just me, everywhere | `~/.claude/skills/<name>/` | Your own toolchain |
| My team, this repo | `.claude/skills/<name>/`, committed | Whatever the repo's setup guarantees |
| Anyone, cross-repo | dedicated repo, installed via the skills CLI | Almost nothing |
| Full plugin (skills + agents + hooks + MCP) | marketplace repo | Almost nothing |

Signals worth reading before asking: is this a shared repo with other
contributors? Is there a `.claude/skills/` already committed? Does the repo
publish anything? A skill for one person on one machine should not be built
as a marketplace, and a skill meant for strangers must not assume `func` is on
their PATH.

Details, and the marketplace layout: [references/distribution.md](references/distribution.md).

---

## 2. Frontmatter: stay on the portable six

The Agent Skills spec defines exactly six fields:

```yaml
---
name: my-skill            # required; ≤64 chars, lowercase/digits/hyphens,
                          # no leading, trailing, or doubled hyphens,
                          # and MUST match the directory name
description: ...          # required; ≤1024 chars
license: MIT              # optional
compatibility: ...        # optional; ≤500 chars, prose requirements
metadata:                 # optional; string → string map only
  version: "1.0.0"
allowed-tools: ...        # optional; space-separated (experimental)
---
```

There is **no `version` field**, no `triggers`, and no `args_schema`. A
version goes in `metadata.version`, where it is inert and read only by your own
tooling. Environment requirements go in `compatibility` as prose — nothing
enforces it.

Claude Code accepts many more fields (`when_to_use`, `paths`, `model`,
`context: fork`, `hooks`…), but they are Claude Code extensions. A skill using
them is rejected by claude.ai upload and the Skills API with
`Unexpected key(s) in SKILL.md frontmatter`. **If the skill is going anywhere
beyond your own machine, stay on the six.**

### The description is the whole activation surface

It is the only part always in context, and it alone decides whether the skill
ever loads. Write concrete trigger tokens — the literal words and symbols
that appear in a request or a file — not a summary of what the skill contains.
Put the key use case first; Claude Code truncates the listing text at 1,536
characters.

---

## 3. Make the scripts functualize jobs

Write `scripts/jobs.py` as an ordinary functualize job file with PEP 723
inline metadata:

```python
#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["functualize[cli]", "httpx"]
#
# [tool.functualize]
# job = "fetch"
# ///
"""Fetch and summarize a resource."""

from functualize.job import RunContext, Log, Stdout
from functualize.types import Secret


def fetch(rc: RunContext, log: Log, out: Stdout) -> None:
    """Fetch the configured resource and emit it as structured output."""
    log("fetching")
    out.emit({"status": "ok"})
```

What each part buys:

- **`# /// script` dependencies** — `uv` builds an ephemeral environment on
  first run. The skill is self-contained; nothing needs installing first. The
  `[cli]` extra is required: `click` and `rich` live there, so a bare
  `functualize` dependency produces a script that cannot run.
- **`[tool.functualize] job = "fetch"`** — declares that this file *is* that
  job, so the command line belongs to the job. Without it, `func file.py --url x`
  reads `--url` as a function name and fails.
- **`Stdout.emit`** — `--output json` gives the agent parseable output instead
  of scraped text.
- **Secret-marked config** — wrap credentials in `Secret(...)` at the point
  they enter job code and they render as `•••` in every log line, traceback,
  and emitted payload. Agent transcripts leak by design; this is what makes
  yours safe. Note the marker/wrapper distinction in the `functualize` skill's
  config reference — the declaration marker alone does not mask output.
- **`--help`** — generated from the signature, so the agent discovers the
  interface at runtime instead of consuming your SKILL.md budget documenting it.

### Do not document the interface twice

Tell the agent to ask the script:

```markdown
Run `uv run --script scripts/jobs.py --help` to see the available flags.
```

That never goes stale. A flag list transcribed into SKILL.md does. When the
script file grows past one job, point at the structured form instead — one call
returns every job's arguments as JSON Schema:

```markdown
Run `func builtin info schema` in the script's directory to see every job and
the arguments it accepts.
```

The single-file mechanics — shebang choices, why global flags must precede the
script path, where a loose script keeps its state, how to test it — are the
`functualize-app` skill's
[standalone-scripts reference](../functualize-app/references/standalone-scripts.md).
Read it once; this skill assumes it.

---

## 4. One permission grant instead of many

Claude Code substitutes `${CLAUDE_SKILL_DIR}` in **both** the body and Bash
rules in `allowed-tools`. A single stable command prefix therefore pre-approves
the skill's entire toolkit:

```yaml
allowed-tools: Bash(uv run --script ${CLAUDE_SKILL_DIR}/scripts/jobs.py *)
```

A pile of heterogeneous scripts cannot be covered this cleanly. This is a real
argument for routing everything through one job file.

Caveats: `allowed-tools` is marked **experimental** in the spec, and
`${CLAUDE_SKILL_DIR}` is a Claude Code extension that does not substitute
elsewhere. For a portable skill, keep the body working without the grant.

---

## 5. Test the scripts

Skill scripts almost never have tests. These can:

```python
from functualize.testing import CapturingLog, FakeStdout

def test_fetch_emits_status():
    log, out = CapturingLog(), FakeStdout()
    fetch(log=log, out=out)
    assert out.emitted == [{"status": "ok"}]
```

A job only needs doubles for the capabilities its own signature declares — this
one never asked for `RunContext`, so the test does not build one.

Worth doing whenever the skill leaves your own machine.

---

## 6. The cost, stated honestly

This adds a dependency a plain bash script does not have: `uv` must be
present, and the first run pays a resolution cost. For a skill distributed to
strangers that is a real adoption tax.

It is worth paying when the scripts do meaningful work — network calls,
config, credentials, structured output, anything worth testing. It is not
worth it for a three-line `grep` wrapper. Prefer plain bash for trivial
scripts and reach for this when the script has actual behavior.

---

## Checklist

- Intent settled; destination matches it.
- Frontmatter on the portable six, `name` matching the directory.
- Description carries literal trigger tokens, key use case first.
- Body under ~500 lines; depth pushed into `references/`.
- Scripts self-contained via PEP 723, with `[tool.functualize] job`.
- Interface discovered via `--help`, not transcribed.
- Credentials declared `Secret[str]`.
- Run it once end to end before shipping.
