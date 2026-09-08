# 07 — Lifecycle & User Experience

> **Status: carried forward, plus one addition.** The three personas and the
> install → scaffold → daily → upgrade journey are realized in
> [`../09-surface-scaffold.md`](../09-surface-scaffold.md). The addition this file
> does not anticipate: the whole surface exists in **two deliveries** — as a
> `func` plugin and as a standalone `rise` CLI, from one object
> ([`../04-delivery.md`](../04-delivery.md)).

This file is the **user experience contract** — the complete journey of each
persona, and the exact command surface each expects. A re-implementation must
reproduce this experience; the internal structure behind it is free.

## The machine user's journey

### 1. One-line install

```
$ <installer one-liner>
```

Installs the framework to a config directory on the machine and wires a
global entry point so the framework's commands are reachable from anywhere.
The only hard dependency is the underlying task runner (v3 generation or
equivalent). Everything else the framework needs, it bootstraps itself.

Result:

```
<config-dir>/
├── (framework entry module)      # the global command surface
├── (metadata registry)           # vocabulary dictionary
├── (per-kind schemas)            # validation schemas
├── (registry/)                   # tool modules with routers
├── (templates/)                  # project + resource templates
└── (skills/)                     # instruction docs for AI agents
```

### 2. Scaffold a project — one command

```
$ <framework> init my-project     # from anywhere
```

Produces a complete, self-contained project:

```
my-project/
├── (root module)                 # kind: base — composes the subsystems
├── src/
│   └── (module)                  # kind: program — build, test, lint, run
├── deployments/
│   └── (module)                  # kind: service — up/down/status/logs
└── .<framework-dir>/
    ├── (meta module)             # kind: meta — local framework management
    ├── (schema copy)             # local snapshot of the vocabulary
    ├── (schema extensions)       # user-owned; never overwritten
    ├── (local registry)          # project-local tools
    ├── (templates)               # for scaffolding new resources
    ├── (skills/)                 # instruction docs for the project team
    └── logs/                     # audit log accumulates here
```

Adding the framework to an **existing** project is the same command run
inside it: the framework layer is added without touching the project's own
files.

### 3. Bootstrap project tools

```
$ <project> meta bootstrap        # install every tool the project registered
```

One command brings a fresh clone to a working state — the "clone → bootstrap →
work" loop is the framework's guarantee of project portability.

### 4. Daily work

Every project member speaks one consistent vocabulary:

```
$ <project> src build             # build
$ <project> src test              # test
$ <project> src dev               # dev server
$ <project> src lint / format / clean
$ <project> src invoke -- <args>  # run the app with arguments
$ <project> deploy up / down / status / logs   # services
```

The root command with no arguments prints a curated menu of top-level
commands — the project is self-documenting at the surface.

### 5. Validate

```
$ <project> validate              # root module: structure + diagnosis
$ <project> src validate          # per-subsystem, same check
$ <project> meta validate         # the framework layer validates itself
```

And the diagnostic:

```
$ <project> diagnose              # one JSON-lines record per module in the tree
```

### 6. Upgrade

```
$ <framework> upgrade             # pull the latest framework bundle
$ <project> meta schema build     # per project: re-merge new schema + local extensions
```

Projects pinned to a framework version keep validating against their pinned
schema; upgrading is an explicit, deliberate act.

## The project member's extension journey

Within a project (never touching the framework):

```
$ <project> meta scaffold program my-tool      # new tool module, correct by template
$ <project> meta scaffold service my-svc       # new service module
$ <project> meta scaffold registry my-reg      # new local registry branch
$ <project> meta scaffold host my-machine      # machine placeholder
```

Adding a tool to the **project registry** is a guided flow:

1. Scaffold the tool entry (router + chosen variants, pre-stubbed).
2. Fill the tool-specific bits: package name, probe commands, install command.
3. Register the entry in the project registry index.
4. `bootstrap` installs it; `diagnose` verifies it; `validate` certifies it.

And the framework's answer to "is my environment sane?":

```
$ <project> meta isolation check   # every program's isolation level, one report
$ <project> meta isolation logs    # the audit log, pretty-printed
```

## The framework maintainer's journey

The maintainer owns the vocabulary and the content:

```
$ build                          # package the release bundle
$ test                           # full suite: fast tier + isolated container tier
$ schema types                   # list the vocabulary
$ schema interfaces              # list interfaces and their kind scoping
$ schema type add -- <name>      # extend the vocabulary (ships on next upgrade)
$ schema interface add -- <kind> <name>   # add a kind-scoped interface
$ reg list / status / lock / audit          # registry management
$ reg scaffold item -- <name> <kind> <variants…>   # grow the registry
$ docs dev / build / preview     # the documentation site
```

The maintainer's changes reach users through exactly one channel: the release
bundle consumed by `upgrade`.

## Command-surface design rules

The experience above implies concrete naming rules; a re-implementation
should keep them because they are part of the vocabulary's predictability:

- **Namespaced families for grouping** (`output:config`, `output:logs`,
  `schema:type:add`, `test:fast` in the original framework — the separator
  there was a colon because the underlying task runner allows it; see
  file `02`). Group related operations under a stable prefix whatever
  separator the substrate offers; callers must be able to discover families.
- **One verb per operation**; every operation has a human-readable
  description (the listing is the primary documentation).
- **Wildcards only where delegation is uniform** (the registry dispatch);
  concrete surfaces stay explicit.
- **Default operation = "show me what you can do"** — every module is
  self-explaining at first contact.
- **Silent machinery, verbose outcomes**: internal plumbing (diagnosis
  assembly, logging) is quiet; user-facing results are clear and marked
  (success/failure glyphs, next-step hints).
- **Idempotent by default** (file `06`): the same command twice must be
  visibly harmless — "already installed", "already running", "no-op".

## Mental model the UX must teach

The framework's UX goal is that these facts become obvious:

1. Every module knows what it is — read its declaration.
2. Every module can prove itself — `validate`, `diagnose`.
3. Nothing dangerous happens without either confirmation or a log entry.
4. The project is complete on its own — the global install is only for
   scaffolding and upgrades.
5. Customization belongs in the project's extension file, never in framework
   files.

## UX acceptance checklist

- [ ] Fresh machine: install → scaffold → bootstrap → run dev — works with
      nothing pre-installed except the task runner.
- [ ] Cloned project: bootstrap → validate → work — no other setup.
- [ ] `diagnose` anywhere in the tree yields valid, schema-checkable records.
- [ ] `validate` catches a broken module *before* anything executes.
- [ ] Host-isolated install prompts; project-isolated install doesn't.
- [ ] Re-running any mutating command is visibly harmless.
- [ ] The audit log records every lifecycle event.
- [ ] Adding a tool to the registry is: scaffold → fill → register →
      bootstrap → verify.
- [ ] Adding a custom kind/interface to a project is: add → rebuild schema →
      validate.
