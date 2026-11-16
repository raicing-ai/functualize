# ADR-043: Rise Is a Convention on the Public API, Never a Dependency of Core

**Status**: accepted — specified, not implemented; Execute is gated on a released Functualize 0.5.0
**Date**: 2026-10-30
**Deciders**: owner, through shape intent SD/18153475 v28 and the canonical
model SD/5407068 v22 (both `Authority: Approved`), the §7 deltas confirmed in
MCH-151 comment `01a1539f-4b62-72e1-84fa-4e3f3d2702b3` on 2026-10-19, and the
answers of 2026-10-30 in MCH-151 comment `01a18d2e-c1b1`.

## Context

Rise defines typed operational subjects, contracts, observations, dependency
routing, and convergent operations. RiseKit supplies reusable authoring bases
and contract checks. A provider package owns contracts and implementations.
Functualize discovers, configures, and runs ordinary jobs. A Cloudflare Worker
plus D1 provider is the forcing case.

Before this decision, a documented subjects example listed verbs by hand, so a
changed verb meant edits in several places. Core could discover module
functions but not a job class's methods, and had no public resolved-secret
read. Both gaps belong to core prerequisites with their own owners, not to
Rise.

## Decision

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

- **Distributions.** `functualize-rise` defines the convention, commands, and
  routing. `functualize-risekit` depends on Rise and supplies typed substrate
  bases and conformance helpers without a provider.
  `functualize-rise-cloudflare` is a separate provider package. All three
  depend on Functualize public API only.
- **Declarations.** `Subject` is a frozen, typed, serializable pydantic model.
  Construction does no operational I/O. An abstract contract declares a
  namespace-owned `ns.name@major` identity, abstract operations, and a
  realization type; it is never a job class. A concrete implementation uses
  Functualize `@job(group=...)`. A concrete subject without a contract ancestor
  uses `local:<name>` identity.
- **Ordinary jobs.** Core class discovery exposes one ordinary Functualize job
  per method of the concrete job class. All its operations share the class
  group's config section and remain callable through
  `func <group> <operation>` without Rise. The concrete class itself owns
  ordinary jobs; Rise does not scan, rebind, or create a second loader.
- **The address stays in Rise.** Rise dispatches to the canonical job with
  explicit field values and the operation name; the subject address does not
  cross into core as an invocation input (SD/5407068 v22, Decision 23). The
  only core-side read derived from a subject address is the vault secret read
  at that address (F6). Rise adds no invocation input.
- **Secrets.** An unset secret comes from a public core vault read for
  `(group, field)` at the subject address under the active environment, with
  nearest-ancestor lookup. Secret bytes never appear in descriptors, findings,
  diagnosis, realizations, logs, or run records.
- **Prerequisites are consumed, not emulated.** A **released** Functualize 0.5.0
  must include class-based discovery (MCH-184) and scoped vault v3 (MCH-185).
  The public resolved-secret read is F6, a generic core amendment whose
  spelling belongs to the vault owner. Rise must not emulate them privately.

All plugin-to-core arrows use public API. Core-to-Rise arrows are forbidden.

## Consequences

### Positive

- A provider works with plain Functualize: its jobs run through
  `func <group> <operation>` with no Rise installed.
- Rise cannot grow a second discovery path, loader, or core invocation input,
  so core's peer layers stay independent and `_app/` stays the only composition
  root.

### Negative

- Rise cannot start before the core prerequisites ship in a released 0.5.0. An
  unmet prerequisite returns the feature to Specify rather than gaining a
  workaround.
- Contract subject, realization, and observation form parallel hierarchies.
  This is accepted: the typed realization and observation are binding shape
  requirements, and collapsing them would lose contract-specific types.

### Neutral

- Realizations go through a persistence Protocol with a local backend, because
  the shape requires a port that can support a later shared backend.
- Module names, builders, JSON schema details, and the F6 function name remain
  provisional where SD/18153475 §7 says so. Released 0.5.0 owns core API
  spelling.

## Alternatives Considered

| Alternative | Pros | Cons | Why rejected |
|-------------|------|------|-------------|
| Rise scans subject classes and binds their methods itself | No wait on core class discovery | A second loader beside core discovery; jobs would differ with and without Rise | B6: Rise adds no discovery path or job loader |
| Pass the subject address into core as an invocation input | Core could resolve per-address configuration directly | A Rise concept leaks into every core invocation | SD/5407068 v22 Decision 23: the address stays in Rise; F6 is the only address-derived core read |
| One `functualize-rise` distribution holding the toolkit and providers | Fewer packages | Providers would force RiseKit on users and tie provider releases to Rise | B3/B5: a provider works without RiseKit, and RiseKit carries no provider |

