# rise-on-functualize — v3

> **This directory is self-contained. Nothing outside it is needed to read the
> design or start the work.**
>
> It is the seventh and current pass of a design worked out in a separate
> scratch corpus during 2026-09-04 → 09-08. The six superseded passes — an
> implementation-neutral intent package, three earlier functualize mappings, a
> scrill/rise relationship study, and a vision brief — are **not carried here**
> and are not needed. Where one is cited below, it is named in prose without a
> link, because the file does not exist in this repository and never will.
>
> Two things travelled with the corpus rather than being left behind, because
> the design is unreadable without them:
>
> - [`intent/`](intent/) — the vision and the 69 acceptance criteria this design
>   is scored against, imported verbatim with per-file status banners and a
>   divergence ledger.
> - [`evidence/`](evidence/) — 19 runnable probes. They import functualize from
>   *this* repository, so they can be re-run here directly, and **probe 11
>   already drifted**: see the drift table in `evidence/README.md`.
>
> What the superseded passes settled, in one line each, so nothing is lost:
> the name `risekit` began as a placeholder for a package that could not be
> called `rise` (the CLI already was); the OOP direction made types classes
> rather than declarations; **scrill is not a package** ([`15`](15-scrill.md)
> §5); and the shared-kernel question resolved to `risekit.core` with no fourth
> distribution ([`17`](17-subject-modeling.md) §1).

The design for **risekit**: rise's vocabulary and guarantees, realized on
functualize **0.2.3**.

v3 supersedes the earlier oop-v2 pass. Three things changed, and each
of them changed the architecture rather than the prose:

1. **The vocabulary is now three axes, not eight kinds** (`01`). v2 carried
   the eight-kind model and argued against it in an appendix; v3 makes the
   substrate / action / target split primary, which is what gives
   repositories a home and `code_audit` a kind.
2. **Binding goes through a plugin, not through `register_dynamic_job`**
   (`03`). Probed: a provider added from inside `plugin.__call__(app)` reaches
   the registry *with its parameters intact* — which downgrades v2's one
   blocking upstream ask from blocker to nice-to-have.
3. **rise ships as both a `func` plugin and its own CLI** (`04`), from one
   binding object. This was not in v2 at all.

Plus `07`, which answers how a functualize project should declare its Python
requirements and where rise's `Library` does and does not belong.

## Verification basis

Every mechanism claim cites `path:line` into functualize **0.2.3**
(`origin/master`, commit `a2f453d`). **[probed]** marks claims executed against
a detached worktree of that commit; the scripts and transcript are in
`evidence/`.

The scrutiny record — how v2's findings were derived, and the two corrections
made to them — stayed in the oop-v2 scrutiny record, which is deliberately
not carried here. v3 carries the *conclusions* (`00`), not the argument.

## What v3 corrects in v2

| v2 said | v3 says | Why |
|---|---|---|
| `add_job_provider` never reaches the registry (F4) | It does, **when called during plugin load** — plugins run at boot step 4, job resolution at step 9 (`_app/boot.py:535` vs `:988`) **[probed]** | v2 only probed the post-constructor call, which is genuinely too late |
| `register_dynamic_job` is the only viable path (F3/F4) | It is the *fallback*; the plugin provider path is better and loses nothing **[probed]** | — |
| P1 (`parameters=[]`) is a **blocker** | Still a real defect, no longer blocking — the provider path extracts parameters **[probed]** | `13` §1 |
| `Auditable` action for audits | **Withdrawn** — it named what a module computes, not a verb against a subject | `01` §4 |
| Eight kinds, with a reframe in an appendix | Three axes, with the eight kinds as presets | `01` |

## Where to start

The full package is ~3,500 lines. The **orientation path is ~600** and enough
to understand the direction:

| # | Read | Why |
|---|---|---|
| 1 | this README | what changed, and what it supersedes |
| 2 | [`17-subject-modeling.md`](17-subject-modeling.md) | the newest and most consequential decision — the split between functualize and risekit. Read it *second*, not last |
| 3 | [`01-vocabulary.md`](01-vocabulary.md) | the three axes. The actual idea |
| 4 | [`15-scrill.md`](15-scrill.md) §5 | where scrill went (it dissolved into a convention + a generator + three upstream asks) |
| 5 | [`11-architecture.md`](11-architecture.md) §1–2 | the package layout and the 13-step build order, executed in the separate `risekit` repository |
| 6 | [`14-risks-decisions.md`](14-risks-decisions.md) | what is settled, and what is not |

