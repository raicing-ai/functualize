# Standalone self-management

## Problem

The standalone binary shipped able to run jobs and unable to manage itself.
Every mutating command — `self update`, `self install`, `self uninstall`,
`plugin install`, `plugin uninstall` — refuses on it and exits `3`.

The cause is an identity failure, not a policy one. PyApp launches the
application as `python -c "from functualize._cli.main import main; main()"`, so
`sys.argv[0]` is the literal string `-c`. `runtime._owning_distribution`
reverse-maps `argv[0]`'s basename through installed console-script metadata,
finds nothing, returns `None`, and `Detection.degraded` is therefore `True` —
the same signal a bare `pip install` into a system interpreter raises. The
standalone branches of `install_commands` and `uninstall_commands` are already
written and already correct. They are simply unreachable.

Two lesser symptoms share that root. Guidance reads ``Run `-c builtin self
doctor` `` because `package_ops.script_name()` returns `-c`. And the
installation registry records the binary as `<prefix>/bin/-c`, a path that has
never existed, which it then correctly reports as stale.

`self update` is a separate and larger hole. `update_commands` returns
`(binary, "pyapp", "update")`. Read against pyapp 0.29.0 that subcommand is
hidden unless `PYAPP_EXPOSE_UPDATE=1` (`commands/self_cmd/update.rs:11`),
refuses outright under `PYAPP_SKIP_INSTALL=1` — `"Cannot update as installation
is disabled"` — and would `pip install --upgrade` from an index if it ran,
replacing the offline-complete environment the binary exists to be. There has
never been a working standalone update path.

## User stories

**As someone who installed the binary on a machine with no Python**, I want
`self update` to fetch the new release and replace the binary, so that upgrading
does not require me to remember which URL I curled months ago.

**As the same person**, I want `self install <package>` to add a dependency my
jobs import, so that a job needing `requests` is not a reason to abandon the
standalone install.

**As someone who built their own PyApp binary over their own application**, I
want `self update` to check *my* releases or refuse cleanly, never to hand my
users functualize's binary.

## Behavior

### Identity

The binary is built with `PYAPP_PASS_LOCATION=1`, which makes PyApp set the
`PYAPP` environment variable to the absolute path of the running executable
(`distribution.rs:54`) instead of `"1"`. That path is the installation's
identity: what `self update` replaces, what the registry records, and what
`self doctor` reports.

Detection tests for the **presence** of `PYAPP`, not its truthiness: PyApp sets
it to the empty string when `current_exe()` fails, and a binary whose own path
is unknown is still a standalone binary.

A standalone installation is **not degraded**. It has no owning distribution by
construction — it is a file, not a package — and that absence is structural
rather than a failed lookup. Where the two must be distinguished, the binary
path is the discriminator: a standalone install that cannot name its own
executable *is* degraded, because there is nothing for a mutating command to
act on.

### `self update`

1. Reads a **release source** from `<sys.prefix>/standalone-release.json`,
   written into the distribution at bake time. Absent, the command refuses with
   guidance and exits `3` — a binary somebody else baked has release channels
   this one cannot know.
2. Asks that source for the latest version. Already current, it says so and
   exits `0` without downloading.
3. Prints the release it will install, the asset it will download and the path
   it will overwrite, then asks for confirmation (`--yes` skips the prompt, not
   the print).
4. Downloads the platform's archive **and** that release's `SHA256SUMS`, and
   verifies the archive against it **before unpacking**. A mismatch, or an
   archive `SHA256SUMS` does not mention, aborts with nothing written.
5. Replaces the running binary atomically: the new executable is written beside
   the old one on the same filesystem and moved into place with `os.replace`.
   An interrupted update leaves either the old binary or the new one, never a
   truncated file.
6. Reports the version now installed.

### `self install` / `self uninstall` / `plugin install` / `plugin uninstall`

Operate on the bundled interpreter through **its own bundled pip**, not through
uv. A standalone binary is the install method for machines with no Python
toolchain, so requiring `uv` on `PATH` to add a package defeats it. `pip` is
present in the baked distribution.

### Unaffected

`self doctor`, `builtin info`, `plugin list`, `self python` and job execution
behave as they already do. `self uv` continues to raise its existing
missing-tool error on a standalone install, because there is no bundled uv;
`self python` is the escape hatch that works.

## Acceptance criteria

**AC1** — Built with `PYAPP_PASS_LOCATION=1`, a standalone binary reports its
own absolute path from `self doctor`, and that path exists.

**AC2** — `detect()` returns `STANDALONE` when `PYAPP` is present and empty,
not only when it is truthy.

**AC3** — `Detection.degraded` is `False` for a standalone install with a known
binary path, and `True` for one without.

**AC4** — `script_name()` never returns `-c`. Given `PYAPP_COMMAND_NAME` it
returns that; otherwise it falls back to the binary's basename, then to `func`.

**AC5** — The installation registry records the binary path from `PYAPP`, and a
standalone install that has just run does not report itself stale.

**AC6** — `self install <package>` on a standalone install runs the bundled
interpreter's pip against the bundled interpreter, and the package is importable
afterwards.

**AC7** — `plugin install` on a standalone install leaves a previously installed
plugin present. (uv-tool's declarative-receipt hazard does not apply to pip, but
the property is the user-visible one and holds for both.)

**AC8** — `self update` with no `standalone-release.json` refuses, changes
nothing, and exits `3`.

**AC9** — `self update` verifies the downloaded archive against `SHA256SUMS`
before unpacking. A tampered archive aborts with the binary untouched.

**AC10** — `self update` on an already-current binary exits `0` and downloads
nothing.

**AC11** — The replacement is atomic: the target path holds a complete
executable at every point, and a failure after download leaves the original.

**AC12** — `self update --yes` skips the prompt and still prints what it will do.

**AC13** — The bake writes `standalone-release.json` naming the repository, the
asset prefix and this build's target triple, and the release workflow sets
`PYAPP_PASS_LOCATION=1`.

**AC14** — No behaviour changes for `tool_uv`, `tool_pipx`, `project`,
`tool_pip` or `unknown` installs. The existing suite covering those passes
unchanged.
