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

## A subject class, bound

Directory discovery ignores classes entirely — a class is not a function, so it never registers from a scanned module (see [Jobs and Auto-Discovery](jobs-discovery.md)). Subject classes bind through a **plugin**: plugins run during boot, *before* job resolution, which is the documented moment to add job providers.

```python title="modules/postgres.py — the subject"
from pathlib import Path

from functualize.job import Log, Shell


class Postgres:
    """A local postgres cluster managed through systemd."""

    group = "pg"  # (1)!

    def present(self) -> bool:  # (2)!
        """True when the cluster answers. Presence, not a job."""
        ...

    def start(self, sh: Shell, log: Log) -> None:  # (3)!
        """Start the cluster."""
        ...

    def stop(self, sh: Shell) -> None:
        """Stop the cluster."""
        ...

    def backup(self, sh: Shell, to: str = "/tmp") -> Path:  # (4)!
        """Back up the cluster to a dump file."""
        return Path(to)
```

1. The group is the subject's CLI namespace: every verb lands under `pg` — `func pg start`, `func pg backup`.
2. Presence is a method, not a job and not a per-job guard. It is the one place that answers "is it there?"
3. Actions are methods. Bound methods register like plain functions: `self` is skipped, typed parameters become flags, and `@job(...)` declarations on the method — guards, caching, deps — are honoured.
4. Take `str` and convert — a bare `Path` parameter is not an injectable type; boot rejects it with `DIValidationError`. A `Path` inside a config model is fine (pydantic converts there).

```python title="plugins/subjects.py — the binding"
from functualize.app import FunctualizeApp, JobSources, PluginSources
from functualize.plugin import Job

from modules.postgres import Postgres

from functualize._discovery.providers import StaticProvider  # (1)!


class SubjectsPlugin:
    name = "subjects"
    version = "0.1.0"
    description = "bind subject classes as jobs"

    def __init__(self, classes: list[type]) -> None:
        self._classes = classes

    def __call__(self, app: FunctualizeApp) -> None:
        jobs = []
        for cls in self._classes:
            subject = cls()  # (2)!
            for verb in ("start", "stop", "backup"):  # (3)!
                jobs.append(Job(
                    function=getattr(subject, verb),
                    name=f"{cls.group}.{verb}",
                    group=cls.group,
                ))
        app.add_job_provider(StaticProvider(jobs))


app = FunctualizeApp(
    "my-app",
    job_sources=JobSources(directories=["jobs"], lazy=False),
    plugin_sources=PluginSources(explicit_plugins=[SubjectsPlugin([Postgres])]),
)
```

1. `Job` is public (`functualize.plugin`); `StaticProvider` is not yet re-exported there — this import is private-but-stable until it is. The alternative is implementing the two-method `JobProvider` protocol (`list_jobs` / `get_job`) yourself.
2. Constructors are inert: no arguments, no side effects. Configuration arrives per invocation, not at construction.
3. The verbs are enumerated explicitly — presence is deliberately not among them.

Verify what registered, and what each job takes, before trusting any of it:

```bash
func builtin info            # pg.start, pg.stop, pg.backup beside your jobs/
func builtin info schema pg.backup
```

For distribution, ship the plugin through the `functualize.plugins` entry-point group instead of `explicit_plugins` — see [Plugins](plugins.md).

## Rules the declaration must follow

1. **The declaration lives in the class line.** Bases state the substrate and the actions; identity is literal class attributes (`group`, config model, target). Nothing computed, nothing dynamic.
2. **Readable without execution.** Tools and agents should be able to answer "what is this module?" from source alone — bases plus literal assignments. Keep that reading in agreement with live reflection; a divergence is a bug in one of them.
3. **Constructors are inert.** No-argument, no side effects, one instance per process. The constructor is a boot-time execution point; treat it as such.
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

- [Jobs and Auto-Discovery](jobs-discovery.md) — how plain job modules register, and why classes never do
- [Composing Capabilities](composition.md) — the injected capabilities (`Shell`, `Log`, …) your verb bodies take, and the guard/fingerprint matrix
- [Task Runner](task-runner.md) — the `@job` decorator: guards, caching, deps, retries
- [Plugins](plugins.md) — the plugin protocol and entry-point distribution
- [Workflows](workflows.md) — the composition tool when there is no subject, only a graph
