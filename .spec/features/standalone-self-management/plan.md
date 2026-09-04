# Plan

## Approach

Three separable pieces, in dependency order: **identity** (the binary knows what
it is), **package operations** (the existing standalone branches become
reachable), and **self-update** (new code, the only part that touches the
network).

Identity first because everything else keys off it, and because it is the piece
that can be verified against a real binary cheaply — `PYAPP_PASS_LOCATION=1` is
a build flag, and a rebuilt binary either prints its own path or does not.

## Files

| File | Change |
|---|---|
| `src/functualize/_cli/runtime.py` | `Detection.standalone_binary`; presence-not-truthiness `PYAPP` test; `degraded` special-cases standalone |
| `src/functualize/_cli/package_ops.py` | `script_name` takes an environ and never returns `-c`; standalone install/uninstall through bundled pip; `StandaloneUpdate` sentinel; guards reordered |
| `src/functualize/_cli/self_update.py` | **new** — release source, fetch, verify, extract, atomic replace |
| `src/functualize/_cli/self_cmd.py` | `update` dispatches to `self_update.perform` on `StandaloneUpdate` |
| `src/functualize/_cli/manifest.py` | `resolve_binary_path` prefers the `PYAPP` path |
| `.github/scripts/bake.sh` | writes `standalone-release.json` |
| `.github/workflows/release.yml` | `PYAPP_PASS_LOCATION: "1"` |
| `README.md`, `docs/getting-started/installation.md` | replace the known-gap warnings with the real behaviour |
| `contributor/adr/015-...md` | supersede the correction's second half |
| `examples/docs/scenarios/l-standalone-binary.toml` | assert the working commands |

## Risks

**The network seam.** `self update` is the first CLI command that reaches the
internet on its own initiative. It is confined to one `Opener` callable so the
rest of the module is pure and testable, and every test replaces it. No test
makes a real request.

**Replacing a running executable.** POSIX unlinks by inode, so `os.replace` over
a running binary is safe and the running process keeps its old image. Windows
holds the file open and refuses; the fallback renames the running executable
aside first and moves the new one in, leaving a `.old` for the next run to
sweep. This is the one behaviour that cannot be verified on this host — the
Windows path is unit-tested against a simulated `PermissionError`, and stated as
untested-on-hardware in the ADR.

**Checksum ordering.** Verification must happen before extraction, not before
installation: `tarfile` on unverified bytes is itself the attack surface. The
test that proves this feeds a tampered archive and asserts no extraction was
attempted, not merely that nothing was installed.

**pip in the baked distribution.** The standalone install path assumes it. The
bake asserts it is importable, so a future `--no-seed`-style change to the bake
fails there rather than in a user's `self install`.

**Scope discipline.** `tool_uv`, `tool_pipx`, `project` and the degraded modes
are untouched. AC14 exists to make a regression there a failure rather than a
discovery.