The full revision 7 record (spec, contracts, plan) is recoverable from
PR #132 at `673d2fc9`; see `.spec/STATUS.md` → *Rise / RiseKit foundation*.

## Addendum — where Rise's source lives (2026-11-12)

**Deciders**: maintainer, 2026-11-12, recorded in MCH-151. It chooses option C
of the topology recommendation posted there on 2026-11-11. The approved shape
SD/18153475 sets Rise's boundary but not its source repository; this addendum
records that choice.

**Decision.** Three repositories, each with one job:

| Repository | Visibility | Owns |
|---|---|---|
| `raicing-ai/functualize` (this one) | public | the Functualize public API that Rise depends on, and the durable record of the Rise convention: this ADR, ADR-044 and the `.spec/STATUS.md` entry |
| `raicing-ai/rise` | private | the source, tests, release workflow and product documentation of `functualize-rise`, `functualize-risekit` and provider distributions such as `functualize-rise-cloudflare`, during development |
| `raicing-ai/funccloud` | private | the workspace: pinned `functualize/` and `rise/` submodules, a check that builds the pinned pair together, and the private documentation wiki and coordination runbooks |

- **Rise stays private until it is usable.** Making it public, and publishing
  its packages, is a separate maintainer decision.
- **Rise keeps its own release cadence.** It does not ride Functualize's tags.
  It depends on a *released* Functualize, so the entry gate above is
  unchanged: a released 0.5.0 must contain class-based discovery (MCH-184)
  and scoped vault v3 (MCH-185), and F6 must exist as a public read.
- **A submodule is how FuncCloud consumes Rise, not where Rise lives.** The
  Rise source repository comes first; FuncCloud pins an existing commit of it.

**What this repository does not depend on.** No build step, test, CI job,
package dependency, submodule or documentation link in
`raicing-ai/functualize` reaches into `raicing-ai/rise` or
`raicing-ai/funccloud`. Everything here builds, tests and reads without
access to either. The boundary above (B1–B6) is unchanged: core imports no
Rise package, and Rise depends on the public Functualize API only.

**Private knowledge stays out of this repository.**

- Curated project memory, the private documentation wiki, repository maps
  and agent coordination runbooks live in FuncCloud's `docs/wiki/`. They are
  readable by members and agents granted FuncCloud access.
- Raw agent memory and transcripts live in the controlled memory service,
  outside Git.
- Secrets live outside every repository.
- Nothing of the above is committed here. A public commit cannot be
  retracted from existing clones, forks or caches, so internal plans, tenant
  details, transcripts or a copied token placed here would stay exposed.

**Order of work.**

1. This record, in this repository.
2. Seed `raicing-ai/rise`, which is empty today, with its default branch.
   Then open a scaffold PR there: repository rules, the spec workflow, a uv
   workspace, distribution skeletons, CI, and a check that Rise imports only
   the public Functualize API.
3. Open a FuncCloud PR that adds `rise/` as a submodule at an existing Rise
   commit, pins a compatible Functualize commit, adds the wiki repository
   map and bootstrap notes, and checks the pinned pair together.
4. After a released 0.5.0 meets the entry gate, implement Rise in Rise PRs.
   Advance FuncCloud's pins through reviewed FuncCloud PRs.

`raicing-ai/rise` therefore ends development as an **active private source
repository and FuncCloud submodule target**, neither empty nor archived.

### Consequences

- **Positive.** Rise develops privately on its own cadence. One FuncCloud
  checkout gives a reading workspace with both sources and the private wiki.
- **Negative.** A change that crosses the boundary is no longer one PR. It
  needs a source PR in each affected repository, then a FuncCloud pin PR,
  and that pin PR must report the exact pair of SHAs it tested. A recursive
  clone of FuncCloud is a reading workspace only: a superproject worktree
  does not create editable child worktrees, so parallel edits use separate
  source worktrees.
- **Superseded.** The earlier in-tree placement of the three distributions
  under `plugins/` in this repository, and their lockstep release with
  Functualize, are superseded. That placement appeared in the revision 6
  working record and in a 2026-11-01 recommendation.

### Alternatives considered

| Alternative | Why rejected |
|---|---|
| Rise under `plugins/` in public `raicing-ai/functualize` | The first commit would publish Rise before the maintainer considers it usable, and Rise would inherit Functualize's tags and release workflow. Its one advantage, atomic core-and-Rise PRs, does not outweigh that. |
| Rise source inside private `raicing-ai/funccloud` | FuncCloud would become Rise's release owner, and extracting Rise later would be a migration. |
| A new umbrella repository of submodules | It adds a second coordination home and another set of pins, and still makes no cross-repository change atomic. FuncCloud already serves that role. |
