# intent/ — the Rise Vision & Intent Package, carried into v3

> **What this is.** The `rise-intent/` package, imported here on **2026-09-08**
> so that `rise-on-functualize-v3/` is self-contained: the *why* and the
> *measure of success* now live beside the design that realizes them. The
> original `rise-intent` folder is retained outside this repository as the
> unannotated historical source — **this copy is the one to read.**

Two things were added during the import, and nothing was removed:

1. **A status banner** at the top of every file, saying whether it is current,
   contract-current-but-mechanism-changed, or superseded — and by which v3 file.
2. **The 69 acceptance criteria are numbered** in `10-acceptance-criteria.md`,
   matching the row numbers in [`../12-acceptance-mapping.md`](../12-acceptance-mapping.md).
   Previously they were unnumbered checkboxes and the mapping's "row 34" pointed
   at nothing you could find.

The prose is otherwise **verbatim**. Intent is not rewritten to fit the design
it produced — that is the whole reason for keeping it. Where the design diverged,
the divergence is recorded below rather than edited into the source.

## Why keep it at all

`01-vision.md` and `10-acceptance-criteria.md` are still load-bearing:

- **`01-vision.md`** is the only statement of *why any of this exists*. Nothing
  in v3's 18 files replaces it; v3 answers "how", never "why".
- **`10-acceptance-criteria.md`** is the contract v3 is scored against. v3
  `12` claims verdicts for 69 criteria; this file is what those verdicts are
  verdicts *about*. Delete it and the mapping becomes unfalsifiable.

The middle files (`04`–`09`) are the *intent* behind v3 `05`–`10` and `15`–`16`.
Read them when you want to know what a v3 mechanism was trying to achieve, not
when you want to know what it does.

## Reading order

| File | Contents | Status |
|---|---|---|
| [`01-vision.md`](01-vision.md) | Why this exists; the problem; design philosophy; non-goals | **current** |
| [`02-concepts.md`](02-concepts.md) | The mental model: self-describing module, declaration triple, variants, diagnosis | partly superseded → [`../01-vocabulary.md`](../01-vocabulary.md) |
| [`03-type-system.md`](03-type-system.md) | The eight kinds + five interfaces, with required capabilities | **superseded** → [`../01-vocabulary.md`](../01-vocabulary.md) |
| [`04-validation-and-diagnosis.md`](04-validation-and-diagnosis.md) | Two-step validation pipeline; the diagnosis record contract | contract current → [`../05-diagnosis-validation.md`](../05-diagnosis-validation.md) |
| [`05-registry-and-routing.md`](05-registry-and-routing.md) | Tool registry, variant routing, lockfile | contract current → [`../06-registry-variants.md`](../06-registry-variants.md) |
| [`06-safety-and-observability.md`](06-safety-and-observability.md) | Isolation, guards, idempotency, audit | **current** → [`../08-safety-audit.md`](../08-safety-audit.md) |
| [`07-lifecycle-and-ux.md`](07-lifecycle-and-ux.md) | Three personas; install → scaffold → daily → upgrade | current + dual delivery → [`../09-surface-scaffold.md`](../09-surface-scaffold.md), [`../04-delivery.md`](../04-delivery.md) |
| [`08-extension-model.md`](08-extension-model.md) | Extending the vocabulary without forking | contract current → [`../10-extension-model.md`](../10-extension-model.md) |
| [`09-ai-agent-alignment.md`](09-ai-agent-alignment.md) | Agent-first design; contracts as prompts | current, expanded → [`../15-scrill.md`](../15-scrill.md), [`../16-skill-to-workflow.md`](../16-skill-to-workflow.md) |
| [`10-acceptance-criteria.md`](10-acceptance-criteria.md) | The 69-criterion test matrix | **current — the measure of success** |

## The divergence ledger

Every place v3 departs from the intent, with where the departure is argued.
A criterion-by-criterion scoring is [`../12-acceptance-mapping.md`](../12-acceptance-mapping.md);
this table is the *conceptual* deltas only.

