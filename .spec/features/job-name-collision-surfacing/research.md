# Specify evidence

WorkflowMode: REPOSITORY_NATIVE. WorkflowAuthority: `.claude/rules/spec-workflow.md` and `.spec/CONSTITUTION.md`. CurrentPhase: Specify. ApprovalState: Shape Intent SD/17072130 v2 approved; behavior specification awaits member confirmation. ContextPolicy: this checkout at `d1c7e40a128f94fce40efa170cdc32ca5c043da8`, fresh run and live tracker reads; no inherited artifact substitutes for a tracker read.

## Live authorities

- `multica issue property list 01a135a3-2118-7390-959f-3115633e0fba --output json`: `Shape intent` points to SD/17072130; `Shape state` displays `approved`.
- Atlassian `getConfluenceContent(content_id=17072130, detail=full, content_format=markdown)`: v2, updated 2026-10-17 03:51:16 UTC, `Authority=Approved`, model A. The opening paragraph and Outcome retain stale “not approved” prose. The approval field controls the gate.
- Atlassian `getJiraIssue(FOSS-126, view=evidence)`: updated 2026-10-13 21:26:07 +0700; original three acceptance rows remain. The first row conflicts with approved model A; this package asks for explicit acceptance of that reconciliation.

## Base and measurements

- `git rev-parse HEAD` returned `d1c7e40a128f94fce40efa170cdc32ca5c043da8`. `git diff --stat e00d870..HEAD --` across the five named source files returned empty.
- In a fresh project with `status()` and `status_()` in one `.functualize/jobs/tools.py`, `<checkout>/.venv/bin/func builtin info --json` returned one `tools.status`, winner `status_`, and one `JobNameCollision`; its `path` is `tools.py`. Two consecutive `func tools status` calls printed only `UNDERSCORE status_() ran` and exited 0. The second invocation checks the warm path.
- In a fresh project with `status()` in `a.py` and `status_()` in `b.py`, `func builtin info --json` returned one `tools.status` descriptor with `source_file` ending `b.py` and one `JobNameCollision` with `path` ending `a.py`. The message names `a` and `b`, not both source files. Thus both file paths are observable in the current full report without changing the existing failure payload, though Plan must prove the intended association for every claimant.
- On the two-file project, `func builtin info jobs --json` returned a one-element array without collision data; `func builtin info jobs` returned only `tools.status  Underscore status.`; `func tools --help` listed one status row; both `func tools status` and `func tools status_` ran `UNDERSCORE status_() ran` without a collision line.
- `rg -n 'JobNameCollision|discovery_failures' src/functualize tests` found existing collision tests in `tests/discovery/test_job_name_collisions.py` and full-report tests in `tests/cli/test_info_discovery_failures.py`. `src/functualize/_discovery/collisions.py:claim_order` sorts `(source_file, python_name)` and `resolve_name_collisions` retains the last claimant. `src/functualize/_types/discovery_report.py:job_name_collision` documents the dropped-claimant path.
- `/usr/local/bin/zg index . -g 'src/**' -g 'docs/**' -g 'contributor/**' -g 'plugins/**' -g '*.md' --embedding local/potion-code-16m-v2` indexed this checkout. `/usr/local/bin/zg query 'Why are job name collisions warnings instead of fatal, and how are missing jobs reported on CLI and warm cache?'` surfaced ADR-018 and the existing CLI path. ADR-018 deliberately keeps a faulty job non-fatal to preserve diagnostic commands and cold/warm agreement; collision policy in `collisions.py` also explicitly replaced fatal behavior.

## Scope correction

Two `def status()` declarations in one Python module are excluded: module namespace replacement happens before job discovery, so no existing `JobNameCollision` exists to surface. This is a shape ruling, not a claim that that source pattern is safe. Model A can only report findings discovery records. The issue's original “nothing prints” claim is false for the full `func builtin info` text and JSON views; the measured gap is the narrow `info jobs` view and invocation/help surfaces.
