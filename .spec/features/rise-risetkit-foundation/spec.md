# Rise / RiseKit foundation — specification

Status: **Revision 7, specification only. Execute is gated** on a released
Functualize 0.5.0 containing the prerequisite core features.

## Authority and scope

Shape intent SD/18153475 v21 has `Authority: Approved`. Page v26 still reads
`Approved` and marks the three earlier post-approval deltas binding. The owner
confirmed them in MCH-151 comment `01a1539f-4b62-72e1-84fa-4e3f3d2702b3`
on 2026-10-19. This page consolidates SD/5407068 and governs revision 7.
The branch starts at `origin/master` `91947bb4f90c611d588de9907f84e61edf2c1514`.
Revision 6's research and task graph remain on the revision 6 branch as
history. They are not copied into this branch because its execution tasks
conflict with the approved revision 7 shape.

Rise defines typed operational subjects, contracts, observations, dependency
routing, and convergent operations. RiseKit supplies reusable authoring bases
and contract checks. A provider package owns contracts and implementations.
Functualize discovers, configures, and runs ordinary jobs. A Cloudflare Worker
plus D1 provider is the forcing case.

**Boundary B1–B6.** Core imports no Rise package and this feature changes no
`src/functualize/` module. Core prerequisites have separate owners. A provider
using Rise without RiseKit works; RiseKit adds no semantics Rise cannot judge.
Rise invokes provider operations through `Invoke`, never by calling them
directly. RiseKit carries no provider; the Cloudflare provider has its own
distribution. Rise adds no discovery path or job loader.

```text
provider package -> RiseKit -> Rise -> public Functualize API
provider package ------------> Rise -> public Functualize API
```

## Declaration and identity

**S1.** `Subject` is a frozen, typed, serializable pydantic model. Construction
does no operational I/O. An abstract contract declares a namespace-owned
`ns.name@major` identity, abstract operations, and a realization type; it is
never a job class. A concrete implementation uses Functualize
`@job(group=...)`. A concrete subject without a contract ancestor uses
`local:<name>` identity.

**S2.** Core class discovery exposes one ordinary Functualize job per method
of the concrete job class. All its operations share the class group's config
section and remain callable through `func <group> <operation>` without Rise.
Rise infers roles: `validate` and `diagnose` read-only; `up` and `update`
convergent; `start` and `stop` mutating; `down` destructive; other verbs
mutating unless the contract declares `@role("read-only")`. Generated
`rise:op:*`, `rise:implements:*`, and `effect:*` tags merge with the author's
own `@job(...)` declaration.

**S3.** An ordinary lazily evaluated job returning `Environment` declares a
tree of subject instances. Dotted addresses name nodes. `Ref[T]` is required;
`Ref[T] | None` is optional. A required child's failure fails its parent; an
optional child's failure is shown without failing the parent. Each subject is
observed once per diagnosis. Dependencies introduced only by a selected
candidate become implicit subjects, one per environment and contract, with a
provisional `~` address form.

**S4.** Descriptors are generated on demand from declarations, cached locally,
and never hand-maintained or committed. They contain identities, operations,
roles, schemas, relations, and realization types, with no secret values. A
realization records subject, contract, candidate, identity, configuration
fingerprint, isolation, time, and dependency chain through a persistence port
with a local backend. Destructive operations require positive identity and
ownership; `down` is refused in v1.

## Configuration and secrets

**S5.** Functualize selects the configuration overlay and vault environment;
Rise has no `--env`. Positional addresses select subjects or subtrees. With no
address, `[rise] default` is a list of roots; overlays replace that list
wholesale. An explicit address wins over the default list.

**S6.** An environment-declared literal travels as an ordinary explicit field
value. An unset secret comes from a public core vault read for `(group, field)`
at the subject address under the active environment, with nearest-ancestor
lookup. Other unset fields follow Functualize's environment, shared job-group
section, and default resolution. Rise adds no invocation input. Secret
literals in source declarations are validation findings. Secret bytes never
appear in descriptors, findings, diagnosis, realizations, logs, or run records.

## Policy, local binding, and registry

**S7 — confirmed Q-6/Q-9 delta.** The committed repository declaration names
the promise; its configuration may `require` or `forbid` candidates. The
cloner's user configuration may `prefer` implementations. Selection order:

1. Contract compatibility plus repository `require`/`forbid` filter candidates.
2. A recorded local binding stays chosen unless explicitly changed.
3. A one-off `--choose ADDRESS=CANDIDATE` changes and records the binding.
4. The cloner's per-contract and general preferences rank candidates.
5. Repository soft `prefer`, then package recommendation, rank remaining ones.
6. Rise reuses what is present, then prefers project-local and per-user
   installation; host-wide installation requires an explicit choice.

