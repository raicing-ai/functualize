# Class-based jobs

Status: **proposed — awaiting confirmation before Plan.** Six decisions in
§ *Decisions to confirm* are written here in their recommended form and are not
final until confirmed.

## Authority

Shape Intent **SD/18317314** — *Class-Based Jobs: Methods as Jobs, Merged
Declarations, No Silent Job Loss* — page **version 3**, `Authority: Approved`,
updated 2026-10-21 11:00:32 UTC, read live on 2026-10-21. This spec implements
its F1 (with F1-a and F1-b), F4 and F5 under its rules R-1 to R-4. F2 and F3 are
not on that page and are not in this feature.

This feature replaces an earlier, withdrawn specification of the same
capability. Nothing from that specification is reused: it required an extra
framework flag and request field on every class job, which R-4 forbids.

The page's rules, in its own words:

- **R-1. Functualize vocabulary only.** Every flag, config key, error message,
  public type and doc for this feature uses Functualize's own words: *job,
  group, configuration section, config field, tag, declaration, discovery,
  plugin, entry point, vault*. A word that belongs to a package built on top of
  Functualize does not enter core.
- **R-2. Useful and testable alone.** Every behaviour here has a use, and an
  acceptance test, in a plain Functualize project with no other package
  installed.
- **R-3. Outside values stay opaque.** A package built on Functualize may give
  core a value in an existing input, such as a tag string, a config value or a
  vault group string. Core stores, compares and passes such values on. It never
  parses or interprets them.
- **R-4. No new invocation input.** A class-based job is invoked exactly as a
  function job is: `func <group> <method> [params]`, `Invoke`, `app.execute`. No
  new flag, request field or envelope key is added for it.

## Problem

A job module is often a handful of verbs acting on one long-lived thing —
`start`/`stop`/`status` for a database — sharing one set of typed settings.
`docs/guides/subjects.md` recommends a class for that shape, but Functualize
cannot discover a class:

- `_find_all_job_functions` (`src/functualize/_discovery/sync.py:410`) and
  `JobRegistry._is_registerable_function` (`src/functualize/_discovery/registry.py:607`)
  admit only `inspect.isfunction` attributes. `git grep -n -e isclass -e
  getmembers -- src/functualize/_discovery src/functualize/_app` returns nothing
  (exit 1) on `master` `bb3aac7`.
- `docs/guides/jobs-discovery.md:141` documents a class as "**not** registered —
  it's a class, not a function", and `docs/guides/subjects.md:65` binds a class
  through a hand-written plugin that enumerates its verbs by hand.
- `@job` replaces rather than merges: `apply` assigns the declaration wholesale
  (`src/functualize/job/decorators.py:105`). A base class has no way to add a
  tag to its subclasses' method jobs.
- Name collisions are resolved to a survivor. Within a directory scan the last
  claimant in `claim_order` wins (`src/functualize/_discovery/collisions.py:81`),
  across sources the first wins (`src/functualize/_discovery/pipeline.py:171`).
  Since `bb3aac7` the survivor's invocation prints the collision to stderr and
  then runs (`src/functualize/_cli/main.py:937`). A class adds new ways to claim
  one name.

The owner decided (2026-10-13) that 0.5.0 contains core class discovery and
declined a hand-written binding plugin as its substitute.

## User stories

1. As a job author, I put a class with typed fields and several methods in a job
   module, decorate it with `@job`, and every public method is an ordinary job
   under one group, with no plugin and no registration step.
2. As an operator, I configure all of that class's jobs in one configuration
   section and one vault entry per secret, and run them exactly as I run
   function jobs.
3. As the author of a base class, I add a tag to every job my subclasses
   publish, without overwriting what each method's author declared.
4. As a user, I never have a class-based job silently replaced by another
   definition: either it runs, or I am told why it does not.

## Behaviour

### F1 — Class-based jobs

**Opt-in and group (decision D1, model A).** `@job` on a class makes it a *job
class*. Its group is `@job(group=...)` when given; otherwise it is the
normalized class name (`LocalPostgres` → `local-postgres`), nested under the
module's `JOB_GROUP` when one is set. `@job` on a class accepts `group`, `tags`
and `visibility`; any other argument is refused at decoration time.

**Discovery.** A job class is found through the ordinary discovery paths: a job
directory module (the class must be defined in that module, as a function must
today), a `functualize.jobs` entry point naming the class, or a plugin's static
jobs. No hand-written plugin and no extra registration step is needed.

**Rule F1-a — an abstract class is never a job class** (page wording). A class
that still has unimplemented abstract methods produces no job and contributes
no group. It does not appear in discovery, `--help`, `func builtin info` or
completion. Only a concrete class can be a job class. If an abstract class
carries `@job` itself, discovery still registers nothing for it and records a
finding that names the class and its unimplemented methods. `func builtin info`
shows that finding, so the opt-in is never dropped silently.

