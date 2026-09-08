# 02 — Core Concepts

> **Status: partly superseded.** The mental model stands; its *vocabulary* does
> not. The declaration triple (KIND / INTERFACES / TAGS) is replaced by the
> three axes — substrate / action / target — in [`../01-vocabulary.md`](../01-vocabulary.md).
> The invariant this file exists to protect ("strategy is a tag, never an
> interface") survives verbatim: v3 enforces it by there being no strategy
> Protocol to import. See the divergence ledger in [`README.md`](README.md), rows 1, 3, 6.

This file defines the vocabulary and mental model everything else builds on.

## The task module

The atomic unit of composition is a **task module**: a single file that
declares what it is, what it promises, and what operations it exposes. A
project is a small tree of modules; the registry is a collection of modules;
the framework itself is described by modules.

A module has exactly three parts:

1. **A declaration** — the machine-readable identity block (see below).
2. **A capability surface** — named operations ("tasks") that do things: run
   the tool, install it, start it, validate it.
3. **Includes** — references to other modules it composes, each under a
   namespace, so capabilities from many modules coexist without collision.

### The declaration triple

Every module begins with a declaration block carrying three fields:

| Field | Meaning | Nature |
|---|---|---|
| **KIND** | What this module *is* — one of a fixed vocabulary (see `03-type-system.md`) | Closed enum |
| **INTERFACES** | Which *behavioral contracts* it fulfills — abstract names only | Closed enum, scoped per kind |
| **TAGS** | Free-form metadata (name, strategy, isolation, runtime…) | Open key/value bag |

**Invariant — the three are different concerns and must never be merged:**

- KIND says what it is.
- INTERFACES say what it promises to *do*.
- TAGS say *how* it does it (which concrete strategy/implementation).

The most important corollary: **the concrete implementation strategy is a tag,
never an interface.** An interface is abstract ("daemonizes"); the strategy is
concrete ("via the system service manager"). An interface list must never
contain strategy names.

### Capability names

Capabilities are organized in **namespaced families**: operations that report
state group under one prefix, lifecycle operations under another. Examples
from the original framework: `install`, `uninstall`, `start`, `stop`,
`output:config`, `output:logs` — everything under `output:` reports state, so
callers can discover a family from its prefix.

**The separator character is an accident of the substrate, not part of the
intent.** The original framework spells these names with a colon
(`output:config`) for one reason only: the underlying task runner
(taskfile.dev) allows colons in task names, so the colon was the cheapest
legal separator available there. No deeper meaning is attached to it.

A re-implementation in a different substrate should pick whatever grouping
mechanism that substrate offers naturally, mapping the same semantic names:

- a command-line tool with subcommands could render the same capability as
  `acli output` with a `--config` flag — i.e. `acli output --config`;
- a package-manager-style CLI could use dot- or slash-separated names;
- a service API could use path segments (`/output/config`).

What survives any substrate change:

- **The grouping intent** — state-reporting capabilities stay a discoverable
  family; the family prefixes are stable.
- **The semantic names** — the *words* a contract pins ("config", "logs",
  "start", "status") are the contract; only the separator/flag/segment
  spelling follows the substrate.
- **Stability within an implementation** — every capability's spelling is
  fixed, documented, and enforced by the schema; interface contracts pin the
  exact set of capabilities a claimer must expose, spelled in that
  implementation's own convention.

## The universal module vocabulary

Every module, regardless of kind, exposes a minimal vocabulary:

- A **default** operation — "show me what you can do."
- A **diagnose** operation — "emit your declaration and runtime truth as one
  machine-readable record."
- A **validate** operation — "check yourself against the canonical schema and
  fail if you don't conform."

Because every module speaks this vocabulary, tooling can walk any module tree
generically: validate everything, diagnose everything, audit everything.

## Diagnosis — the self-description in action

`diagnose` produces **one line of machine-readable output** (JSON-objects-per-
line) per module, containing at minimum:

- The declaration fields (kind, interfaces, tags);
- A fixed status field with the literal value `"N/A"` — whose meaning is
  "the meaningful status lives in the runtime block below; this record is
  structurally valid";
- For kinds that have runtime state, a **diagnosis block**: where the thing is,
  its version, whether it's installed, whether it runs correctly, what
  operations are possible.

Design intent of the format:

- **Streamable**: many modules → many lines; each line independent.
- **Grep-friendly**: audit by filtering lines.
- **Self-validating**: the record is itself checked against a schema (file
  `04-validation-and-diagnosis.md`).
- **Single source of truth**: install/uninstall/verify operations delegate
  their state checks to diagnose rather than re-deriving state.

## Composing modules

A module composes others through namespaced includes. The rules:

- Include is **optional-friendly**: a module may declare a dependency on
  another module that may not exist yet (e.g. an uninstalled registry); the
  host module still works. This is *graceful degradation*: core capabilities
  function without the optional surface.
- Composition is **transitive**: the root module includes subsystems, each of
  which includes its own. A diagnosis walk recurses through the whole tree and
  emits one record per node.
- Namespaces prevent collisions: two included modules can both define an
  operation called `install`; callers address them as `namespace:install`.

## The framework triangle

The same three-part shape recurs at three scales:

| Scale | Identity (kind) | Promises (interfaces) | Strategy (tags) |
|---|---|---|---|
| A tool | "program" | (a daemon contract, or none) | installed via version manager |
| A project subsystem | "program" / "service" | source-control contract, backup contract… | docker, systemd… |
| The registry | "registry" | (none) | bundled with the framework |

## What "self-contained project" means

A project created by the framework carries **everything it needs to validate
and operate itself**: its copy of the schema, its templates for adding new
modules, its local registry, its audit log location, and its instruction
documents. The machine-level framework is only needed to *create* the project
and to *upgrade* it. The project must remain valid if the global install is
absent.

## Glossary

| Term | Meaning |
|---|---|
| **Module** | One self-describing file with a declaration, capabilities, and includes |
| **KIND** | What a module is; closed vocabulary |
| **Interface** | An abstract behavioral contract; a module claims it, the schema enforces it |
| **Tag** | Open metadata, including the concrete implementation strategy |
| **Variant** | One concrete strategy for an abstract behavior, implemented as its own module under the behavior's namespace (e.g. a brew-installer module beside a version-manager module) |
| **Diagnosis** | The single machine-readable truth record emitted by diagnose |
| **Registry** | A module that aggregates tool modules |
| **Router** | A tool module that auto-picks the best variant (see file 05) |
| **Lockfile** | The persistent record of a router's decision |
| **Isolation** | Where an installation lives: machine-wide, project-scoped, or process-scoped |
| **Effective schema** | Canonical schema merged with a project's local extensions |
