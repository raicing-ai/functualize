# Standalone self-management

**Status**: intent — not specified, not scheduled
**Raised**: 2026-09-04, from building the binary for the first time (v0.2.2 pipeline work)

## The gap

The standalone binary works: it launches offline, discovers and runs jobs, loads
every first-party plugin, and answers `self doctor`, `builtin info` and
`plugin list`. What it cannot do is manage itself. Every mutating command —
`self update`, `self install`, `self uninstall`, `plugin install`,
`plugin uninstall`, `self python`, `self uv` — refuses and exits `3`.

Verified against a real binary, offline:

```
$ func builtin self update      -> exit 3, "maps to no installed distribution"
$ func builtin self install requests -> exit 3, same
$ func builtin plugin list      -> exit 0, correct output
```

## Why

Two independent causes, and only the first is a bug.

**1. `argv[0]` is `-c`.** PyApp launches the application as
`python -c "from functualize._cli.main import main; main()"`, so `sys.argv[0]`
is literally `-c`. `runtime._owning_distribution` reverse-maps `argv[0]`'s
basename through installed console-script metadata; `-c` matches nothing, so
`owning_distribution` is `None`, so `Detection.degraded` is `True`, so every
mutating command takes the refusal branch.

This is a **false** degraded signal. ADR-015 makes `owning_distribution`
`None`-never-a-guess precisely so a consumer application is not upgraded as if
it were the framework — but a standalone binary has no owning distribution to
find *by construction*, not by failure. It is the file itself. The standalone
branches of `install_commands` and `uninstall_commands` are already written,
already correct (`uv pip install --python <bundled interpreter>`), and simply
unreachable.

Two lesser symptoms share this root: `package_ops.script_name()` returns `-c`,
so guidance reads ``Run `-c builtin self doctor` ``; and the installation
registry records the binary as `<prefix>/bin/-c`, a path that does not exist,
which it then correctly reports as stale.

**2. `self update` has no implementation.** `update_commands` returns
`(binary, "pyapp", "update")` for `STANDALONE`. Read against pyapp 0.29.0's
source, that command:

- is hidden unless `PYAPP_EXPOSE_UPDATE=1` (`commands/self_cmd/update.rs:11`);
- refuses outright when `PYAPP_SKIP_INSTALL=1` and updates are not explicitly
  allowed — `"Cannot update as installation is disabled"`, `exit 1`;
- and, if it did run, would `pip install --upgrade` from an index, replacing the
  baked offline-complete environment with one assembled over the network.

So the documented standalone update path never existed. This is not a wiring
bug; it is an unanswered design question.

## The question to answer first

**What does updating a pre-baked binary mean?** Three shapes, in increasing
order of ambition:

1. *Guidance only.* `self update` prints the install-script one-liner and exits.
   Honest, tiny, and what the docs now say. The binary never rewrites itself.
2. *Self-replacing.* The binary downloads the new release, verifies it against
   `SHA256SUMS`, and swaps itself. Real self-update, but it puts release-channel
   knowledge, signature checking and an atomic-replace-on-Windows problem inside
   the framework.
3. *Re-enable PyApp's updater.* Set `PYAPP_EXPOSE_UPDATE=1` and drop
   `PYAPP_SKIP_INSTALL`. Cheapest to build, and it discards the entire reason
   recipe B exists — the first run would need an index again.

(3) is rejected by ADR-015 already. (1) and (2) are both defensible; (1) is
where the documentation now sits.

## What is *not* in question

Fixing cause 1 is a bug fix under any of the three answers: standalone is
self-managing for `install`/`uninstall`, and `Detection.degraded` should say so.
It is separated out here only because it cannot land through the spec gate
without a feature, and because shipping it half-done — `install` works,
`update` refuses — is a worse surface than the current uniform refusal.

## Related

- `contributor/adr/015-standalone-distribution-and-self-management.md`
- `examples/docs/scenarios/l-standalone-binary.toml` — the `self update` step
  asserts the refusal, and carries the reason inline
