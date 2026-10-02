# Rise / RiseKit foundation — research record

Findings and verification evidence for the set. This file is never a gate. It
records what was checked, when, and with what result. Base for every
repository command: `origin/master` at `ef1939d`, branch head `a86f2c1`
(revision 1) plus the revision-2 working changes, all in the worktree.

## Provenance

- **Revision 1** (`a86f2c1`). `spec.md` and `contracts.md` were written by a
  design run that read Jira and Confluence live and then died before
  committing. A second run judged both files, corrected two defects, and wrote
  `plan.md`, `tasks.md` and this record. That second run had no Atlassian
  access, and said so.
- **Revision 2** (this one, 2026-10-02). It applies the member's two corrections
  and Mika's audit of 2026-10-02 on the tracker thread. It re-reads every
  product source live (§ *Live reads*), which retires revision 1's "not read
  live" limitation. It also re-verifies the new seams the revision relies on.

## Live reads (2026-10-02, through the Atlassian connector on the design runtime)

| Source | Id | Version / state | What it contributed |
|---|---|---|---|
| Shape Intent — Rise/RiseKit Canonical Model | Confluence `SD` 5407068 | **v15**, updated 2026-09-28T10:29:34Z; **0 inline comments, 0 footer comments** | Decisions 1, 3–6, 11–15 as cited in spec.md §8; the member's planned comments have not arrived yet |
| Functualize 1.0.0 North Star | `SD` 4882435 | v6, 2026-09-28T10:23:53Z | step 6 (acquire the Cloudflare package through Rise/RiseKit); planning consequence ("Rise/RiseKit package interface" is not a contract until accepted) |
| Initiative — 1.0.0 North Star Journey | `SD` 4882456 | v11, 2026-09-28T10:28:32Z | scope; slice 6; continuation queue items 4–7; ticket-creation policy ("When FUN-8 resolves the Rise/RiseKit boundary, update this queue first") |
| Functualize 2.0.0 North Star | `SD` 4849705 | v5, **Proposed**, 2026-09-20T11:06:03Z | *Proof-carrying Rise packages*: a forward-compatibility constraint only ("should not yet create a 2.0 Jira commitment") |
| Northstar 1.0 Journey — Run 1 | `SD` 5046398 | v1, 2026-09-18 | no Rise content; Run 1 is deliberately Rise-independent (FUN-5) |
| Decision — Claims live in Jira, decisions and sources live in Confluence | `SD` 11370545 | v4, accepted 2026-10-01 | where artifacts live (AC-9); the two preflight queries an agent runs before planning |
| 01 — Decisions Taken (D1–D7) | `SD` 9273345 | v1 | D4 (hold generalisations no second package needs); D7 (R1 means D1) |
| FUN-8 | Jira | In Progress, updated 2026-10-01T17:41Z, no comments | scope and acceptance criteria as cited |
| FUN-3 | Jira | To Do, updated 2026-09-19 | delivery principles; initial delivery order item 7 (FUN-8 in parallel) |
| FUN-22 | Jira (read 2026-10-01) | To Do | "D1 FIRST"; "The provider is a PLUGIN" |

Preflight per Decision 11370545 §4, run 2026-10-02:

- Open items: `project in (FOSS, FCLOUD) AND (labels in (area-rise, area-risekit, area-plugins, area-packaging) OR text ~ "rise" OR text ~ "risekit") AND statusCategory != Done`
  returned FOSS-80 (dead symbols in `functualize-ai`/`functualize-mcp`) and
  FOSS-75 (`ToolScope.approval_required()`). Neither touches this feature's
  files. No Rise or RiseKit item exists.
- Decision records: `type = page AND label = "decision"` returned one page
  (11370545). No area-labelled Rise decision exists. The Rise decisions are the
  Shape Intent's own.

## Verification (Retrieval Before Assertion evidence)

