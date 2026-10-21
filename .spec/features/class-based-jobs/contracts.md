# Class-based jobs — contracts

External surfaces only. Internal descriptor and cache types belong to
`plan.md`/`schema.md`. Every name below uses R-1's vocabulary; no item adds an
invocation flag, request field or envelope key (R-4).

## C1 — `@job` on a class

`functualize.job.job` — the existing decorator; its signature does not change.

```python
from pydantic import BaseModel
from functualize.job import Shell, job
from functualize.job.decorators import Guards
from functualize.types import Secret


@job(group="pg")                      # or bare @job → group "postgres"
class Postgres(BaseModel):
    host: str = "localhost"
    port: int = 5432
    password: Secret[str]

    def start(self, sh: Shell) -> None: ...

    @job(guards=Guards(...))          # the method's own declaration is honoured
    def stop(self, sh: Shell, force: bool = False) -> None: ...

    def _present(self) -> bool: ...   # private: not a job
```

| Rule | Behaviour |
|---|---|
| Target type | The class must subclass `pydantic.BaseModel`. Otherwise `ValueError` at decoration time. |
| Accepted arguments on a class | `group`, `tags`, `visibility`. Any other (`deps`, `cache`, `guards`, `exec`, `examples`, `category`, `extra_description`, `config_section`) → `ValueError` at decoration time. |
| Group | `group=` when given, else `normalize_segment(cls.__name__)`, nested under the defining module's `JOB_GROUP` when set. |
| Opt-in is own-definition only (F1-b) | Read from the class's own namespace, never through a base. |
| Abstract class (F1-a) | No job, no group. With its own `@job`: a discovery finding, below. |
| Second `@job` on the same class or function (D4) | `ValueError` at decoration time: `"@job is already applied to <qualname>; combine the arguments into one @job(...)"`. |

Invocation is unchanged:

```console
$ func pg start
$ func pg stop --force
```

```python
invoke("pg.stop", force=True)          # Invoke
app.execute("pg.start")                # FunctualizeApp
```

Configuration — one section, the group's:

```toml
# config.base.toml
[pg]
host = "db.internal"
```

Environment variables follow the existing group rule (`PG__HOST`). The secret
field's vault identity (D2):

```console
$ func builtin vault put --group pg --field password
```

## C2 — inheritance and abstract classes

```python
from abc import abstractmethod
from typing import ClassVar

class Database(BaseModel):            # abstract: no job, no group
    JOB_TAGS: ClassVar[tuple[str, ...]] = ("database",)   # contributes a tag to subclasses' jobs (F4)
    host: str = "localhost"
    @abstractmethod
    def start(self, sh: Shell) -> None: ...
    @abstractmethod
    def stop(self, sh: Shell) -> None: ...

@job(group="postgres")
class LocalPostgres(Database):        # jobs postgres.start, postgres.stop, tags ("database",)
    def start(self, sh: Shell) -> None: ...
    def stop(self, sh: Shell) -> None: ...

class TunedPostgres(LocalPostgres):   # no @job of its own: no jobs
    port: int = 6432

@job(group="postgres-tuned")
class PooledPostgres(LocalPostgres):  # postgres-tuned.start, postgres-tuned.stop
    pool_size: int = 20
```

`JOB_TAGS` — an optional class attribute, a `tuple[str, ...]` of literal tag
strings, read from every class in the job class's method resolution order. It
never makes a class a job class. It must be annotated `ClassVar`: a bare
`JOB_TAGS = ("database",)` in a pydantic model body is a `PydanticUserError`
("a non-annotated attribute was detected") raised while the class is being
created, so no Functualize code ever sees it. `cls.__dict__["JOB_TAGS"]` holds
the tuple either way, which is where discovery reads it.

## C3 — discovery sources

| Source | Form | Result |
|---|---|---|
| Job directory | a job class defined in the scanned module | its method jobs; a job class imported into the module is not re-registered from it |
| `functualize.jobs` entry point | `pg = "my_pkg.pg:Postgres"` | the class's method jobs, named by the class's group rule; the entry-point name does not rename them |
| Plugin static jobs | `StaticProvider([Postgres])` | the class's method jobs |
| Plugin static jobs | `StaticProvider([Job(function=Postgres, ...)])` | `ValueError` at construction: a job class names its own jobs and group; pass the class directly |

## C4 — discovery findings

Both are `DiscoveryFailure` records shown by `func builtin info` (and
`func builtin self doctor`), like any other discovery finding. Message text uses
R-1 vocabulary only.

| Finding | When | Message names |
|---|---|---|
| abstract job class | an abstract class carries its own `@job` | the class, its module, and each unimplemented method |
| method group conflict | a method's `@job(group=...)` differs from its class's group | the method, its class, both groups |

## C5 — class-derived name collision (D3, model E)

When at least one claimant of a canonical name is a method of a job class:

- neither claimant is registered under that name; all other jobs register;
- `func builtin info` lists the name with both definitions and their source
  files;
- invoking the name prints, on stderr, a message naming both definitions and
  their files, and exits `2` (`ExitCode.USAGE`); `Invoke` raises the
  `JobNotFoundError` it raises today for an unknown name
  (`src/functualize/_engine/capabilities/invoke.py`), carrying the same text,
  and `app.execute` fails the same way it fails for an unknown name.

Collisions between two plain functions keep today's `JobNameCollision` record,
its JSON keys and its rendering, unchanged.

## C6 — run records and listings

A class-based job's descriptor, `func builtin info` row, schema
(`func builtin info schema pg.start`) and run record carry the job name and
group exactly as a function job's do. The schema's inputs are the method's
invocation parameters; the class's fields appear where a function job's
config-model fields appear today. No new record field, JSON key or envelope key.
