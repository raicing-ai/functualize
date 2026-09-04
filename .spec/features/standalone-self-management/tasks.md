# Tasks

## Wave 0 — identity

- [ ] **1.1** `runtime.py`: add `Detection.standalone_binary`, read `PYAPP` by
      presence rather than truthiness, and special-case `degraded` for
      `STANDALONE`. Gates: AC2, AC3.
      Files: `src/functualize/_cli/runtime.py`, `tests/_cli/test_runtime_detect.py`

- [ ] **1.2** Build inputs: `PYAPP_PASS_LOCATION: "1"` in the `binaries` job and
      `standalone-release.json` written by `bake.sh` (repo, asset prefix,
      target). Gate: AC13.
      Files: `.github/workflows/release.yml`, `.github/scripts/bake.sh`

## Wave 1 — package operations

- [ ] **2.1** `package_ops.py`: `script_name(environ)` resolving
      `PYAPP_COMMAND_NAME` → basename → `func`, never `-c`; standalone
      install/uninstall through the bundled interpreter's pip; `StandaloneUpdateError`
      sentinel; the `distribution is None` guards moved below the `STANDALONE`
      case. Gates: AC4, AC6.
      Files: `src/functualize/_cli/package_ops.py`, `tests/_cli/test_package_ops.py`

- [ ] **2.2** `manifest.resolve_binary_path` prefers the `PYAPP` path over
      `argv[0]`, so the registry records a path that exists. Gate: AC5.
      Files: `src/functualize/_cli/manifest.py`, `tests/_cli/test_self_manage.py`

## Wave 2 — self-update

- [ ] **3.1** `self_update.py`: `ReleaseSource`, `read_release_source`,
      `latest_release`, `verify`, `extract_executable`, `replace_binary`.
      Pure but for the injected `Opener`. Gates: AC8, AC9, AC10, AC11.
      Files: `src/functualize/_cli/self_update.py`, `tests/_cli/test_self_update.py`

- [ ] **3.2** Wire it: `self_cmd.update` catches `StandaloneUpdateError` and calls
      `self_update.perform`, honouring `--yes` and printing the plan first.
      Gates: AC12, and the production call path for 3.1.
      Files: `src/functualize/_cli/self_cmd.py`, `tests/_cli/test_self_manage.py`

## Wave 3 — surface and documentation

- [ ] **4.1** Cross-surface parity for the newly reachable commands, and AC14's
      regression guard for the untouched modes.
      Files: `tests/_cli/test_self_management_surfaces.py`

- [ ] **4.2** Documentation: replace the known-gap warnings with the real
      behaviour, supersede the ADR correction's second half, and update the
      scenario to assert the working commands. Gates: AC1, AC7 (as scenario
      steps run against a real binary).
      Files: `README.md`, `docs/getting-started/installation.md`,
      `contributor/adr/015-standalone-distribution-and-self-management.md`,
      `examples/docs/scenarios/l-standalone-binary.toml`,
      `.spec/shape-intents/standalone-self-management.md`

## Task Dependency Graph

```json
{
  "waves": [
    {"wave": 0, "tasks": ["1.1", "1.2"]},
    {"wave": 1, "tasks": ["2.1", "2.2"]},
    {"wave": 2, "tasks": ["3.1", "3.2"]},
    {"wave": 3, "tasks": ["4.1", "4.2"]}
  ],
  "edges": [
    {"from": "1.1", "to": "2.1"},
    {"from": "1.1", "to": "2.2"},
    {"from": "1.2", "to": "3.1"},
    {"from": "2.1", "to": "3.2"},
    {"from": "3.1", "to": "3.2"},
    {"from": "3.2", "to": "4.1"},
    {"from": "3.2", "to": "4.2"}
  ]
}
```
