| Field | Value |
| --- | --- |
| Document type | Shape Intent |
| Status | Exploring |
| Authority | Proposed |
| Owner | m.hakim.adiprasetya |
| Product | Functualize |
| Last reviewed | Awaiting review |
| Carried by | MCH-294 (MCH-298 Phase A6) |
| Depends on | None |
| Related | `plugins/PUBLISHING.md`; `contributor/guides/plugin-development.md`; SD/3080295 v3 |

## 1. The shape at a glance (shape)

The Jev distribution becomes a Tier 1 — Published provider. Its package README shows an installable, runnable decision gate instead of calling the package a scaffold:

```text
$ pip install functualize-decision-jev
Successfully installed functualize-decision-jev ...
$ uv run pytest plugins/domains/functualize-decision-jev/tests/ -q
... passed, ... skipped
```

The example under `plugins/domains/functualize-decision-jev/examples/` demonstrates a gate whose Jev proposal selects a declared choice only when the gate's own thresholds pass. Its README names `OPENCODE_API_KEY` for a live run and documents a secret-free, hermetic verification path. The package remains in the core `[all]` extra and standalone binary.

## 2. Problem

Today a reader sees:

```text
> Status: Tier 3 — experimental.
> The package is an empty scaffold today ...
```

The checked-in provider and plugin already implement the decision strategy. A reader cannot learn how to install and use it from this README; a generated package test leg cannot collect tests that live only under root `tests/plugins/`.

## 3. Current reality

At `d58500f76ba65ba169451e3cb4af3820e271e266`, `plugins/domains/functualize-decision-jev/README.md:3-9` has the status above; `plugins/PUBLISHING.md:217` lists Tier 3, and `:227-228` records missing examples and package-local tests. `plugins/domains/functualize-decision-jev/pyproject.toml:1-33` declares the package, typed classifier, Apache-2.0 SPDX license, and plugin entry point. `src/functualize_decision_jev/_plugin.py:1-15` describes the registered decision strategy. Root tests are `tests/plugins/test_jev_decision_provider.py`, `test_jev_wire.py`, and `test_jev_live.py`. The package directory has no `LICENSE`, `NOTICE`, `examples/`, or `tests/` at this base.

| Surface | Before | After |
| --- | --- | --- |
| Package README | Tier 3 scaffold claim | Tier 1 Published, installation, Quick Start, features, public API, development |
| Package contents | No licence copies or examples | `LICENSE`, `NOTICE`, runnable `examples/` with its own README |
| Test discovery | Jev tests at repository root only | Functional and live tests collect from package-local `tests/`; a generated plugin leg can run them |
| Publishing table | Jev row says `3 — Experimental` | Jev row says Tier 1 and describes actual published state |

## 4. Use cases (shape)

### UC-1 — A workflow author installs Jev and runs a decision example

The author reads the package README, installs the distribution, sets `OPENCODE_API_KEY` for a live call, and runs the example's documented command. The example declares a `ChoiceDecision` on a `Gate` with named options and a fallback, using the existing workflow API. The result shows the selected declared option and whether the gate used a proposal or fallback; the Jev provider never overrides the gate's thresholds. The live output depends on the service response, so the README does not promise one fixed choice.

```text
$ OPENCODE_API_KEY=<configured-in-shell> <example command from examples/README.md>
route=<declared option>  decided_by=<decision or fallback>
exit 0
```

### UC-2 — No key is available

The author follows the documented hermetic verification path without a credential. The package-local test suite uses recorded or fake responses and passes; the live test is skipped with a reason. A live gate without a key records `not_configured` and takes the workflow's declared fallback, as the existing plugin behavior specifies.

```text
$ env -u OPENCODE_API_KEY uv run pytest plugins/domains/functualize-decision-jev/tests/ -q
... passed, 1 skipped ...
exit 0
```

### UC-3 — CI collects the Jev package

The generated plugin suite discovers the package-local tests and invokes the package path. Hermetic tests run without a secret. A separately scheduled live smoke can use a repository credential when its owner supplies one. A live credential and the shared matrix are separate work; the Jev package must be collectable by that leg.

## 5. The shape, surface by surface (shape)

| Surface | Proposed example |
| --- | --- |
| Authoring / library API | `from functualize.workflow import ChoiceDecision, Gate`; a workflow uses `Gate(name="route", awaits=RouteChoice, decide=ChoiceDecision(field="route", options={"shipping": "parcel journey", "human_review": "manual review"}, state=FromStep("intake"), instructions="Route this request", accept_at=0.70, min_margin=0.10, fallback="human_review"))`. The installed entry point registers Jev; no manual provider registration is required. |
| Command line | README shows `pip install functualize-decision-jev`, one executable example command, `uv run pytest plugins/domains/functualize-decision-jev/tests/ -v`, and the example test command. |
| Configuration | `OPENCODE_API_KEY` is required only for a live Jev request. The existing optional `[jev]` section and defaults remain the configuration surface. No secret value appears in documentation or test output. |
| Wire / HTTP / file formats | Not touched by this promotion. Existing Jev request and response mapping remain internal to the provider. |
| UI | Not touched. The gate's recorded decision is the observable surface. |
| Errors and refusals | Without a key, the existing `jev not_configured: OPENCODE_API_KEY is not set` provider failure is handled by the gate's declared fallback; the example explains this rather than claiming a model choice. |
| Generated / observable artifacts | The package has a Tier 1 README, `LICENSE`, `NOTICE`, `examples/README.md`, a runnable scenario, and package-local `tests/`; `plugins/PUBLISHING.md` records Tier 1. |