**Rule F1-b — `@job` on a class is not inherited** (page wording). Each concrete
class opts in with its own `@job(...)`, and so names its own group. Discovery
reads the opt-in from the class's own definition, never through a base class. A
subclass without its own `@job` is not a job class and produces no job, even
when its base class is one. Only the opt-in and the group are not inherited.
Metadata that a base class contributes to its subclasses' jobs (F4) still
applies once a subclass opts in.

**One method, one job, one name.** Each public method of a job class is exactly
one job, named `<group>.<method>` with the usual name normalization
(`stop_all` → `stop-all`). The name is the same on cold and warm boot and does
not depend on import order. An inherited method appears once, under the
concrete class's group. *Public method* means an instance method whose name has
no leading underscore, defined on the job class or on one of its bases other
than pydantic's `BaseModel` and `object`; properties, `classmethod`s and
`staticmethod`s are not jobs.

**Method `@job` inside a job class.** A method may carry its own `@job(...)`
(guards, cache, deps, exec, tags, …); it is honoured as on a function. A method
`@job(group=...)` naming a group other than its class's is a contradiction of
"one class, one section": that method produces no job and discovery records a
finding naming the method and both groups.

**Typed fields are configuration.** The class's typed fields are the
configuration of every one of its method jobs. All methods of a class share
**one configuration section**, the class's group section. Each field resolves
through the existing order (runtime override → explicit argument → vault →
environment variable → config file → default), exactly as the fields of a
config-model parameter on a function job in the same group resolve today.

**Instance per run.** For each run, Functualize builds one instance from the
resolved configuration and calls the method on it. Discovery, `--help`,
`func builtin info` and completion never build an instance.

**Method parameters stay invocation inputs.** Parameters other than `self`
behave as they do on a function job: CLI flags, `Invoke` arguments, and injected
capabilities such as `Shell` and `Log`.

**Secret fields (decision D2).** A secret-marked field is a secret config field
and resolves through the vault under the **class's group** identity — one entry
shared by every method job: `func builtin vault put --group pg --field password`.
That is the identity a secret `GroupOptions` field already uses
(`docs/guides/group-options.md:141`); no new vault identity is introduced.
Secret values are masked on every surface that masks a function job's secret
config field today.

**Same surfaces.** `func builtin info`, `--help`, the TUI and run records show a
class-based job like any other job. The record keeps the job name and group, and
nothing new.

### F4 — Declaration metadata that merges

- Metadata contributed for a method's job by its class or by a base class merges
  with the author's own `@job(...)` on that method. In this feature the
  contributed metadata is **tags** (decision D5):
  - the job class's own `@job(tags=...)` contributes to every method job of
    that class;
  - a class anywhere in the job class's bases contributes through a literal
    class attribute `JOB_TAGS`, a tuple of strings — the class-level
    counterpart of the module-level `JOB_GROUP`. It contributes without making
    that class a job class.
- **The author wins on every conflict.** Contributed tags are added to the
  author's tags. A contributed value never overwrites a value the author set
  explicitly (`group`, `visibility`, `guards`, `exec`, `cache`, `deps`). The
  class's `visibility` applies to a method that does not set its own.
- Contributed metadata is a plain value. Core stores and shows a contributed tag
  but gives it no meaning (R-3).
- The merged tag order is stable: author tags first, then contributed tags from
  the job class outward along the method resolution order, duplicates removed.
- **Two author-written `@job` on one function or one class (decision D4)** is
  refused at decoration time with a `ValueError` naming the target. Silent
  replacement no longer happens.

### F5 — No silent job loss

- Every collision in which at least one claimant comes from a job class is
  reported. Examples: a method and a module function in one group, two classes
  mapping to one group, or the same class arriving through two sources. The
  report names both definitions and their source files.
- **Groups are never shared by inheritance.** Two implementations of one base
  claim the same group only when their authors wrote the same group. That case
  is a collision under this rule: reported, never a silent merge or a silent
  winner.
- **Loudness (decision D3, model E — strict for the new surface).** When either
  claimant is class-derived, neither definition runs under that name. Invoking
  it exits with `ExitCode.USAGE` (2) and a message naming both definitions and
  their files; `func builtin info` lists it. The rest of the project boots and
  runs normally (the posture ADR-018 takes for an unsatisfiable job).
- Collisions between two plain functions keep today's rule, unchanged.

### Documentation (decision D6)

`docs/guides/subjects.md` is revised to the discovered form: the binding-plugin
section is replaced by a decorated job class, "constructors are inert … one
instance per process" becomes "construction must not do I/O; one instance per
run", and the related guides that say classes never register
(`docs/guides/jobs-discovery.md:134-141`, `subjects.md:172`) are corrected. A
`CHANGELOG.md` `## [Unreleased]` entry describes the capability.

