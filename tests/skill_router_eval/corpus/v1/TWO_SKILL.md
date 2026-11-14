# Requests that need two skills — corpus v1

The label set in `scenarios.jsonl` is single-skill: the router answers with one
option or `none`. A request whose honest answer is two of them would measure
the question instead of the router, so it is not labelled — see `LABELING.md`
§7, which this file exists to satisfy.

Each entry below is a real request shape, the two options it needs, and why no
single label is honest. None of them appears in `scenarios.jsonl`, and none may
be squeezed into one label by any reading of the rubric.

### a capability and the skill that documents it

**Request:** "add a Metrics capability to functualize next to Log and Invoke,
then write the SKILL.md our team will use to find it"

**Needs:** `functualize` + `functualize-skill`

**Why not one:** the source change is §1 work on the RunContext, and the
artifact the user also asks for is a §4 skill. Answering with the capability
alone leaves the skill unwritten; answering with the skill alone leaves the
capability missing.

### the tool is missing, and the app is what calls it

**Request:** "the deploy CLI dies in CI with `func: command not found`, and the
entrypoint also passes `--env` twice. which of these do I fix first?"

**Needs:** `functualize-cli` + `functualize-app`

**Why not one:** the first half is §3's subject — the tool, PATH and the image —
and the second half is §2's, the program's own argument wiring. §6.1 would take
the whole request if it were only about the missing binary; it is not.

### publish the skill, and fix the job it documents

**Request:** "our SKILL.md points at `jobs/rotate.py`, whose secret handling is
wrong — fix the job and then publish the skill so the other teams get the
corrected version"

**Needs:** `functualize` + `functualize-skill`

**Why not one:** the edit is §1 (credential and config handling in a job) and
the distribution question is §4 (repo, marketplace or skills CLI). §6.2 keeps
the job but says nothing about publishing, and §6.4 keeps the skill but cannot
fix the job.

### scaffold the program and install the tool into it

**Request:** "start a new functualize project for our billing reconciliation
and make sure `func` is installed and pinned inside its environment"

**Needs:** `functualize-app` + `functualize-cli`

**Why not one:** §2 owns the scaffold and §3 owns installing and pinning the
tool. §6.1 only claims a request whose subject is the tool itself; this one
starts from the program.

## What happens to these at measurement time

Nothing. They are listed here so a reader can see the failure mode the corpus is
not measuring, and so a future version can decide whether the router should
learn to answer two skills. Corpus v1 keeps the single-label question.
