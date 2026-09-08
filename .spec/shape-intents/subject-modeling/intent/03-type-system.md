# 03 — The Type System

> **Status: superseded by [`../01-vocabulary.md`](../01-vocabulary.md).** This is the
> eight-kind / five-interface vocabulary. v3 replaced it with three axes: 8
> substrates, 7 action Protocols, and a target. The eight kinds survive as
> **presets** (`../01-vocabulary.md` §7) and existing modules keep their
> spelling, so this file still reads as true at the surface — but it is no
> longer the definition, and two names changed: `invoke` → **`run`**, and
> `continuous-integration` was dropped. Read `../01-vocabulary.md` first; use
> this file only to see what the presets came from. Ledger rows 1–4.

The type system is the framework's single most valuable artifact: a fixed
vocabulary of **kinds** and **interfaces**, each with a precise contract. It
turns "this module promises X" from prose into a checkable statement.

## The eight kinds

| Kind | What it is | Required capabilities (beyond the universal vocabulary) | Required configuration | May claim interfaces |
|---|---|---|---|---|
| `base` | The minimal foundation every module extends | — | — | none |
| `meta` | Framework orchestration: bootstrap the toolchain, manage the local framework layer | `bootstrap` (set up the local framework directory) | optional framework-version pin | none |
| `program` | A CLI tool invocable with arguments | `invoke` (run with args), `install`, `uninstall`, `test`, `output:config`, `output:config_dir` | `CONFIG_DIR`, `CONFIG_FILE`; tag `isolation` (required) | `daemon` (+ service contracts when it also acts like one) |
| `library` | An importable language package (not runnable from the shell) | `install`, `uninstall`, `output:version`, `test` | `PACKAGE_NAME`, `PACKAGE_VERSION`; tags `language`, `package-manager` | `version` |
| `service` | A managed long-running service | `test`, `start`, `stop`, `restart`, `status` | `SERVICE_NAME` | `git`, `backup`, `version` |
| `host` | A physical or virtual machine (placeholder for future machine management) | — | — | none |
| `registry` | An aggregator bundling tool modules as includes | `bootstrap` (install the registry's prerequisites) | — | none |
| `workflow` | A CI/CD pipeline definition | — | — | `continuous-integration` |

Intent behind the distinctions:

- `program` vs `library`: the decisive difference is **how existence is
  detected**. A program is found on the executable path; a library is found by
  importing it in its language. They therefore have different diagnosis
  shapes, different required tags, and different capability surfaces. They
  must never be merged: a library is not a daemon, not a service, not directly
  runnable.
- `service` owns *operational* lifecycle (start/stop/restart/status) plus
  *operational* contracts (source control, backup, version). A service can be
  backed by a container, a process supervisor, or plain scripts — that is a
  strategy, recorded as a tag.
- `host` is intentionally a placeholder. Its presence in the vocabulary
  declares that machine-level management belongs in the same uniform model;
  its emptiness says it's not built yet.
- `meta` is the framework's own presence inside a project: the operations that
  extend, validate, and upgrade the framework layer.

## The five interfaces

Interfaces are **abstract behavioral contracts** with exact required
capabilities and configuration. Claiming one is a promise; the schema enforces
it.

| Interface | Scoped to kind | Required capabilities | Required configuration | Meaning |
|---|---|---|---|---|
| `daemon` | `program` | `start`, `stop`, `restart`, `status`, `output:logs` | pid-file path, log-file path | "I can run as a background process" |
| `git` | `service` (and `program`) | `clone`, `pull`, `push` | repo directory, repo URL | "My lifecycle is under source control" |
| `backup` | `service` (and `program`) | `backup`, `restore` | source/target dirs for data and for config | "My state can be saved and restored" |
| `version` | `service`, `library` | `update` | current version | "I can be updated" |
| `continuous-integration` | `workflow` | `build`, `test`, `lint`, `deploy`, `clean`, `dev` | — | "I define a CI/CD pipeline" |

### Interface scoping

An interface's identity is the **pair (kind, name)** — `daemon` on `program` is
a different contract from any hypothetical `daemon` elsewhere. The schema
enforces scoping in both validation directions: a `service` claiming `daemon`
is rejected; a `program` claiming `git` is allowed only where the schema
defines that pair.

### What is NOT an interface

Two classic mistakes the vocabulary is designed to prevent:

1. **"program" and "service" are kinds, not interfaces.** A program's required
   capabilities are enforced by its kind, not by claiming a `program`
   interface. Programs therefore declare an **empty interface list** by
   default (plus `daemon` if they daemonize).
2. **Strategy names are not interfaces.** `pip`, `brew`, `mise`, `systemd`,
   `docker` are *variants* — concrete implementation strategies. They live in
   tags (and in a naming pattern for variant sub-names), never in interface
   lists.

## The three-layer vocabulary

The complete classification model, in increasing concreteness:

| Layer | Question answered | Where declared | Extensible by |
|---|---|---|---|
| **KIND** | What is it? | The declaration block | Schema extension |
| **Interface** | What does it promise to do? | The declaration block | Schema extension |
| **Variant** | Which concrete strategy implements it? | A tag (`variant` key) | Anyone, freely — open value |

### Variant naming

Concrete variants are organized as **one module per strategy** under the
abstract behavior's directory: a tool "mise" installed via its version
manager lives in its own module beside the brew-based one; a service
daemonized via systemd in its own module beside the container-based one. The
strategy identity is the module's placement (its namespace) plus its
`variant` tag, not a naming pattern baked into capability names. Rules:

- The variant name is lowercase, alphanumeric plus `-`/`_`, never empty.
- Adding a new variant **never requires a schema change** — any well-formed
  variant module is accepted. This is deliberate: the framework cannot predict
  every package manager, so the vocabulary stays open at the concrete layer
  while closed at the abstract layers.

### Typical variant families

| Behavior | Common variants |
|---|---|
| CLI tool installation | version manager, brew, nix, cargo, pip, distro-native, custom |
| Daemonization | system service manager, lightweight supervisor, container, custom |
| Language library installation | pip, uv, poetry, cargo, custom |
| CI pipeline | github, gitlab |

## The declaration record (pseudocode)

```
Module := {
  declaration: {
    kind:       one of <closed enum of 8 kinds>
    interfaces: list of <closed enum of 5 names, scoped to kind>
    tags:       map<string,string>          # open; key "variant" holds strategy
  }
  capabilities: map<name, operation>       # must cover the kind's required set
                                            # and each claimed interface's required set
  includes:     map<namespace, moduleRef>   # optional-friendly
}
```

## Required-capability table as pseudo-schema

The framework must express these constraints as **machine-checkable
declarations** (one contract definition per kind, one per (kind, interface)
pair), each stating:

```
KindContract := {
  requiredCapabilities: [names…]      # e.g. program: invoke, install, …
  requiredConfiguration: [names…]      # e.g. program: CONFIG_DIR, CONFIG_FILE
  requiredTags: [names…]              # e.g. program: isolation
  allowedInterfaces: [names…]         # e.g. service: git, backup, version
  diagnosisShape: <which runtime block is required, if any>
}
```

Validation logic is derived from these definitions, not hardcoded per kind.
This single-source-of-truth design is what makes "add a new kind" a one-line
vocabulary change rather than an implementation surgery.

## Why closed at the top, open at the bottom

- **Closed kinds/interfaces** → every module means the same thing to every
  reader (human or agent); wrong is unrepresentable; tooling stays simple.
- **Open tags/variants** → the framework doesn't pretend to know every tool
  ecosystem; new strategies appear without ceremonies.

## Extension without dilution

The closed vocabulary is not a straitjacket: projects extend it **locally**
(see file `08-extension-model.md`). The canonical vocabulary grows only by
maintainer decision and ships via framework upgrades; project-local additions
never pollute the shared meaning.
