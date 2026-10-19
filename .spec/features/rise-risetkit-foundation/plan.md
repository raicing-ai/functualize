# Rise / RiseKit foundation — plan

Revision 7 plan for `spec.md` and `contracts.md` on a branch from
`origin/master` `91947bb4f90c611d588de9907f84e61edf2c1514`.
This is an artifact revision, with no implementation or Execute task closure.
The revision 6 `tasks.md` remains on its original branch. It must be replanned
and reviewed before Execute. A released 0.5.0 containing the core
prerequisites remains the entry gate.

## Alignment

**Shape intent:** [SD/18153475](https://raicing-ai.atlassian.net/wiki/spaces/SD/pages/18153475)
v26, `Authority: Approved`; approved body v21, owner-confirmed §7 deltas in
MCH-151 comment `01a1539f-4b62-72e1-84fa-4e3f3d2702b3`, and owner inline
comments 18808989 (registry Git source) and 18809013 (package install targets).
The v25→v26 page diff adds only those two comments' guidance in §5.6 and §5.2.
The page consolidates SD/5407068; its approval header was untouched.

**In scope, in the shape's own words:**

| Shape wording | Planned surface |
|---|---|
| "The implementation is a Functualize job class" and "Rise adds no new invocation input" (§7) | Concrete `@job(group=...)` provider; Rise passes ordinary explicit field values through `Invoke`. |
| "Verbs `up`, `ps`, `start`, `stop`, `down`, `config` under `func rise`, with positional `ADDRESS...`" (§7) | Compose-style command jobs; `down` refuses in v1. |
| "Flag `--force-reconcile`" (§7) | The confirmed re-run spelling. |
| "The repository says *what*; the person who cloned it decides *how*" (§5.6) | Repository `require`/`forbid`, cloner `prefer`, stable local bindings and dependency chains. |
| "`rise-lock.json` is local, never committed" (§7) | Per-machine realization and binding provenance; `.functualize/rise-lock.json` remains a provisional path. |
| "A registry is a read-only **index file**" (§5.6) and "`up` never adds a package" (§7) | `search`, explicit `add`, available candidates in dry-run plans, refusal before installation. |
| "The registry index should be able to reference a github / git repository folder / file structure" (inline 18808989) | Read-only Git/GitHub registry sources with optional revision and folder/file selection; spelling provisional. |
| "Adding / using a rise package could be" a Python plugin, global XDG directory, or repo-level directory (inline 18809013) | V1 keeps the approved Python plugin `add` path; global and repo-level targets are named deferrals. |
| "The North Star forcing slice" (§4 and §8) | Separate Cloudflare Worker plus D1 provider and offline forcing test. |

**Out of scope, in the shape's own words:** "designing core interfaces",
"approver authentication, Merge/Deploy authority and OAuth", "Worker secret
delivery and the runtime integration", "a target preview", and "Rise as a
deployment engine itself" (§8). Class-based jobs belong to SD/18317314 and
the public vault read F6 to the SD/12779576 amendment. Run tags belong to
SD/18972686. Registry "Signing and trust stay later layers" (§5.6).

## Architecture gate

### BEFORE — current base

```text
Public audience                         Internal audience / layer
docs/guides/subjects.md                 _discovery/ (peer): directory scan ignores classes
  subject class practice ──────────────> _app/boot.py (composition root)
  hand-listed plugin binds methods       └── wires providers to discovery
src/functualize/plugin/ (public) ──────> _discovery/providers.py (peer)
src/functualize/job/ (public) ─────────> _engine/capabilities/invoke.py (peer)
src/functualize/app/vault.py (public) ──> _config/ vault internals (peer)
  put / inspect / remove; no public resolved-secret read
src/functualize/_primitives/vault_identity.py (foundation): environment field
```

Core's peer layers are independent; `_app/` composes them. The codemap
`overview.md` states this boundary, and `modules.md`, `dependencies.md`,
`data-flow.md`, and `entry-points.md` identify the discovery, config, engine,
plugin, and CLI entry paths. On this base, a documented subjects example lists
verbs by hand: **Shotgun Surgery** when a verb changes. Class discovery and
the public vault read are **Incomplete Library Class** gaps owned outside Rise.
Plain dotted addresses scattered through a future implementation would cause
**Primitive Obsession**; the plan retains one address value object.

### AFTER — target once 0.5.0 prerequisites are released

```text
user jobs/environments.py: Environment declaration
  └── constructs provider subject instances, Ref edges
plugins/domains/functualize-rise-cloudflare (provider)
  └── contract + concrete @job(group=...) class
       └── plugins/domains/functualize-risekit (toolkit, no provider)
            └── plugins/domains/functualize-rise (convention and CLI)
                 ├── identity / declaration / descriptor
                 ├── validate / diagnose / realization port
                 ├── router / local binding / read-only registry
                 └── up / ps / config / start / stop / search / add
                      └── public Functualize job, plugin, app, types API
                           ├── _app/ (composition root)
                           ├── _discovery/ (peer: class jobs)
                           ├── _config/ (peer: group and vault resolution)
                           ├── _engine/ (peer: Invoke dispatch)
                           └── _primitives/ (foundation: vault identity)
```

All plugin-to-core arrows use public API. Core-to-Rise arrows are forbidden.
The concrete class itself owns ordinary jobs; Rise does not scan, rebind, or
create a second loader. A subject address stays within Rise. Core receives
ordinary explicit fields; the public vault read returns a resolved `Secret`.
The registry adds **candidate metadata**, never an implicit install side
effect to `up`.

The earlier candidate AFTER registered only three Rise commands and let one
candidate either win or refuse. Revision 7 requires compose-style verbs and
recursive candidate chains. Folding both into a monolithic `up.py` would
introduce **Divergent Change** (routing, registry parsing, diagnosis, and
dispatch each change for different reasons). Keep their responsibilities
separate and share one selection result. No new internal core cross-import is
needed. The exact module split is a Plan hypothesis to check when tasks are
re-derived against the released API, not a settled public interface.

### Retrieval and design advice

- `zg` was indexed for this checkout and queried for subject/provider prior
  art. It surfaced `docs/guides/subjects.md`; the current code was also checked
  at `_discovery/providers.py`, `_app/configuration_facade.py`, and
  `app/vault.py`. `rg` verified the scaffolded `.functualize/` ignore rule and
  that this checkout has no `v0.5*` tag.
- Serena's symbol overview read `_discovery/providers.py` in this checkout;
  graphify's `StaticProvider` neighbors show construction in `_app/boot.py`.
  The graph is used for dependency direction, not current line numbers.
- The repository `python-design-patterns` skill guided the separation of
  routing, registry I/O, and execution. `design-patterns-refactoring` supplied
  the smell names and the Strategy reading of interchangeable candidates.

## Surviving smells

| Smell | Where | Why accepted | Maintainer review? |
|---|---|---|---|
| **Parallel Inheritance Hierarchies** | Contract subject, its realization, and observation | The typed realization and observation are binding shape requirements; collapsing them would lose contract-specific types. | No |
| **Speculative Generality** | Realization persistence Protocol with a local backend | The shape explicitly requires a port that can support a later shared backend; a Protocol satisfies the repository's port rule. | No |

The core **Incomplete Library Class** gaps remain external prerequisites, not
compromises in Rise. The revised AFTER has no accepted peer-layer cross-import,
global mutable registry, ABC port, or hard-coded user config path.

## Technical approach for the next iteration

1. Before editing runtime code, verify the **released** 0.5.0 against class
   discovery, shared class configuration, merged declarations, scoped vault
   v3, and the public resolved-secret read. Capture actual call shapes. An
   unmet item returns the feature to Specify rather than gaining a workaround.
2. Re-plan `tasks.md` into ordered waves with a parseable dependency graph.
   The revision 6 tasks still name `rise validate`, `rise diagnose`,
   `--scope`, and a single-candidate router; they are not executable as r7.
   Review the task list and surviving smells before Execute.
3. Specify the Rise package boundary, then implement identities, declaration
   metadata, environment traversal, validation, diagnosis and realization.
   Every production path gets a public-entry test and reachability sabotage
   after a safe commit.
4. Add a separate resolver for contract candidates and their dependency
   chains, reading repository constraints, local bindings, cloner preferences,
   and registry metadata in the approved order. Accept HTTPS, disk, and
   read-only Git/GitHub sources. Keep `up` free of package installation. Test
   two clones with different local bindings and record the two deferred
   install targets for a later design.
5. Expose the compose-style command jobs, the explicit `search`/`add` path,
   RiseKit's remote-resource substrate, and the separate Cloudflare provider.
   Prove the offline case first; gate the live tier on credentials.

## Files, gates, and risks

This artifact step changes only `spec.md`, `contracts.md`, and `plan.md` in
`.spec/features/rise-risetkit-foundation/`. The revision 6 `research.md` and
`tasks.md` remain recoverable on their original branch; copying the obsolete
task graph into this branch would make it look executable. No production files
or dependencies change in this step.

Before Execute, the revised task file must supply file scopes found through
current references and acceptance gates run against released APIs. The release
gate currently fails because this checkout has no `v0.5*` tag and class
discovery has not been delivered. The public vault read may also need its
generic amendment even though scoped vault v3 has merged. Registry index JSON,
`rise-lock.json` path/schema, and implicit dependency address spelling remain
provisional under §7, so tests must assert behavior without freezing those
spellings prematurely. Secret masking, local binding stability, and refusal
before installation need end-to-end evidence.
