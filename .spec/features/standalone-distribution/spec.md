# Spec: Standalone Distribution & Self-Management

**Feature**: `standalone-distribution`
**Date**: 2026-09-03
**Source**: [`.spec/shape-intents/standalone-distribution.md`](../../shape-intents/standalone-distribution.md)
(60 assertions, re-audited against HEAD `39a0be2`; decisions O1–O4 resolved 2026-09-03)
**Phase**: Specify — behavior only. No implementation, no file layout, no type design.

---

## Problem

Installing and maintaining functualize leaks Python packaging into the user experience.

A user who installed with `uv tool install` and one who downloaded a binary have no shared
way to ask "how do I upgrade this?" or "how do I add a plugin?" — and functualize cannot
answer, because it does not know how it was installed. Any answer it guesses is wrong for
someone: a `uv tool upgrade` printed to a pipx user is a command that does not exist, and an
updater run against a binary it does not own is worse than no answer.

There is a second, quieter failure. Functualize can be *embedded* — a consumer application
built on it gets the whole first-party command tree by default. Today those commands would
speak about `functualize` when they should speak about the consumer's own distribution.

And there is no answer at all for a user with no Python. There is no binary.

**None of this exists.** Verified 2026-09-03 at `39a0be2`: a repo-wide grep for
`FUNCTUALIZE_RUNTIME`, `install.json`, `PYAPP` and `InstallMode` returns zero hits.

## Scope

**In**, per the shape intent's five sections plus two items pulled in by decision on
2026-09-03:

| # | Area |
|---|---|
| 1 | Runtime detection — how this `func` was installed, and which distribution owns it |
| 2 | Install manifest, and a first-run hint |
| 3 | `func builtin self doctor`, `self update`, `self install`, `self python`, `self uv` |
| 4 | `func builtin plugin list \| install \| uninstall` |
| 5 | A pre-baked, fully offline single binary |
| **P1** | Make builtin terminal-ownership resolution family-aware (prerequisite to §4) |
| **P2** | Fix `func builtin skills install` corrupting the inline TUI |

**Out**:

- The daemon. `.spec/STATUS.md` records it has no spec and no unblocking event. The former
  `self daemon *` subcommands are removed, not deferred.
- Converting builtins to jobs. Tracked separately and **undecided** —
  [`builtins-as-jobs.md`](../../shape-intents/builtins-as-jobs.md).
- Any new top-level command name. Exactly one is reserved and it is `builtin`.

> **P1 and P2 are in scope by explicit decision.** Both are independently shippable and were
> offered as separate changes; the maintainer chose to keep them here. P1 **must** land
> before any §4 command declares itself terminal-owning. P2 is unrelated to §4 and may land
> at any point.

## Core principle

**One installation has one owner, and every mutating command names that owner's tool.**

Where the owner cannot be determined, the command **refuses and explains**. It never
guesses, and never performs part of an action. A wrong guess prints commands that do not
exist and runs updaters against binaries they do not own.

---

## User stories

**As an ops user with no Python**, I download one file, mark it executable, and run it. It
works with no network connection, because everything it needs is already inside it.

**As a Python developer who installed with `uv tool install`**, when I ask functualize to
update itself or add a plugin, it tells me the exact `uv` command it is about to run and
waits for me to confirm.

**As a pipx user**, the same, in `pipx` terms.

**As a developer working in a project checkout**, functualize tells me it cannot manage
itself here and explains why, rather than running something that would damage my venv.

**As a user of an application built on functualize**, `myapp builtin self update` talks about
*myapp*, never about functualize.

**As anyone whose install is broken**, `func builtin self doctor` still runs and still tells
me what is wrong — including when the application cannot boot at all.

**As a user of the inline shell**, a command that needs the terminal gets the terminal,
whether it is `config edit`, `skills install`, or `plugin install`.

---

## Behavior

### B1 — Runtime detection

Functualize determines two independent facts before answering any self-management question:

1. **Environment kind** — one of: standalone binary, uv tool, pipx tool, project checkout,
   bare pip (degraded), or unknown (degraded).
2. **Owning distribution** — which distribution provides the console script currently
   running. For `func` this is `functualize`; for a scaffolded app's own script it is that
   app's distribution.

Detection is first-match-wins over an ordered ladder. An explicit environment override is
honoured first so tests and CI can pin a mode. Detection consults the filesystem only after
every cheaper signal has been tried, and never on the warm path of an unrelated command.

