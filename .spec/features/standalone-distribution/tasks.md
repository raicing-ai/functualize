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

### [x] 1.1 — P1: make `needs_terminal` resolve per family

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


---

## Wave 1 — P2

### [x] 2.1 — P2: `skills install` declares terminal ownership

`[F]` `src/functualize/_cli/builtins.py`, `tests/_cli/test_builtin_handoff.py`

Add `terminal_subcommands=("install",)` to the `skills` registry entry (`:96-105`).

**Do not modify `skills_install`'s body.** Its `subprocess.call` is correct — it inherits fd
0/1/2, which is what makes `npx skills add` interactive from a terminal. Changing it, or
capturing its output, breaks the working path (AC29).

Ordered after 1.1 by convention, but **not blocked by it** — corrected while executing 1.1.
Production resolves terminal ownership through `_builtin_needs_terminal(family, segment)`
(`app/commands.py:306-316`), which looks the *family* up and never consults the root's
flattened set.

**Wired at close**: `job_execution.run_builtin` → `_node_needs_terminal` →
`_run_builtin_handoff` → `request_handoff`.

Acceptance:
- From the inline shell, `builtin skills install` routes to `_run_builtin_handoff` rather than
  the worker (AC28) — **write this test before the fix and watch it fail**
- From a terminal, behavior is unchanged (AC29)
- `root.needs_terminal(["config","edit"])` still `True`; `["scaffold","add"]` still `False`

---

## Wave 2 — detection, reaching a real command

### [ ] 3.1 — Detection + `self doctor`, mounted and pre-boot

`[F]` `src/functualize/_cli/runtime.py` (new), `src/functualize/_cli/self_cmd.py` (new),
`src/functualize/_cli/builtins.py`, `src/functualize/_cli/main.py`,
`tests/_cli/test_runtime_detection.py` (new), `tests/_cli/test_self_doctor.py` (new)

**One slice, because detection with no caller is not done.** Four files is over the usual
1–3, and deliberately so: a `runtime.py` that nothing invokes would close unwired, which is
the ordering problem this wave structure exists to avoid.

`runtime.py` — pure `detect(prefix, base_prefix, environ, argv0) -> Detection` per
`schema.md`. Ladder order in `plan.md` §1 is **binding**; rung 5 is the only filesystem rung
and stays behind the pure ones. Docstring declares "stdlib + `_cli` siblings only".

`self_cmd.py` — a click group with **`doctor` only**. Later commands land in 6.1. Checks in
this slice: Python floor, CLI extras, job discovery from cwd, child-process boot probe,
runtime mode, owning distribution. **No manifest checks yet** — those need 4.1.

**The plugin-loading check is omitted, not faked** (AC12): `_load_file_plugin` records no
failures (`_plugins/loader.py:748,761-773`).

`builtins.py` — one `BuiltinCommand` entry for `self`, one `_mount`, following `skills`
(`:1521`) and `scaffold` (`:1526`).

`main.py` — intercept `self doctor` **pre-boot** beside `--version` (`:1694-1760`). `cli_app`
boots a full app before any builtin runs (`:160-330`), so a doctor mounted normally could
only ever report success for anything boot-shaped, and would never be reached when boot
fails.

**Wired at close**: `_run_cli` → pre-boot intercept → `self_cmd.doctor` → `runtime.detect`.
Cold and warm both, since the intercept precedes cache use entirely.

Acceptance:
- Every mode reachable in a test **without changing the interpreter the suite runs under** —
  the reason `detect()` takes its inputs as arguments (AC4)
- Each mode returned for its own synthetic input, asserted positively (AC1)
- No input yields `standalone` without a genuine PyApp signal (AC2)
- A scaffolded app's `argv0` yields that app's distribution (AC3)
- An unrecognised `FUNCTUALIZE_RUNTIME` raises rather than falling back
- `grep -n "^import\|^from" src/functualize/_cli/runtime.py` shows stdlib only
- Doctor produces a report when the app cannot boot (AC11) — `@surfaces("func")`; the app
  surface has no pre-boot layer
