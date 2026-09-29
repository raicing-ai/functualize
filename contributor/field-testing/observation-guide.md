# Observation guide

What to notice, where to look, and how to grade what you find. Read §1 and §4 before you
start. Use §2 and §3 as a checklist while you work.

---

## 1. What counts as a finding

Anything where functualize, its docs or its skills made the task **slower, riskier,
more confusing or less correct** than a capable newcomer would reasonably expect. Also
anything that made it notably **better**.

Record it even when:

- you figured it out quickly (the time it cost is data);
- it might be your own mistake (say so, since a mistake the tool invited is still a UX
  finding);
- it seems too small (the maintainer can discard it; they cannot recover what you never
  wrote).

Leave out problems in the user's original code that have nothing to do with functualize.
Those belong in your Mission A report.

---

## 2. The journey, stage by stage

Log at least one journal line for every stage you pass through. The questions are
prompts, not a form, so skip the ones that do not apply.

### J1 · Install and reach `func`
- Did the install command in the docs work as written, on this platform?
- Was it obvious which extra you needed (`[cli]`), and what happens without it?
- Did `<prefix>` detection (skill `functualize` §0) pick the right invocation first time?
- Did `func builtin version` agree with what you thought you installed?

### J2 · Orient
- From `func --help` alone, could you tell what to do next?
- Did `func builtin info` / `info schema` show what you expected, in a form you could use?
- Were the shipped skills findable (`func builtin skills list`, `skills path`), and did
  they load?
- Were any names confusing: `builtin`, jobs vs commands, groups?

### J3 · Choose the shape
- Was it clear whether to write a standalone script, workspace jobs or a scaffolded
  project?
- Did the docs, skills and examples agree?

### J4 · Author the job
- Did the signature-to-CLI mapping do what you expected for every parameter type the
  original used: `bool`, `list[...]`, `Path`, `Enum`, `Optional`, defaults, `*args`?
- Did capability injection work first time? Were any names or imports surprising?
- Did you hit any of the "wrong by default" traps (return not printed, invisible job)
  even after reading about them?
- How did the size and readability of the converted code compare with the original?

### J5 · Discovery
- Was the job discovered where you put it? If not, did `func builtin why <job>` explain
  why, in words that led to the fix?
- Did anything change after a second run (the warm cache)? Edit the file, re-run, and
  check the change is picked up.
- Did a helper function or an import show up as a job when it should not have?

### J6 · Config and secrets
- Could you express the original's env vars, config file and defaults?
- Was precedence (flags > shell env > `.env` > files > defaults) what you expected, and
  could you *see* where a value came from?
- Did secrets stay masked everywhere: logs, `--help` defaults, errors, tracebacks,
  emitted JSON, `builtin info`, `builtin env`?
- Was the marker vs wrapper distinction for secrets clear before you got it wrong?

### J7 · Run
- Did the output match the original's? Was stdout clean for machine consumers?
- Were exit codes right on success, on failure and on bad arguments?
- Non-TTY / CI / agent use: no hangs, no ANSI sequences in piped output, no prompts
  without a terminal.
- Run-time overhead: `time` the original against the converted job (cold and warm). Note
  anything above ~1 s.

### J8 · Errors
- Pass a bad argument, leave out a required one, point at a missing file, make the job
  raise. Was each error message **actionable**? Did it name the thing to change?
- Did any error expose a functualize traceback where a one-line message belonged?
- Did any error mention an internal name (`_engine`, `ScopeStore`, …) that a user would
  never have seen?

### J9 · Test
- Could you test the job with `functualize.testing` doubles, following
  `references/testing.md`?
- Did the doubles' recorded shapes match the docs?

### J10 · Neighbouring surfaces (at `depth: deep`, or when the task touches them)
- **TUI:** does `func` with no arguments open, list your job, and run it? Is the
  parameter form right?
- **MCP:** does `func mcp serve` expose the job with the same schema as `info schema`?
- **Workflows:** does a gate block, persist, answer and resume as the README says?
- **Scaffold:** does `func builtin scaffold init` produce a project that passes its own
  tests?
- **History:** do `func builtin history` / `func builtin run` show what ran?

### J11 · Hand-off
- Could the user, or another agent, run the converted thing from the instructions you
  are leaving them?
- What would you tell them to watch out for? Each of those is a finding.

---

## 3. Cheap probes

