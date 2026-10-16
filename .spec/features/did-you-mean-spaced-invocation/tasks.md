# Tasks — did-you-mean-spaced-invocation

Each task is checked only when its own acceptance gate is green against the code
as it stands. Behaviour is in `spec.md` (B1–B6, AC1–AC8). The signatures are in
`contracts.md`. Base: `master` `d1c7e40a128f94fce40efa170cdc32ca5c043da8`.

Toolchain, from the repo root: `uv sync --frozen --all-extras --all-packages`,
then `uv run …`. Never use bare `python`.

## T1 — Regression test, written first (tests only)

[F] `tests/cli/test_did_you_mean_spelling.py` (new).

Use `cli_run` and `project_tree`, restricted with `@surfaces("func")`
(`from tests.conftest import surfaces`). The app door is out of scope; see
`research.md` R2. Project: `suite.py` (`JOB_GROUP = "suite"`, jobs `inventory`
and `versions`) and `deploy_web.py` (`JOB_GROUP = "deploy.web"`, job `run`).
Each job prints a marker.

- AC1: `func suite.inventori` gives `"  func suite inventory\n"` in stderr,
  `"func suite.inventory"` not in stderr, `"  func suite\n"` in stderr, and
  exit 1.
- AC3: `func deploy.web.rnu` gives `"  func deploy web run\n"` in stderr.
- AC4: `func versions` gives `"  func suite versions\n"` in stderr.
- AC2: for every `  func …` line printed above, run it back with
  `cli_run(line.split()[1:])`. It exits 0, and job lines print their marker.
- AC5: `func suite` and `func deploy --help` stdout, and the non-TTY job listing
  lines, equal the base text in `spec.md` (the listing stays dotted).

- [ ] Acceptance: at `d1c7e40`, `uv run pytest tests/cli/test_did_you_mean_spelling.py -q`
  fails on AC1, AC3 and AC4 only, and passes AC2 and AC5. Paste the failure
  summary into the delivery record. Commit before T2.

## T2 — One derivation for a job's segments, made public

[F] `src/functualize/_types/naming.py`, `src/functualize/app/commands.py`,
`tests/discovery/test_group_trie.py`, `tests/core/test_job_invocation.py` (new).

- Rename `_job_segments` → `job_segments` and add it to `__all__`. The body is
  unchanged. No alias is kept (CONSTITUTION: no shims).
- In `app/commands.py`, add
  `job_invocation(job: Any) -> str = " ".join(job_segments(getattr(job, "group", None), str(job.name)))`,
  with a docstring stating the rule and why it shares the trie's derivation.
  Add it to `__all__`.
- In `tests/discovery/test_group_trie.py:89`, update the docstring reference to
  the new name.
- New unit tests (AC6). Each takes a `SimpleNamespace(name, group)`:
  - `("suite.inventory", "suite")` gives `suite inventory`.
  - `("deploy.web.run", "deploy.web")` gives `deploy web run`.
  - `("tools.lint", None)` gives `tools.lint`.
  - `("pack", "ci")` gives `ci pack`.
  - `("hello", None)` gives `hello`.

Authoring-time hit set for the rename: `rg -n "_job_segments" src tests plugins`
returned **3** hits (`naming.py:385`, `naming.py:561`,
`test_group_trie.py:89`). That is the full [F] for the rename.

- [ ] Acceptance: `rg -n "_job_segments" src tests plugins` returns 0 hits.
  `uv run pytest tests/core/test_job_invocation.py tests/discovery/test_group_trie.py -q`
  is green. `uv run lint-imports` is green. T1 is still red on AC1, AC3 and AC4,
  because nothing calls the new function yet.

## T3 — The hint prints the job's command path

[F] `src/functualize/_cli/main.py`, `CHANGELOG.md`.

- At `_cli/main.py:1466-1471`, keep `discovered_names` and the
  `suggest_similar_commands` call as they are. Before the loop, build
  `jobs_by_name = {j.name: j for j in jobs}`. Print
  `f"  func {job_invocation(job) if (job := jobs_by_name.get(suggestion)) else suggestion}"`,
  or the equivalent plain form. Import `job_invocation` lazily from
  `functualize.app.commands`, matching the neighbouring lazy import of
  `suggest_similar_commands`.
- Add `CHANGELOG.md` → `## [Unreleased]` → one `### Fixed — …` entry in the
  file's own prose style. It should say the hint now prints a grouped job the
  way the group help and docs spell it (`func suite inventory`), that the dotted
  form still runs, and that the job listing stays dotted.

Authoring-time hit set: `rg -n 'print\(f"  func \{suggestion\}"' src` returned
**1** hit (`_cli/main.py:1470`).

- [ ] Acceptance: T1 is fully green. **Reachability:** commit, then temporarily
  restore `print(f"  func {suggestion}", ...)` and watch T1's AC1, AC3 and AC4
  go red. Restore with `git checkout -- src/functualize/_cli/main.py`. The
  production call path is `main()` → `_handle_job` → unknown-command branch →
  `job_invocation`. `rg -n 'print\(f"  func \{suggestion\}"' src` returns 0
  hits.

## T4 — Validation checkpoint and durable half

[F] `.spec/STATUS.md`, plus no source file.

- `uv run ruff check --fix src/ tests/ plugins/ examples/`,
  `uv run ruff format --check src/ tests/ plugins/ examples/`,
  `uv run mypy src/` and `uv run lint-imports` all pass.
- Run the pytest tier with at most two invocations: the touched files first,
  then `uv run pytest -x -q --no-header` with the log written to
  `/tmp/functualize-pytest.log`.
- Run `uv run python .github/scripts/dead_code_delta.py d1c7e40 HEAD`.
  `job_invocation` must not be `NEW_DEAD`/`TESTS_ONLY`, because T3 calls it.
- Re-run the repro from `spec.md` on the branch head and paste the after-output
  (E1–E5 of SD/17104932).
- Migrate the durable half to `.spec/STATUS.md` under `## Completed`: one entry
  stating the rule ("the CLI prints a job's command path as `job_segments`
  joined by spaces; the identity stays dotted"), plus the two named follow-ups
  (the leaf usage line, and the app-door hint/TUI renderers adopting
  `job_segments`).
- The **last** commit, pushed separately after the feature push validates, is
  deletion-only: `git rm -r .spec/features/did-you-mean-spaced-invocation`.

- [ ] Acceptance: every command above is green. The dead-code delta and the
  repro output are pasted into the delivery record. `.spec/STATUS.md` carries
  the entry.

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["T1"] },
    { "id": 1, "tasks": ["T2"] },
    { "id": 2, "tasks": ["T3"] },
    { "id": 3, "tasks": ["T4"] }
  ]
}
```
