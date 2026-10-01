# Report template

Three files in `$SESSION/`, split into two folders. Keep the field names and headings
exactly as shown, because the maintainer greps across many reports.

```
$SESSION/
├── local/      NEVER LEAVES THIS MACHINE
│   ├── journal.md
│   └── summary.md
└── upload/     the only folder that may be sent anywhere
    ├── findings.md
    └── repro/<id>/run.sh
```

A file's folder says what is allowed in it. `local/` may quote the target repository and name it.
Everything in `upload/` is written as if a stranger will read it, so it contains nothing
from the target repository (`AGENT_BRIEF.md` §6).

---

## 1. `local/journal.md` — written while you work (stays on this machine)

### Header (write it at setup)

```markdown
# Field journal — <target-repo> — <task in one line>   (local only: never upload)

- date: 2026-09-29
- agent / model: <what you are, if known>
- task (verbatim from the prompt): <…>
- options: source=<…> depth=<light|normal|deep> focus=<…>
- functualize: <`func builtin version` output> via <pypi | local editable @ <sha> | binary | uv tool | project dep>
- invocation prefix: <e.g. `uv run func`>
- python / uv / os: <…> / <…> / <…>
- original artefact: <path(s) being converted, LOC>
```

### Entries (append as you go)

One entry per event. Start with a time, then a tag, then the journey stage from
`observation-guide.md` §2:

```markdown
- 14:02 [J2] ran `uv run func builtin info schema --kind job`. expected: my job. got: `[]`.
- 14:04 [J5] !ux `func builtin why sync-assets` → "no job named sync-assets". expected: a
  reason. The file was in `scripts/`, not `.functualize/jobs/`. Took 2 min to find. Count: 1
- 14:10 [J4] !win `--help` rendered the `Path` and `Enum` params perfectly, zero effort.
- 14:15 [J6] !bug fake secret printed in clear inside a traceback:
      ValueError: bad token sk-FIELDTEST-0000   ← (fake value, safe to quote)
- 14:20 [J4] !opinion wanted `out.table(rows)`; `emit` of a list of dicts renders as ___.
```

Tags: `!bug` `!ux` `!docs` `!gap` `!opinion` `!win`. An untagged line is plain
narration. That is fine, and it shows which stages you passed through.

---

## 2. `upload/findings.md` — written at the end

Start with a one-line index, then one block per **root cause**. Order the blocks by
severity, then by how often you hit them.

```markdown
# Findings — <what kind of task, no repo name> — <date>

| id | sev | type | category | status | title |
|----|-----|------|----------|--------|-------|
| F01 | S1 | bug | skills | confirmed | Skill's documented invocation runs nothing and exits 0 |
| F02 | S3 | ux | discovery | confirmed | `why` does not mention the discovery root when a job is absent |
| F03 | - | win | signature-mapping | confirmed | Enum and Path params need no annotation beyond the type |
```

### Finding block

````markdown
---
id: F01
title: Skill's documented invocation runs nothing and exits 0
type: bug                      # bug | ux | docs | gap | opinion | win
severity: S1                   # S1..S4, or - for win/opinion
category: skills               # observation-guide.md §4.3
stage: J7                      # journey stage where it surfaced
status: confirmed              # confirmed | suspected | not-reproduced (= does it reproduce; NOT a verdict on whether it is a defect)
hits: 3                        # how many times you ran into it
functualize: 0.4.0 (pypi)
sha: -                         # `git rev-parse --short HEAD` of the checkout when source is a local checkout, else -
followed: functualize-skill/SKILL.md §3   # the doc / skill / --help section you relied on, or `none (guessed)`
repro: repro/F01/run.sh        # runnable check, exits NON-ZERO while the bug shows; `-` if status is not confirmed
cost: ~20 min                  # time lost, your best estimate
---

**What I was doing.** Converting `.claude/skills/asset-sync/scripts/sync.py` into a
functualize job, following the `functualize-skill` skill §3.

**Expected.** `uv run --script scripts/jobs.py --help` prints the job's flags, as the
skill says.

**Actual.** No output, exit code 0.

```text
$ uv run --script scripts/jobs.py --help; echo "exit=$?"
exit=0
```

**Minimal repro.** `repro/F01/`: one 12-line `jobs.py` with a PEP 723 header, then the
command above. Deterministic.

**Workaround.** Shebang `#!/usr/bin/env -S func`, and invoke with `func scripts/jobs.py --help`,
as in `functualize-app` `references/standalone-scripts.md`.

**Suspected cause.** The two shipped skills disagree. `functualize-skill` §3 has the old
shebang; `standalone-scripts.md` explains why it runs nothing. (suspected; I did not read
source)

**Suggestion.** Align `functualize-skill` §3 with `standalone-scripts.md`, and make a
functualize-headed file that is executed by bare `python` warn instead of exiting 0.

**Evidence.** journal 14:31, 14:40, 15:02. Docs followed: `functualize-skill/SKILL.md` §3.
````

Rules for the block:

- **Expected and Actual are mandatory** for `bug`, `ux` and `docs`. For `gap`, Expected is
  what you needed and Actual is what exists.
- **Quote output verbatim** in a fenced block. Say if you trimmed it. Redact secrets.
- **`Suspected cause` stays labelled as a suspicion**, unless you verified it, in which
  case say how.
- **`Suggestion` is optional** and is only ever a suggestion. You never apply it to
  functualize.
- **Cite the doc or skill you followed**, by file and section, whenever the finding is
  about following instructions. Put it in the `followed:` field. It is **mandatory for
  `bug`, `ux` and `docs`**. Whoever triages the finding uses it to tell "the docs misled
  the reporter" from "the reporter guessed".
- **`repro:` points at a runnable script**, not a description. `run.sh` must exit non-zero
  while the problem is present and zero once it is fixed, so anyone can re-run it later to
  check a fix. Prose steps go in "Minimal repro" as before; the script is the executable
  form of the same steps.
- **The repro must contain nothing from the target repository.** Toy files, invented
  names, fake values. See `AGENT_BRIEF.md` §5 step 1 and §6.
- **`status: confirmed` means the finding reproduces.** It does not mean maintainers have
  agreed it is a defect. Triage decides that, and it can rule your finding working as
  intended even though it reproduces. That is fine and useful.

---

## 3. `local/summary.md` — the one page the maintainer reads first (stays on this machine)

```markdown
# Summary — <target-repo> — <task in one line>   (local only: never upload)

## Verdict
- Journey completed with functualize: **yes | partially | no**
- Parts left un-converted and why: <… or "none">
- Would I choose functualize for this task again? **yes | maybe | no**. <one sentence why>

## Before / after
| | Original | Converted |
|---|---|---|
| Files / LOC | | |
| CLI parsing code (LOC) | | 0 if the signature replaced it |
| Tests | | |
| `--help` quality | | |
| Machine-readable output | | |
| Secret handling | | |
| Cold / warm run time | | |

## Top 3 problems
1. F.. — <title> — <why it matters, one sentence>
2. …
3. …

## What worked well
- F.. — …

## Opinions and suggestions
<Grounded in this task. Format per observation-guide.md §5. Most important first.>

## Journey coverage
| Stage | Touched? | Notes |
|---|---|---|
| J1 Install | yes/no | |
| … | | |
| J11 Hand-off | | |

## Where the field protocol itself fell short
<Anything unclear, wrong or missing in these instructions, or "nothing".>
```