- The boot check drives the real CLI entry point, so it reports critical where
  `func builtin version` fails (AC11a)
- Doctor produces a report on a project whose plugin raises at import, and **does not claim
  plugin health** — the check is absent, not green (AC10, AC12)
- Report renders from one structure to both text and `--format json` (AC30a)
- Top level still holds exactly `BUILTIN_NAMES` (AC30)
- `uv run pytest tests/_cli/test_builtin_command_pilot.py -q` → **21 passed**, covering the
  new family without edits to that file
- Sabotage the `_mount(builtin_app, self_app, "self")` call; confirm a test fails

---

## Wave 3 — the registry

### [ ] 4.1 — Manifest, first-run registration, and doctor's manifest checks

`[F]` `src/functualize/_cli/manifest.py` (new), `src/functualize/_cli/main.py`,
`src/functualize/_cli/self_cmd.py`, `tests/_cli/test_manifest.py` (new)

Types per `schema.md`. Path from `resolve_user_config_dir()` via `functualize.app.utils` —
never a hardcoded home (AC5). No `remove` in the API (AC6). The record carries `packages`
alongside `plugins`, disjoint by construction.

One-shot registration via a marker file keyed over **`(binary_path, functualize_version)`** —
keyed on path alone, an in-place upgrade is masked forever. Appends are atomic
(temp file + `rename`). A malformed or higher-`schema_version` file degrades to empty.

Doctor gains the checks that need the registry: stale `binary_path` entries, and
enumeration of registered installations.

**Wired at close**: `_run_cli` → first-run marker `stat()` → (miss) `manifest.register`; and
`self doctor` → manifest read → stale + enumeration lines.

Acceptance:
- Written under `xdg_dirs.functualize_config` (AC5)
- A second install appends; no entry is removed (AC6)
- Registering the same installation twice adds one record, not two (AC9a)
- After a version change at the same `binary_path`, the record is **refreshed**, not appended
  (AC9d) — the test that catches a path-only key
- Two concurrent registrations both survive (AC9b) — drive it with real threads or processes;
  a mocked write cannot fail the way `rename()` protects against
- Enumeration returns every record with the running one distinguishable (AC9c)
- With the config dir read-only, the command still succeeds and prints no warning (AC9e)
- Hint on first invocation, absent on second (AC8)
- `functualize._cli.manifest` **absent from `sys.modules`** after a warm second invocation of
  an unrelated command (AC9) — structural, not timed
- Doctor reports an entry whose `binary_path` no longer resolves as stale (AC7)
- A corrupt file yields an empty manifest and does not raise
- **Negative gate (AC9f)**: `grep -rn "shutil.which\|os.walk\|iterdir\|subprocess" src/functualize/_cli/manifest.py`
  must be empty. The registry is written and read; it is never derived
- Sabotage the first-run registration call; confirm AC8's test fails

---

## Wave 4 — info

### [ ] 5.1 — Install facts in `builtin info`

`[F]` `src/functualize/_cli/builtins.py`, `src/functualize/_cli/info.py`

`full_report` gains the `install` block from `contracts.md` §3; the human form gains two
lines, `info all` also the manifest summary.

**Label it `Install mode:`, never `Mode:`** — `builtin info` already prints `Mode:` for state
storage whose value is already `standalone` (AC20a, `research.md` §1.6).

Rides `info`'s existing `--json`; adds no second spelling to that command.

**Wired at close**: `cli_app` → `builtin info` → `full_report` → `runtime.detect` + manifest.

Acceptance:
- `builtin info --json` carries `install.mode` and `install.owning_distribution`;
  `info all --json` also `install.manifest` (AC20)
- Both `Mode:` lines are unambiguous when both read `standalone` (AC20a)
- No `self paths` / `self config-info` command exists (AC21)

---

## Wave 5 — self-management

### [ ] 6.1 — `self update`, `self install`, `self python`, `self uv`

`[F]` `src/functualize/_cli/self_cmd.py`, `src/functualize/_cli/manifest.py`,
`src/functualize/_cli/builtins.py`

