# Subjects

A **subject** is a thing your jobs manage that exists between runs: a tool on `PATH`, a service, a repository checkout, a remote endpoint, a cluster. Most jobs don't have one — they *are* the work (build, transform, report) and finish. This guide is about the modules that do have one, and answers two questions:

1. **When should a job module be a class that models the subject** — and when should it stay plain functions?
2. **What shape should that class take** so it composes with functualize instead of fighting it?

!!! note "Actions, not capabilities"
    functualize's **capabilities** are injected parameters — `Shell`, `Log`, `Stdout`, and friends ([Composing Capabilities](composition.md)). This guide uses **actions** for something else: the verbs a subject supports (`start`, `install`, `backup`). Two words, two meanings, deliberately not shared.

## The test

> **Name the thing that exists between runs. If you can name it and your verbs act on it, model it as a class — substrate, actions, target. If you can't — the work itself is the artifact — write jobs and compose them with functualize's native pieces.**

Everything else in this guide is elaboration of that one sentence.

## When a class earns its keep

| Signal | What the class buys |
|---|---|
| **Presence is a question more than one job asks** — the same "is it there?" check copy-pasted as a guard on several jobs | one presence method instead of repeated guards; "is it healthy?" becomes one job, not N copy-pasted checks |
| **Two or more verbs against one subject** — install/uninstall/run, start/stop/status, backup/restore, clone/pull/push | one group, one config model, one declaration that names the thing once |
| You want a **meta-surface** — health over the whole project, provenance, staleness | presence and verbs in one place; a diagnose-style job falls out of the shape |
| **Config is shared across the verbs** | one config model instead of the same fields repeated per job |
| The subject has **identity that should flow into records** — a revision, a version, an origin | a declared target whose resolved identity reaches fingerprints and logs |

## When plain jobs are the answer

| Signal | Because |
|---|---|
| The job **is the work** — transform, build, report, one-shot compute | there is no subject to name |
| The "subject" is really an **input of this invocation** — files read or written | `@job(cache=Fingerprint(sources=…, generates=…))` and `sources: Sources` already declare it |
| It's a **pipeline** — chains, fan-out, walks with pauses | `Deps`, `FromJob`, and `@workflow` are the composition tools; a class adds nothing to them |
| It's a **one-off script** | write the job; a class can come later if a subject appears |

!!! tip "Grouping is not modeling"
    A class whose only job is putting functions in one namespace is not modeling a subject. `JOB_GROUP` already groups functions, and `GroupOptions` already shares flags between them. Classes earn their keep through the signals above — presence, verbs, identity — not through grouping alone.

## The three axes

A subject class states three things, and only three things, about its subject.

### Axis 1 — Substrate: what it is, hence what "present" means

The class's base declares what kind of thing the subject is, and the substrate's whole job is to define **presence**: what "is it there?" means, and what a diagnosis of it reports. `shutil.which` for an executable, an import probe for a package, a status query for a process, `git rev-parse` for a checkout.

A subject may genuinely be more than one thing — a package that is both importable and executable carries both, and saying so is more truthful than picking one.

### Axis 2 — Actions: what you can do to the subject

Actions are verb Protocols mixed into the class — `start`/`stop`/`status` is one action set, `install`/`uninstall` another. Each method implementing an action becomes one job.

Every action must pass one test:

> An action names something you can **do to the subject**. If it names what the module **computes**, it is a pipeline step — an ordinary method, not vocabulary.

`build`/`test`/`report` against the module's own artifacts fail that test: they describe work, not verbs against a persistent thing. Write them as plain jobs or methods and compose them with functualize's native pieces.

### Axis 3 — Target: what it acts on but does not claim to be

A subject class *is* its subject. A module that *acts on* something external — audits a repository, inspects an endpoint, migrates a database — declares a **target** instead: a declared, resolvable reference whose identity (a revision, a URL) flows into records and fingerprints. That is what makes staleness identity-aware rather than merely byte-aware: a branch switch with identical file bytes is a change.

## A subject class, declared

A subject class is a **job class**: `@job` on a `pydantic.BaseModel` subclass,
where each public method is one verb. Discovery finds it in a job module like
any function job; there is no registration step and no plugin to write
([Job classes](job-classes.md)).

```python title="jobs/pg.py — the subject"
from pathlib import Path

from pydantic import BaseModel

from functualize.job import Log, Shell, job

@job(group="pg")  # (1)!
class Postgres(BaseModel):
    """A local postgres cluster managed through systemd."""

    data_dir: Path = Path("/var/lib/postgresql")  # (2)!

    @property
    def present(self) -> bool:  # (3)!
        """True when the cluster answers. Presence, not a job."""
        ...

    def start(self, sh: Shell, log: Log) -> None:  # (4)!
        """Start the cluster."""
        ...

    def stop(self, sh: Shell) -> None:
        """Stop the cluster."""
        ...

    def backup(self, sh: Shell, to: Path = Path("/tmp")) -> Path:  # (5)!
        """Back up the cluster to a dump file."""
        return to
```

