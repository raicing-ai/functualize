# Design Review — Evaluating the Proposal's Engineering Quality

Claim verification (Phases 1–3) answers "is this document true?" Design review
answers the harder second question: **"is the proposed design good?"** —
correct from a programming-language standpoint, idiomatic for this repository,
patterned appropriately for the problem, and reliable under failure.

Read this file when you reach Phase 3.5. It defines the standards index, the
five lenses with their techniques and artifacts, the finding grammar, and the
verdict vocabulary.

## Why a separate phase and vocabulary

Factual findings and design findings are different kinds of statement. A
factual finding is falsification: claim, evidence, verdict. A design finding
is evaluation: there is no single oracle, and the reviewer's taste is a
systematic bias, not a perspective. Mixing the two destroys both — the author
stops trusting `CONFIRMED` once it sits next to "should use Strategy pattern."

So design evaluation runs as its own phase with its own verdicts
(`SOUND | CONCERN | VIOLATION | UNJUDGEABLE`), and every design finding cites a
**standard** the way a factual finding cites evidence.

## The three guards against taste

1. **Citable standard.** Every design finding names its yardstick: a
   constitution/ADR rule, a repo idiom with precedent at `file:line`, or a
   named failure mode the design concretely produces. "Violates the registry
   idiom — `DIRegistry` enforces X at `file:Y`" is auditable. "I would use a
   dataclass here" is not a finding.

2. **Idiom beats textbook.** If the repo deliberately does something
   differently from general best practice, the repo wins and the finding is
   void. Check precedent *before* citing best practice. A repo that
   standardizes on Protocol-based extension points does not need "consider an
   ABC" findings; a repo that deliberately keeps a module-global catalog does
   not need "inject that dependency" findings — and when the proposal itself
   is the fix for such a shape, flagging the current shape is noise.

3. **Question-form findings (the steelman mechanism).** State every design
   finding as a reachable scenario the document cannot answer:

   > **A design finding = a reachable scenario, constructed from the
   > proposal's own components, that the document does not address, plus the
   > named bad outcome.**

   The reachability constraint separates findings from FUD: the scenario must
   be built from elements the proposal itself introduces. "What if the network
   fails?" is not constructible from a widget-swap design. "The mode resolver
   flips between keystroke and submit" is — both elements exist in the design.

   Question-form findings are self-steelmanning: if the design already handles
   the scenario, the finding evaporates on contact. The author can falsify a
   finding two ways — show the design addresses the scenario, or show the
   scenario is unreachable.

   For findings that would gate adoption (VIOLATION candidates), you may
   optionally spend a subagent on a **defender pass** — "argue for this design
   as written, using the repo's constraints" — and rebut its actual arguments.
   This buys real independence at agent cost; reserve it for blocking
   candidates, because a defender framed by the same reviewer only partially
   escapes the reviewer's framing.

## The standards index (Phase 1.5 output)

"Best practice" is unverifiable in the abstract; the index makes it concrete
per-repo. After decomposing claims, enumerate the standards *applicable to
those claims* (a document that touches no registries does not need the
registry idiom extracted):

- **Binding rules**: constitution documents, ratified ADRs, enforceable
  configs (import-linter contracts, lint rules, CI gates). These make
  VIOLATION findings possible — a design contradicting them is objectively
  wrong, not debatably wrong.
- **Authoritative architecture docs**: the docs the repo itself declares
  authoritative for a domain.
- **Idioms with precedent**: repeated shapes the codebase already uses — how
  its registries are constructed and validated, how its stores handle
  paths/durability, how public API homes are organized, how errors are typed.
  Cite each idiom at `file:line`. Two or more consistent instances make an
  idiom; one instance is an anecdote — flag single-instance "idioms" as weak
  standards and weigh findings against them accordingly.
- **Repo-specific review concerns**: testing strategy, transitional-change
  disclosure, migration/cache coordination. These enter via the index, not as
  extra lenses — the lens list stays universal and stable.

List the index in the report. It is the yardstick the author can appeal
against — and its entries are themselves factual claims, checkable like any
other.

## The five lenses

Each lens has a named technique and a required artifact. The artifact is what
makes the phase auditable rather than impressionistic — another agent should
be able to check that the technique was actually performed. Embed small
artifacts in the report; summarize large ones, but always record the
*negative* results explicitly (unhandled cells, unjustified deltas,
substitution failures) — those are the findings.

### Lens 1 — Type/PL correctness

**Technique: Liskov walk.** For each proposed Protocol/ABC/interface member,
substitute every known or planned implementation. Can each one honestly
satisfy the member's declared shape?
**Artifact:** substitution table (member × implementation → fits? why not?).

Watch for: attributes that one implementation can only compute from arguments
(a `bool` on the interface, a `method(args)` on the impl); `runtime_checkable`
Protocols — `isinstance` checks method *presence*, never signatures, so a
"hand-rolled stub satisfies isinstance" acceptance test proves nothing about
the real implementation; `None` smuggled into fields that are never actually
optional; mutability leaking through frozen/immutable types; unions used to
avoid naming a real variant type.

