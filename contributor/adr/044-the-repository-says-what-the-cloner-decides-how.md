# ADR-044: The Repository Says What, the Cloner Decides How — Rise's Selection and Command Surface

**Status**: accepted — specified, not implemented; Execute is gated on a released Functualize 0.5.0
**Date**: 2026-10-30
**Deciders**: owner, through shape intent SD/18153475 v28 (§5.2, §5.6, §7) and
the canonical model SD/5407068 v22 (Decisions 23 and 25), the §7 deltas
confirmed in MCH-151 comment `01a1539f-4b62-72e1-84fa-4e3f3d2702b3`, owner inline
comments 18808989 (registry Git source) and 18809013 (package install
targets), and the answers of 2026-10-30 in MCH-151 comment `01a18d2e-c1b1`.

## Context

A Rise declaration names subjects by contract, and more than one installed or
registry-listed candidate can satisfy a contract. Someone has to choose which
one runs, and the choice has to survive a policy change without silently
rerouting a running binding. The command surface also had two earlier
spellings to retire: `validate`/`diagnose` command names and a `--scope` flag.

This ADR sits on [ADR-043](043-rise-is-a-convention-on-the-public-api.md):
everything below runs ordinary Functualize jobs through public API.

## Decision

**Environment and addresses.** Functualize selects the configuration overlay
and vault environment; Rise has no `--env`. Positional addresses select
subjects or subtrees. With no address, `[rise] default` is a list of roots;
overlays replace that list wholesale. An explicit address wins over the
default list.

**Selection.** The committed repository declaration names the promise; its
configuration may `require` or `forbid` candidates. The cloner's user
configuration may `prefer` implementations. Selection order:

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
repository lockfile.

**Registry.** `[rise] registries` lists read-only HTTPS index URLs, disk paths,
or Git/GitHub repository references in order. A Git source may name an optional
revision and a path to a folder or one file holding the index. `func rise
search CONTRACT` reads these sources. Their entries are candidates marked
**available, not installed**, and appear in a dry-run plan. `up` refuses if a
selected candidate is uninstalled, suggesting `func rise add PACKAGE`; `up`
never installs a package. Only explicit `add` delegates to Functualize's plugin
install, checks a digest, records package and source in the local binding
record, then uses normal discovery.

**Install target.** The approved v1 `func rise add` target is option 1, a
Python package/plugin discovered by Python. Option 2, a global Functualize XDG
directory, and option 3, a repository-level `.functualize/` directory, are
explicit deferred targets; neither alters v1's `up` refusal or explicit `add`
rule.

**Commands.** `func rise up [ADDRESS...]` diagnoses, then runs convergent `up`
in dependency order where state differs. `--force-reconcile` runs `up` even if
diagnosis passes. `--dry-run` resolves, diagnoses, and prints actions and
candidate chains without mutation. `--no-deps` acts only on named addresses but
still diagnoses required dependencies and refuses if they fail. `--wait` and
`--wait-timeout` re-diagnose touched subjects.

`func rise ps [ADDRESS...]` runs `diagnose` and reports a table or NDJSON.
`func rise config [ADDRESS...]` runs `validate` and can render a masked tree.
`start` and `stop` invoke corresponding mutating operations when implemented.
`down` refuses in v1. Several positional addresses are allowed. The prior
`validate`/`diagnose` command names are superseded by `ps`/`config`. The prior
`--scope` flag is replaced by positional addresses. The owner approved this on
2026-10-30 (MCH-151 comment `01a18d2e`), and SD/5407068 v22 specifies
positional addresses in Decisions 23 and 25.

There is no Rise `--env` flag, `--scope` flag, or `--yes` choice shortcut.
Rise uses Functualize exit codes: 0 success, 1 failure or findings, 2 usage
error, and 3 refusal.

## Consequences

### Positive

- Two clones of one repository may hold different uncommitted bindings, and
  neither repository policy drift nor a new registry entry changes what a clone
  already runs; drift appears in `ps`.
- `up` never has an install side effect: a missing candidate is a refusal with
  the `add` command to run.

### Negative

- A tie between candidates refuses rather than guessing, so a cloner with no
  preference and no binding must choose once.
- Registry index JSON, the `rise-lock.json` path and schema, the Git source
  spelling and folder convention, and the implicit dependency address spelling
  remain provisional under SD/18153475 §7; tests must assert behavior without
  freezing those spellings.

### Neutral

- Registry signing, publishing, and trust policy are later layers.
- Approver authentication, Merge/Deploy authority, OAuth, Worker secret
  delivery/runtime integration, target preview, and destructive adoption are
  outside this foundation.

## Alternatives Considered

| Alternative | Pros | Cons | Why rejected |
|-------------|------|------|-------------|
| `--scope <address>` flag | One spelling for a single subtree | Departs from the `docker compose up <service>...` shape the canonical model names | Owner answer of 2026-10-30; SD/5407068 v22 Decisions 23 and 25 specify positional addresses |
| Repository preference outranks the cloner's | The repository author controls every clone | The repository says *what*; the person who cloned it decides *how* (SD/18153475 §5.6) | Hard constraints stay with the repository as `require`/`forbid`; soft `prefer` ranks below the cloner |
| `up` installs a selected registry candidate | One command to converge | An implicit install side effect on a convergent operation | §7: `up` never adds a package; only explicit `add` installs |
| A committed, portable lockfile | Reproducible bindings across clones | Bindings are machine provenance, and two clones may legitimately differ | `rise-lock.json` is local, never committed |

The full revision 7 record (spec, contracts, plan) is recoverable from
PR #132 at `673d2fc9`; see `.spec/STATUS.md` → *Rise / RiseKit foundation*.
