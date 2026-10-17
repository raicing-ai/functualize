# Job-name collision surfacing

Status: proposed behavior specification; member confirmation required before Plan. Shape authority: SD/17072130 v2, `Authority: Approved`, model A. Base: `d1c7e40a`.

## Problem and user outcome

When distinct discovered job definitions claim the same normalized command address, one job remains registered and the other is unavailable. Running the shared address currently executes the survivor without telling the user about the displaced definition. The user must see the existing collision when invoking that command, inspecting its group help, or listing jobs through `func builtin info jobs`.

## Required behavior

1. One normalized address continues to execute one job. The currently selected winner and job stdout/exit behavior stay unchanged. Discovery remains non-fatal. A colliding invocation emits one concise diagnostic per existing collision finding to stderr before the job's output, naming the shared address, both Python function names, both source files, the registered function, and “rename one.” This applies on cold and warm invocations and to either spelling of the same normalized address.
2. A group's `--help` continues to show the surviving command and its summary. It also emits the matching collision diagnostic(s), including both source files, so the row cannot imply that the command has an unambiguous definition. A group with no collisions gains no diagnostic.
3. `func builtin info jobs` text and `--json` associate every existing collision finding with the listed surviving command. The collision diagnostic names both source files and distinguishes the unavailable from the registered function. A project without collisions retains its existing job listing behavior.
4. `func builtin info` text and `--json` also identify both source files for each collision. Their existing `discovery_failures` entries, keys, values, order, and rendering stay unchanged; supplementary collision details sit with the affected job instead. In particular, the published finding continues to record the dropped claimant's path. The new surfaces may use information already available in discovered job descriptors to name the registered claimant's file; they must not repurpose that published path.
5. A two-file pair under one group (`jobs/a.py` and `jobs/b.py`) receives the same diagnostics as a one-file pair. Other healthy commands remain runnable, and the collision does not turn discovery into a refusal.

## Acceptance mapping

| Ticket row | Meaning under approved model A |
| --- | --- |
| (a) both reachable or discovery refusal | Superseded by the approved warning model: the displaced function remains unreachable until renamed, while every in-scope entry point makes the collision loud. This exception to the original row needs explicit confirmation of this spec. |
| (b) `func builtin info` and JSON report both source files if warning remains | Full `info` already reports a collision in both renderings, but its finding has only the dropped file path. This change retains that record and its rendering exactly, and adds a companion collision detail alongside the affected job in full `info` text/JSON. It also adds both files to invocation, group help, and `info jobs` text/JSON diagnostics. |
| (c) regression fails on ticket head and passes with fix | The implementation task must add an end-to-end assertion for the missing diagnostic on `e00d870`, covering at least the two-file run, `info jobs --json`, help, and warm invocation; run it red on base and green on the implementation. |

## Non-goals and invariants

- Do not alter normalization, the naming contract, the deterministic last claimant chosen by `claim_order`, or the existing `discovery_failures` payload and full-report rendering.
- Do not cover NFKC-only pairs, other projects or ancestor roots, or two identically named Python declarations in one module. That last case produces no collision finding for model A to display and would require a separate declaration-time mechanism.
- Do not invent a second address for the unavailable function or make discovery fatal.

## Evidence and open gate

`research.md` records the live authority reads and falsifying commands run on `d1c7e40a`. The member must confirm the behavior specification, especially the accepted replacement of ticket row (a), before the architecture pass begins.