An unrecognised environment resolves to **unknown**. It never falls back to standalone.

### B2 — Install manifest and first run

Functualize records each installation it has run from: where the binary is, what kind of
install it is, which distribution owns it, the Python and functualize versions, any plugins
added through `plugin install`, and when it was first seen.

The record is **append-only** — installations are never deleted, because two installs
coexisting is a real state and PATH decides which one runs. An entry whose binary no longer
exists is *reported as stale*, not silently trusted or removed.

On the first run after installation, functualize prints a one-line hint pointing at
`self doctor`. Nothing is blocked, and the hint appears once.

**The manifest is the registry of every `func` that has run on this machine**, not only a
history of one installation. It lives in one user-global location, so a project-local
`.venv/bin/func`, a uv tool install, and a downloaded binary all register in the same file,
each under its own binary path. Any installation can therefore enumerate the others, with the
running one marked. A project-scoped view is a filter over that one file — there is no
second, per-project registry to keep in sync.

**Nothing is discovered.** The registry is a pre-defined file that any running `func` updates
voluntarily — there is no `PATH` scan, no tool-directory listing, no filesystem walk, and no
executing another binary to interrogate it. An installation is therefore knowable only **after
it has run at least once**, which is the intended predicate: a `func` that has never executed
has produced no state, no config and no jobs, and is not yet a fact about the system
(`research.md` §1.10).

**Registration is voluntary, so failing to register is never an error.** A read-only config
directory, a container, a sandbox — each makes it impossible, and each must degrade silently.
No warning, no non-zero exit, no retry. Bookkeeping may not interfere with the command the
user typed.

**Registration happens once per installation identity, and ordinary commands do not pay for
it.** An installation records itself on first run and leaves a marker; every later run
confirms that marker's existence and does nothing else. **Identity includes the version** — an
in-place upgrade must refresh that installation's record rather than being masked by a marker
from the previous version, or replaced by a second record for the same binary. Measured on this machine: confirming the marker
costs ~3 µs against a ~474 ms baseline, while *importing* the manifest machinery costs ~1 ms
per record type — so the constraint that matters is that ordinary runs never load that
machinery at all, not that they avoid reading the file (`research.md` §1.9).

**Two installations registering at the same moment must both survive.** Append-only is
precisely the property a lost update violates.

### B3 — `self doctor`

Doctor reports the health of the installation, and it must work when the application is
too broken to start. A check that could only ever succeed is not shipped.

Doctor reports:

- Python version against the supported floor
- Whether the CLI extras are present
- Whether jobs are discoverable from the current directory
- Whether the application can boot — observed, not assumed
- Runtime mode and owning distribution
- Manifest entries whose binary path no longer exists
- Terminal capabilities
- In standalone mode: manifest-recorded plugins that are no longer installed

Doctor does **not** claim plugin-loading health it cannot observe. Functualize currently
discards plugin load failures without recording them; until a failure record exists, the
plugin check is **omitted rather than faked**.

### B4 — `self update`

`self update` upgrades the *owning distribution* using the tool that owns it, always
printing the exact command first and asking for confirmation.

In standalone mode it additionally reconciles afterwards, because rebuilding the managed
environment discards everything installed into it separately.

**Reconciliation works from observation, not only from records.** The manifest knows what
`self install` and `plugin install` added, but the `self python`/`self uv` escape hatch
bypasses that bookkeeping by design — anything added through it would otherwise be destroyed
silently. So the update:

1. **Captures the environment before it starts**, and persists that capture before touching
   anything, so an interrupted update can still recover.
2. Runs the update, which rebuilds the environment.
3. **Captures the environment again.** This second capture is the new baseline — what the
   distribution itself ships.
4. **Restores by name difference**: anything present before and absent after was a user
   addition, and is reinstalled. Recorded packages and plugins are included whether or not
   the capture saw them.

**The comparison is by name, never by name-and-version.** A package the distribution ships is
present in both captures at different versions after an upgrade; restoring the earlier version
would silently undo the upgrade's own dependency updates. Only names absent from the *new*
environment are user additions.

Restoration prefers the version that was present and falls back to unresolved when the new
dependency set cannot satisfy it — saying which, rather than silently choosing either. A
package that cannot be reinstalled at all is reported and does not fail the update.

