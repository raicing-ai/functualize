# Field testing — for the maintainer

functualize is pre-alpha. The fastest way to find out what is broken is to ask an agent
to do real work with it, somewhere else, and write down everything that got in the way.

This folder is a **protocol you attach to any prompt**. The agent still does the job you
gave it, such as "convert `scripts/sync_assets.py` to functualize" or "rewrite this skill's
scripts as jobs". While it works, it keeps a field journal. When it finishes, it turns
the journal into a structured report you can triage.

## Files

| File | Reader | Holds |
|---|---|---|
| [`AGENT_BRIEF.md`](AGENT_BRIEF.md) | the agent, **read first** | The two missions, the priority rule, setup, the journal habit, what it must never do |
| [`conversion-playbook.md`](conversion-playbook.md) | the agent | How to convert a Python script or a skill to functualize, and where to find the authoritative docs |
| [`observation-guide.md`](observation-guide.md) | the agent | What to watch for at each stage of the journey, cheap probes to run, and the categories and severity scale |
| [`report-template.md`](report-template.md) | the agent | The exact shape of the journal, the findings and the summary |

## How to use it in a prompt

Give the agent the **absolute path** of the brief. The agent will be working in a
different repository, so a relative path means nothing to it.

```text
Convert scripts/release_notes.py in this repo to a functualize job.

While doing it, follow the field-testing protocol in
/path/to/functualize/contributor/field-testing/AGENT_BRIEF.md
```

Optional knobs you can add to the prompt. The brief tells the agent what each one does:

```text
Field-testing options:
- functualize source: local checkout at <path>        # default: whatever is already installed, else PyPI
- report directory: ~/functualize-field-reports        # default shown
- focus: config and secrets                           # spend extra probes here
- depth: light                                         # light | normal (default) | deep
```

- **light**: journal only what the agent runs into. No extra probes. Use this when the
  original task is the priority and you just want to catch problems as they come.
- **normal**: journal, plus the cheap probes in `observation-guide.md` §3 for each surface
  the task touches.
- **deep**: also try the neighbouring surfaces the task did not need, such as the TUI, MCP,
  `--help` for every job, and non-TTY runs. Use this for dedicated dogfooding sessions.

## Where reports land

By default:

```
~/functualize-field-reports/<YYYY-MM-DD>-<target-repo>-<task-slug>/
├── journal.md      raw, timestamped, written while working
├── findings.md     one block per finding, structured, deduplicated
├── summary.md      the one-page verdict: did the journey complete, top issues, opinions
└── repro/<id>/     one toy reproduction per confirmed finding, with a runnable run.sh
```

Reports are **deliberately kept out of this repository**. The journal quotes other
repositories' code, and reports are raw material rather than decisions. The report itself
never gets committed here. `findings.md` and `repro/` are written to contain nothing from
the target repository (see `AGENT_BRIEF.md` §6), so they are the parts that can be
ingested into the shared tracker described below. The journal never is.

## From report to plan

A finding is a **claim from a newcomer who was told not to read the source**. It may be a
real defect, a misreading of what a feature is for, or a symptom of something else. It
does not go straight into the plan.

```
report on disk ──ingest──▶ ledger (REPORTED) ──agent triage──▶ verdict
                                                                  │
      ┌────────────── needs a human ──────────────────────────────┤
      ▼                                                           ▼
 discussion page (Confluence comments)                     clear-cut defect
      │                                                           │
      └──▶ RECONCILED: accepted → plan │ new decision │ rejected │ deferred
                                       │
                                       ▼
                          Jira issue under the Initiative's Epic
```

The shared tracker is the **Alignment Hub** in the Functualize Confluence space (key `FUN`),
under `00 — Start Here`. It holds the append-only ledger, the triage rules, the
discussion pages and the mapping from `category` to the area of the code it touches.
This folder defines what a report looks like. The Hub defines what happens to it.

Ingest is done by the maintainer or an agent acting for them, never by the field-testing
agent, which still files and posts nothing. Ingest gives each finding a global `FT-NNN`
ID and records which report and finding id it came from, so a report is never ingested
twice and the same finding in several reports is counted, not duplicated.

## Local triage

Before ingesting, every finding carries an `id`, a `category`, a `severity` and a
`status` (`confirmed` / `suspected`). `status` says whether it **reproduces**, not
whether it is a defect. That makes a batch of reports easy to look through:

```bash
# Every blocker across all sessions
rg -l '^severity: S1' ~/functualize-field-reports/*/findings.md
# Everything about discovery
rg -A3 '^category: discovery' ~/functualize-field-reports/*/findings.md
```

When the same finding shows up in several reports, that is the priority signal. Agents
are told to reproduce a finding in a minimal case before marking it `confirmed`. A
`suspected` finding is a lead to chase, not a fact, and even a `confirmed` one is a
reproducible observation, not yet an agreed defect.

## What the agent is told not to do

It does not edit functualize, file issues, open PRs or post anything. It records, and
you decide. See `AGENT_BRIEF.md` §6.