### Lens 2 — Repo idiom conformance

**Technique: Precedent diff.** Find the closest existing analog for each new
component (a new registry vs the existing registries; a new store vs the
existing stores). Diff the proposal against the analog. Every delta needs a
justification in the document; unjustified deltas are findings.
**Artifact:** analog `file:line` + delta list with per-delta verdict
(justified / unjustified / weak-standard).

Watch for: a fourth way to do something the repo already does three ways;
construction/validation/freeze lifecycle drift from the analog's pattern;
test-placement drift from the repo's testing strategy; public-surface
additions that bypass the repo's `__all__`/re-export idiom.

### Lens 3 — Pattern fitness

**Technique: Null-alternative test.** What breaks if the proposal does *less*?
What constraint *forces* this much machinery? The forcing constraint must be
cited (a boot-laziness requirement, a real extension point, a correctness
invariant). The deepest form of this question is about the decomposition
itself, not its parts: is this the right cut at all, and what breaks with half
of it?
**Artifact:** forcing-constraint citation per major mechanism — or its
explicit absence, which is the finding.

Watch for: registries with one registrant and no extension point; abstractions
introduced "for symmetry"; indirection whose only caller is the test that
proves it; two-altitude designs where the constraint forcing the split is
never named.

### Lens 4 — Reliability

**Technique: Lifecycle walk.** For every stateful component the proposal
introduces, enumerate states × events. Unhandled cells are findings. Events
include the ugly ones: exception mid-transition, reentrancy, duplicate
delivery, shutdown mid-write, non-TTY/headless contexts, concurrency with
existing workers.
**Artifact:** the grid + an explicit list of unhandled cells.

Watch for: durability profiles chosen implicitly (flush-on-shutdown vs
write-ahead are different promises — the design must choose, not drift);
guards that exist on today's code path but are bypassed by the new path;
degradation named without a contract ("degrades gracefully" — to *what*,
surfaced *how*?); lifecycles owned by nobody during async transitions.

This lens is where the highest-severity design findings live: the code does
not exist yet, so factual verification can never find them.

### Lens 5 — Layer/scope fitness

**Technique: Import-arrow audit.** Draw the new dependency edges the proposal
creates; check each against the layer order and composition rules. Where
enforcement is mechanized (import-linter), the machine is the oracle — the
finding is an edge the machine would reject, or an edge that forces weakening
a contract.
**Artifact:** edge list with the binding rule per edge.

Watch for: peer-layer edges; delivery concerns leaking into the kernel; public
API surface added to escape a layer rather than because it belongs;
"temporary" bridges without a removal plan.

## Verdicts and severity

| Verdict | Meaning |
|---|---|
| **SOUND** | The decision survives its steelman; standard cited where applicable |
| **CONCERN** | A named reachable scenario the document does not address |
| **VIOLATION** | Contradicts a binding rule (constitution/ADR/enforcement config) OR a demonstrated reachable failure |
| **UNJUDGEABLE** | The document is too underspecified to evaluate; state which decision must land first |

Severity discipline — the antidote to inflation:

- VIOLATION requires a binding-rule citation *or* a demonstrated reachable
  failure.
- CONCERN requires the named scenario. No scenario → not a finding.
- Anything weaker goes to **Observations** — a non-gating report section that
  never blocks adoption.
- **SOUND carries the denominator.** Explicitly record the major decisions you
  judged and passed, with the supporting standard. A report listing only
  CONCERNs hides how much was evaluated; the SOUND list is what makes two
  CONCERNs meaningful.

## Interaction with factual findings

Cross-reference, don't merge:

- A factual DRIFTED/FALSIFIED finding can *cause* a design finding — e.g. a
  contract section falsified by a premise correction elsewhere in the same
  document is an interface contradiction → VIOLATION candidate.
- A design finding can reveal an unverifiable factual claim — an
  underspecified design is why a claim is UNTESTABLE.
- Factual findings gate adoption on truth; design findings gate adoption on
  fitness. The recommendation can be REVISE on design grounds even when every
  factual claim is CONFIRMED.

## Worked example

A document's contract section declares `needs_terminal: bool` as a Protocol
attribute. A premise correction elsewhere in the same document observes that
one existing implementation exposes `needs_terminal(args) -> bool` — a method
requiring arguments.

- **Factual pass:** the correction is CONFIRMED — both shapes exist in today's
  code, cited at `file:line`. Done.
- **Design pass (Lens 1, Liskov walk):** the contract-as-written has no honest
  implementation for that builtin — declare the bool and the `config
  edit`-style command cannot express its terminal need; declare the method and
  the published contract is wrong. Verdict: **VIOLATION** (interface
  unimplementable as written), severity load-bearing. Resolution: the shape
  decision must land in the contract before the phase that consumes it.

The factual pass marked the claim true and moved on; the design pass found
the document contradicting its own contract. That is the division of labor.