| # | Intent says | v3 says | Why | Argued in |
|---|---|---|---|---|
| 1 | A closed enum of **eight kinds** is the primary vocabulary | **Three axes** — substrate / action / target. The eight kinds survive as **presets**, and existing modules keep their spelling | The eight kinds had no home for a repository and no kind for `code_audit`; the axes give both, and stop presets being the only legal shapes | [`../01-vocabulary.md`](../01-vocabulary.md) §1, §7 |
| 2 | **Five interfaces**: `daemon`, `git`, `backup`, `version`, `continuous-integration` | **Seven action Protocols**: `Installable`, `Runnable`, `Controllable`, `Loggable`, `Backupable`, `Updatable`, `Syncable`. `daemon` splits into `Controllable` + `Loggable`; `continuous-integration` is **dropped** | An action must be a verb done *to* a subject; `continuous-integration` named a context, not a verb, and `daemon` bundled two independent capabilities | [`../01-vocabulary.md`](../01-vocabulary.md) §3, §4 |
| 3 | Strategy is a **tag**, never an interface — enforced by schema rejection | Same rule, enforced by **absence**: no strategy Protocol exists, so `from risekit.core.protocols import pip` is an `ImportError` | Strictly stronger. The illegal state is unrepresentable rather than rejected | [`../02-module-model.md`](../02-module-model.md) |
| 4 | The run-the-thing capability is **`invoke`** | **`run`**. `run()` is the tool being run; `rc.invoke()` is one job calling another | "Invoke" meant two things once rise sat on functualize. Renamed deliberately, while it was still free | [`../14-risks-decisions.md`](../14-risks-decisions.md) §5 |
| 5 | A canonical **schema file**, merged with project extensions into an effective schema | **No schema file anywhere.** Contracts are pydantic models and Protocols; JSON Schema is *derived* on demand via `rise schema export`. Extension is subclassing + module discovery | One source of truth. A schema file and a class cannot disagree if there is no schema file | [`../05-diagnosis-validation.md`](../05-diagnosis-validation.md) §5, [`../10-extension-model.md`](../10-extension-model.md) |
| 6 | The atomic unit is a **task module** — a file with a declaration block | The atomic unit is a **Python class**. Its bases are the declaration; its public methods are the surface | The class line is machine-readable without execution (AST), which the intent's "readable without running it" requirement demands anyway | [`../02-module-model.md`](../02-module-model.md) §5 |
| 7 | Exactly **two runtime prerequisites**: a YAML parser and a schema validator | **pydantic + stdlib** for `risekit.core`, enforced by an import-linter contract; the runtime adds functualize | Same intent — the vocabulary must be checkable without the runtime. Different two things. Scored **reduced**, not met | [`../12-acceptance-mapping.md`](../12-acceptance-mapping.md) row 16 |
| 8 | *(absent)* | A **`Repository` substrate** and a **`Target`** axis: a subject can act upon something that carries identity into records and fingerprints | Required sibling repos and `code_audit` were unsayable in the intent's vocabulary | [`../01-vocabulary.md`](../01-vocabulary.md) §5, §6 |
| 9 | *(absent)* | **Two deliveries from one object** — a `func` plugin and a standalone `rise` CLI | The intent assumed one CLI. Users who already have functualize should not get a second binary | [`../04-delivery.md`](../04-delivery.md) |
| 10 | *(absent)* | The three axes are a **functualize practice**, not rise's property; rise is one vocabulary + tooling instance on it | Keeps functualize free of an opinion about what jobs mean, while giving the discipline its brand and review | [`../17-subject-modeling.md`](../17-subject-modeling.md) |

**Nothing in the intent has been abandoned.** Rows 1, 2, 5, 6 and 7 change
*mechanism*; row 3 strengthens enforcement; rows 8–10 are additions. The
design philosophy in `01-vision.md` — schema as guardrails, contracts as
constraints, idempotency as safety, self-description at every layer — is
untouched, and `12`'s tally is the evidence.

## Terminology note, updated

The original README noted that this package says "task module" to stay
implementation-neutral, and that the then-current implementation said
"taskfile" — which is where the public name came from (`rise-of-taskfile`, the
GoTask-based original). In v3 the unit is a **class**, the package is
**`risekit`**, the CLI is **`rise`**, and the plugin namespace is **`rise`**
(settled in [`../14-risks-decisions.md`](../14-risks-decisions.md) §5). No
taskfile remains anywhere in the design.