| Claim in the set | Command or read | Result |
|---|---|---|
| no `risekit` anywhere on master | `git grep -i -c risekit origin/master \| wc -l` | 0 |
| no `\bRise\b` anywhere on master | `git grep -E -l '\bRise\b' origin/master \| wc -l` | 0 |
| "capability" already means a DI-injectable (592 uses) | `rg -c -i '\bcapabilit' src/functualize`, summed | 592 |
| the ext seam exists | read `src/functualize/_discovery/providers.py:296-312` | as claimed |
| namespace ownership and orphan warning | read `src/functualize/_app/boot.py:2104-2148` | warning by default; raise under `plugins.strict` |
| the public host port has job lookup and DI | read `src/functualize/_types/host.py:106-122, 296-308` | `get_jobs`, `get_job`, `execute`, `di.provide` (revision 2) |
| entry-point jobs enumerate without metadata | read `src/functualize/_discovery/providers.py:700-740`, `src/functualize/app/commands.py:158-182` | as claimed; `get_job` materializes (revision 2, S4) |
| `Invoke` by name returns the callee's value | read `src/functualize/_engine/capabilities/invoke.py:96-125` | `-> JobResult` with `return_value` |
| an unread entry-point group fails the repository's tests | read `tests/spec/test_every_declared_group_has_a_reader.py`; ran it | refuses any `functualize.*` group not in `READ_GROUPS` and not a live domain's group; **30 passed** on this branch, 2026-10-02 (revision 2, gate G9) |
| the `functualize.plugins` → `ADAPTER` label is accepted | read `.spec/STATUS.md:2930-2933` | "Maintainer decision, 2026-09-17" |
| Jev registers the same way, from `plugins/domains/` | read `plugins/domains/functualize-decision-jev/pyproject.toml:23-24` | `jev = "functualize_decision_jev:JevPlugin"` |
| 9 plugin files already import `functualize._*` against the plugin guide | `rg -l 'from functualize\._\|import functualize\._' plugins/*/*/src \| wc -l` (2026-10-01) | 9; gate G11 forbids a tenth |
| zero plugins use the ext seam today | `rg -l '__functualize_ext_' plugins \| wc -l` (2026-10-01) | 0; Rise is its first consumer |
| core mentions Cloudflare only in prose | `rg -n -i cloudflare src/functualize` (2026-10-01) | 4 docstring hits in `_types/persistence.py`; **FUN-22's gate "`grep -rn 'cloudflare' src/functualize/` stays at 0" is already false**, so this set's gates are import-level |
| credential names already in use | `tests/substrate_probe/d1.py` | `CLOUDFLARE_ACCOUNT_ID`, `CLOUDFLARE_API_TOKEN` |
| grouped plugin layout | `ls plugins/` | `adapters credentials domains substrates` |
| ADR-031 is the next free number | `ls contributor/adr/` | highest is 030; the dispatch's "016" was stale |
| G1 still empty | `git show --stat HEAD` (5 files under `.spec/features/`) plus `git status --porcelain` (4 of those files modified) | nothing under `src/functualize/` |

Prose pass (revision 1): `zg` over the worktree index. Its hits on ADR-016
(providers in plugins, `boto3` kept out of core) and ADR-026 ("One
implementation does not earn an abstraction package") are weighed in plan.md
§ *Candidate-AFTER smell check*.

## Corrections

Revision 1, to the inherited draft:

1. spec.md §7 P-2 cited ADR-016 as "puts providers in plugins". ADR-016 is the
   remote config layer. The citation was replaced with the constitution's
   completed invariant and FUN-22's own criterion.
2. contracts.md C4 pointed at an undefined "D4 review check". It was pointed at
   D-2 instead. (Revision 2 cites the actual source: review decision D4,
   page 9273345.)

Revision 2, from the member and the audit (2026-10-02):

3. **P-1 withdrawn.** It is now development traceability (spec.md §7, §8), as
   the member corrected.
4. **Providers moved out of RiseKit.** This affects C1, C2, spec.md §2–3, B5,
   S15, T8 and T9, as the member corrected.
5. **P-2 reworded.** The *namespace owner* owns the Cloudflare contracts. Rise
   and RiseKit do not.
6. **Contract discovery replaced.** `functualize.rise_contracts` was excluded
   by Decision 14 and refused by the declared-group reader test. It is replaced
   by `contract_ref` (B6, C3, C4). Revision 1 would have failed CI at T8.
7. **S4 added.** Entry-point jobs carry no metadata until materialized, so
   revision 1's Rise would have read every provider job's Rise metadata as `{}`.
8. **T11 extended** past artifact non-duplication, to implementation
   traceability against live sources (AC-9, G10).

## Premise changes against the tracker

- **P-2**: "the Cloudflare Worker + D1 capability" is two provider-owned
  contracts plus generic Functualize plugins for run persistence and Worker
  execution.
- **P-3**: the forcing case is diagnosed and provisioned, not deployed. FUN-8's
  dependency criterion is met by stage-5 ordering.
- P-1 is withdrawn (correction 3). It was never a premise change.

## Limitations of this pass

- This session's sandbox refused serena and any shell search outside the run
  workdir. Revision 2's new checks were therefore made by reading the files
  directly, plus one test run. graphify was not re-run, and revision 2 adds no
  dependency-direction claim that graphify would be needed for: B1 means no
  core edge changes.
- Sizes in plan.md § *Files to change* are estimates for new trees.
- The Shape Intent has no owner comments yet. T11 re-reads it before closing,
  and anything that arrives in the meantime is checked against the set then.
