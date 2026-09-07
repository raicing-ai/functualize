# Spec: One rule for two functions claiming one job name

**Closes `.spec/STATUS.md` #32, and the same-name-in-two-modules half found while
verifying it.** Unblocks `eager-boot-provider`, which cannot route the eager
branch through the provider while the eager registry is the only place a
collision is caught.

Every measurement below was taken against `78d9ff4` (master, post-#29), not
carried over from the authoring note.

## Problem

Job names are canonicalized to lowercase-hyphenated form, so two distinct
functions can resolve to one job address. There are two shapes, and the
registration path every `func` invocation uses drops a job silently for both.

```python
# wheels.py — shape A: normalization collision
def build_wheel() -> None: ...      # -> build-wheel
def buildWheel() -> None: ...       # -> build-wheel

# a.py / b.py — shape B: same spelling, two modules
def build_wheel() -> None: ...      # -> build-wheel   (both files)
```

Measured, cold, on master:

| Shape | default path (`lazy=True`, all CLI) | eager path (`lazy=False`) |
|---|---|---|
| A | `['build-wheel']`, no message, `discovery_failures: []` | `ValueError` at construction |
| B | `['build-wheel']` (from `b`), no message | **two** entries, both named `build-wheel` |

Four answers to one question. The provider hands `register_descriptors` both
descriptors — `[('build-wheel', 'buildWheel'), ('build-wheel', 'build_wheel')]`
— and the registration is a bare dict assignment (`_app/boot.py`,
`register_descriptors`), so the information needed for a diagnostic is present
and discarded.

`_discovery/registry.py` already carries the check and the reasoning for it
("Without this the second silently replaces the first and one job vanishes with
no diagnostic anywhere"), on the path nobody runs.

## Behavior

### One job per canonical name, one rule on every path

A canonical job name addresses exactly one function. When more than one
claimant resolves to the same name:

- **One claimant is registered.** It is the **last** in discovery order, which
  is what happens today and is deterministic: configured directories in order,
  files alphabetically (`sorted(dir_path.iterdir())`), functions alphabetically
  within a file (`dir(module)`).
- **Every other claimant is unavailable and reported.** It appears in
  `discovery_failures`, is printed once per boot as a single formatted warning
  line, and is not registered under any name.
- **The rule does not depend on the shape of the collision.** A and B above
  produce the same class of report and the same outcome.
- **The rule does not depend on the boot path.** The eager path stops raising
  and stops registering two entries under one name; it reports and skips.

Preserving today's winner rather than switching to first-wins is deliberate: a
project that already has a collision keeps running the function it runs today,
and only gains the message it was missing.

### What a collision is not

Two references to the *same* function object reaching the registry twice is not
a collision — it is idempotent re-registration and stays silent. So is the
pre-existing "same spelling, two modules" case *when the second module's
descriptor is identical in every field*, which cannot occur for distinct files
and is stated only to fix the boundary.

### Reporting shape

A collision is a `DiscoveryFailure`, the record type `builtin info` and
`self doctor` already consume, so no new report surface is introduced. Its
`error_type` is `JobNameCollision`.

## Acceptance criteria

Executable. Authoring-time state measured on `78d9ff4`.

| # | Criterion | Authoring-time state |
|---|---|---|
| A1 | Shape A on the default path: one job registered, one collision reported | one job, **nothing reported** |
| A2 | Shape A: the registered job is the same one as before this change (`build_wheel`, the last claimant) | `build_wheel` — must not change |
| A3 | Shape B on the default path: one job registered, one collision reported | one job, **nothing reported** |
| A4 | Shape B: the registered job is `b`'s, the last claimant | `b` — must not change |
| A5 | The collision appears in `builtin info --json` under `discovery_failures` with `error_type: "JobNameCollision"` | `discovery_failures: []` |
| A6 | The collision survives a warm boot (reported on the second invocation with no cache clear) | n/a — nothing reported at all |
| A7 | Eager path, shape A: reports and skips instead of raising `ValueError` | raises `ValueError` |
| A8 | Eager path, shape B: one entry registered, not two under one name | two entries, both `build-wheel` |
| A9 | Both paths return the same job-name set for the same tree | differ for shape B |
| A10 | A project with no collision reports none, and its job list is unchanged | holds; must keep holding |
| A11 | Re-registering the identical function object stays silent | holds; must keep holding |
| A12 | `func --help` and `func builtin info` still work with a collision present | they do (the drop is silent); must keep holding |
| A13 | Full gates green, `lint-imports` included | — |

## Out of scope

- **`register_dynamic_job`'s duplicate guard.** It raises `ValueError` on an
  already-registered name today. That is a caller error at an explicit API
  call, not a scan finding, and it stays a raise.
- **Which claimant wins.** Fixed to today's behavior by A2/A4 rather than
  redesigned.
- **Renaming or namespacing colliders automatically.** A collision is an
  authoring error; the fix is to rename one function.
