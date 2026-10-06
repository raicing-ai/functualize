# secrets-plugin-names

Mechanical rename of the two deferred credentials plugins before their first
launch. See spec.md; nothing behavioral changes.

## Tasks

- 1.1 Move the plugin trees and their import packages (`git mv`, no content edits).
- 2.1 Update the moved trees' internals: distribution names, entry-point values, READMEs, tests.
- 2.2 Update root `pyproject.toml` (the `[all]` extra, deferral comments) and `.github/workflows/release.yml` strip globs.
- 2.3 Update core references: boot, plugin catalog data, plugin command, plugin kinds, presets.
- 2.4 Update docs: installation, configuration, plugins guide, CONTRIBUTING, ADR 016, PUBLISHING tables.
- 2.5 Update tests referencing the old names (cli, config, substrate probes, spec tests).
- 2.6 Regenerate `uv.lock` and the example project lockfiles; record the rename in the CHANGELOG `[Unreleased]`.

## Task Dependency Graph

```json
{"waves": [{"id": 0, "tasks": ["1.1"]}, {"id": 1, "tasks": ["2.1", "2.2", "2.3", "2.4", "2.5", "2.6"]}]}
```