At `depth: normal`, run the probes for each surface your task touched. At `deep`, run
all of them. Each takes seconds. Record the result, including "worked as expected".

| Probe | Command / action | Looking for |
|---|---|---|
| Help quality | `func <job> --help` | Types, defaults and docstrings rendered. No internal parameters (capabilities) leaking into flags |
| Schema parity | `func builtin info schema <job>` against `--help` | Same parameters, same required set |
| Typo tolerance | `func <jb>` (misspelled job), `func <job> --envronment x` | A "did you mean" hint, or at least a clear error |
| Missing required | `func <job>` without a required arg | A named parameter and a non-zero exit |
| Non-TTY | `func <job> … < /dev/null \| cat` | No hang, no escape codes |
| JSON purity | `func --emit-format json <job> … 2>/dev/null \| python -m json.tool` | Parses. Logs went to stderr |
| Exit codes | `echo $?` after a success, a raised exception and a bad flag | Distinct and non-zero on failure |
| Warm cache | Run, edit the job's docstring or a default, run again | The change is visible |
| Secret leak | A fake secret (`sk-FIELDTEST-0000`) through config, then raise an error in the job | `•••` everywhere, including tracebacks |
| `why` usefulness | Rename the file so a filter excludes it, then `func builtin why <job>` | Names the filter that excluded it |
| From elsewhere | Run the job from a subdirectory, and from outside the repo | Behaviour matches what the docs say about discovery roots |
| Docs as written | Copy one command from the docs or skill you followed, verbatim | It works unchanged |

---

## 4. Grading

### 4.1 Type (pick one)

| Type | Meaning |
|---|---|
| `bug` | functualize did something wrong: a crash, wrong output, wrong exit code, a leak, lost data |
| `ux` | It worked, but in a way that confused you, surprised you or cost you effort |
| `docs` | The docs, a skill, `--help` or an error message was wrong, missing, contradictory or misleading |
| `gap` | A capability you needed does not exist |
| `opinion` | A design judgement: "this should work differently", with your reasons |
| `win` | Something that worked notably well and should be kept |

### 4.2 Severity

| Level | Meaning | Test |
|---|---|---|
| **S1 · blocker** | The journey could not be completed with functualize | You abandoned part of the task, or kept the original code for it |
| **S2 · major** | Completed only with a workaround, by reading source, or with real risk (a leak, wrong output) | A typical newcomer would likely have given up or shipped something wrong |
| **S3 · minor** | Friction. Cost minutes, not the outcome | You'd mention it in a code review |
| **S4 · polish** | Cosmetic, naming, wording | You'd mention it only if asked |

`win` and `opinion` take no severity. Give them `severity: -`.

Type also decides what happens next, after you have written the finding:

| Type | What triage does with it |
|---|---|
| `bug`, `ux` | Re-run your repro, then check the result against the feature's documented and decided intent |
| `docs` | Usually confirms the docs were unclear and proposes a wording or `--help` fix |
| `gap`, `opinion` | Goes straight to discussion, since there is no defect to reproduce |
| `win` | Recorded as behaviour to keep, so later cleanups do not remove it |

### 4.3 Category (pick the closest one)

`install` · `invocation` · `discovery` · `signature-mapping` · `capabilities` ·
`config` · `secrets` · `output` · `errors` · `exit-codes` · `performance` · `cache` ·
`tui` · `mcp` · `workflows` · `scaffold` · `testing` · `skills` (the shipped agent
skills) · `docs` (the public docs site / README) · `examples` · `field-protocol` (this
folder was wrong or unclear)

If none fits, use `other` and propose a name in the finding.

### 4.4 Status

- `confirmed`: reproduced in a minimal case under `$SESSION/repro/<id>/`.
- `suspected`: seen, but not reduced. Say what stopped you.
- `not-reproduced`: seen once and could not be made to happen again. Keep it, because
  flaky behaviour is also data.

---

## 5. Opinions are welcome, and have a format

The maintainer explicitly wants your opinions on improving functualize. Make them
useful:

- **Ground each one in the task.** "When converting X I wanted Y because Z" beats "it
  should support Y".
- **Name the alternative**: what you would have expected instead, or how another tool
  you know (click, typer, invoke, just, make, fire) handles it.
- **State the cost.** What would the change break or complicate?
- **Separate taste from evidence.** "I prefer" is fine. Label it as such.
