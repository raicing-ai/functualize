# Job classes

A **job class** is a `pydantic.BaseModel` decorated with `@job`. Each public
method of the class becomes one job, and the class's typed fields become the
configuration every one of those jobs reads.

Nothing else about a job changes. A class job is invoked with
`func <group> <method>`, with `invoke(...)`, and with `app.execute(...)`, and it
appears in `func builtin info`, `--help` and the run records exactly where a
function job appears. The class is a different way to *declare* a job, not a
different way to run one.

A class that models a thing existing between runs — a cluster, a service, a
checkout — is the case this form was built for. [Subjects](subjects.md) answers
*when* a module should be a class; this guide answers *how* one is declared.

## The class form

```python title="jobs/pg.py"
from typing import ClassVar

from pydantic import BaseModel

from functualize.job import Guards, Shell, job

@job(group="pg")  # (1)!
class Postgres(BaseModel):
    """A local postgres cluster managed through systemd."""

    JOB_TAGS: ClassVar[tuple[str, ...]] = ("database",)  # (2)!

    host: str = "localhost"  # (3)!
    port: int = 5432

    @property
    def present(self) -> bool:  # (4)!
        """True when the cluster answers. Presence is not a verb."""
        ...

    def start(self, sh: Shell) -> None:
        """Start the cluster."""

    def stop(self, sh: Shell, force: bool = False) -> None:  # (5)!
        """Stop the cluster."""

    @job(guards=Guards(preconditions=["pg-ready"]))  # (6)!
    def backup(self, sh: Shell, target: str = "s3://backups") -> None:
        """Back the cluster up to a dump file."""

    def _reload(self) -> None:  # (7)!
        """Discovered as no job at all."""
```

1. The target must subclass `pydantic.BaseModel`. Anything else is a `ValueError`
   at decoration time: *"@job target … is a class but not a pydantic.BaseModel
   subclass; a class job declares its config class"*.
