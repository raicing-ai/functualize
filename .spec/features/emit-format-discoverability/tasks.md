# Tasks — emit-format-discoverability

- [x] **T1** `_cli/dispatch.py`: add `invalid_value_message(flag, value)` and
  `refused_optional_value(argv_tail)`; route `_assign_option`'s two messages
  through the first. Gate: `uv run pytest tests/cli/test_global_options.py -q`.
- [x] **T2** `_cli/main.py`: `_handle_job` not-found branch reports the refused
  value (B3). Gate: AC3, AC4.
- [x] **T3** `_cli/main.py`: `_LeftMarginEpilogGroup.format_options` renders
  the `Run options` section (B1, B2). Gate: AC1, AC2 (func half), AC5.
- [x] **T4** `app/adapters/cli.py`: `--emit-format` help carries the
  return-value sentence (B4). Gate: AC2 (app half).
- [x] **T5** `tests/cli/test_emit_format_discoverability.py` covering AC1–AC5
  through the real entry points; sabotage T2 and T3 once each after commit.
- [x] **T6** `CHANGELOG.md` Unreleased entry; full checks
  (`ruff`, `ruff format --check`, `mypy`, `lint-imports`, `pytest`).

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["T1"] },
    { "id": 1, "tasks": ["T2", "T3", "T4"] },
    { "id": 2, "tasks": ["T5"] },
    { "id": 3, "tasks": ["T6"] }
  ]
}
```
