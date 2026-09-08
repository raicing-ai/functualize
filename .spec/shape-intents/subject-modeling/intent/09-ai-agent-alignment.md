# 09 — AI Agent Alignment

> **Status: carried forward and substantially expanded.** The agent-first
> premise is intact. v3 goes considerably further than this file: see
> [`../15-scrill.md`](../15-scrill.md) (a job that ships its skill; a skill that
> fires on state rather than on similarity) and
> [`../16-skill-to-workflow.md`](../16-skill-to-workflow.md) (prose procedure
> compiled to a gated `@workflow`). Read those two as this file's real
> continuation.

A defining, non-optional property of the framework: **AI coding agents are
first-class users**, not an afterthought. The framework ships instruction
documents to agents at every level, and its data formats are designed so an
agent can understand any module *by reading, without executing*.

## The premise

Agents cannot be trusted to remember anything across sessions. The framework
therefore puts **all operational knowledge in files the agent reads**:

- The declaration block tells an agent what a module is and promises.
- The schema tells an agent what is and isn't representable.
- The diagnosis record tells an agent the runtime truth.
- The audit log tells an agent what was done.
- The shipped instruction docs tell an agent *how to behave* at its level.

Documentation is the primary communication mechanism between agents working on
the same project — agents read docs, not chat history. (Architectural
decisions are therefore recorded as persistent decision records with context
→ decision → consequences, so later agents inherit the reasoning.)

## Instruction docs per persona

Each of the three personas receives its own instruction document, shipped
with the framework and refreshed on upgrade:

| Persona | Receives | Covers |
|---|---|---|
| Framework maintainer | repository-level agent docs | vocabulary extension, module authoring, consistency rules, repo navigation |
| Machine user | docs installed with the global framework | scaffolding, project lifecycle, upgrade, the command surface |
| Project member | docs shipped inside every project | contracts, validation, adding tools, extending the vocabulary, mental-model traps |

The project member's docs additionally include **reference tables** an agent
can consult rather than guess from: one covering installer strategies (each
with detection command, install command, remove command, platforms, idempotent
pattern), one covering daemon strategies (start/stop/status/logs, restart
behavior, platform constraints, configuration-file shape). These references
exist so an agent generating a new variant module produces *correct* strategy
code instead of plausible-but-wrong shell.

## Contracts as prompts

The declaration contract doubles as the prompt an agent needs to work on any
module:

- KIND + INTERFACES + TAGS is the complete "what is this and what must it
  do" in three lines.
- The interface contract (required capabilities + configuration) is the
  checklist for generating or repairing a module.
- The validation pipeline is the agent's feedback loop: generate → validate →
  read the rejection → fix. No human in the loop required.

The framework explicitly wants agents to *generate* module files: rigid
templates with placeholder markers ("set the package name here", "replace with
the importable name") make generated output correct-by-shape, and validation
catches the rest.

## Read-don't-execute safety

Everything an agent needs to decide safely is readable:

- **Risk profile of a tool**: read its declaration — the isolation tag states
  whether operating it is dangerous.
- **Current state of a tool**: read the diagnosis record — installed or not,
  where, which variant, verified or not.
- **What was done**: filter the audit log.
- **What's valid**: run validate (a pure check) — or read the schema.

An agent should never need to *run* a tool to learn whether it may safely
manage it.

## Idempotency as agent permission

The idempotency rule (file `06`) is what makes agent-automation safe: an
operation that is safe to run twice is safe for an agent to run *always*.
Without this property, agents would need state-tracking and confirmations at
every step; with it, they may act. The framework's design statement is:
**agents may act freely precisely because every operation is idempotent and
every dangerous operation gates itself.**

## The agent-facing mental-model traps

The instruction docs explicitly call out wrong assumptions agents tend to make.
A re-implementation should ship equivalents:

| Wrong assumption | Correct understanding |
|---|---|
| "I set the interface to `program.mise`" | Interface lists hold abstract names only; strategies are tags. Programs typically have an empty interface list (plus `daemon` if they daemonize). |
| "I must re-validate after any change" | Validation matters when the *declaration* changes; day-to-day work uses the module's own operations. |
| "I edit the project's schema copy to add a kind" | Edit the extensions file instead — it survives upgrades. Then rebuild the effective schema. |
| "The project registry replaces the framework registry" | They are distinct surfaces: framework registry for framework tools, project registry for project tools. |
| "`diagnose` debugs my code" | `diagnose` reports installation state and runtime capabilities — run it when a tool isn't working. |
| "I can hardcode my own state checks" | Install/verify logic must consult the diagnosis record — one source of truth. |

## Vocabulary discoverability for agents

Agents (and humans) discover the full operational surface without reading
every file:

- Listing a module shows its capabilities — the description field on every
  operation is the documentation.
- The registry listing shows every tool and its install status.
- Schema listing commands enumerate the vocabulary (kinds, interfaces with
  their kind scoping).
- The diagnosis walk emits the whole tree's truth in one stream.

## What the agent-alignment requirements imply for a re-implementation

1. Ship instruction documents with the framework, per persona, refreshed on
   upgrade.
2. Keep declaration, diagnosis, and log formats machine-readable and
   self-describing.
3. Maintain strategy reference tables for installers and daemonizers.
4. Keep every dangerous operation gated by its own confirmation; keep every
   other operation idempotent.
5. Make validation the feedback loop for generated code: generate → validate →
   fix.
6. Record architectural decisions persistently, with context and
   consequences, so later agents inherit rationale.
