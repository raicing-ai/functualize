# 01 — Vision

> **Status: carried forward — current.** The problem, the vision, the design
> philosophy and the non-goals are unchanged by v3 and still govern every
> decision in it. Nothing in this file is superseded.

## The problem

Every software project reinvents the same scaffolding. Developers write
near-identical commands for installing tools, building code, running tests,
starting services, backing up data — and every project does it slightly
differently. Worse, this knowledge is held by **AI coding agents** as much as
by humans: when an agent enters a new repository, it must rediscover how the
project works — by reading files, guessing conventions, asking the user.

Three concrete failures follow from this:

1. **No shared vocabulary.** Project A calls its setup command `setup`, project
   B calls it `bootstrap`, project C has no command and expects manual steps.
   A human or agent moving between projects must relearn everything.
2. **Improvements never propagate.** If someone invents a better way to
   install a tool safely, it lives in one project's files forever. There is no
   channel for good patterns to spread to other projects.
3. **No enforcement.** Even within one project, nothing stops a task from being
   written badly — mutating state on every run, missing a required sub-command,
   declaring behavior it doesn't actually provide. Errors surface at run time,
   in the worst case by corrupting the machine.

## The vision

**A shared, schema-backed framework that ships a consistent vocabulary of
self-describing task modules to every project.**

Every module declares *what it is* and *what it promises* up front, in a
standard machine-readable form. A validation pipeline rejects any module that
doesn't live up to its own declaration **before anything executes**. A bundled
registry of well-written tool installers means the framework, not each project,
owns the "how do I install X correctly and safely" knowledge. And because the
framework is shipped to every project and can be upgraded, improvements finally
propagate: fix the pattern once, every project receives it.

The core loop of the value proposition:

> **Scaffold → Validate → Upgrade.** A project starts from canonical
> templates; every module self-certifies against the canonical type system;
> when the framework improves, one command brings the project forward.

## Design philosophy

These principles are the soul of the framework. A re-implementation that loses
any of them is not Rise.

- **Schema as guardrails.** The canonical type system defines exactly which
  kinds of modules exist, which capabilities each requires, and which
  interfaces each may declare. Any agent or human authoring a module cannot
  produce an invalid structure — validation rejects it. Guardrails, not
  open-field freedom: the point is that *wrong* is unrepresentable.
- **Contracts as constraints.** A module declares its kind and interfaces up
  front; the diagnose-and-validate loop catches violations before execution.
  Declared promises are checked promises.
- **Idempotency as safety.** Every mutating operation checks current state
  before acting. Run install twice, stop twice, restore twice — nothing breaks.
  This single rule is what makes the framework safe for unattended agents and
  CI pipelines: an operation that is safe to run twice is safe to run always.
- **Variants as templates.** One abstract behavior ("install this CLI tool")
  has many concrete strategies (via a version manager, a package manager, a
  container). Each strategy is a rigid, well-formed template; the author fills
  in tool-specific details inside a predefined contract. Predictable output,
  no free-form drift.
- **Registry as discoverable surface.** The collection of tool strategies is
  itself just the framework's own module format — no custom index, no separate
  database. Listing what's available must show the whole API surface without
  reading every file.
- **Separation of what, how, and is.** What a module *is* (its kind), what it
  *promises* (its interfaces), and how it *actually works* (its concrete
  strategy) are three different concerns, stored in three different places,
  and never conflated.
- **Diagnosis as single source of truth.** One command reports the complete
  runtime truth about a module — installed or not, where, which version,
  which strategy, what it can do, whether it actually runs. All lifecycle
  operations consult this record; no other state check is authoritative.
- **Version anchoring.** Projects pin the framework version they were built
  against. Upgrades to the framework can therefore never silently change what
  a project validates.
- **AI agents are first-class users.** The framework ships instruction
  documents to agents at every level (framework maintainer, machine user,
  project team). The declaration block doubles as the prompt an agent needs to
  understand any module at a glance.
- **Self-description at every layer.** Everything — projects, individual
  modules, the registry, the framework itself — answers the same three
  questions in the same format: what are you, what do you promise, are you
  working?

## Three personas

The framework explicitly designs for three distinct roles. Every command,
every shipped instruction, every configuration location is organized by
persona.

| Persona | Who they are | What they do |
|---|---|---|
| **Framework maintainer** | Develops the framework itself | Owns the canonical type system, the registry, the templates, the tests. Extends the vocabulary; changes ship to everyone on next upgrade. |
| **Machine user** | Installs the framework on their machine | Scaffolds new projects, validates projects, manages a global tool collection, upgrades the framework. Runs everything through a single global entry point. |
| **Project member** | Works inside a generated project | Manages the local framework layer (validate everything, scaffold new resources, extend the type system locally) while the whole team runs day-to-day commands. |

The intent: each persona never needs to understand the other two. A project
member never edits canonical framework files; a framework maintainer never
touches a user's project extensions.

## Non-goals

Stating what the framework is **not** keeps the vision honest:

- **Not a package manager.** It organizes and executes install/uninstall/verify
  operations for tools; it delegates the actual fetching to existing package
  managers (pip, brew, nix, cargo, version managers, containers). It replaces
  the *knowledge* of how to install, not the *mechanism*.
- **Not a replacement for the underlying task runner.** It is a layer of
  structure, vocabulary, and validation on top of a generic task-runner
  substrate. The substrate provides execution; the framework provides
  meaning.
- **Not a monorepo manager, orchestrator, or deployment system.** A few
  resource kinds touch deployment (a service kind exists), but the framework
  describes and validates the *shape* of those concerns, it doesn't execute
  business logic.
- **Not opinionated about application code.** It says nothing about how the
  project's actual software is written — only about how the project's
  operational surface is organized.

## The three-context reality

The framework simultaneously exists in three places, which shapes every design
decision:

| Context | Example | Schema scope |
|---|---|---|
| **Framework development** | The canonical repository | The single source of truth |
| **The machine** | A global install directory | A local copy |
| **The project** | A hidden framework directory inside each project | A copy + local extensions |

A project is **self-contained and portable**: everything needed to validate
and operate it travels with the project. The machine-level install exists only
to scaffold and upgrade projects. The canonical repository exists only to
produce releases. Extension rules (file `08-extension-model.md`) exist
precisely because these three copies must never diverge dangerously.

## The "dogfooding" requirement

The canonical repository must itself be a valid project: it should use its own
templates, validate against its own schemas, and manage its own development
tools through its own registry. This is not vanity — it is the guarantee that
the framework's own surface is as well-formed as it demands every user project
be. A framework that cannot pass its own validation has no business
distributing it.
