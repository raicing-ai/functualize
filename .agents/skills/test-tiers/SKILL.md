---
name: test-tiers
description: >
  Choose how much of the pytest suite to run for a change — the step tier
  (only the tests importing what you touched, selected by the deterministic
  tests-for-diff mapper), the wave tier (the touched directories), or the
  tip tier (everything). Holds each tier's measured cost and the one hard
  rule: no pytest command may be expected to outrun the 600 s tool-call
  cap, and none may be backgrounded.
---

# Test tiers — run the smallest suite that answers the question

**Never issue a pytest command whose expected runtime exceeds the 600 s
tool-call cap, and never background one.** If the tier you picked cannot
finish inside the cap, drop to a narrower tier or split it into foreground
chunks. Backgrounding does not make a long suite shorter — it makes its
result unobservable and its failure invisible.

## The tiers

| Tier | What runs | Measured cost | How to select |
|---|---|---|---|
| **Step** | the test files that import what you touched | one file: 3.2 s wall, 0.18 s of it tests; a 26-file importer set (321 tests): 16.4 s at `-n 6` | `tests-for-diff` output |
| **Wave** | the directories this wave touches | 4 dirs / 2633 tests: 67.0 s at `-n 6`, 310.9 s serial | name the directories |
| **Tip** | everything, including property tests | 12 598 tests: **1257 s** at `-n 6` locally — no single tool call holds it; 1597 s in CI | shared infrastructure changed, or a release-grade question |

Measured on the shared 6-core host at load 2–7 (2026-09-24/25). Step-tier
numbers re-measured at `498a8a5`; wave and tip numbers were measured at
`1f3b760` — re-measure before quoting them for a different tree. The
"~10 min" full-suite claim is false: 1257 s locally, 1597 s on the 4-core
CI runner (`test-fast` 758.6 s, `test-full` 1597.2 s).

## The mapper: tests-for-diff

`scripts/tests-for-diff` in this skill's directory maps a change set to
pytest paths — deterministic, stdlib-only, no database to build or
invalidate:

```bash
uv run pytest -n auto -q --no-header $(.agents/skills/test-tiers/scripts/tests-for-diff)
```

Default input is the diff against `$(git merge-base origin/master HEAD)`
plus the uncommitted changes. `--files <path>...` names the change set
directly (no git needed); `--base <ref>` re-bases the diff. Output is
deduplicated, sorted, existing paths, one per line.

Selection rules, per changed path:

- a changed `tests/**/test_*.py` selects itself;
- a changed `src/functualize/<pkg>/<mod>.py` selects every test file whose
  source imports that module — `functualize.<pkg>.<mod>` in any form, or
  `from functualize.<pkg> import <mod>`;
- if no test imports it directly (measured case: `_engine/job_middleware.py`,
  exercised through DI, imported by no test), it falls back to every test
  file referencing `functualize.<pkg>` and says so on stderr;
- a changed `plugins/<group>/<name>/**` selects that plugin's own `tests/`
  directory, if it has one;
- shared infrastructure — `tests/conftest.py`, `tests/_support/**`,
  `pyproject.toml`, `uv.lock` — prints nothing and **exits 3**: narrowing
  is not sound there, run the tip tier;
- everything else (`docs/`, `.spec/`, `contributor/`, …) selects nothing;
  exit 0.

Exit codes: `0` selection printed (possibly empty), `3` shared
infrastructure changed, `2` usage or git error.

## Why narrowing beats a cache

An import-graph scan needs no warm-up database, cannot serve stale hits,
and its per-step cost is dominated by interpreter startup, not selection:

- whole-tree collection costs 25.5 s warm / 67.8 s cold — the step and
  wave tiers never pay it; one directory collects in 3.2 s;
- `-n 6` is the local optimum (4.64× over serial; `-n 8` is worse),
  ~1.2 GB RSS across workers at `-n 6`;
- one property test (`test_parallel_and_log_properties.py` →
  `test_results_maintain_input_positional_order`) takes 212.6 s alone and
  floors every full-tier wall time;
- `perf_budget` stays a CI-enforced budget, never a local gate: a serial
  local run went red at 0.55–0.7× cores with no code cause.