Everything restored is listed. Reconciliation is never silent, in either direction.

In degraded modes it refuses, explains, and exits with the refusal exit code.

### B4a — Reaching the installation's own environment

A job runs under the interpreter that runs `func`, against that interpreter's packages. In a
project this is already the project's environment — `uv run func`, an activated venv, `mise`
putting `.venv/bin` first — so the user's `PATH` selects it and nothing needs to intervene.

A **deliberately-invoked standalone binary** is the case with no such environment. Its bundle
holds functualize and the first-party plugins and nothing else, so a job importing `requests`
fails with no supported remedy.

Two surfaces close that, without functualize ever reaching into an environment it does not
own:

- **`self install <package>`** — first-class. Installs into the owning installation's
  environment using that installation's tool, printing the exact command and asking for
  confirmation. **Recorded in the manifest**, so `self update` restores it after an update
  rebuilds the environment.
- **`self python -- <args>`** and **`self uv -- <args>`** — the escape hatch. Each runs the
  given arguments against that environment, so anything `self install` does not cover remains
  possible. Invoked bare, each prints the absolute path instead, for the case that wants a
  path rather than an execution.

`self install` and `plugin install` share a mechanism and differ in bookkeeping: a plugin
extends functualize and appears in `plugin list`; a package satisfies a job's imports and does
not. They are recorded under separate manifest keys so the distinction survives an update.

In modes where there is no environment functualize owns, all three refuse with the refusal
exit code rather than guessing.

### B5 — `plugin list | install | uninstall`

`plugin list` shows every registered functualize extension, not only one kind. The codebase
reads eight distinct extension groups, and at least one first-party plugin appears in none
of the group most listings use. Each entry shows both the name it registers under and the
distribution that provides it, because uninstalling needs the latter.

`plugin install` and `plugin uninstall` mutate the installation using the owning tool, and
always print the exact command and ask for confirmation before any side effect. In the
uv-tool case the existing set of extras must be preserved, since a naive install drops them.

Neither command reads back the extension list in the same invocation — the running process's
view of installed distributions is a snapshot taken at start.

In degraded modes both refuse with guidance and the refusal exit code.

### B6 — Install facts appear in `info`, not in new commands

Runtime mode, owning distribution and manifest summary are added to the existing `builtin
info` output and to its full-document and JSON forms. **No `self paths` or `self config-info`
command is created** — the existing `config path` and `info` already answer those questions,
and a second answer would drift from the first.

**The new field is labelled `Install mode:`, never `Mode:`.** `builtin info` already prints
`Mode:` under *Runtime State*, for state storage, and its value there is already the word
`standalone` — meaning "no project directory found". This feature's install mode has a
`standalone` value meaning "the pre-baked binary". Both would appear on one screen. The label
and the JSON nesting must keep them distinguishable (see `research.md` §1.6).

### B7 — A standalone binary

A single downloadable executable per supported platform, containing a Python distribution
with functualize and **all** first-party plugins already installed. Running it for the first
time requires **no network access**.

Its self-management commands speak in terms of the bundled tooling. Its internal updater
remains reachable but is not part of the documented surface.

### B8 (P1) — Terminal ownership resolves per family

When functualize decides whether a first-party command takes over the terminal, the answer
is resolved against the family the command actually belongs to.

Today a subcommand name declared by one family is matched in *every* family, so two
unrelated families sharing a subcommand name produce a wrong answer. This must become
impossible rather than avoided by choosing names carefully.

Behavior visible to users is unchanged for every command that exists today.

### B9 (P2) — `skills install` gets the terminal

`func builtin skills install` runs an interactive third-party installer. Run from a terminal
it works correctly today and **must keep working exactly as it does**.

Run from the inline shell it currently executes without the terminal being handed over, so
the installer's prompts and output reach the terminal underneath the running interface.
After this change the inline shell steps aside for it, exactly as it does for
`config edit`.

---

## Acceptance criteria

Each is a behavior, checkable without reference to implementation. Per
`.spec/CONSTITUTION.md` → *Acceptance Gates*, each is run at authoring time.

### Detection

- **AC1** — For each supported environment signal, detection returns that exact mode.
  Asserted as the right answer, never as "not the wrong one".
- **AC2** — An unrecognised environment returns unknown. No input produces standalone
  except a genuine standalone signal.
- **AC3** — For a scaffolded application's console script, the owning distribution is that
  application, not functualize.