2. `JOB_TAGS` is the class-side tag contribution — see
   [Tags merge outward](#tags-merge-outward-from-the-method). Annotate it
   `ClassVar`; a plain annotation makes it a configuration field instead.
3. Fields are configuration, not parameters — see
   [Configuration is the class's fields](#configuration-is-the-classs-fields).
4. Presence is a question, not a verb. A `@property` is not a job, so it stays
   available to every method without becoming a command.
5. Parameters other than `self` are the job's own: `--force` here, plus the
   injected capabilities a function job would receive.
6. A method may carry its own `@job(...)`. Guards, caching, deps and tags apply
   to that method's job only.
7. Public means no leading underscore. `_reload` produces nothing.

The names are the class's group plus the method's name, normalized the usual
way — `stop` → `pg.stop`, `stop_all` → `pg.stop-all`:

```console
$ func pg
Usage: func pg <command> [options]

Commands:
  start   Start the cluster.
  stop    Stop the cluster.
  backup  Back the cluster up to a dump file.
```

`classmethod`s and `staticmethod`s are not jobs either. Inheritance works as
you would expect: a public method defined on a base class outside pydantic
(`BaseModel` and `object` excluded) is one job, listed once, under the
**concrete** class's group.

## The group rule

The group is the configuration section, the CLI namespace and the vault
identity, all at once — so it is decided in one place:

| You write | Group | Jobs |
|---|---|---|
| `@job(group="pg")` on `class Postgres` | `pg` | `pg.start`, `pg.stop` |
| bare `@job` on `class Postgres`, no `JOB_GROUP` | `postgres` | `postgres.start` |
| `JOB_GROUP = "data"` in the module + bare `@job` on `class Reports` | `data.reports` | `data.reports.generate` |
| `JOB_GROUP = "data"` in the module + `@job(group="pg")` | `pg` | `pg.start` |

An explicit `group=` wins outright. Without one, the class name is the group,
normalized, and the module's `JOB_GROUP` stays the namespace above it — the same
way `JOB_GROUP` namespaces functions in that file
([Jobs and Auto-Discovery](jobs-discovery.md#job-names-are-canonical)).

Two levels in one name means two words on the command line: `func data reports
generate`, not `func data.reports generate`.

Groups are never shared by inheritance. Two subclasses of one base claim the same
group only when their own `@job(group=...)` says so, and then that is a
[collision](#when-two-definitions-claim-one-name), never a silent merge.

## Configuration is the class's fields

The class's typed fields are the configuration of **every** method job of that
class, and all of them read **one section**: the class's group. A
`host: str` field on the `pg` class above resolves as the `host` key of the
`[pg]` section, through the same order a config-model parameter on a function
job resolves through — runtime override → explicit argument → vault →
environment variable → config file → default
([Configuration System](configuration.md)).

```toml title="config.base.toml"
[pg]
host = "db.internal"
port = 6543
```

```console
$ func pg backup
backed up db.internal:6543 to s3://backups
```

A field marked `Secret[str]` is a secret configuration field, resolved through
the vault under the **class's group**: one entry shared by every method job of
the class, and no new identity is invented for it.

```console
$ func builtin vault put --group pg --field password
```

The same identity a secret `GroupOptions` field already uses
([Group Options](group-options.md)).

**One instance per run, built from resolved configuration.** For a single
invocation Functualize resolves the fields, constructs the class with them, and
calls the method on that instance. Discovery does not construct it, and neither
does `--help`, `func builtin info`, `func builtin info schema` or completion — so
constructing a job class must not do I/O and must not be the place a side effect
happens. The constructor receives arguments; it is not the execution point.

## Tags merge outward from the method

A method's job has three places to get tags, and it takes all of them:

```python
class Database(BaseModel):
    JOB_TAGS: ClassVar[tuple[str, ...]] = ("database",)

@job(group="pg", tags=["class-tag"])
class Postgres(Database):
    JOB_TAGS: ClassVar[tuple[str, ...]] = ("cluster",)

    @job(tags=["method-tag"])
    def backup(self, target: str = "s3://backups") -> None: ...
```

`backup`'s tags are `method-tag`, `class-tag`, `cluster`, `database` — the
method's own declaration first, then its class's, then `JOB_TAGS` outward along
the MRO, nearest class first. Duplicates keep their first position, so the order
is deterministic and mergeable.

`JOB_TAGS` is read from each class's `__dict__`, which is why it must be a
`ClassVar`. Written as a plain annotation it becomes a configuration field
instead and contributes no tags — silently, since the annotation is legal Python
and a valid pydantic field.

```console
$ func builtin info --json | jq '.jobs[] | {name, tags}'
```

## What a class cannot do

Three declarations are refused, two of them at decoration time:

```python
@job(group="pg", guards=Guards(...))   # ValueError: @job on class Postgres accepts
                                       # only group, tags and visibility;
                                       # offending arguments: guards

@job(group="pg")
@job(group="pg", tags=["again"])       # ValueError: @job is already applied to
                                       # Postgres; combine the arguments into one
                                       # @job(...)
```

A class accepts `group`, `tags` and `visibility` — the declaration that belongs
to *one name*. Guards, cache, deps, examples and the rest belong to a single job
and therefore go on the method.

A method's own `@job` may name a group, but it has to be the class's: the group
is the class's, so a method that declares a different one is refused as a
`MethodGroupConflict` finding and registers no job.

The other refusal is not about arguments at all: **`@job` on a class is not
inherited.** Each concrete class opts in with its own `@job(...)` and so names
its own group. A subclass without its own `@job` is not a job class and produces
no job, even when its base is one. What a base *does* contribute — fields,
`JOB_TAGS`, methods — arrives the moment a subclass opts in.

An **abstract class** is never a job class: while it still has unimplemented
abstract methods it produces no job and contributes no group, and nothing about
it appears in discovery, `--help`, `func builtin info` or completion. Give one an
`@job` anyway and discovery still registers nothing for it, but records a
finding naming the class and its unimplemented methods, so the opt-in is never
dropped silently.

## When two definitions claim one name

Canonical names are unique. When a class method and something else produce the
same name — a function in the same group, a second class mapped to the same
group, the same class arriving through two sources — the collision is **strict**
if either claimant is class-derived:

- neither definition runs under that name; every other job registers and the
  project boots normally;
- `func <group> <method>` exits `2` with a message naming both definitions and
  their files;
- `func builtin info` reports it under discovery failures, and
  `func builtin info jobs` lists it as a row.

```console
$ func pg start
Job name 'pg.start' is declared twice: 'start' (…/jobs/legacy.py) and
'Postgres.start' (…/jobs/pg.py). Neither is registered.
$ echo $?
2
```

```console
$ func builtin info jobs
pg.backup   Back the cluster up.
pg.start    Name collision: neither definition is registered.
            Job name 'pg.start' is declared twice: 'start' (…/jobs/legacy.py) and
            'Postgres.start' (…/jobs/pg.py). Neither is registered.
pg.stop     Stop the cluster.
```

A collided name is not a command, so it does not appear under `func pg` — that
listing shows what can actually run. Two *plain functions* colliding keep the
rule they always had (`JobNameCollision`, reported the same way); the strict arm
is what a class-derived claimant adds.

## Where a class is discovered from

Same three sources as a function, and no registration step:

| Source | Form | Result |
|---|---|---|
| Job directory | the class defined in a scanned module | its method jobs; a job class merely imported into the module is not re-registered there |
| `functualize.jobs` entry point | `pg = "my_pkg.pg:Postgres"` | the class's method jobs, named by the class's own group rule — the entry-point name does not rename them |
| Plugin static jobs | `StaticProvider([Postgres])` | the class's method jobs |

Every one of them reaches the same declaration, so the names and the
configuration section are identical whichever way the class arrives.

## Related guides

- [Jobs and Auto-Discovery](jobs-discovery.md) — how plain function jobs register, and where a class fits
- [Subjects](subjects.md) — when a module should be a class at all
- [Configuration System](configuration.md) — the resolution order the class's fields follow
- [Group Options](group-options.md) — flags for a group instead of a job, and the vault identity a secret field uses
- [Composing Capabilities](composition.md) — the injected parameters a method receives
- [JobConfig with Pydantic](job-config.md) — the same field resolution on a function job's config model

`examples/standalone/job_classes_lab` is the runnable form of this page: a job
class with merged tags, a second class grouped by its own name, and a collision
that refuses both claimants.