An unresolved tie refuses. Policy changes never silently reroute a binding.
Bindings and dependency chains live in local, never-committed `rise-lock.json`;
`.functualize/rise-lock.json` is its provisional path and is covered by the
scaffolded `.functualize/` ignore rule. It is machine provenance, not a portable
repository lockfile. Candidate dependencies resolve recursively by the same
rules and use a thin `Requires[...]` handle that invokes the chosen job.

**S8 — confirmed Q-8 delta, extended by owner comment 18808989.**
`[rise] registries` lists read-only HTTPS index URLs, disk paths, or
Git/GitHub repository references in order. A Git source may name an optional
revision and a path to a folder or one file holding the index. The exact
source spelling and folder convention remain provisional. `func rise search
CONTRACT` reads these sources. Their entries
are candidates marked **available, not installed**, and appear in a dry-run
plan. `up` refuses if a selected candidate is uninstalled, suggesting
`func rise add PACKAGE`; `up` never installs a package. Only explicit `add`
delegates to Functualize's plugin install, checks a digest, records package
and source in the local binding record, then uses normal discovery. Registry
order resolves duplicate package names. Index JSON spelling is provisional;
signing, publishing, and trust policy are later layers.

**S8a — owner comment 18809013.** The approved v1 `func rise add` target is
option 1, a Python package/plugin discovered by Python. Option 2, a global
Functualize XDG directory, would make the installation available across
projects and needs global lifecycle rules. Option 3, a repository-level
`.functualize/` directory, would scope installation to one repository and
needs a repository package and trust model. Options 2 and 3 are explicit
deferred targets; neither alters v1's `up` refusal or explicit `add` rule.

## Commands, records, and refusals

**S9 — confirmed Q-3 delta.** `func rise up [ADDRESS...]` diagnoses, then runs
convergent `up` in dependency order where state differs. `--force-reconcile`
runs `up` even if diagnosis passes. `--dry-run` resolves, diagnoses, and prints
actions and candidate chains without mutation. `--no-deps` acts only on named
addresses but still diagnoses required dependencies and refuses if they fail.
`--wait` and `--wait-timeout` re-diagnose touched subjects.

`func rise ps [ADDRESS...]` runs `diagnose` and reports a table or NDJSON.
`func rise config [ADDRESS...]` runs `validate` and can render a masked tree.
`start` and `stop` invoke corresponding mutating operations when implemented.
`down` refuses in v1. Several positional addresses are allowed. The prior
`validate`/`diagnose` command names and `--scope` flag are superseded.

**S10.** Each NDJSON diagnosis line has a flat universal envelope and one
typed `observation`. Status is `pass` or `fail`; parent records refer to child
records rather than copying them. Ordering is deterministic; cycles are
findings before traversal. Rise uses Functualize exit codes: 0 success,
1 failure or findings, 2 usage error, and 3 refusal.

## Acceptance criteria

| # | Observable result |
|---|---|
| AC-1 | An ADR and package boundaries agree; core has no Rise import and a hand-written provider works without RiseKit. |
| AC-2 | A concrete `@job(group=...)` subject exposes ordinary jobs, preserves author metadata, and works without Rise. |
| AC-3 | Environment addresses, required/optional `Ref`, `[rise] default` overlays, field precedence, and subject-address vault reads behave as S3–S6. |
| AC-4 | `config` reports malformed declarations; `ps --format json` emits stable referential NDJSON with one observation per address and masked secrets. |
| AC-5 | `up` converges in dependency order, is idempotent, honors `--force-reconcile`, `--dry-run`, `--no-deps`, and `--wait`, and records a realization. |
| AC-6 | Repository hard constraints filter; local binding stays stable; explicit choice changes it; cloner preference outranks repository soft preference; ties refuse; two clones may hold different uncommitted bindings. |
| AC-7 | Registry search and dry-run expose available packages; `up` refuses before installation; only explicit `add` installs via Functualize and records the checked digest and source. |
| AC-7a | Registry lookup accepts HTTPS, disk, and read-only Git/GitHub sources, including optional revision and folder/file selection; global XDG and repository-level package installation remain deferred. |
| AC-8 | Exit codes 0/1/2/3, `start`/`stop` dispatch, v1 `down` refusal, and an offline Cloudflare Worker plus D1 forcing case pass through the public CLI. |
| AC-9 | A live Cloudflare tier runs only with credentials and confines created resources to a test prefix. |

These are planned gates, to be re-derived against released APIs before any
Execute task closes. Revision 7 adds no runtime code.

## Dependencies and exclusions

A **released** Functualize 0.5.0 must include class-based discovery (MCH-184)
and scoped vault v3 (MCH-185). The public resolved-secret read is F6, a generic
core amendment whose spelling belongs to the vault owner. Run tags are a
separate core feature. Rise consumes these without designing them here.

Instance routes, `Setting()` markers, run-record source provenance, Gate
resolution from ordinary jobs, and person-required mechanics have separate
owners. Approver authentication, Merge/Deploy authority, OAuth, Worker secret
delivery/runtime integration, target preview, destructive adoption, registry
signing, trust policy, and publishing are outside this foundation.
