# Tasks: Standalone Distribution & Self-Management

**Feature**: `standalone-distribution`
**Date**: 2026-09-03
**Inputs**: `spec.md` (36 AC), `contracts.md`, `plan.md`, `schema.md`, `research.md`
**Baseline**: HEAD `39a0be2`

## Environment note for the executor

The venv is healthy as of 2026-09-03 — use the normal commands (`uv run pytest`,
`.venv/bin/pytest`, `uv run func`). Run `uv sync --all-extras` if anything is missing.

**If test commands start failing oddly, suspect a relocated venv.** A venv is built for one
absolute path: every console script in `.venv/bin` has the interpreter baked into its
shebang. Move or copy a worktree and all of them break at once, with a misleading symptom —
`uv run pytest` reports `Failed to spawn: pytest` (the kernel cannot find the interpreter the
shebang names, so it returns `ENOENT`), while `python -m pytest` still works because it
bypasses the shebang entirely.

`uv sync` does **not** repair it; it reconciles package state without regenerating scripts.
The fix is `rm -rf .venv && uv sync --all-extras`. `git worktree add` never copies `.venv`
(it is gitignored), so this only happens when a worktree is moved or copied by something
other than git. `mise.toml` now carries an `enter` hook that detects it.

Baselines measured at authoring time, all green:

| Command | Result |
|---|---|
| `uv run pytest tests/_cli/test_builtin_handoff.py tests/core/test_click_command_provider.py -q` | **29 passed** |
| `uv run pytest tests/_cli/test_builtin_command_pilot.py -q` | **21 passed** |
| `uv run lint-imports` | **5 kept, 0 broken** |

---

## Wave 0 — foundations

### 1.1 — P1: make `needs_terminal` resolve per family

`[F]` `src/functualize/_cli/builtins.py`, `tests/_cli/test_builtin_handoff.py`

Resolve the family before matching, per `plan.md` → P1. `get_builtin` (`:219-229`) already
answers for the root and each family; add no new state. Change only how the **root**
answers.

**Do not touch `_types/commands.py` or `app/commands.py`.** `_types/commands.py:52-70`
documents `CommandNode.needs_terminal` as a plain bool *because* `BuiltinCommand.needs_terminal`
is a predicate over args; P1 must not widen that.

Acceptance:
- `uv run pytest tests/_cli/test_builtin_handoff.py tests/core/test_click_command_provider.py -q` → **29 passed** (unchanged; run before editing too — AC27)
- New: with a simulated family declaring `install` terminal, `root.needs_terminal(["skills","install"])` is `False` and `root.needs_terminal(["plugin","install"])` is `True` (AC26). Assert the right answer, not `!= wrong`
- Commit, then sabotage by restoring the flat `any(...)` and confirm the new test fails

### 1.2 — `_cli/runtime.py`: detection

`[F]` `src/functualize/_cli/runtime.py` (new), `tests/_cli/test_runtime_detection.py` (new)

Pure `detect(prefix, base_prefix, environ, argv0) -> Detection` per `schema.md`. Ladder order
in `plan.md` §1 is **binding** — rung 5 is the only filesystem rung and must stay behind the
pure ones.

Module docstring declares "stdlib + `_cli` siblings only", matching
`_cli/data/func_settings.py:31`.

Acceptance:
- Every mode is reachable in a test **without changing the interpreter the suite runs
  under** — the whole reason `detect()` takes its inputs as arguments (AC4)
- Each mode returned for its own synthetic input, asserted positively (AC1)
- No input yields `standalone` without a genuine PyApp signal (AC2)
- A scaffolded app's `argv0` yields that app's distribution (AC3)
- An unrecognised `FUNCTUALIZE_RUNTIME` raises rather than falling back
- `grep -n "^import\|^from" src/functualize/_cli/runtime.py` shows stdlib only

### 1.3 — `_cli/manifest.py`: append-only install record

`[F]` `src/functualize/_cli/manifest.py` (new), `tests/_cli/test_manifest.py` (new)

Types per `schema.md`. Path from `resolve_user_config_dir()` via `functualize.app.utils` —
never a hardcoded home (AC5). No `remove` in the API (AC6). The record carries `packages`
alongside `plugins` (`schema.md`), disjoint by construction — `self install` writes one,
`plugin install` the other.

A malformed or higher-`schema_version` file degrades to empty with a warning; it never raises
into a command.

Also implements one-shot registration via the marker file and atomic appends
(`schema.md` → *The registration marker*, *Concurrency*). The registry is user-global, so a
project-local `func`, a uv tool install and a binary all register in the same file — there is
no second per-project store.

