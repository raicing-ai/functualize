# 05 — Registry & Smart Variant Routing

> **Status: contract current, mechanism narrowed.** Router, variants and the
> lockfile are intact and realized in
> [`../06-registry-variants.md`](../06-registry-variants.md). One change worth
> knowing: install-mode detection and package-install planning are no longer
> rise's to implement — they delegate to functualize's public
> `functualize.app.packaging` (upstream ask 5, landed), so the two cannot drift
> on what "how was this installed?" means. v3 also makes **repositories**
> first-class registry subjects, which this file has no slot for.

## The registry concept

The registry is the framework's answer to "how do I install tool X correctly?"
— a bundled collection of tool modules, organized by **tool name → concrete
strategy (variant)**.

**The registry is nothing special.** It is a module of kind `registry` — the
same module format as everything else, with the same declaration, the same
universal vocabulary. There is no custom index format, no separate database,
no sync protocol. The registry's structure *is* its index: directories per
tool, one module per variant under each tool. Any module can include the
registry; listing the registry's surface is the same operation as listing any
module.

## Two-level hierarchy

```
registry/
├── (registry module — kind: registry)
├── tool-A/
│   ├── (router module — kind: registry)
│   ├── variant-1/ (module: kind program, tag variant = "variant-1")
│   ├── variant-2/ (module: kind program, tag variant = "variant-2")
│   └── …
├── tool-B/
│   ├── (router module)
│   └── …
└── library-X/            # libraries form their own branch
    ├── (router module)
    └── variant/…
```

- Each variant module is a fully self-describing module: its own declaration
  (kind `program` or `library`), its own tag carrying the variant name, its
  own install/uninstall/verify capabilities, idempotent by construction.
- The variant name doubles as the module's namespace and as its `variant` tag.

## The registry is not a package manager

A deliberate positioning:

- It **organizes knowledge** about how to install, configure, verify, and
  remove tools consistently across strategies.
- It **delegates the actual fetching** to existing package managers (pip,
  brew, nix, cargo, version managers, distro package tools) — never replaces
  them.
- It **provides a uniform command surface** regardless of strategy:
  `install` means the same thing whether the variant is brew or a version
  manager.

## Why routers exist — the problem

Without a router, using the registry requires *knowing the variant*:
"install jsonschema via pip" demands the user remember pip is the strategy.
Two failures:

1. **Bad UX.** Users don't want to know; agents shouldn't have to know.
2. **Namespace explosion.** Exposing every variant of every tool as a
   top-level name floods the command listing with hundreds of entries nobody
   calls directly.

## The smart router

Each tool gets a **router module** alongside its variant modules. The router
exposes the clean surface (`install`, `uninstall`, `test`, `lock`, `invoke`)
and internally **auto-detects the best variant**, remembering the decision in
a **lockfile**.

### Detection — priority arrays

The router declares two ordered preference lists:

```
host_variants:    [brew, pip]          # machine-level strategies, checked first
project_variants: [mise, nix]          # project-scoped strategies, checked second
```

**Algorithm:**

```
function find_variant(tool):
    if lockfile exists and lockfile.chosen_by == "user":
        return lockfile.selected             # honor explicit user choice forever
    if tool already installed and lockfile consistent:
        return lockfile.selected             # reuse the recorded decision
    for variant in host_variants + project_variants:
        if availability_check(variant.package_manager) is present:
            selected = variant
            write_lockfile(selected, chosen_by: "auto")
            return selected
    fail("no known strategy available for this tool on this machine")
```

`availability_check` answers one question: "is this variant's package manager
present on this machine?" (on the path / in the language environment). The
**first available wins** — host strategies before project strategies, because
host tools are already globally usable.

### The install pipeline

The router's `install` runs a fixed sequence of internal steps:

```
install → 1. overwrite guard (see file 06)
          2. already-installed check (lockfile + runtime truth agree? skip)
          3. find variant (above)
          4. install via the chosen variant, then record reality in lockfile
```

Idempotency falls out: the second run finds step 2 satisfied and exits
without touching anything.

