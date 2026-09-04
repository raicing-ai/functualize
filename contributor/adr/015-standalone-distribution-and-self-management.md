# ADR-015: Standalone Distribution and Self-Management

**Status**: accepted
**Date**: 2026-09-04
**Deciders**: Hakim, with the spec-driven workflow. The specification artifacts were
cleared at merge, as that workflow requires; recover them from the pull request ref if
needed.

## Context

Functualize could be installed four ways and knew about none of them. That gap
produced two separate problems.

**For the user with no Python**, there was no way in at all. Every documented
install began with an interpreter, which is the one thing an ops user on a
locked-down box, a container, or a CI image most often cannot add.

**For everyone else**, the tool could not answer questions about itself. "Which
`func` is running?" was `which -a func` plus inference. "How do I upgrade?"
depended on an install method the user had to remember. And a plugin installed
into a `uv tool` environment could be silently removed by installing a second
one, because `uv tool install` is declarative and drops prior `--with` entries.

## Decision

Ship a pre-baked standalone binary, and give every installation the commands to
report on and manage itself.

### The binary is pre-baked, not bootstrapping

PyApp with `PYAPP_DISTRIBUTION_EMBED=1` and `PYAPP_SKIP_INSTALL=1`, over a
distribution that already has `functualize[all]` installed. **The first run
needs no network.** That is the entire reason the binary exists — its audience
is precisely the machine that cannot reach an index — and it costs ~100 MB of
payload, accepted deliberately.

Every PyApp variable is set explicitly. This is not tidiness: PyApp's *defaults*
are the online recipe, so a missing variable still produces a binary that works
on a networked build machine and fails only for the offline user. The mistake
would ship.

`PYAPP_SELF_COMMAND=pyapp` renames the builder's own management group. Left at
its default it would expose a working `self` command in standalone mode that
exists in no other mode, so the command surface would differ by install method.
`func pyapp …` is internal and carries no stability guarantee.

### Detection resolves two independent axes

*How* it was installed (`standalone`, `tool_uv`, `tool_pipx`, `project`,
`tool_pip`, `unknown`) and *which distribution owns it*. Both are needed
together, because resolving one without the other is how a command names the
wrong tool: a consumer application built on functualize upgrades **itself**, and
naming the framework there would upgrade a package the user did not install.

`detect()` takes every input as a parameter — `sys.prefix`, `sys.base_prefix`,
the environment, `argv[0]`, the working directory. That is a **testability
requirement driving a design constraint**, not a style preference: `sys.prefix`
cannot be set by an environment variable, so a version reading it directly could
only ever be exercised in the single mode the test suite happens to run under.

The ladder's order is binding, and the filesystem rung — a bounded upward walk
for a project declaring functualize — stays last of the non-trivial ones. An
unbounded walk is the shape that once cost 63% of boot.

### Refusal is a first-class outcome

`tool_pip` and `unknown` are **degraded**: every mutating command prints
guidance naming the tool that *does* own the installation, changes nothing, and
exits `ExitCode.REFUSED` (3). A script can distinguish "functualize declined to
act because it does not own this" from "the action ran and failed".

An unknown owning distribution is `None`, never a guess. Guessing `functualize`
is exactly the wrong-owner failure the two-axis design exists to prevent.

### The registry is voluntary and discovers nothing

One user-global `install.json`, updated by any installation that runs. No `PATH`
scan, no directory walk, no subprocess, no interrogating another binary.
Discovery was measured and rejected: executing five installations to read their
versions costs ~2.1 s serial, against ~39 µs to read the file. An installation
that has never run is genuinely unknown, which is the right answer rather than a
gap — it has produced no state, no config and no jobs.

Registration is best-effort and its failure is **always silent**. A read-only
config directory or a sandbox must not interfere with the command the user
typed.

The installations list is append-only. Two installations coexisting is a real
state and `PATH` decides which runs, so a record whose binary has gone is
*reported* as stale rather than deleted.

### A consumer application never registers itself implicitly

The registry means **functualize installations**, not every application built on
functualize that has run. An app embedding functualize is not an installation of
it: it has its own name, release cycle and owner — which is exactly what
detection already reports for it. An explicit opt-in stays open.

### Reconciliation differences over names, never versions

`self update` captures the environment before and after, and restores what the
upgrade removed. **The difference is over names alone.** A distribution-shipped
package appears in both captures at different versions after an upgrade;
differencing over `(name, version)` pairs would classify it as a user addition
and reinstall it at its *old* version, silently undoing the upgrade's own
dependency updates.

The capture reads `dist-info` **directory names** (2.4 ms), never package
metadata (172 ms for the same mapping the directory name already encodes).

The pre-update snapshot is persisted **before** the upgrade runs. Held only in
memory, an update interrupted between rebuilding the environment and restoring
it loses every user addition — the one failure the mechanism exists to prevent.

Manifest records are unioned with the capture rather than trusted alone: the
capture catches escape-hatch installs the records never saw, and the records
survive a capture that failed.

### A uv receipt is reproduced faithfully or refused

`uv tool install` rewrites the tool environment from the arguments it is given,
so every prior requirement has to be restated or installing a second plugin
uninstalls the first. A receipt key this cannot render back is **refused**, not
dropped: an unreproducible requirement is removed from the environment, not
merely missing from one command. `func builtin self uv -- tool install …` is the
escape hatch, and its existence is what makes the refusal acceptable.

### Two commands, not one with a flag

`self install` and `plugin install` are mechanically identical today and stay
separate. `plugin install` is a **seam**: plugin-specific behaviour — verifying
a distribution actually registers a `functualize.*` entry point, warning on
framework version skew, an uninstall that checks nothing still depends on it —
has an obvious home there without contorting a general package installer.

