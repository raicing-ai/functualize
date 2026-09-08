# 08 — Extension Model & Upgrade Safety

> **Status: contract current, mechanism superseded.** Two-scale extension
> (project-local vs framework) is intact and realized in
> [`../10-extension-model.md`](../10-extension-model.md). The mechanism is
> subclassing plus module discovery (`[risekit] module_packages`, entry points,
> and a `ModulePreFilter` so a `modules/` directory works like `jobs/` does) —
> **not** schema merging, because there are no schema files to merge. Ledger row 5.

The closed vocabulary must not be a straitjacket. Projects need kinds and
interfaces the framework hasn't imagined (`pipeline`, `cron`, `health`,
`metrics`). The extension model exists to answer: **how does a project grow
the vocabulary without forking the framework, and without breaking on the
next framework upgrade?**

## The three-schema-file pattern

Every project carries three schema-related artifacts with strict ownership:

| Artifact | Owner | Replaced on upgrade? | Meaning |
|---|---|---|---|
| Base schema (snapshot) | framework | **yes** — overwritten | The vocabulary at the version the project was created |
| **Extensions file** | **user/project** | **never** — untouched | The project's local vocabulary additions |
| **Effective schema** | generated | regenerated on demand | Base + extensions, merged |

**Invariant — the upgrade boundary is the extensions file.** The framework may
freely replace anything it owns; it must never write to the extensions file.
Every design rule in this file serves that invariant.

## What can be extended

| Layer | Extensible per-project? | How |
|---|---|---|
| Kind | yes | add a name + contract (required capabilities/configuration/tags, allowed interfaces) to the extensions file |
| Interface | yes | add a name scoped to a kind + contract (required capabilities/configuration) |
| Variant | always — no schema involvement | pick any well-formed tag value; variants are open by design |

## The extensions file format (conceptual)

```
Extensions := {
  kinds:      [names…]                    # vocabulary additions
  interfaces: [names…]                    # vocabulary additions (scoped below)
  kindContracts: {
    "<kind>": {
      description:        text
      allowedInterfaces:  [names…]
      requiredCapabilities: [names…]
      requiredConfiguration: [names…]
      requiredTags:       [names…]
    }
  }
  interfaceContracts: {
    "<kind>": {
      "<interface>": {
        description: text
        requiredCapabilities: [names…]
        requiredConfiguration: [names…]
        # optional: variant templating hints — how concrete variants
        # derive their capability names (see below)
      }
    }
  }
}
```

## Adding a kind — the guided flow

```
$ <project> meta schema kind add -- pipeline "run,status,abort" "PIPELINE_NAME"
```

1. Validates the name against the vocabulary rules (lowercase, hyphens/
   underscores allowed, no spaces, no capitals).
2. Writes the name + contract into the extensions file.
3. Rebuilds the effective schema.

Idempotent: adding an existing name is a no-op, not an error.

## Adding an interface — the guided flow

Interfaces are kind-scoped, so adding one names its kind:

```
$ <project> meta schema interface add -- program health "start,stop,status" "HEALTH_URL"
```

1. Validates the name.
2. Records the interface **under its kind** in the extensions file.
3. Adds the interface to that kind's `allowedInterfaces` list (the two must
   stay consistent).
4. Rebuilds the effective schema.

## Variant templating for new interfaces

A newly added interface should support concrete variants with **zero further
schema work**, through a simple naming convention: a concrete variant appends
its name to each required capability — `health` with variant `http` yields
`health:check:http`, `health:status:http`.

The extension record may carry an optional templating hint capturing this
derivation (`{task}:{variant}`) so tooling can generate and check concrete
variant modules without hardcoding anything.

## Merging — building the effective schema

```
function build_effective_schema(base, extensions):
    if extensions is empty or absent:
        effective = base                       # no-op path
    else:
        effective = deep_copy(base)
        effective.kinds      += extensions.kinds
        effective.interfaces += extensions.interfaces
        effective.kindContracts.update(extensions.kindContracts)
        effective.interfaceContracts.update(extensions.interfaceContracts)
    write(effective)
```

Two validation duties:

1. **Validate the extensions file itself** against a meta-schema before
   merging (a malformed extension must fail the build loudly, not corrupt the
   effective schema).
2. **All validators consume the effective schema when present**, falling back
   to the base snapshot. One resolution rule everywhere — the effective schema
   is the single validation authority inside a project.

## Upgrade flow

```
$ <framework> upgrade              # 1. replace framework-owned files (base schema, schemas, templates, skills)
$ <project> meta schema build      # 2. per project: re-merge new base + preserved extensions
```

What survives, what refreshes:

| Artifact | After upgrade |
|---|---|
| Project's own modules | untouched |
| Extensions file | untouched — this is the promise |
| Base schema snapshot | replaced with the new version |
| Effective schema | regenerated from the pair |
| Framework layer's modules/utilities | refreshed from the bundle |

## Version pinning

A project may pin the framework version it was built against. Semantics:

- Validation selects the schema **for the pinned version**, so a framework
  upgrade cannot silently change what an old project validates.
- The pin is explicit and visible in the meta module.
- Unpinned projects follow the installed framework.

This is the answer to "how do upgrades never break old projects": old projects
validate against old contracts until a human deliberately moves them.

## The two-scale extension rule

| Where | Command surface | Effect |
|---|---|---|
| **Framework scale** (maintainer) | `schema kind add` / `schema interface add` in the canonical repo | ships to **all** users on next upgrade |
| **Project scale** (member) | `meta schema kind add` / `meta schema interface add` in the project | local to **one** project, forever |

The same vocabulary rules and the same contract shape apply at both scales —
only the blast radius differs. This symmetry is intentional: learning the
extension model once serves both personas.

## Naming rules for vocabulary additions

| Rule | Correct | Incorrect |
|---|---|---|
| Lowercase only | `pipeline` | `Pipeline` |
| Hyphens/underscores as separators | `data-pipeline`, `batch_job` | `dataPipeline` |
| No spaces | — | `my pipeline` |
| Dot notation reserved for variants | `health.http` (variant) | `health:http` in an interface list |

## Upgrade-safety checklist

- [ ] Framework upgrade overwrites only framework-owned files.
- [ ] Extensions file survives upgrades byte-for-byte.
- [ ] Effective schema rebuild is one command, idempotent.
- [ ] A malformed extensions file fails the rebuild loudly (never silently
      ignored, never merged half-way).
- [ ] Version-pinned projects keep validating against their pinned schema.
- [ ] Custom kinds/interfaces are accepted by all validators immediately after
      rebuild.