- **AC4** — Detection is decidable from supplied inputs alone, so every mode is reachable in
  a test without changing the interpreter it runs under.

### Manifest and first run

- **AC5** — The manifest is written under the user config directory honoured by the rest of
  the CLI, never a hard-coded home path.
- **AC6** — A second installation adds a record; no existing record is removed.
- **AC7** — An entry whose binary path no longer exists is reported by doctor as stale.
- **AC8** — The first-run hint appears on the first invocation and not on the second.
- **AC9** — A warm second invocation of an unrelated command does not load the manifest
  machinery at all.
- **AC9a** — An installation registers itself once. A second run of the same installation
  adds no record and rewrites nothing.
- **AC9b** — Two registrations racing each other both survive; neither overwrites the other.
- **AC9c** — Any installation can enumerate every registered installation, with the running
  one distinguishable from the rest.
- **AC9d** — After an in-place version upgrade, the registry reports the new version, and the
  binary still has exactly one record.
- **AC9e** — When the registry cannot be written, the invoked command still succeeds, prints
  no warning about it, and exits with the code it would otherwise have used.
- **AC9f** — No command performs a `PATH` scan, a directory walk, or a subprocess in order to
  learn about other installations.

### Self

- **AC10** — `self doctor` produces a report on a project whose plugin raises on import,
  and the report does not claim plugin health.
- **AC11** — `self doctor` produces a report even when the application cannot boot. It does
  not fail with a traceback of its own.

  **On the `func` entry point only** — found while implementing 3.1. A consumer application's
  own `main.py` has no pre-boot layer at all (`contributor/architecture/surface-boundary.md`),
  so it reaches `self doctor` through the mounted group, which boots first; a boot failure
  makes doctor unreachable there exactly as it does every other builtin. Answering under a
  broken boot is a property of *how you reach the program*, which that document allows to be
  `func`-only. Closing the gap would mean giving `CliAdapter` a pre-boot layer, which is a
  larger decision than this feature.
- **AC11a** — The boot check drives the **real CLI entry point**, not a bare `FunctualizeApp`.
  A bare app boots with none of the CLI's discovery config and reports success in projects
  where `func builtin version` in fact fails.
- **AC12** — No check in doctor's output can only ever report success.
- **AC13** — `self update` in a degraded mode prints guidance, performs no action, and exits
  with the refusal code.
- **AC14** — `self update` prints the exact command it will run and does nothing without
  confirmation.
- **AC14a** — `self install <pkg>` prints its exact command, requires confirmation, and
  records the package in the manifest under a key distinct from plugins.
- **AC14b** — After `self update`, packages recorded by `self install` are restored, in the
  same reconciliation that restores recorded plugins.
- **AC14f** — A package installed through the `self python`/`self uv` escape hatch — never
  recorded by `self install` — survives an update.
- **AC14g** — A package the distribution itself ships is **not** pinned back to its
  pre-update version by reconciliation. Comparison is by name.
- **AC14h** — The pre-update capture is persisted before the update begins, so an update
  interrupted midway can still restore.
- **AC14i** — Every restored item is listed, and a package that cannot be reinstalled is
  reported without failing the update.
- **AC14c** — `self python -- <args>` and `self uv -- <args>` run the arguments against the
  owned environment, passing them through untouched and proxying the exit code.
- **AC14e** — Invoked bare, each prints exactly one absolute path and nothing else on stdout,
  so it remains capturable.
- **AC14d** — In a mode with no functualize-owned environment, `self install`, `self python`
  and `self uv` refuse with the refusal exit code and explain.

### Plugin

- **AC15** — `plugin list` includes an extension registered only in the interactivity group,
  showing both its registered name and its distribution name.
- **AC16** — `plugin install` in unknown mode prints guidance, executes nothing, and exits
  with the refusal code.
- **AC17** — In uv-tool mode, installing a second plugin leaves the first still installed.
- **AC18** — Every mutating plugin command prints its exact command and requires confirmation
  before any side effect.
- **AC19** — From the inline shell, a mutating plugin command hands over the terminal rather
  than running captured on a worker.

### Info

- **AC20** — `builtin info` reports install mode and owning distribution; the full-document
  form additionally reports the manifest, and its JSON form carries the same fields.
- **AC20a** — The install-mode line is labelled distinctly from the existing state-storage
  `Mode:` line, and both are unambiguous when both read `standalone`.