For *why any of this exists*, read [`intent/01-vision.md`](intent/01-vision.md)
first — it is the only file in the corpus that answers that question.

## Reading order

| File | Contents |
|---|---|
| [`intent/`](intent/) | **the vision and the 69 acceptance criteria** — imported from `rise-intent/`, with a divergence ledger. The *why* and the measure of success |
| `00-baseline.md` | What functualize 0.2.3 gives, what it does not, and the ten facts rise must not assume away |
| `01-vocabulary.md` | **Substrate / action / target.** The `Repository` substrate; the test an action must pass |
| `02-module-model.md` | The class: declaration, the AST reader, the constructor contract |
| `03-binding.md` | Class → jobs, through the plugin provider path **[probed]** |
| `04-delivery.md` | **rise as a `func` plugin and as its own CLI**, from one object |
| `05-diagnosis-validation.md` | Meta-reflected `diagnose`/`validate`; derived and exported schemas |
| `06-registry-variants.md` | Tools, variants, lockfile — and repositories as first-class subjects |
| `07-dependencies.md` | How a project declares its Python requirements; where rise's `Library` belongs |
| `08-safety-audit.md` | Guards, isolation, the TTY host-guard, audit, the twice-run prover |
| `09-surface-scaffold.md` | The command surface in both deliveries; `rise new` |
| `10-extension-model.md` | Subclassing; what version pinning can and cannot mean |
| `11-architecture.md` | Package layout, build order, the tests that pin each probed claim |
| `12-acceptance-mapping.md` | All 69 intent criteria, re-scored under the three-axis vocabulary |
| `13-upstream-asks.md` | What functualize should add, re-prioritized for 0.2.3 |
| `14-risks-decisions.md` | Residual risks and the decisions that need a call |
| `15-scrill.md` | Scrill: a job that ships its skill, a skill that ships its scripts — four shapes, human + agent lifecycles, upstream asks 6–8 |
| `16-skill-to-workflow.md` | The skill compiler: prose procedure → `@workflow` with `ai_inbound`/`ai_outbound` gates; the compile target already ships |
| `17-subject-modeling.md` | **The pattern generalized:** subject modeling as a functualize practice; rise as one vocabulary + tooling instance on it |
| `18-display-provider.md` | Ambient awareness: rise's one `DisplayProvider` for the inline TUI, in both deliveries — and why a project cannot override it |
| `19-dagger-parity.md` | **Dagger audit:** where the two designs independently agreed, six gaps ranked by value-per-cost, and the two things not to copy |
| `guide/` | the proposed functualize guide (`subjects.md`) and its landing instructions |
| `evidence/` | 18 probes + transcript |

## The shape in one example

```python
from risekit import Executable, Installable, Runnable, Isolation
from functualize.job import Guards, Log, Shell, job

class Jsonschema(Executable, Installable, Runnable):
    group = "tools.jsonschema"
    isolation = Isolation.PROJECT

    @job(guards=Guards(status=["command -v jsonschema"]))
    def install(self, sh: Shell, log: Log) -> None: ...
    def uninstall(self, sh: Shell) -> None: ...
    def run(self, sh: Shell, args: list[str]) -> None: ...
```

```
own CLI :  rise tools jsonschema install | run | diagnose | validate
in func :  func rise tools jsonschema install | …
```

Same class, same plugin object, two deliveries — `04`.

**`tools jsonschema` is the class above, not a task in your project.** Rise
binds its own modules' methods and runs those. It scans no `jobs/` directory, so
`rise build` and `rise deploy` do not exist in either delivery — the project's
own jobs stay `func`'s alone, and there is exactly one runner for them
(`04` §1B). The standalone `rise` executes rise modules because that is what
bootstrapping a bare machine requires: `rise tools mise install` has to work
before any project or `func` exists (`09` §2).