Acceptance:
- Written under `xdg_dirs.functualize_config` (AC5)
- A second install appends; no entry is removed (AC6)
- Registering the same installation twice adds one record, not two (AC9a)
- After a version change at the same `binary_path`, the record is **refreshed**, not appended
  — one binary, one record, new version (AC9d). The marker key covers the version, so this is
  the test that catches a path-only key
- With the config dir read-only, the command still succeeds and prints no warning (AC9e)
- Two concurrent registrations both survive (AC9b) — drive it with real threads or
  processes; a mocked write cannot fail the way `rename()` protects against
- Enumeration returns every record with the running one distinguishable (AC9c)
- A corrupt file yields an empty manifest and does not raise
- **Negative gate (AC9f)**: no discovery. Run at authoring time and record the hit count —
  `grep -rn "shutil.which\|os.walk\|iterdir\|subprocess" src/functualize/_cli/manifest.py`
  must be empty. The registry is written and read; it is never derived

---

## Wave 1 — P2

### 2.1 — P2: `skills install` declares terminal ownership

`[F]` `src/functualize/_cli/builtins.py`, `tests/_cli/test_builtin_handoff.py`

Add `terminal_subcommands=("install",)` to the `skills` registry entry (`:96-105`).

**Do not modify `skills_install`'s body.** Its `subprocess.call` is correct — it inherits fd
0/1/2, which is what makes `npx skills add` interactive from a terminal. Changing it, or
capturing its output, breaks the working path (AC29).

Requires 1.1: under the flat predicate this name would match in every family.

Acceptance:
- From the inline shell, `builtin skills install` routes to `_run_builtin_handoff` rather than
  the worker (AC28) — **write this test before the fix and watch it fail**
- From a terminal, behavior is unchanged (AC29)
- `root.needs_terminal(["config","edit"])` still `True`; `["scaffold","add"]` still `False`

---

## Wave 2 — command modules

### 3.1 — `_cli/self_cmd.py`: doctor + update + environment access

`[F]` `src/functualize/_cli/self_cmd.py` (new), `tests/_cli/test_self_cmd.py` (new)

Depends on 1.3 for the manifest's `packages` key.

Exports a click group with `doctor`, `update`, `install`, `python` and `uv` — **no `paths`,
no `config-info`** (O3, AC21). Types per `schema.md`; **no `SKIPPED` status** — an unperformable check is absent.

Boot-shaped checks run in a child process. **The plugin-loading check is omitted**, not faked
(AC12): `_load_file_plugin` records no failures (`_plugins/loader.py:748,761-773`).

`update` names the axis-2 distribution, never a hardcoded `functualize` (AC31); prints the
exact command before doing anything (AC14); refuses in degraded modes with
`ExitCode.REFUSED` imported from `functualize.app.utils` (AC13).

`self install <pkg>` reuses `plugin install`'s mechanism but records under the manifest's
`packages` key, stays out of `plugin list`, and is restored by `self update` alongside
plugins (AC14a, AC14b).

`self python` / `self uv` have two modes on one subcommand: **with `--`, run the arguments**
against the owned environment (the primary form — portable where `$(…)` is not, and
`--help`-discoverable); **bare, print the absolute path** and nothing else on stdout, so it
stays capturable (AC14c, AC14e).

Both are declared terminal-owning in 4.1: `CommandNode.needs_terminal` is a plain bool and
cannot vary per invocation, and running `uv pip install` captured on a TUI worker is the
defect P2 exists to fix. This does not affect shell capture — a builtin's `needs_terminal` is
read only by the TUI.

Acceptance:
- Degraded-mode `update` prints guidance, executes nothing, exits 3 (AC13)
- `self install` prints its command, requires confirmation, records under `packages` (AC14a)
- `self update` restores recorded `packages` as well as `plugins` (AC14b)
- A package added via the `self python`/`self uv` escape hatch, never recorded, survives an
  update (AC14f) — this is the case records alone cannot cover
- A distribution-shipped package is **not** pinned back to its old version (AC14g) — the test
  that catches differencing over `(name, version)` instead of name
- The pre-update capture is persisted before the update runs (AC14h)
- Restored items are listed; an unreinstallable package is reported without failing (AC14i)
- `self python` / `self uv` emit exactly one path; `$(func builtin self uv)` composes (AC14c)
- With no functualize-owned environment, all three refuse with exit 3 (AC14d)
- Report renders from one structure to both text and `--format json` (AC30a)
- Doctor produces a report when the app cannot boot (AC11)
- Doctor reports a manifest entry whose `binary_path` no longer resolves as stale (AC7)
- Doctor produces a report on a project whose plugin raises at import, and **does not claim
  plugin health** — the check is absent, not green (AC10, AC12)
