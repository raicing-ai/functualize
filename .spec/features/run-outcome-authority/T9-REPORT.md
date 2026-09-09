# T9 Report — The click builders read the grammar

## Files Changed

- `src/functualize/app/adapters/click_params.py` (1 line)

## Gate

```bash
rg -n 'from functualize.types import.*negative_flag_for' src/functualize/app/adapters/click_params.py
```

**before:** `39:from functualize._types.naming import negative_flag_for`
**after:** `40:from functualize.types import negative_flag_for`

```bash
rg -c 'negative_flag_for' src/functualize/app/adapters/click_params.py
```
**before:** 5 (1 import + 4 calls)
**after:** 5 (1 import + 4 calls)

## Identity Proof

```bash
uv run python -c "import functualize._types.flag_grammar as g, functualize.types as t, functualize.app.utils as u; print(t.negative_flag_for is g.negative_flag_for, u.negative_flag_for is g.negative_flag_for)"
```
```
True True
```

## Module Import Check

```bash
uv run python -c "import functualize.app.adapters.click_params"
```
(no output — import succeeded)

## Verify Commands

```bash
uv run ruff check src/ tests/ && uv run ruff format --check src/ tests/
```
```
All checks passed!
1097 files already formatted
```

```bash
uv run mypy src/functualize/app/adapters/click_params.py
```
```
Success: no issues found in 1 source file
```

```bash
uv run lint-imports
```
```
Contracts: 6 kept, 0 broken.
```

```bash
uv run pytest tests/adapters tests/group_options tests/cli -q -p no:randomly
```
```
1849 passed, 346 skipped in 68.16s (0:01:08)
```

## Sabotage

**What broke:** `_config_option_params` call site — `negative_flag_for(field_name + "_broken", names)` instead of `negative_flag_for(field_name, names)` at line 595. This corrupts every `--no-<flag>` secondary opt emitted from a config-model field.

**Which test failed:** `tests/adapters/test_boolean_negation.py` — 4 failures:
- `TestEveryBooleanShapeGetsANegativeForm::test_the_shape_emits_a_negative[cfg_bool]` — `assert '--no-cfg-bool' in ['--no-cfg-bool-broken']`
- `TestEveryBooleanShapeGetsANegativeForm::test_the_shape_emits_a_negative[cfg_bool_short]` — `assert '--no-cfg-bool-short' in ['--no-cfg-bool-short-broken']`
- `TestTheCollisionRuleIsDeterministic::test_declaration_order_does_not_change_the_answer[cache-first]` — `assert ['--no-cache-broken'] == []`
- `TestTheCollisionRuleIsDeterministic::test_declaration_order_does_not_change_the_answer[no_cache-first]` — `assert ['--no-cache-broken'] == []`

**Restored by editing the file back** (no `git checkout`). Re-ran green: 9 passed in 0.17s.

## Notes

The other call sites (`:309`, `:662`, `:863`) were already on the public import path — only the import statement at line 39 needed updating. The `_types/naming.py` re-export remains for `tests/adapters/test_boolean_negation.py` which still imports from there.