`plugin list` **discovers** its entry-point groups rather than listing them. A
fixed set goes stale the moment a domain declares a new provider group, and
domains do exactly that.

## Correction (2026-09-04, after the binary was first built)

Two claims above were written from the design and never checked against a
running binary. Building one falsified both.

**The baked artifact must be a Python *installation*, not a virtual
environment.** The original pipeline baked a `uv venv --relocatable`. A venv's
`bin/python` is a symlink to the interpreter it was created from, and its
standard library lives in that interpreter's prefix — so a venv tarred up and
unpacked anywhere else contains no Python at all. The binary built over one dies
on launch with `project execution failed / No such file or directory (os error
2)`. The pipeline now copies the python-build-standalone installation itself and
installs into its `lib/pythonX.Y/site-packages`.

Three consequences travel with that. `uv` installs a workspace root as an
*editable* by default, which writes a `.pth` pointing at the build machine and
puts no package in site-packages, so `--no-editable` is load-bearing and the
bake asserts no `_editable_impl_*.pth` survives. A python-build-standalone
install on Windows puts `python.exe` at the distribution root, not under
`Scripts/`, so that path is not the venv path it would otherwise be. And
`uv python install` only offers the *host* libc's distributions, so a musl
target baked on a glibc runner would embed a glibc interpreter — the musl bakes
run inside an Alpine container.

**`self update` on a standalone install does not work, and never did.** The
decision above says PyApp's own updater handles it. Read against pyapp 0.29.0,
that subcommand is hidden unless `PYAPP_EXPOSE_UPDATE=1`, refuses outright under
`PYAPP_SKIP_INSTALL=1` (`"Cannot update as installation is disabled"`), and
would `pip install --upgrade` from an index if it ran — which would replace the
offline-complete environment this decision exists to produce. Separately, every
mutating `self`/`plugin` command refuses on a standalone binary, because PyApp
launches the app through `python -c` and `argv[0]` is `-c`, which reverse-maps
to no console script and so reads as a degraded install. That signal is false:
a standalone binary has no owning distribution *by construction*, and the
standalone `install`/`uninstall` branches are already written and correct but
unreachable.

The refusal is honest and the read-only commands are unaffected, so the binary
ships as it stands and the documentation now says so. The design question —
what updating a pre-baked binary should mean — is recorded in
`.spec/shape-intents/standalone-self-management.md`.

Both were invisible to every gate the feature had. The scenario written to catch
exactly this, `l-standalone-binary.toml`, carried the same wrong recipe and was
never executed; its build step is the expensive one. **A verification step that
has not been run is not evidence.**

## Consequences

### Positive

- A machine with no Python can run functualize, offline, from one file.
- `func builtin self doctor` answers "what is wrong with this installation"
  **before the app boots**, so it still works when boot itself is broken.
- Upgrading no longer requires remembering how you installed it.
- Plugin installs survive each other in uv-tool mode.

### Negative

- ~100 MB of binary, most of it one plugin. Accepted for a genuinely complete
  offline artifact; CI asserts the *measured* size so the number stays visible.
- Seven release targets to build and keep building.
- The receipt merge is coupled to a uv file format that is not a public
  contract. Mitigated by refusing rather than guessing, which turns a format
  change into a clear message rather than a silent environment corruption.

### Neutral

- Two spellings of structured output now coexist across the tree (`--json` on
  `info`/`why`, `--format json` on the newer commands). This feature adopts
  `--format` for new commands and rides `--json` where it extends an existing
  one, so it adds no new inconsistency and normalizes none. Normalizing is a
  separate breaking change — see `.spec/shape-intents/output-flag-normalization.md`.

## Alternatives Considered

| Alternative | Pros | Cons | Why rejected |
|---|---|---|---|
| Bootstrapping binary (PyApp default) | ~5 MB, trivial to build | First run needs an index | Defeats the only reason the binary exists |
| `[cli]` payload instead of `[all]` | Much smaller | A plugin the user expects is absent offline | The offline user is least able to add it later |
| Discovering other installations by scanning `PATH` | Complete inventory | ~2.1 s, and no honest root for a filesystem walk | A voluntary registry costs ~39 µs and is honest about what it does not know |
| Delegating `self doctor` into a project's own venv | Answers about the venv you meant | Overrides a deliberate `PATH` choice, and a 0.1.2 project has no `self` command to delegate to | Would answer "no such command" for a command the user can see |
| One `install` command with a `--plugin` flag | Smaller surface | No home for plugin-specific behaviour | `plugin install` is a seam worth keeping |
| Differencing captures over `(name, version)` | Catches version changes too | Pins distribution-shipped packages back, undoing the upgrade | Silently defeats the upgrade it is meant to protect |
| Dropping unrenderable uv receipt keys | Always succeeds | Silently changes what is installed | A clear refusal plus an escape hatch is strictly better |

## Verification

Container scenarios, run on demand rather than in CI (`examples/docs/scenarios/`):

- `b-install-flows.toml` — every mode detected against a real install of that
  kind, including the `tool_pipx` signal no earlier audit host could verify, and
  the ladder's order shown by one installation reporting `project` from inside a
  project and `tool_pip` from outside it.
- `k-plugin-lifecycle.toml` — a second plugin install leaves the first present.
- `l-standalone-binary.toml` — the binary runs a job with `--network none`,
  which is what turns the offline claim into a gate; plus the install script
  picking musl and refusing a tampered archive before unpacking it.
