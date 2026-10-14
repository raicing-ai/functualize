# Core subject class discovery

Status: proposed for confirmation before Plan.

## Authority and scope

The approved Shape Intent is SD page 5407068, version 18, `Authority: Approved`,
read live on 2026-10-14. Its Decisions 16, 17, and 23 require one generic
Functualize class discovery path, typed immutable subject configuration, and
one canonical operation job at class level. The Rise foundation's P-1 contract
at revision 6 supplies capability requirements R1.1–R1.10; it leaves this
ticket's public interface to this specification.

This change belongs in core discovery, configuration, and execution. Core does
not interpret Rise capabilities, substrates, relations, environment trees, or
generated instance routes. The scoped vault's address and environment lookup
is a separate prerequisite. The lane that lands second integrates its lookup
with the address carried here.

## Problem

`_discovery/sync.py` admits public module functions with `inspect.isfunction`;
its class path is absent. The existing subject guide binds an instantiated
class through a project plugin and explicitly enumerates its verbs. That
produces another registration path and an instance-bound function, while the
approved shape requires ordinary class-level jobs. A class's typed fields also
need the same configuration and masking path as a job config model.

## User stories

1. As a package author, I can declare a typed subject class once and let a
   directory, entry point, or plugin expose its public operation methods as
   ordinary jobs, without listing verbs in a binding plugin.
2. As a caller, I can invoke one canonical operation job with a subject address
   and have the operation run on the immutable instance selected by that address.
3. As an operator, I can inspect the class's job schema, shared config section,
   resolved values, and discovery failures without exposing secret bytes.

## Required behavior

### Discovery and identity

- A class explicitly marked by inheriting `Subject` is eligible. Its public
  instance methods declared in the class or a `Subject` ancestor are operations.
  Private methods, properties, class/static methods, abstract methods without
  implementations, and ordinary non-subject classes are not jobs.
- Directory discovery, static job sources, and `functualize.jobs` entry points
  lower eligible methods into the same `JobDescriptor` and execution machinery
  as module functions. Plugin job providers can supply a subject class through
  the same static source; no subject-specific binding plugin is needed.
- A class has a required literal `job_group`. Each operation's sole canonical
  identity is `<job_group>.<method>` under existing name normalization. An
  address never creates another registered job. The descriptor records the
  class and method needed for deferred materialization, so cold and warm cache
  paths resolve the same callable and name.
- A canonical name claimed by a subject method and any other job is refused
  with both claimant locations named. It is never silently discarded. Plain
  function collision policy outside such a conflict is unchanged.

### Invocation and configuration

- A subject job requires a nonempty subject address separate from ordinary job
  arguments. The engine materializes the subject for that run and invokes its
  operation through the existing job engine. The typed subject object is the
  job's config model and includes the immutable address.
- Every operation of a subject class uses its `job_group` config section.
  Config fields not fixed by an address declaration resolve from the existing
  resolution chain, including its supported secret source. Address-declared
  field values have final precedence for that invocation: a CLI flag, request
  argument, environment variable, file, or vault value cannot replace them.
  An explicit conflicting field argument is refused rather than ignored.
- Subject fields use existing type validation and secret markers. Secret bytes
  do not appear in schema, `info`, `env`, command displays, errors, run records,
  or logs produced by framework surfaces. The operation receives the actual
  value. The address is recorded separately from canonical job identity.
- `info` and `env` report the same section and resolved subject fields that a
  run for the same job and address uses. Without an address, schema inspection
  can describe fields but must not claim instance values were resolved.
- Class and ancestor `job_tags` merge with method `@job(tags=...)` in stable
  order without duplicates. Other `@job` declaration values remain intact.
  A method-level group or config-section override conflicting with the class
  group is rejected; subject operations cannot drift into different sections.

## Acceptance criteria

| Requirement | Observable acceptance |
| --- | --- |
| R1.1 | A subject class in a job directory, a static source supplied by a plugin, and a `functualize.jobs` entry point each exposes its public operations through normal job discovery; no verb list or binding plugin is involved. |
| R1.2 | Two addresses invoke the same canonical descriptor. Restart and warm cache preserve the class/method identity and produce the same behavior as cold discovery. |
| R1.3 | Two classes claiming one canonical name, or a class method colliding with a module function, fail visibly with both claims named. |
| R1.4 | CLI and `RunRequest` each carry a subject address; the method sees that address on the constructed subject, and an absent/empty address fails before operation I/O. |
| R1.5 | A frozen typed subject resolves fields through the config chain. A real `Secret[str]` field is masked on user-facing and persisted run surfaces while the method receives the secret. |
| R1.6 | A fixed value supplied with the address wins over all config-chain tiers; a conflicting explicit field argument fails. The same value appears in introspection, masked when secret. |
| R1.7 | Two operations on one class read the same section; `get_job_config_section`, `info`, `env`, and actual execution agree. |
| R1.8 | Inherited and concrete class tags merge with `@job` tags without replacing category, guards, or other method declaration fields. Cold and warm metadata agree. |
| R1.9 | A public method of a non-`Subject` class remains undiscovered. Existing module function behavior is preserved. |
| R1.10 | `docs/guides/subjects.md` teaches the released class path, immutable per-address config, and no plugin verb enumeration; its examples are executable. |

The discovery tests cover each source path, collision path, and cache path.
An end-to-end CLI test follows declaration through resolution and execution.
`CHANGELOG.md` receives an entry under `[Unreleased]`. All native lint, type,
import, and test gates apply.

## Explicitly outside this slice

- Rise-specific declaration semantics, generated per-instance CLI routes,
  environment-tree authoring, and a new provider resolver.
- The scoped vault's nearest-ancestor and environment-qualified lookup. Its
  eventual integration uses the subject address carried on the request.
- Backward compatibility for the guide's plugin binding example, which is
  documentation of a prior practice rather than a core API contract.