The README follows `plugins/PUBLISHING.md:141-192`: at least 30 lines, distinct Installation, Quick Start, Features, API Reference, and Development headings, valid Python examples using public imports, and a development test command. The package satisfies the rest of the Tier 1 checklist too: functional assertions, typed marker, build, entry point, classifiers, dependency bar, and installability. The current `0.1.0` version and `Development Status :: 3 - Alpha` classifier need review against the Tier 1 presentation during Specify; this shape does not choose a version number.

## 6. Diagrams (shape)

```text
Structure (proposed)
workflow author -> functualize.workflow Gate/ChoiceDecision
                -> installed Jev entry point -> Jev provider -> model service
                -> gate threshold/fallback -> recorded choice
package README/examples -> public workflow API; package tests -> public behavior + provider wire
generated plugin leg -> package-local tests
```

```text
Behavior
author runs example -> workflow reaches decision gate -> Jev proposes option
  -> gate checks declared thresholds -> accepted option OR declared fallback
  -> run records decision and chosen route -> author sees route and decision source
```

## 7. Binding, provisional and illustrative (shape)

- **Binding:** Distribution `functualize-decision-jev`; Tier 1 — Published; package README headings Installation, Quick Start, Features, API Reference, Development; package-local `LICENSE`, `NOTICE`, `examples/`, `examples/README.md`, and `tests/`; `plugins/PUBLISHING.md` Tier 1 row; `OPENCODE_API_KEY` for live requests; `[jev]` config; existing `decision` gate strategy; `[all]` and standalone binary inclusion; gate-owned threshold and fallback behavior; no secret required for hermetic tests.
- **Provisional:** The runnable scenario's name, exact command and output wording; the test file names and how root tests are migrated or mirrored; the package version and development classifier wording; the scheduled live smoke's exact command. Specify must settle these without changing the binding surfaces.
- **Illustrative:** Parcel-routing labels `shipping` and `human_review`, the threshold values, ellipses in transcripts, and model response data.

## 8. Boundaries and non-goals

| Surface | Owner and boundary |
| --- | --- |
| Jev package docs, example, tests and metadata | MCH-294; this shape fixes the destination, not the file-move mechanism |
| Generated plugin-suite matrix | Shared CI work under MCH-298; MCH-294 supplies a collectable package suite |
| Live Jev credential | Member's separate MCH-298 decision; this shape does not choose, reveal, or install a key |
| Core workflow gate semantics and Jev wire protocol | Existing implementation; this promotion does not redesign either |

The broader post-release plugin test standard remains MCH-294 work after the A6 promotion, not part of this shape approval.

## 9. Candidate models

**Selected — Tier 1 package-local surface.** `uv run pytest plugins/domains/functualize-decision-jev/tests/ -v` collects Jev's functional tests; the package README documents the runnable example. This matches `plugins/PUBLISHING.md` and the generated CI leg's package path.

**Rejected — keep root-only tests and relabel the table.** `uv run pytest tests/plugins/test_jev_*.py` still runs locally, but `uv run pytest plugins/domains/functualize-decision-jev/tests/ -v` cannot collect them. A Tier 1 label would misrepresent the package.

## 10. Hypotheses and risks

- Package-local collection may expose imports or fixture dependencies previously supplied by root tests. Specify must measure the collected suite in isolation.
- A genuinely live scenario needs a key and network service. The example must give a reproducible hermetic route and clear live prerequisites.
- The current version/classifier may contradict a Published status; package metadata must be checked during Specify before Tier 1 is claimed.

## 11. Next falsifiable experiment

At the implementation head, from a clean checkout:

```bash
uv run pytest plugins/domains/functualize-decision-jev/tests/ -q
uv run pytest plugins/domains/functualize-decision-jev/examples/ -q
uv build --package functualize-decision-jev
```

Expected: package-local hermetic tests and example tests pass without a key, the live test reports a skip, and the build succeeds. Failure to collect functional tests from the package path or inability to run the documented example falsifies this shape's readiness claim.

## 12. Open questions

None requiring a shape decision. Specify chooses a move or mirror of the existing root tests and the example's exact invocation; both preserve the same package-local experience. The credential and shared CI matrix decisions proceed on MCH-298 independently.

## 13. Outcome

Proposed for member review on MCH-294. No approval has been given; Specify, Plan, and implementation remain gated until the issue's fixed-SHA approval protocol is complete.
