# Spec: A plugin can build a job provider without private imports

Upstream ask 9 from the rise design corpus, plus the Subjects guide that
depends on it.

## Problem

The documented way for a plugin to contribute jobs of its own is to hand
functualize a *job provider* — an object with two methods. What is public:

| Piece | Status |
|---|---|
| `JobProvider`, the protocol you implement | public, `functualize.plugin` |
| `JobDescriptor`, what its methods return | public, `functualize.types` |
| `Job`, a wrapper naming and grouping a callable | public, `functualize.plugin` |
| `StaticProvider`, which turns callables into a working provider | **private** |
| the helper that reads a function's arguments | **private** |

Two consequences.

**The public `Job` wrapper has no public consumer.** `StaticProvider` is the
only code that reads it, so functualize exports a type whose only use requires
a private import.

**Hand-rolling is possible but quietly lossy.** The two methods can be
implemented from public imports, but then the author fills in each job's
arguments, and the helper that does it correctly — skips `self`, excludes
injected capabilities, understands the argument markers and `Secret`
annotations — is private. Hand-roll without it and the jobs publish as taking
no arguments: the defect just fixed on the dynamic-registration door.

The docs page for this area says *"Modules under `functualize._discovery` are
implementation details. Import from `functualize.types` or `functualize.app`
instead"* while offering no public alternative.

Verified working today, with the one import that should not be needed:

```python
from functualize.plugin import Job                            # public
from functualize._discovery.providers import StaticProvider   # private

provider = StaticProvider([
    Job(function=obj.install, name="install", group="tools.jsonschema"),
    Job(function=obj.run,     name="run",     group="tools.jsonschema"),
])
```
```
install    params=['force']      <- self correctly skipped
run        params=['args']
```

## Behavior

`StaticProvider` is exported from `functualize.plugin`, under that name.

The name is kept rather than improved on the way out: it is what the class is
called in the code, in the tests and in the internal-location docs, and it
matches its siblings (`DirectoryScanProvider`, `EntryPointProvider`).
Promoting the existing shape rather than inventing one is the same call
ADR-017 made for `ModulePreFilter.should_import`.

## The Subjects guide

A drafted guide describing when a job module should be a class — the subject
test, the three axes, and how subject classes bind through a plugin — lands
with this, because its example is the code above and its accuracy depends on
the export. Three edits: the page, one bullet in the guides index, one line in
the site navigation. Its warning admonition about the private import is
deleted at the same time, since that is what this feature removes.

## Acceptance criteria

| # | Criterion | Authoring-time state |
|---|---|---|
| A1 | `from functualize.plugin import StaticProvider` works | ImportError |
| A2 | It appears in `functualize.plugin.__all__` | absent |
| A3 | A provider built from public imports registers jobs with their arguments intact | needs a private import |
| A4 | Bound methods work — `self` skipped, capabilities excluded | holds; must keep holding |
| A5 | The guide's example runs as written, from public imports only | the example carries a private-import warning |
| A6 | The guide is reachable from the guides index and the site nav | absent |
| A7 | `mkdocs build --strict` passes | — |
| A8 | Full gates green, `lint-imports` included | — |

## Out of scope

- **Making the parameter-extraction helper public.** Considered and declined:
  exporting the provider removes the need for it, and a second public surface
  is a second thing to keep stable forever.
- **Renaming `StaticProvider`.** Decided above.
- **Native class-to-jobs binding in functualize.** A separate, larger question
  the rise corpus defers.
