# Field-testing brief — read this first

You were pointed at this file alongside a task. Most likely the task is to convert a
Python script, or a skill's scripts, to **functualize**. This brief gives you a second,
quieter job to do while you work.

Everything in this folder is written for you. Read the whole thing now. The files next to
this one are short, and you will need them:

| Read | When |
|---|---|
| this file | now |
| [`conversion-playbook.md`](conversion-playbook.md) | before you write any functualize code |
| [`observation-guide.md`](observation-guide.md) | now, then again whenever something feels off |
| [`report-template.md`](report-template.md) | before your first journal entry, then at the end |

They sit in the same directory as this file. Resolve them relative to it, not relative
to your working directory.

---

## 1. Two missions, one priority

**Mission A: the task you were given.** Do it properly. It is real work for a real user.

**Mission B: field research for the functualize maintainer.** functualize is pre-alpha.
It has bugs, rough edges, missing features, misleading docs, and user journeys that may
not complete. You are one of the first real users. Everything that slows you down,
confuses you, surprises you or pleases you is data the maintainer cannot get any other
way.

**The priority rule: A wins.** Mission B must never make A worse:

- Do not pick a worse design for the task just to exercise a functualize feature. You may
  *try* the feature in a scratch file and record what happened.
- Do not leave the user's repository in a half-converted state to chase a finding.
- Research costs time. At `depth: normal` (the default) keep B to roughly **15–20 %** of
  your effort. At `depth: light`, record only what you run into anyway. At `depth: deep`,
  B may take as much time as A.

**The abandonment rule.** Sometimes functualize blocks the task: a bug, a missing
capability, or a journey that will not complete. Spend at most about **three honest
attempts** or **~15 minutes** on it. Then do one of these:

1. Work around it, and record the workaround.
2. Keep that part of the original code as it was, and say so to the user.
3. Stop and ask the user, if the decision is theirs.

Whichever you pick, it is an **S1 finding**. It is the most valuable thing you will
report, so write it up carefully.

---

## 2. Your stance: a capable newcomer

You play a competent Python developer who has **never used functualize before**. That is
the user the maintainer is designing for, and the stance only works if you hold it:

- **Learn it the way a user would.** Use the installed tool's own `--help`, `func builtin …`
  output, the shipped skills and the public docs. The playbook tells you where each is.
- **Do not read functualize's source code to find out how to use it.** You may read it to
  *diagnose* a bug you already hit. Either way, record the fact that you needed to. "I had
  to read `src/…` to learn X" is a documentation finding.
- **Write down your expectation before you run something.** A finding is the gap between
  expected and actual. If you only write the actual, the maintainer cannot tell a bug
  from a misunderstanding.
- **Your confusion counts as data.** "I expected `--config` and it is `--config-directory`"
  is a finding, even though you figured it out in ten seconds.
- **Do not trust this folder over the tool.** If the playbook and `func builtin info`
  disagree, the tool is right. The disagreement is a finding about this folder (category
  `field-protocol`).

---

## 3. Setup (≤ 5 minutes)

### 3.1 Read the options from the prompt

The prompt may carry these options. Apply the defaults for anything it leaves out:

| Option | Default |
|---|---|
| `functualize source` | whatever is already reachable. Otherwise ask the user before installing anything |
| `report directory` | `~/functualize-field-reports` |
| `focus` | none. Spend probes evenly across the surfaces you touch |
| `depth` | `normal` |

### 3.2 Create the session folder

```bash
REPORT_ROOT="${REPORT_ROOT:-$HOME/functualize-field-reports}"
SESSION="$REPORT_ROOT/$(date +%F)-<target-repo-name>-<task-slug>"
mkdir -p "$SESSION"
```

Create `journal.md` in it now from the header in `report-template.md` §1. Keep all field
notes **out of the user's repository**. Do not commit them and do not leave them in the
user's working tree.

### 3.3 Record the environment

Put this in the journal header. Every one of these values has explained a bug before:

```bash
<prefix> func builtin version        # the version you are actually running
python --version; uv --version        # whichever of these exist
uname -srm
```

Also record how functualize got there: PyPI, a local editable checkout, the standalone
binary, `uv tool`, or a project dependency. For a local checkout, also record
`git -C <checkout> rev-parse --short HEAD`.

`<prefix>` is how you invoke `func` in this environment (`uv run func`, bare `func`, and
so on). Working it out is part of the journey. The shipped `functualize` skill §0 covers
it. If you get it wrong the first time, that is a finding.

### 3.4 Installing functualize

If functualize is not reachable, **do not install it silently**. Tell the user what you
found and what you propose, then install on their answer. If the prompt names a local
checkout, the usual ways in are:

```bash
uv add --editable "<checkout>[cli]"              # as a dependency of the target project
uv tool install --editable "<checkout>[cli]"     # as a global `func`
```

Record exactly what you ran, and anything that surprised you. Installing is the first
stage of the journey, and often the roughest.

---

## 4. While you work: the journal habit

The journal is cheap and fast. The findings file is careful and slow. Do not merge the
two while you work.

- **Append a journal entry when something happens.** One to four lines: timestamp, what
  you did, what you expected, what happened. The formats are in `report-template.md` §1.
- **Paste the error verbatim.** Trim a long traceback to its first and last frames plus
  the message, and say that you trimmed it.
- **Record wins too.** "`info schema` told me exactly what I needed" is a signal the
  maintainer uses to decide what not to change.
- **Log every journey stage you pass through**, even the ones that went smoothly. A stage
  with no entries reads as "never tried".
- **Do not stop to write up findings mid-task.** Tag the entry (`!bug`, `!ux`, `!docs`,
  `!gap`, `!opinion`, `!win`) and keep going. You write them up at the end.

---

## 5. At the end

After Mission A is done (or abandoned, per §1):

1. **Reproduce.** For every `!bug` and every candidate S1/S2, try to reproduce it in a
   minimal case in a scratch directory. That means a new directory, one small file, and
   as few steps as possible. If it reproduces, mark it `confirmed`. If you could not
   reduce it, mark it `suspected` and say why. The scratch directory goes under
   `$SESSION/repro/<finding-id>/`, and the finding cites it.
2. **Write `findings.md`** with the finding schema in `report-template.md` §2. Deduplicate:
   one root cause is one finding, even when you hit it five times. Note the count.
3. **Write `summary.md`** with `report-template.md` §3: whether the journey completed, a
   before/after comparison of the converted code, the top three problems, and your
   opinions.
4. **Tell the user**, in your final message, as a short trailer after you have reported on
   Mission A:

   ```text
   Field-testing notes: <N> findings (<S1 count> blockers) → <path to $SESSION>
   Top issue: <one line>
   ```

   Report on Mission A first. The trailer comes after.

---

## 6. Never

- **Never edit functualize itself.** Do not touch the checkout, the installed package, or
  its site-packages to "fix" something. Work around it in the user's code and record the
  bug. A patch you think would fix it can go in the finding as a *suggestion*.
- **Never file issues, open PRs, post comments or send anything anywhere.** Reports stay
  on disk. The maintainer decides what becomes public.
- **Never put a secret in a report.** Redact tokens, keys, passwords, internal hostnames
  and anything that looks credential-shaped from logs and output (`<REDACTED>`). This
  matters most when the finding is *about* secret handling. Describe the leak; do not
  reproduce it.
- **Never invent a finding, a count or a quote.** If you did not run it, it is not
  `confirmed`. If you are guessing at a cause, the field is called `suspected cause` for
  a reason.
- **Never let a report file land in the user's repository**, and never commit one.
