# 01 — The Vocabulary: Substrate, Action, Target

rise's type system, restated on three orthogonal axes. This replaces the
eight-kind enum of `intent/03-type-system.md`, and keeps those eight
names as presets.

The long argument for the split lived in the superseded oop-v2 package
("rethinking kinds", §2), which is not carried into this repo; the short
version is §1 below and is sufficient. The payoff is that repositories, dual-detected
tools, and modules that *act on* something all become sayable.

## 1. Why not eight kinds

`kind` claims to answer "what is it?", but across the eight rows "it" means six
different things: `program`/`library` are **detection strategies** (the intent
says so outright — "the decisive difference is how existence is detected"),
`service` is an **action set**, `workflow`/`registry` are **composition
shapes**, `meta` is a **scope**, `host` is a **subject**, `base` is null.

Three consequences that bite:

- **functualize itself is unrepresentable.** `pip install functualize` yields
  an importable package *and* a `func` console script — verified. Under eight
  kinds you pick one and lie. Same for ruff, pytest, uv.
- **`Service` and `Daemon` are the same contract** at two scopes
  (start/stop/restart/status, ±`logs`/`test`). The `(kind, interface)` scoping
  table exists to hide the duplication.
- **No kind targets a repository**, so `pipeline-readiness/acceptance/code_audit`
  has no home. `git` is an *interface* meaning "my lifecycle is under source
  control" — reflexive, and scoped to `service`/`program`, so a pipeline cannot
  claim it anyway.

## 2. Axis 1 — Substrate: what it is, hence what "present" means

A substrate defines presence and shapes the diagnosis block. That is all it
does; it carries no actions.

| Substrate | Present means | Diagnosis block |
|---|---|---|
| `Executable` | resolvable on `PATH`, and runs | path, origin, version, `runs_correctly` |
| `Package` | importable in its runtime | spec location, version, language, manager, `source` (`07` §6) |
| `Process` | a supervised runtime responds | running / stopped / unknown, pid, uptime |
| **`Repository`** | a working tree exists at a resolvable revision | url, path, sha, branch, dirty, ahead/behind |
| `Machine` | reachable | reachability, platform, arch |
| `Endpoint` | a remote probe answers | url, status, latency, auth mode |
| `Artifact` | files exist and are fresh | paths, hashes, produced-at |
| `Nothing` | presence is not meaningful | — |

Presence is one Protocol, not a per-kind special case:

```python
@runtime_checkable
class Detectable(Protocol):
    def presence(self) -> Presence: ...
```

`program` vs `library` becomes what the intent said it was: two implementations
of `Detectable`.

**A module may declare more than one substrate.** `functualize` is
`Executable + Package`; its record carries both presence blocks, which is
strictly more truthful than choosing.

## 3. Axis 2 — Actions: what you can do to the subject, as Protocols

```
Installable    install(), uninstall()
Runnable       run(args)
Controllable   start(), stop(), restart(), status()      ← was Service AND Daemon
Loggable       logs()
Backupable     backup(), restore()
Updatable      update(), version
Syncable       clone(), pull(), push()                   ← covers repo-as-subject
```

The `(kind, interface)` scoping table **disappears**. What replaces it is a
`supports` tuple on each substrate — a property of the substrate rather than a
pair table, and one a project-local substrate can state for itself.

`runtime_checkable` checks method *presence* only — not signatures, not
non-method members. So the ladder does not lean on it alone: mypy covers
signatures (`02` §6).

## 4. The test an action must pass

> An action Protocol names something you can **do to the subject**.
> If it names what the module **computes**, it is a pipeline shape — and
> pipeline shapes are ordinary methods, not vocabulary.

Every surviving protocol passes as a verb against the subject: install *the
executable*, start *the process*, back up *the service's state*, pull *the
repository*, update *the package*, read *the process's logs*.

**Three candidates fail it**, and all three are excluded above:

- **`Auditable`** (`scan()`/`report()`) — proposed in v2 and **withdrawn**. It
  named the module's own pipeline stages. It also did no work in its own worked
  example (§6 below), fit only 4 of 11 plausible repo-targeting modules, and
  what those four share is a *result data shape* that
  a separate pipeline-library design already owns: *"functualize orchestrates
  work; the library materializes it."*