- No generated command string contains a literal `functualize` where the owner belongs (AC31)

### 3.2 — `_cli/plugin_cmd.py`: list / install / uninstall

`[F]` `src/functualize/_cli/plugin_cmd.py` (new), `tests/_cli/test_plugin_cmd.py` (new)

Spans **eight** entry-point groups (`plan.md` §4). Uses stdlib `importlib.metadata` directly —
`_cli` may not import `_primitives.entry_points`.

**Does not read the extension list back after installing** (B5): the snapshot is taken at
process start.

Receipt merge reconstructs PEP 508 from **every** key and round-trips unknown ones.

Terminal declaration for `install`/`uninstall` is added in 4.1, not here.

Acceptance:
- `plugin list` shows an `interactivity_providers` entry with both names (AC15) —
  `functualize-inline` registers in no other group
- `plugin install` in `unknown` mode prints guidance, executes nothing, exits 3 (AC16)
- Receipt merge round-trips `{name}`, `{name,specifier}`, `{name,url}` and an unknown key
  (property test, `_properties.py`)
- Every mutating path prints its command before any side effect (AC18)

---

## Wave 3 — registry

### 4.1 — Register and mount `self` and `plugin`

`[F]` `src/functualize/_cli/builtins.py`

Two `BuiltinCommand` entries appended to `BUILTIN_COMMANDS`; two `_mount` calls following
`scaffold` (`:1526`) and `skills` (`:1521`).

- `self` — subcommands `doctor`, `update`, `install`, `python`, `uv`
- `plugin` — subcommands `list`, `install`, `uninstall`

Declare terminal: `self install`, `self python`, `self uv`, `plugin install`,
`plugin uninstall` — safe now that 1.1 has landed. `self python` / `self uv` are included
because their passthrough form runs arbitrary commands; their bare path-printing form stays
capturable from a shell regardless, since only the TUI reads the flag.

No other registry surface changes. The mirror test derives from `BUILTIN_COMMANDS` and needs
no edit.

Acceptance:
- `uv run pytest tests/_cli/test_builtin_command_pilot.py -q` → **21 passed**,
  now covering the two new families without edits to that file
- Top level still holds exactly `BUILTIN_NAMES` (AC30)
- From the inline shell, `plugin install` requests handoff (AC19)
- Commit, then sabotage the `_mount(builtin_app, self_app, "self")` call and confirm a test fails

---

## Wave 4 — surfaces

### 5.1 — Install facts in `builtin info`

`[F]` `src/functualize/_cli/builtins.py`, `src/functualize/_cli/info.py`

`full_report` gains the `install` block from `contracts.md` §3; the human form gains two
lines, `info all` also the manifest summary.

**Label it `Install mode:`, never `Mode:`** — `builtin info` already prints `Mode:` for state
storage whose value is already `standalone` (AC20a, `research.md` §1.6).

Rides `info`'s existing `--json`; adds no second spelling to that command.

Acceptance:
- `builtin info --json` carries `install.mode` and `install.owning_distribution`; `info all --json`
  also `install.manifest` (AC20)
- Both `Mode:` lines are unambiguous when both read `standalone` (AC20a)
- No `self paths` / `self config-info` command exists (AC21)

### 5.2 — Pre-boot doctor intercept and first-run hint

`[F]` `src/functualize/_cli/main.py`

Intercept `self doctor` in `_run_cli` beside `--version` (`:1694-1760`) so it answers before
`cli_app` boots the app (`:160-330`).

First-run hint costs **one `stat()`**; `_cli.manifest` is imported only on the miss path.

Acceptance:
- Doctor reports when the app cannot boot (AC11)
- Hint on first invocation, absent on second (AC8)
- `functualize._cli.manifest` **absent from `sys.modules`** after a warm second invocation of
  an unrelated command (AC9) — structural, not timed
- Consumer app with `register_builtins=False` still starts (AC33)

---

## Wave 5 — release pipeline

### 6.1 — Bake distributions and build binaries

`[F]` `.github/workflows/release.yml`

Insert **bake** (matrix over platform/arch: python-build-standalone + `functualize[all]`
installed) and **binaries** (PyApp over the baked artifacts) between `build` and
`github-release`. Current chain: `verify-ci → build → publish → github-release`.

Every variable from `contracts.md` §7 set explicitly (AC25). No `src/` change; the wheel
publishes unchanged.

Acceptance:
- Binaries for each supported platform/arch attached to the release (AC24)
- CI asserts the **measured** binary size and reports it (AC23) — no estimate
- Workflow parses: `.venv/bin/python -c "import yaml,sys; yaml.safe_load(open('.github/workflows/release.yml'))"`

---