`update` names the axis-2 distribution, never a hardcoded `functualize` (AC31); prints the
exact command before doing anything (AC14); refuses in degraded modes with `ExitCode.REFUSED`
imported from `functualize.app.utils` (AC13).

Reconciliation captures the environment **before and after**, and restores by *name*
difference (`schema.md` → *Reconciliation*). Capture reads `dist-info` directory names
(2.4 ms), never package metadata (172 ms). `before` is persisted before the update starts.

`self install <pkg>` records under `packages`, stays out of `plugin list`, is restored by
`self update`. `self python` / `self uv`: with `--`, run the arguments; bare, print one
absolute path and nothing else.

Registry entry gains the four subcommands; `install`, `python`, `uv` declared terminal.

**Wired at close**: `cli_app` → `builtin self <cmd>`; and the TUI handoff path for the
terminal-owning three.

Acceptance:
- Degraded-mode `update` prints guidance, executes nothing, exits 3 (AC13)
- `self install` prints its command, requires confirmation, records under `packages` (AC14a)
- `self update` restores recorded `packages` as well as `plugins` (AC14b)
- A package added via the escape hatch, never recorded, survives an update (AC14f)
- A distribution-shipped package is **not** pinned back to its old version (AC14g) — the test
  that catches differencing over `(name, version)` instead of name
- The pre-update capture is persisted before the update runs (AC14h)
- Restored items are listed; an unreinstallable package is reported without failing (AC14i)
- `self python -- <args>` runs them and proxies the exit code (AC14c); bare prints one path
  (AC14e)
- With no functualize-owned environment, all three refuse with exit 3 (AC14d)
- No generated command string contains a literal `functualize` where the owner belongs (AC31)

---

## Wave 6 — plugins

### [ ] 7.1 — `builtin plugin list / install / uninstall`

`[F]` `src/functualize/_cli/plugin_cmd.py` (new), `src/functualize/_cli/builtins.py`,
`tests/_cli/test_plugin_cmd.py` (new)

Spans **eight** entry-point groups (`plan.md` §4). Uses stdlib `importlib.metadata` directly —
`_cli` may not import `_primitives.entry_points`. **Does not read the extension list back
after installing** (B5): the snapshot is taken at process start.

Receipt merge reconstructs PEP 508 from **every** key and round-trips unknown ones.

Registry entry plus mount; `install`/`uninstall` declared terminal.

**Wired at close**: `cli_app` → `builtin plugin <cmd>`; TUI handoff for the mutating two.

Acceptance:
- `plugin list` shows an `interactivity_providers` entry with both names (AC15) —
  `functualize-inline` registers in no other group
- `plugin install` in `unknown` mode prints guidance, executes nothing, exits 3 (AC16)
- Receipt merge round-trips `{name}`, `{name,specifier}`, `{name,url}` and an unknown key
  (property test, `_properties.py`)
- Every mutating path prints its command before any side effect (AC18)
- From the inline shell, `plugin install` requests handoff (AC19)
- Sabotage the `_mount(builtin_app, plugin_app, "plugin")` call; confirm a test fails

---

## Wave 7 — release pipeline

### [ ] 8.1 — Bake distributions and build binaries

`[F]` `.github/workflows/release.yml`

Insert **bake** (matrix over platform/arch: python-build-standalone + `functualize[all]`
installed) and **binaries** (PyApp over the baked artifacts) between `build` and
`github-release`. Current chain: `verify-ci → build → publish → github-release`.

Artifacts named by target triple, **including a musl Linux variant and Windows**
(`contracts.md` §8). Every variable from §7 set explicitly (AC25). No `src/` change.

Acceptance:
- Binaries for each supported platform/arch attached to the release, plus checksums
  (AC24, AC24a)
- CI asserts the **measured** binary size and reports it (AC23) — no estimate
- Workflow parses: `uv run python -c "import yaml; yaml.safe_load(open('.github/workflows/release.yml'))"`

---

## Wave 8 — verification and docs

### [ ] 9.1 — Container scenarios

`[F]` `examples/docs/scenarios/k-plugin-lifecycle.toml` (new),
`examples/docs/scenarios/l-standalone-binary.toml` (new),
`examples/docs/scenarios/b-install-flows.toml`