## Behaviour that must not change

Plain function jobs, `JOB_GROUP`, `GroupOptions`, the configuration order, the
existing `JobNameCollision` record and its rendering (in `func builtin info` and
on invocation), and plugin and entry-point discovery for functions. A module
containing classes without `@job` lists exactly the jobs it lists today. A
distribution whose entry points name only functions keeps enumerating without
importing them.

## Out of scope

A new discovery path, loader or plugin type; any new invocation flag, request
field or envelope key (R-4); giving any tag a built-in meaning; changing name
normalization or the naming contract; collisions between plain functions; the
vault identity grammar; F2 and the configuration-section half of F3.

## Acceptance criteria

All run in a plain Functualize project with no other package installed (R-2).
Fixture: `.functualize/jobs/pg.py` holding the `Postgres` job class of
`contracts.md` § C1, `config.base.toml` with `[pg] host = "db.internal"`, and one
vault entry for `password`; AC-9/AC-10 add `.functualize/jobs/databases.py` from
`contracts.md` § C2. Rows map to the page's experiment rows E1–E10.

| # | Run | Must hold | Page row |
|---|---|---|---|
| AC-1 | `func builtin info jobs --json` | exactly `pg.start` and `pg.stop` from `pg.py`; no plugin in the project | E1 |
| AC-2 | `func pg start` | runs with no extra flag; `self.host == "db.internal"` from `[pg]`; `self.password` is the vault value | E2 |
| AC-3 | `func pg stop --force`, then `FUNCTUALIZE_ENV=prod func pg stop` with `config.prod.toml` `[pg] host` | the method parameter binds; the overlay value reaches `self` | E3 |
| AC-4 | `func pg --help`, `func builtin info`, completion | a constructor side-effect counter stays 0 | E4 |
| AC-5 | a base class declares `JOB_TAGS = ("t1",)`; `stop` keeps `@job(guards=…, tags=["mine"])` | `stop` has tags `(mine, t1)` and its guards | E5 |
| AC-6 | add module function `def start()` with `JOB_GROUP = "pg"` | `func pg start` exits 2 naming both definitions and files; `func builtin info` lists it; `func pg stop` still runs | E6 |
| AC-7 | repeat AC-1, AC-2, AC-6, AC-9, AC-10 on a warm cache | identical results | E7 |
| AC-8 | review every new public name, flag, config key and message in the diff | each uses only R-1's vocabulary; no new invocation flag, request field or envelope key (R-4) | E8 |
| AC-9 | listing and `func --help` with `databases.py`; then add `@job` to abstract `Database` | no job and no group for `Database`; with `@job`, still no job, and `func builtin info` shows a finding naming `start` and `stop` as unimplemented | E9 |
| AC-10 | same listing; then add `OtherPostgres(Database)` with `@job(group="postgres")` | `TunedPostgres` produces no job; `PooledPostgres` lists only under `postgres-tuned`; `OtherPostgres` and `LocalPostgres` collide on `postgres.start`/`postgres.stop` and the collision is reported per AC-6 | E10 |
| AC-11 | `func builtin vault put --group pg --field password`, then `func pg start` and `func pg stop` | both receive the one entry; `func builtin info` and `env` mask it | D2 |
| AC-12 | a second `@job(...)` applied to one function, and to one class | `ValueError` at decoration time naming the target | D4 |
| AC-13 | the same job class published through a `functualize.jobs` entry point, and through a plugin's `StaticProvider` | the same jobs, names and config section as AC-1/AC-2; the same class through two sources is a collision per AC-6 | F1, F5 |
| AC-14 | the plain-function and collision suites that exist on `master` | pass unchanged | must-not-change |

## Decisions to confirm

Each is written into this spec in its recommended form.

| # | Question | Recommended |
|---|---|---|
| D1 | How does a class opt in, and what is its group? (page Q1) | Model A: `@job` on the class; `group=` or the normalized class name |
| D2 | Where does a class's secret field live in the vault? (page Q2) | Once, under the class's group: `--group pg --field password` |
| D3 | How loud is a class-derived name collision? | Model E: strict — neither runs, exit 2, listed in `info` |
| D4 | Two author-written `@job` on one target (page Q3) | Refuse at decoration time |
| D5 | How does a base class contribute tags? | `JOB_TAGS = (...)` class attribute; tags only in this feature |
| D6 | The guide's title word (page Q5) | Rename to `docs/guides/job-classes.md`, "Job classes"; keep the modelling advice |

Page Q4 (F2 and the configuration-section half of F3) has no ticket and is not
decided here.