### Explicit selection still works

Users may bypass detection with an explicit variant: `install:brew`,
`install:mise`. The router then records the choice **as a user decision**, and
all future automatic runs respect it (never re-detect over a user's explicit
choice).

### Wildcard delegation for clean namespaces

The registry index does **not** include every tool router as a named
namespace. Instead it exposes a **wildcard surface**: a fixed set of patterns
that dispatch `<tool>:<action>` and `<tool>:<action>:<variant>` calls to the
right router module by looking up the tool directory. Effect:

- The command listing stays **fixed-size** — a handful of wildcard entries and
  a few registry-level operations — no matter how many tools exist.
- The full tool-first syntax still works: `registry:tool:install`,
  `registry:tool:install:brew`.

```
on call "<tool>:<action>":     dispatch action to tool router directory
on call "<tool>:<action>:<sub>": dispatch "<action>:<sub>" to tool router
```

### Registry-level operations

| Operation | Purpose |
|---|---|
| `list` | Enumerate entries with install status (filterable) |
| `status` | Per-tool: on path? lockfile state? installed? |
| `lock` | Aggregate all tools' lockfiles into one report |
| `audit` | Run validation against every entry, report pass/fail |
| `bootstrap` | Install the registry's own prerequisites (the validator and parser libraries it needs) |
| `scaffold` | Generate a new tool entry (router + variant skeletons) from templates |

## The lockfile contract

One lockfile per tool, living in the tool's directory, recording:

```
Lockfile := {
  format_version:  1
  tool:            name
  selected_variant: string
  isolation:       host | project | process
  resolved_at:     ISO timestamp
  resolved_by:     "auto" | "user"
  user_choice:     string | null          # the variant the user explicitly picked
  installed: {
    status:        bool
    version:       string | null
    path:          string | null
    installed_at:  ISO timestamp | null
  }
}
```

Lifecycle rules:

| Trigger | Effect |
|---|---|
| Auto-detected install | written with `resolved_by: auto` |
| Explicit `install:<variant>` | written with `resolved_by: user`, `user_choice` set |
| `uninstall` | status → false, version/path/timestamp cleared |
| Outside-the-router changes | lockfile can go stale; the consistency check (runtime truth vs lockfile) detects this and re-detects |

The lockfile is simultaneously a **cache** (don't re-detect), an **audit
trail** (who chose what, when), and an **idempotency anchor** (skip if
consistent).

The lockfile is **vendor-level state, not user configuration**: it may be
discarded and re-derived at any time. Clearing it only costs one re-detection.

## The library router

Libraries use the identical router contract with one difference: existence
checks and installation use **language-level import/package-manager
semantics** instead of path lookup (see the library diagnosis contract in
file `04`). Priority example for Python libraries: fastest project-scoped
manager → full project manager → universal fallback.

## Scaffolding new registry entries

New tools join the registry through a scaffold operation:

```
scaffold_item(name, kind, variants…):
    create router module from router template (substitute name/domain)
    for each variant: create variant module from that variant's template
    report next steps: fill placeholders, register, validate
```

The templates are rigid (kind-correct declarations, required capabilities
pre-stubbed, TODO markers where tool-specific knowledge goes), so a generated
entry is **closer to valid than to invalid** — the author's remaining work is
small and guided. Unsupported variant names are skipped with a warning, not
fatal.

## Consuming the registry

A project includes the registry **optionally**, under two namespaces — one for
the machine-global registry, one for the project-local copy:

- **Optional include** → the project remains fully functional when the
  registry is absent (graceful degradation; only tool commands disappear).
- **Two namespaces** → project-local tools can shadow or coexist with global
  tools, and the project stays self-contained on machines without the global
  install.

## Why this design matters

The router + lockfile combination is the framework's answer to the
"deterministic environments without ceremony" problem: one word (`install`)
is enough on any machine, the outcome is recorded and auditable, the choice is
repeatable, and expertise (which strategy is sane for this tool) lives in the
registry instead of in every user's head.