## Wave 6 — verification and docs

### 7.1 — Container scenarios

`[F]` `examples/docs/scenarios/k-plugin-lifecycle.toml` (new),
`examples/docs/scenarios/l-standalone-binary.toml` (new),
`examples/docs/scenarios/b-install-flows.toml`

doc-verify scenarios, **not pytest** — they are never imported by the suite. Follow
`b-install-flows.toml`'s existing `engine = "docker"` shape.

- extend `b-install-flows.toml`: a `uv tool install` step asserting `tool_uv`, and a `pipx
  install` step asserting `tool_pipx` — **this settles the one detection signal still marked
  UNVERIFIED** (no pipx on the original audit host)
- `k-plugin-lifecycle.toml`: install plugin A, then B, assert **A survives** (AC17)
- `l-standalone-binary.toml`: run the binary with `--network none`, execute a job (AC22)

Acceptance: each scenario passes under `run-scenario`. A failing scenario is **reported, never
silently updated** (doc-verify rule 4).

### 7.2 — Documentation

`[F]` `README.md`, `contributor/reference/code-map.md`,
`contributor/architecture/codemaps/modules.md`

README gains a standalone install row (AC-adjacent, `PY.5`): download, `chmod +x`, run — no
Python prerequisite, no network caveat. Both codemaps enumerate `_cli/` modules and would not
fail `tests/test_contributor_docs.py` if left stale (it only checks referenced paths exist),
so update by hand.

Acceptance: `uv run pytest tests/test_contributor_docs.py -q` green; the four new
modules appear in both codemaps.

---

## Wave 7 — checkpoint

### 8.1 — Close-out review

`[F]` none (review only)

- **AC12 by reading**: every doctor check can report something other than success. No
  automated form exists; do not invent one
- Skills in `skills/` teach no command or flag this changed — `evals/` measures them
- Full suite: `uv run pytest -q`
- import-linter: **5 kept, 0 broken** (baseline)
- Name every wiring path from `spec.md`'s list, cold and warm; confirm each sabotage already
  performed in 1.1, 2.1 and 4.1 was committed first
- **AC32** — exercise every command from all three surfaces: direct CLI, inline TUI, and a
  scaffolded consumer app. This is the criterion no single earlier task owns, because each
  task tests its own command on one surface
- **AC9f, repo-wide** — no command scans `PATH`, walks a directory, or spawns a subprocess to
  learn about other installations. Re-run the 1.3 grep across `self_cmd.py` and
  `plugin_cmd.py` too; `self update`'s environment capture reads `dist-info` names in the
  owned environment, which is not discovery
- Migrate the durable half to `.spec/STATUS.md` or an ADR, then `git rm -r .spec/features/standalone-distribution`
  — the `spec-artifacts-cleared` check blocks merge until that lands

---

## Notes on scope discipline

Three findings surfaced during Specify and are **out of scope**. Do not fix them here:

| Finding | Where it lives |
|---|---|
| Global `--output` hard-errors on every builtin | `research.md` §1.4 — file separately |
| `--perf-report` misparses before a builtin | `research.md` §1.5 — file separately |
| `--json` / `--format` split across six commands | `.spec/shape-intents/output-flag-normalization.md` — **D1 open** |

Also out of scope: converting builtins to jobs
(`.spec/shape-intents/builtins-as-jobs.md`, **B1 undecided**).

---

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1.1", "1.2", "1.3"] },
    { "id": 1, "tasks": ["2.1"] },
    { "id": 2, "tasks": ["3.1", "3.2"] },
    { "id": 3, "tasks": ["4.1"] },
    { "id": 4, "tasks": ["5.1", "5.2"] },
    { "id": 5, "tasks": ["6.1"] },
    { "id": 6, "tasks": ["7.1", "7.2"] },
    { "id": 7, "tasks": ["8.1"] }
  ]
}
```

**Why these waves.** Ordering is forced more by file disjointness than by logic: **five tasks
touch `_cli/builtins.py`** (1.1, 2.1, 4.1, 5.1) and cannot share a wave.

Logical dependencies are only:

- 1.1 → 2.1 and 1.1 → 4.1 — declaring a name terminal is unsafe under the flat predicate
- 1.2, 1.3 → 3.1, 3.2 — the command modules consume detection and the manifest
- 3.1, 3.2 → 4.1 — mounting needs the groups to exist
- 3.1 → 5.2 — the pre-boot intercept dispatches to doctor

Wave 4 pairs 5.1 (`builtins.py` + `info.py`) with 5.2 (`main.py`) — disjoint. Waves 5 and 6
depend on nothing in `src/` and are placed last so a CI-infrastructure failure cannot block
shippable behavior.