- **AC21** — No `self paths` or `self config-info` command exists.

### Binary

- **AC22** — The binary launches and runs a job **with networking disabled**.
- **AC23** — CI asserts the binary's actual measured size. No estimate is treated as the
  assertion.
- **AC24** — Release builds produce binaries for each supported platform and architecture,
  including a **musl** Linux variant and a Windows variant, named by target triple.
- **AC24a** — Every release publishes a checksum file covering every artifact.
- **AC24b** — The install script detects platform **and libc**, and picks the musl archive on
  a system without glibc.
- **AC24c** — The install script verifies the downloaded archive against the published
  checksum before installing it.
- **AC25** — Every build variable is set explicitly; none is left to an implicit default.

### P1 / P2

- **AC26** — Two different families declaring the same subcommand name, where only one is
  terminal-owning, produce the correct answer for each.
- **AC27** — Every terminal-ownership answer that is correct today remains correct.
- **AC28** — From the inline shell, `skills install` hands over the terminal.
- **AC29** — From a terminal, `skills install` behaves exactly as before this change.

### Cross-cutting

- **AC30** — No new top-level command name is introduced.
- **AC30a** — New commands spell structured output `--format json`. No command in this
  feature ships two spellings for the same question.
- **AC31** — No command string contains a hard-coded `functualize` where the owning
  distribution belongs.
- **AC32** — Every command in this feature is reachable and correct from the direct CLI, the
  inline shell, and a consumer application's CLI.
- **AC33** — A consumer application that declines the first-party command tree still starts
  and runs correctly.

---

## Risks

| Risk | Consequence | Mitigation |
|---|---|---|
| Detection guesses wrong | A user is told to run a command that does not exist, or an updater touches a binary it does not own | AC2 — unknown is explicit and refuses; never fall back to standalone |
| Doctor reports health it did not observe | Worse than no doctor: a health check that cannot report ill | AC12 — a check that can only succeed is deleted, not shipped |
| Detection lands on the hot path | Measurable startup regression; the repo has a documented case of a filesystem check costing 63% of boot | B1 orders cheap signals first; AC9 asserts the warm path structurally, since no pre-boot timing budget exists |
| P1 changes shared behavior | A regression in terminal handoff for existing commands | AC27 — existing correct answers are pinned before P1 is written |
| P2 "fixed" by changing how the installer is invoked | The working terminal path breaks | AC29 — the terminal path is asserted unchanged. The subprocess invocation is correct and is not the defect |
| The offline claim is asserted but never tested | The binary's entire selling point is unverified | AC22 — tested with networking disabled |
| Payload size | ~104 MB of dependencies, ~82 MB of it one plugin | Accepted by decision O2 in favour of a genuinely complete offline binary; AC23 keeps the real number visible |

## Open questions

None blocking. O1–O4 resolved 2026-09-03.

One item is **deliberately deferred and must not be silently resolved**: doctor cannot
report plugin load failures because none are recorded. B3 omits the check. Adding a failure
record is a separate change; if it lands, doctor gains the check.

**One question is raised but not answered here** (see `research.md` §1.3, §1.7):

> Six existing commands answer "text or JSON?" in two incompatible ways — `--json` (a bool
> honouring the configured renderer) on `why`, `info`, `info jobs`, `info all`, and
> `--format` (a choice ignoring it) on `workflow list`, `workflow state`. So
> `FUNCTUALIZE_CLI_OUTPUT=json` is honoured by one set and ignored by the other.
>
> This feature **adds no new inconsistency** — new commands use `--format`, and `info`
> additions ride its existing `--json`. **Normalizing the six is a separate breaking
> change** and is not in this scope unless explicitly added.

Two live defects were found during the audit and are **out of scope**, recorded in
`research.md` §1.4 and §1.5: the global `--output` hard-errors on every `func builtin …`
invocation, and `--perf-report` misparses in its documented bare form before a builtin.

---

## Sizing note for the Plan phase

This is large for one feature: five sections plus two prerequisites, spanning detection, a
new on-disk artifact, two command groups, a shared-registry change, a release pipeline, and
a new CI baking step. The Plan phase should expect several waves, with **P1 in the first**
(§4 depends on it), **P2 independent of everything**, and §5 last — it is the only part
requiring new CI infrastructure with no prior art in this repository.
