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
├── local/                  STAYS ON THIS MACHINE. May quote the target repository
│   ├── journal.md          raw, timestamped, written while working
│   └── summary.md          the one-page verdict: did the journey complete, top issues, opinions
└── upload/                 the ONLY folder that may be sent anywhere. No target-repo content
    ├── findings.md         one block per finding, structured, deduplicated
    └── repro/<id>/         one toy reproduction per confirmed finding, with a runnable run.sh
```

Reports are **deliberately kept out of this repository**. The journal quotes other
repositories' code, and reports are raw material rather than decisions. The report itself
never gets committed here. The two folders say what may leave the machine:

| Folder | Holds | May quote the target repo? | May be sent to the tracker? |
|---|---|---|---|
| `local/` | `journal.md`, `summary.md` | yes | **no, never** |
| `upload/` | `findings.md`, `repro/` | **no** (`AGENT_BRIEF.md` §6) | yes, the whole folder |

If a file is in `upload/`, a stranger can read it. If it might not be safe for that, it
belongs in `local/`. How `upload/` reaches the tracker (who sends it, and where) is the
ingest step below, not the agent's job while it works.

## From report to plan

A finding is a **claim from a newcomer who was told not to read the source**. It may be a
real defect, a misreading of what a feature is for, or a symptom of something else. It
does not go straight into the plan.

```
report on disk ──ingest──▶ Field Report in Jira (Reported) ──agent triage──▶ verdict comment (Triaged)
                                                                                    │
                ┌───────────────────────────── needs the maintainer ────────────────┤
                ▼                                                                   ▼
 discussion in the issue's comments                                          clear-cut defect
                │                                                                   │
                └──▶ Accepted → a linked Bug or Story │ Rejected │ Triaged + `deferred`
```

Every finding is ingested as a `Field Report`, whatever its type. A `Bug` or `Story` is a
**new ticket**, created only once triage has confirmed there is work to do, and the report
is linked to it.

The shared tracker is the Jira project for the repository, with the **Alignment Hub** in
the Functualize Confluence space (key `FUN`, under `00 — Start Here`) holding the rules:
what to check before planning, how triage works, how a report is ingested, the label
vocabulary and the mapping from `category` to the area of the code it touches. This
folder defines what a report looks like. The Hub defines what happens to it.

Ingest is done by the maintainer or an agent acting for them, never by the field-testing
agent, which still files and posts nothing. Ingest reads only `upload/`, names the session
by an opaque report key (never by its folder name, which carries the target repository's
name), and records the report key, the finding id and a content hash in each issue, so a
report is never ingested twice and the same finding in several reports is linked as a
duplicate, not counted twice.

## Local triage

Before ingesting, every finding carries an `id`, a `category`, a `severity` and a
`status` (`confirmed` / `suspected`). `status` says whether it **reproduces**, not
whether it is a defect. That makes a batch of reports easy to look through:

```bash
# Every blocker across all sessions
rg -l '^severity: S1' ~/functualize-field-reports/*/upload/findings.md
# Everything about discovery
rg -A3 '^category: discovery' ~/functualize-field-reports/*/upload/findings.md
```

When the same finding shows up in several reports, that is the priority signal. Agents
are told to reproduce a finding in a minimal case before marking it `confirmed`. A
`suspected` finding is a lead to chase, not a fact, and even a `confirmed` one is a
reproducible observation, not yet an agreed defect.

## What the agent is told not to do

It does not edit functualize, file issues, open PRs or post anything. It records, and
you decide. See `AGENT_BRIEF.md` §6.
