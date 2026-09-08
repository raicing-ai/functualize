# 17 — The Pattern, Generalized: Subject Modeling as a functualize Practice

The three axes are not rise's. "What it is / is it present", "what you can
do to it", "what it acts on" is an authoring discipline for **any** job
module that manages a persistent thing — and functualize, not risekit, is
its natural home. rise demotes itself from "framework with a vocabulary" to
**one standardized vocabulary + tooling built on a functualize practice**,
which is what the v3 package layout already was (`11` §1: `core` is
pydantic + stdlib, only `binding`/`plugin`/`_cli` touch functualize) — minus
the naming.

## 1. The decision

| Question | Answer |
|---|---|
| What generalizes? | the discipline: one subject, one class; the substrate defines presence; actions are verb Protocols; the target carries identity into records and fingerprints. Plus the meta-rules: declaration in the class line, readable without execution, inert constructors, one binding path, closed core / extensible per project |
| What stays rise? | the concrete sets — 8 substrates with their diagnosis blocks, 7 action Protocols, `Target` types, `supports` tuples, the 8 presets — and the tooling: vocabulary binding checks, registry/lockfile, scaffold, dual delivery, skills, safety |
| Where does the practice live? | [`guide/subjects.md`](guide/subjects.md) — the **proposed** functualize guide, to land at `docs/guides/subjects.md` in this repository alongside the upstream asks. functualize names the axes and the tests, **never a concrete substrate, action, or target**; the moment it does, it has acquired an opinion about what jobs mean (the reason the scrill/rise placement analysis rejected putting the
vocabulary in functualize core) |
| Enforcement? | functualize's contribution is generic: mypy, the plugin seam, asks 1–2's correctness fixes. The five-layer ladder (`01` §8) belongs to the vocabulary layer, and the guide says so |
| Terminology | Axis 2 is **Actions**. "Capability" already means injected parameters (`Shell`, `Log`) in functualize, and the collision was live in v3's own flagship example (`02` §1: both senses in one import block). The Protocol names themselves stay — `Installable`, `Runnable` already read as subject-descriptors |

Why this beats the rejected A2 (`functualize-resources` workspace
SDK): no fourth package, no shared-code version skew (08 risk 3), coupling
at convention level rather than code level. Why it beats A3-as-was: the
practice gets functualize's brand and review discipline, and any third
framework gets a canonical way to be a vocabulary layer. A2 remains the
fallback **only** if concrete classes ever need code-level sharing — v3
`15` §5 already showed scrill does not (the kernel is `risekit.core`; packs
that need prose get generation, packs that need code subclass through rise).

The dogfood objection (08 §3: "functualize ships an API it doesn't use")
dissolves at the pattern level: functualize dogfoods the *discipline* — its
own class-shaped pre-filters and the plugin seam — while the concrete
vocabulary stays with its consumer, which does dogfood it.

## 2. Mechanism vs policy — the amendment to `13`

v3 `13` declined "native method-jobs" to protect rise's binding. The
adapter's own factoring (`03` §4) shows the asset is narrower than "the
binding":

| `ClassBinding` piece | Grade |
|---|---|
| checks 2 (no-arg construction, abstract gate), 4 (`isinstance` per Protocol), 7 (`config` is a `BaseModel`), 9 (boolean flag collisions), 10 (reserved names) | **mechanism** — vocabulary-blind |
| the `Job` emission shape (`name=f"{group}.{method}"`, qualified names, group-composed namespace) | **mechanism** |
| checks 5 (`supports` legality), 6 (the concrete `Target`), and the substrate tables | **policy** — the value-add |

So the decline is re-recorded as **deferred, seam preserved** (`13`, "Not
asked for"): if a generic class→jobs binding ever lands upstream,
`risekit.binding` shrinks to the policy checks and the descriptor shape —
hence nothing downstream — changes not at all. Not asked for now; nothing
needs it, and the practice lands as a guide first.

## 3. Ask 9 — re-export `StaticProvider` from `functualize.plugin`

Discovered while drafting the guide: `03` §2 claimed "the public `Job` /
`StaticProvider` re-exported from `functualize.plugin`", and half of that is
wrong. `Job` is public (`plugin/__init__.py:12`); **`StaticProvider` is not
in `__all__`** (`plugin/__init__.py:56`) — it lives at
`_discovery/providers.py:651`, and probe 10 imports it from the private
path. `add_job_provider` takes the public `JobProvider` protocol
(`app/core.py:911`), but every user of the documented binding seam either
hand-rolls a two-method provider or imports private.

Severity: small, but it is the one non-public line in what is otherwise the
documented route for class-shaped modules. `03` §7 is corrected in this
revision; the guide carries the caveat until the ask lands.

## 4. The guide's decision rule

Normative text lives in the guide; recorded here for the corpus:

> **Name the thing that exists between runs. If you can name it and your
> verbs act on it, model it as a class — substrate, actions, target. If you
> can't — the work itself is the artifact — write jobs and compose them
> with functualize's native pieces.**

Class signals: presence asked by more than one job (the copy-pasted status
guard is the smell); ≥2 verbs against one subject; a wanted meta-surface;
config shared across verbs; identity that should flow into records.
Plain-job signals: the job *is* the work; the "subject" is an invocation
input (`Fingerprint` + `Sources` already model it); pipeline shapes
(`Deps`/`FromJob`/`@workflow`); one-off scripts. The guide also states the
organizational-class limit: grouping alone is `JOB_GROUP`'s and
`GroupOptions`' job, not a subject model's.

## 5. What changed in this revision

| Change | Where |
|---|---|
| Axis 2 renamed **capability → action** (Protocol names unchanged) | `01`, `02`, `03`, `05`, `06`, `09`, `10`, `12`, `13`, `14`, `15`, README |
| `rise new capability` → `rise new action`; `rise schema capabilities` → `rise schema actions` | `09` §1, §4; `10` §5 |
| `CapabilityName` → `ActionName` in the record models | `05` §1 |
| Sub-group declaration pinned: class-body literal `subgroups = {…}`, not a `@job` kwarg (`@job` has no `subgroup` parameter, `job/decorators.py:46`; its `group=` override is absolute) | `02` §3 |
| Native method-jobs: declined → deferred, seam preserved | `13` "Not asked for" |
| `StaticProvider` public-re-export claim corrected; ask 9 opened | `03` §7, §3 here |
| The guide drafted — proposed in-corpus, functualize untouched | `guide/subjects.md` + `guide/README.md` (landing: copy to `functualize/docs/guides/`, one index bullet, one mkdocs nav line) |

One adjacent finding, recorded not fixed: `functualize/docs/guides/
jobs-discovery.md` documents `JOB_NAME`, but the source reads `JOB_GROUP`
everywhere (`_discovery/registry.py:363`, `_types/naming.py:584`, scaffold
templates). The guide is stale against the implementation; fixing it is a
functualize docs pass, out of scope here — the new guide uses `JOB_GROUP`.