- **`Pipelined`** (build/test/lint/deploy/clean/dev) — the intent's
  `continuous-integration`. Same error, but pre-existing vocabulary the intent
  owns, so flagged rather than deleted. Under the reframe `Workflow` is better
  as `Nothing` plus ordinary methods.
- **`Aggregating`** (members/bootstrap) — aggregation is composition, which
  substrates plus child projects already express.

Repositories need **no new action**: `Syncable` covers everything you can
do *to* a repo.

## 5. Axis 3 — Target: what it acts upon

The axis rise never had, and the one that gives `code_audit` a home.

```python
class Target(BaseModel):
    """A subject a module acts on but does not claim to be."""

class RepositoryTarget(Target):
    url: str
    rev: str = "HEAD"          # branch, tag, or sha
    path: Path | None = None
```

A target is declared, diagnosable and fingerprintable. Its resolved identity
flows into three places:

1. the **diagnosis record** — provenance: what did I look at?
2. the job's **fingerprint** — the resolved sha is an input, so staleness is
   revision-aware, not merely byte-aware;
3. the **audit log** — findings are attributable to a revision.

Isolation stays a tag, orthogonal to all three axes.

## 6. `code_audit`, expressed

```python
class CodeAudit(Nothing):
    group = "audit"
    target = RepositoryTarget(url="https://github.com/acme/service", rev="main")

    def parse(self) -> Parsed: ...
    def check(self, parsed: Parsed) -> Findings: ...
    def annotate(self, findings: Findings) -> None: ...
    def report(self, findings: Findings) -> None: ...
```

No action protocol — one substrate, one target, four ordinary methods that
become four jobs. Against what the case needs:

| Need | Satisfied by |
|---|---|
| identify the subject | `target`, declared and AST-readable (`02` §5) |
| key findings to a revision | the target's resolved sha, in the record |
| detect staleness | the sha in the fingerprint — a branch switch with identical bytes **is** a change |
| report provenance | "computed at `abc123`; tree is now `def456`" |
| survive regeneration | the existing notes sidecar, unchanged |

Every win comes from Axis 3. That is the evidence that `Auditable` was
ceremony.

## 7. The eight kinds survive as presets

```python
Program  = Executable + Installable + Runnable          # + isolation required
Library  = Package    + Installable + Updatable
Service  = Process    + Controllable + Loggable
Host     = Machine
Meta     = Nothing                                       # scope tag: framework
Base     = Nothing
Workflow = Nothing                                       # + ordinary methods (§4)
Registry = Nothing                                       # + composition (§4)
```

Existing modules keep their spelling. What changes is that presets are no
longer the *only* legal shapes.

Newly sayable, none of which was expressible before:

| Module | Shape |
|---|---|
| `functualize` | `Executable + Package + Installable + Runnable` |
| a required sibling repo | `Repository + Syncable` |
| `code_audit` | `Nothing`, `target=RepositoryTarget(...)` |
| a git-backed service | `Process + Controllable + Syncable` |

## 8. Enforcement

Five layers, earliest first.

| # | Layer | When | Mechanism | Catches |
|---|---|---|---|---|
| 1 | authoring | edit time | mypy | missing methods, **wrong signatures**, wrong attribute types |
| 2 | import | module import | Python | unknown substrate, strategy-as-action, dot-notation bases |
| 3 | instantiation | binding | `@abstractmethod` | missing required action **[probed]** |
| 4 | binding checks | binding | the adapter (`03` §4) | tags, illegal action for the substrate, config, reserved names, boolean flag collisions, shadowed vocabulary |
| 5 | runtime | `rise validate` | `Resource.validate` | 3–4 re-run as structured findings, plus record validation |

Layer 5 is not redundant: 3 and 4 raise, 5 *reports*, and the intent asks for a
verdict over a whole tree (criterion 15) — which cannot be built on exceptions
that abort binding.

## 9. Closed, and extensible

- **Closed** where it matters: substrates and action Protocols are fixed
  sets in `risekit.core`. The combinations grow; the vocabulary does not.
- **Extensible** per project: a project-local substrate is a subclass of
  `Substrate`, validated by the same binding path as a built-in (`10` §2).
  There is no second validation authority.
