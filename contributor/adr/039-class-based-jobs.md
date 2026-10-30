# ADR-039: A Job Class's Methods Are Its Jobs

**Status**: accepted
**Date**: 2026-10-29
**Deciders**: maintainer

## Context

A job module is often a handful of verbs acting on one long-lived thing —
`start`/`stop`/`status` for a database — sharing one set of typed settings. The
subjects guide recommended a class for that shape, but discovery admitted only
module functions (`inspect.isfunction`), so a class had to be bound through a
hand-written plugin that listed its verbs. The maintainer declined that binding
as a substitute for discovery: classes had to be discovered the way functions
are.

Three gaps opened with it. `@job` replaced a declaration wholesale, so a base
class had no way to label its subclasses' jobs without overwriting what each
method declared. A class adds new ways for two definitions to claim one job
name — a method and a module function in one group, two classes in one group,
or the same class reached through two sources. And an earlier draft of this
capability required an extra framework flag and request field on every class
job, which a plain Functualize project has no use for.

## Decision

**Opt-in and naming.** `@job` on a `pydantic.BaseModel` subclass makes it a
*job class*. Its group is `@job(group=...)`, otherwise the normalized class name
nested under the module's `JOB_GROUP`. On a class, `@job` accepts only `group`,
`tags` and `visibility`; anything else, a non-model class, or a second `@job`
on the same class or function is a `ValueError` at decoration time — a
declaration is never silently replaced.

**One method, one job.** Each public instance method is one job,
`<group>.<method>`. Public methods are read along the MRO, excluding pydantic's
own bases, and **the nearest definition of a name decides it**: a subclass that
turns an inherited method into a `property`, `staticmethod`, `classmethod` or
plain value removes that method and nothing else. Discovery, `--help`, `info`
and completion never construct an instance; each run builds one from the
resolved configuration and calls the method on it.

**Abstract classes and inheritance.** A class with unimplemented abstract
methods is never a job class; if it carries `@job` itself, discovery registers
nothing and records a finding naming the class and its unimplemented methods.
The opt-in is read from the class's own definition and is **not inherited**: a
subclass without its own `@job` produces no job and every concrete job class
names its own group. A base contributes tags to its subclasses' jobs through
`JOB_TAGS: ClassVar[tuple[str, ...]]` without becoming a job class; tags merge
method first, then the class's own `@job(tags=...)`, then `JOB_TAGS` outward
along the MRO, and the author's own value wins every other conflict.

**One configuration section, the group's.** A job class's typed fields are the
configuration of all its methods and resolve the way a `GroupOptions` field
does: section `[pg]`, environment `PG__HOST`, vault identity
`--group pg --field password` — one secret, provisioned once. This is
deliberately *not* how a function job's config-model parameter resolves (it
reads its own job section, `[pg.start]` / `PG_START_HOST`). `builtin env` and
`builtin info --job` ask the engine for the same section and scope the run uses.

**Discovery paths.** A job class is found in a job directory module, through a
`functualize.jobs` entry point naming the class, and as a plugin's
`StaticProvider` item. The admission pre-filter qualifies a module when a
top-level public class has a public method in its own body *or* carries a
decorator named `job`, so a class whose methods are all inherited is still
imported. An entry point is classified from its module's source and imported
only when that source says it is a class; a function entry point still
enumerates without importing. If the source cannot be read (a zipped or frozen
distribution), the entry point keeps today's lazy descriptor and resolving it
to a class is reported at first use — an accepted limitation.

**Collisions involving a class are strict.** When at least one claimant of a
name is a job-class method, no claimant is registered under that name, in one
scan and across providers alike: invoking it exits `2` with a message naming
every definition and its real source file, `builtin info` lists it, and every
other job — including the class's uncontested methods — runs. A collision
between two plain functions keeps its earlier rule (one runs, the other is
reported).

**No new invocation input.** A class job is invoked exactly as a function job:
`func <group> <method> [params]`, `Invoke`, `app.execute`. Run records, listings
and schemas carry the job name and group and nothing new.

## Consequences

### Positive

- A subject's verbs are declared once, as a class, and discovered with no
  plugin; its settings live in one section and one vault entry.
- A class job can never be lost or replaced silently: an abstract opt-in, a
  method/group contradiction and every class-derived collision is a finding.
- Nothing about invoking a job changed, so a class job composes with
  `Invoke`, workflows, caching and guards as a function job does.

### Negative

- Two collision rules exist side by side — strict for class-derived names,
  survivor-runs for plain functions — until the plain rule is revisited.
- A class job's configuration spelling differs from a function job's config
  model in the same group (`PG__HOST` vs `PG_START_HOST`); the guides state it.
- The pre-filter matches the opt-in syntactically: a class opted in through an
  aliased import (`from functualize.job import job as opt_in`) with no method
  of its own is not imported.
- The discovery cache format moved to version 25; every existing cache is
  rebuilt once.

### Neutral

- `docs/guides/job-classes.md` ("Job classes") is the guide; the subjects guide
  now declares its subject class in this form.

## Alternatives Considered

| Alternative | Pros | Cons | Why rejected |
|-------------|------|------|-------------|
| Discover any class with typed fields and public methods (no decorator) | No opt-in to write | Helper classes and models in job modules start producing jobs; existing job lists change on upgrade | Not opt-in, not testable from the class alone |
| Class fields as `GroupOptions` (CLI flags) | Reuses an existing surface | Turns configuration into flags on every verb, with no per-file or per-environment values | Contradicts "typed fields are configuration" |
| A hand-written plugin binds the class | Already possible | A second registration path; verbs listed by hand | Declined by the maintainer as a substitute for discovery |
| Class collisions follow the plain-function rule | One rule | A survivor runs in place of a class method the user wrote with its siblings | Strictness is cheap to add before release and costly after |
| One vault entry per method job | Mirrors function-job config fields | The same secret provisioned N times for one class | One secret should be provisioned once |
| Inherit `@job` from a base | Less to write | Two implementations of one base would share a group by accident | Each concrete class names its own group |