1. The decorator names the group, which is the subject's CLI namespace, its
   configuration section and its vault identity at once — every verb lands under
   `pg`: `func pg start`, `func pg backup`. A bare `@job` would take the
   normalized class name instead, nested under the module's `JOB_GROUP` if it
   has one ([Job classes](job-classes.md#the-group-rule)).
2. Fields are configuration. `[pg] data_dir = "/srv/pg"` reaches every verb of
   the class through the resolution order a config-model parameter on a function
   job uses ([Configuration System](configuration.md)).
3. Presence is a question, not a verb — and every **public** method is a job, so
   presence is a `@property` (or an underscore-prefixed method) rather than a
   fourth command. A property is never a job.
4. Actions are methods. `self` is skipped, typed parameters become flags, and a
   method's own `@job(...)` — guards, caching, deps — applies to that verb alone.
5. `Path`, `UUID`, `date`, `datetime`, `Decimal` and `Enum` subclasses are
   caller-supplied values: they become flags and arrive converted. A type
   outside that set is treated as a dependency to inject, so annotate it with
   `Arg()` or `Option()` if the caller should supply it instead.

The class is constructed **once per run, from its resolved configuration**, and
never during discovery, `--help`, `func builtin info` or completion. Construction
therefore is not where the subject is probed: `present` is, and it runs when a
verb (or a guard) asks it to.

Verify what registered, and what each job takes, before trusting any of it:

```bash
func builtin info            # pg.start, pg.stop, pg.backup beside your jobs/
func builtin info schema pg.backup
```

!!! note "A subject that cannot be a model"
    The decorated form requires a `pydantic.BaseModel`, because its fields are
    the declaration. A class whose constructor needs arguments nobody declares,
    or whose base already fixes `__init__`, is not one. It can still be bound
    through a plugin that adds a provider — `Job(function=...)` per method, or
    your own `JobProvider` — see [Plugins](plugins.md). Then the parameter
    extraction and the configuration story are yours.

## Rules the declaration must follow

1. **The declaration is the class line and its decorator.** Bases state the substrate and the actions; `@job(group=…)` names the group; typed fields carry the configuration; a target is a literal class attribute. Nothing computed, nothing dynamic.
2. **Readable without execution.** Tools and agents should be able to answer "what is this module?" from source alone — bases plus literal assignments. Keep that reading in agreement with live reflection; a divergence is a bug in one of them.
3. **Construction is not an execution point.** One instance per run, built from the resolved configuration — never built during discovery, `--help`, `func builtin info` or completion. No I/O in the constructor; it receives the subject's fields and does nothing else.
4. **Presence is a method, not a per-job guard.** Per-verb idempotency is still `Guards(status=…)` — "already done" is a different question from "is the world fit to run" ([Composing Capabilities](composition.md) §2).
5. **One binding path validates everything.** Whatever checks your vocabulary applies, built-in and project-local shapes go through the same path. No second validation authority.
6. **Closed core, extensible per project.** Fix the substrate and action sets in one place; projects extend by subclassing, not by editing tables.

## Migration signals

Each signal is a cost you are already paying:

- The same status guard on two or more jobs → a substrate's presence method.
- The same config fields on two or more jobs → one shared config model (or `GroupOptions`, if you stay plain — that is the honest fork).
- A docstring that says "manages X" or "maintains X", where X persists between runs → X is a substrate waiting to be named.
- Re-deriving identity — a revision, a version, a path — that should flow into records and fingerprints → a target.

## What this guide does not define

functualize ships **no concrete substrates, actions, or targets**, deliberately: it has no opinion about what jobs mean. Concrete sets belong to a **vocabulary layer** — a package that supplies substrate base classes, action Protocols, validation, and tooling on top of this practice, and owns the enforcement ladder (static types at authoring, checks at binding, findings at validate). If you want a ready-made resource vocabulary rather than your own, that is a separate package's job, not functualize's.

## Related guides

- [Job classes](job-classes.md) — the declared form of a subject class: group, configuration, tags and collisions
- [Jobs and Auto-Discovery](jobs-discovery.md) — how plain job modules register, and where a job class fits in the scan
- [Composing Capabilities](composition.md) — the injected capabilities (`Shell`, `Log`, …) your verb bodies take, and the guard/fingerprint matrix
- [Task Runner](task-runner.md) — the `@job` decorator: guards, caching, deps, retries
- [Plugins](plugins.md) — the plugin protocol and entry-point distribution
- [Workflows](workflows.md) — the composition tool when there is no subject, only a graph