doc-verify scenarios, **not pytest** — never imported by the suite. Follow
`b-install-flows.toml`'s existing `engine = "docker"` shape.

- extend `b-install-flows.toml`: a `uv tool install` step asserting `tool_uv`, and a
  `pipx install` step asserting `tool_pipx` — **this settles the one detection signal still
  marked UNVERIFIED** (no pipx on the original audit host)
- `k-plugin-lifecycle.toml`: install plugin A, then B, assert **A survives** (AC17)
- `l-standalone-binary.toml`: run the binary with `--network none`, execute a job (AC22);
  and the install script picking musl without glibc, verifying the checksum first
  (AC24b, AC24c)

Acceptance: each scenario passes under `run-scenario`. A failing scenario is **reported, never
silently updated** (doc-verify rule 4).

### [ ] 9.2 — Documentation

`[F]` `README.md`, `contributor/reference/code-map.md`,
`contributor/architecture/codemaps/modules.md`

README gains a standalone install row: download, `chmod +x`, run — no Python prerequisite,
no network caveat. Both codemaps enumerate `_cli/` modules and would not fail
`tests/test_contributor_docs.py` if left stale (it only checks referenced paths exist), so
update by hand.

Acceptance: `uv run pytest tests/test_contributor_docs.py -q` green; the four new modules
appear in both codemaps.

---

## Wave 9 — checkpoint

### [ ] 10.1 — Close-out review

`[F]` none (review only)

- **AC12 by reading**: every doctor check can report something other than success. No
  automated form exists; do not invent one
- **AC32** — exercise every command from all three surfaces: direct CLI, inline TUI, and a
  scaffolded consumer app. No single earlier task owns this, because each tests its own
  command on one surface
- **AC33** — a consumer app with `register_builtins=False` still starts
- **AC9f, repo-wide** — no command scans `PATH`, walks a directory, or spawns a subprocess to
  learn about other installations. Re-run the 4.1 grep across `self_cmd.py` and
  `plugin_cmd.py`; `self update`'s capture reads `dist-info` names in the *owned*
  environment, which is not discovery
- Skills in `skills/` teach no command or flag this changed — `evals/` measures them
- Full suite; `uv run lint-imports` → **5 kept, 0 broken**
- Migrate the durable half to `.spec/STATUS.md` or an ADR, then
  `git rm -r .spec/features/standalone-distribution` and
  `.spec/shape-intents/standalone-distribution.md` — the `spec-artifacts-cleared` check
  blocks merge until that lands

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
    { "id": 0, "tasks": ["1.1"] },
    { "id": 1, "tasks": ["2.1"] },
    { "id": 2, "tasks": ["3.1"] },
    { "id": 3, "tasks": ["4.1"] },
    { "id": 4, "tasks": ["5.1"] },
    { "id": 5, "tasks": ["6.1"] },
    { "id": 6, "tasks": ["7.1"] },
    { "id": 7, "tasks": ["8.1"] },
    { "id": 8, "tasks": ["9.1", "9.2"] },
    { "id": 9, "tasks": ["10.1"] }
  ]
}
```

**Restructured 2026-09-03, after 1.1, into vertical slices.** The original graph built
`runtime.py` and `manifest.py` as wave-0 components and wired them two waves later, so both
would have closed with no production call path — the condition
`contributor/guides/wiring-discipline.md` §2 exists to prevent, and which 1.1 hit for a
different reason.

Each task now lands a component **together with the code that reaches it**, so every close
names a real path. The cost is 3.1 touching four files rather than the usual one to three:
a `runtime.py` with no caller is not a smaller task, only a task whose wiring is deferred.

Waves are almost fully serial, and that is the honest shape rather than a missed
parallelism: **`_cli/builtins.py` is the mount point for everything**, so six of the ten
tasks touch it and cannot share a wave. Only 9.1 and 9.2 are genuinely disjoint. 8.1 depends
on nothing in `src/` and could run at any point; it is placed late so a CI-infrastructure
failure cannot block shippable behavior.
