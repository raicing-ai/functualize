# Tasks

## 3.1 — the list and the classification

- [x] `_primitives/parameter_types.py`: `CLI_VALUE_TYPE_NAMES`,
      `is_cli_value_type`, `has_explicit_cli_marker`.
- [x] `_engine/executor.py::_di_binding_errors` consults them before the
      registry, and names the *parameter* in the error.
- [x] Tests: each listed type binds without a provider (A1, A2); an explicit
      marker wins over an unlisted type (A3); a genuine dependency still
      errors (A4); the message names job and parameter (A9).

**Reachability:** `FunctualizeApp.__init__` → `boot_standard` →
`validate_di_bindings` → `_di_binding_errors`. Break by removing the skip and
confirm A1 fails.

**Gate:** `uv run pytest tests/execution/ -q`; mypy; lint-imports.

## 3.2 — an unsatisfiable job fails alone

- [x] `validate_di_bindings` returns per-job errors (C2).
- [x] `_app/boot.py` records a `DiscoveryFailure` for each affected job.
      **Revised:** unregistering them was implemented and reverted — it made
      the cold boot disagree with the warm one (where proxies are never
      validated, so the job necessarily still exists), and "no such command"
      is a worse answer than a message naming the parameter. See ADR-018.
- [x] Rewrite the three modules that pin `DIValidationError` at boot to pin the
      per-job outcome instead.
- [x] Tests: unrelated jobs still run (A5); `builtin info` and `self doctor`
      still work (A6); the job is reported (A7); invoking it gives a message,
      not a traceback (A8); cold and warm agree (A11); `--help` works (A12).
- [x] ADR recording the constitutional departure and its approval.

**Gate:** `uv run pytest tests/execution/ tests/cli/ tests/app/ -q`.

## 3.3 — conversion

- [x] `_resolve_type`: `UUID`, `date`, `datetime`, `Decimal`.
- [x] Tests: a value arrives as its annotated type, not `str` (A1, A2); a
      malformed value is a usage error (A10).

**Gate:** `uv run pytest tests/cli/ -q`.

## 3.3b — a fifth classifier, found by the tests

- [x] `_cli/annotation_utils.py::CLI_COMPATIBLE_TYPES` was `(str, int, float,
      bool, Path)` and decided whether a parameter reached the CLI **at all**.
      So a `UUID` job published a parameter that the CLI then rejected as an
      unexpected argument. Now reads the shared list through the public
      re-export, the route `_cli` already uses for the injected-capability
      names.
- [x] An explicit CLI marker now outranks the type-based DI guess in
      `parse_annotation`: `Annotated[Widget, Option(...)]` was classified DI
      and dropped, so the author's explicit statement was overruled.
- [x] `_is_cli_marker` there held a sixth hardcoded copy of the marker names;
      pointed at the shared list.

## 3.4 — close

- [ ] Full suite `--run-slow -n auto`; `uv run pytest examples/ -q`.
- [ ] mypy, format check, lint-imports, `mkdocs build --strict`.
- [ ] Update `.spec/STATE.md`.

**Gate:** all green (A13).

## Task Dependency Graph

```json
{"waves": [
  {"id": 0, "tasks": ["3.1"]},
  {"id": 1, "tasks": ["3.2", "3.3"]},
  {"id": 2, "tasks": ["3.4"]}
]}
```
