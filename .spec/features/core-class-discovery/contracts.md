# Core subject class discovery: external contract

Status: proposed for confirmation. This document names public shapes; it does
not prescribe private module placement or implementation algorithms.

## Declaration

```python
from typing import ClassVar

from functualize.job import Shell, Subject, job
from functualize.types import Secret


class Postgres(Subject):
    job_group: ClassVar[str] = "pg"
    job_tags: ClassVar[tuple[str, ...]] = ("database",)

    host: str
    token: Secret[str]

    @job(tags=("service",), category="operations")
    def start(self, sh: Shell) -> None:
        ...

    def stop(self, sh: Shell) -> None:
        ...

    def _probe(self) -> bool:
        ...
```

`Subject` is a public frozen Pydantic model base with a framework-owned
`address: str` field. `job_group` is a required nonempty dotted Python-identifier
group; `job_tags` defaults to empty. The subclass's typed fields are its job
configuration. A subclass may inherit group and tags from a `Subject` base;
base and concrete tags merge in MRO order. Only public instance methods
declared on `Subject` subclasses are operation candidates; `_probe` above is
not one. `@job` enriches an operation and is optional. A class that does not
inherit `Subject` is unchanged by this contract.

For this example discovery publishes exactly `pg.start` and `pg.stop`, one
descriptor each, regardless of how many addresses name a `Postgres`. The
method declaration's category and other metadata survive class-tag merging.

## Address selection and run request

```python
from functualize.types import RunRequest, SubjectSelection

selection = SubjectSelection(
    address="local/postgres/main",
    fixed={"host": "db.internal"},
)
result = app.execute(
    RunRequest(job_name="pg.start", surface="app.execute", subject=selection)
)
```

`SubjectSelection` is a frozen public value object with `address: str` and
`fixed: Mapping[str, object]` (default empty). The address is required and
nonempty for a subject job. `fixed` carries fields explicitly set by an
environment declaration or another trusted address source; its values are
copied at request creation so later caller mutation cannot change a run.
Unknown fixed fields fail validation. Fixed values, including `address`, are
not replaceable by `RunRequest.kwargs` or any config-chain source. An ordinary
job rejects a non-`None` subject selection rather than silently dropping it.

`RunRequest.subject: SubjectSelection | None` is the authoritative execution
input, separate from `kwargs`. Wire envelopes carry the address outside their
`arguments` object as `"subject": "local/postgres/main"`; a delivery adapter
does not accept arbitrary fixed values from this envelope. An environment
resolver may provide them when it builds the `RunRequest`.

The CLI form is `func pg start --subject local/postgres/main` (and equivalent
group routing). `--subject` is a framework control, not an operation parameter.
It can be entered on both the standalone `func` route and an application's CLI
adapter. Job names and run records retain `pg.start`; the address is a separate
field. All paths still call the existing `JobExecutionEngine`.

## Configuration and introspection

The common section for every `Postgres` operation is `pg`. For a selected
address, resolution uses existing chain tiers for fields not in `fixed`, then
validates one immutable `Postgres` instance. The framework supplies its
`address`. A caller's explicit job arguments may supply ordinary operation
parameters, but may not replace fixed subject fields. Existing secret markers
control masking; framework serialization must preserve usable secret values
inside the operation and redact display and persisted views.

`app.configuration.get_job_config_section("pg.start")` returns `"pg"`, as does
the same call for `pg.stop`. The address-aware read is
`app.configuration.resolved_subject_config("pg.start", selection) -> Postgres`;
it uses the same resolver as execution. `func builtin info` and
`func builtin env` accept `--subject <address>` for resolved subject values. With no address,
they may show the subject schema and `pg` section, but not a purported instance
value. Secret fields are masked in both displays.

## Source and cache contract

`JobSources.functions` and `StaticProvider` accept `type[Subject]` alongside
their existing inputs. A plugin may supply the class through either existing
job-provider seam; no new plugin type is introduced. A `functualize.jobs` entry
point may target a `Subject` subclass. Directory discovery finds locally
defined `Subject` subclasses in ordinary job modules. All source kinds publish
the same class/method descriptor identity and use the existing name-collision
check. A cached descriptor carries the class and method attribute names and
declaration metadata required to materialize without guessing or creating an
instance at scan time. Warm listing remains import-free for directory jobs.

A subject name collision is a discovery error naming the canonical job and
both source/class/method claims. It is not resolved by choosing a winner.

## Compatibility boundary

Ordinary module functions, unmarked classes, and their existing configuration
behavior remain valid. `@job(group=...)` or `@job(config_section=...)` on a
subject operation may only restate the class's group; a divergent value fails
declaration or discovery. The separate scoped-vault work owns address-ancestor
secret lookup. This contract carries the address so that integration can use
it when both prerequisites land.
