# T8 Report — `_types/flag_grammar.py`, and the vocabulary moves out of `dispatch.py`

**Task:** T8 of `run-outcome-authority` feature
**Status:** Complete
**Date:** 2026-09-09

## Summary

Created `src/functualize/_types/flag_grammar.py` as the single authority for flag
vocabulary and alias matching. Moved the value-flag tables, optional-value
tables, bool-flag set, alias matchers, and `negative_flag_for` out of
`_cli/dispatch.py` and `_types/naming.py`. Re-exported the new public names
through `types/__init__.py` and `app/utils.py`.

## Files Changed

| File | Change |
|------|--------|
| `src/functualize/_types/flag_grammar.py` | **NEW** — flag tables, alias matchers, `negative_flag_for` |
| `src/functualize/_cli/dispatch.py` | Import from `app.utils` (public API); removed local definitions |
| `src/functualize/_types/naming.py` | `negative_flag_for` now re-exports from `flag_grammar` |
| `src/functualize/types/__init__.py` | Export 9 new public names |
| `src/functualize/app/utils.py` | Import and export 9 new public names |
| `tests/test_public_api_surface.py` | Added 9 new names to `EXPECTED_EXPORTS["functualize.types"]` |
| `tests/_cli/test_dispatch_bug_condition.py` | Import `OPTIONAL_VALUE_VALID_SET` from `functualize.types` |
| `tests/_cli/test_dispatch_preservation.py` | Import `OPTIONAL_VALUE_VALID_SET` from `functualize.types` |
| `tests/skills/test_api_claims.py` | Import `OPTIONAL_VALUE_VALID_SET` from `functualize.types` |

## Key Decisions

1. **Public names, not private.** The tables are now `GLOBAL_OPTIONS_ALWAYS_VALUE`
   (not `_GLOBAL_OPTIONS_ALWAYS_VALUE`). `_cli` can't import `_types` (lint-imports
   contract), so the names must be public — re-exported through `app/utils.py`
   which `dispatch.py` already imports from.

2. **`perf-report` lookahead stays in `dispatch.py`.** The lookahead behavior
   (consuming the next token only if it's in the valid set) is tightly coupled
   to the pre-boot argv scan. Moving the table without the lookahead would split
   the rule from its enforcement. Documented this exclusion in `flag_grammar.py`.

3. **Backward-compat aliases in `dispatch.py`.** `_cli/main.py` imports the old
   private names from `dispatch.py` (which I can't edit). Added re-export aliases
   so existing callers keep working. New consumers should import the public names
   from `functualize.app.utils`.

4. **`negative_flag_for` re-exported from `naming.py`.** Existing importers
   (`click_params.py:39`, `test_boolean_negation.py:21`) keep working. The
   implementation lives in `flag_grammar.py`; `naming.py` delegates via a
   runtime import to avoid a cycle.

## Gate Results

### Gate 1: the grammar exists
```bash
test -f src/functualize/_types/flag_grammar.py && rg -c 'def negative_flag_for' src/functualize/_types/flag_grammar.py
```
**Result:** `1` ✓

### Gate 2: the lookahead deliberately stays behind
```bash
rg -c 'perf-report|perf_report' src/functualize/_cli/dispatch.py
```
**Result:** `8` (unchanged) ✓

Plus a comment in `flag_grammar.py` naming the exclusion and why.

## Verification

```bash
uv run ruff check src/ tests/ plugins/         # PASS
uv run ruff format --check src/                 # PASS
uv run mypy src/functualize/_types/flag_grammar.py src/functualize/_cli/dispatch.py src/functualize/_types/naming.py src/functualize/types/__init__.py src/functualize/app/utils.py  # PASS
uv run lint-imports                             # PASS (6 contracts KEPT)
uv run pytest tests/types tests/test_public_api_surface.py tests/_cli/test_dispatch_bug_condition.py tests/_cli/test_dispatch_preservation.py tests/skills/test_api_claims.py tests/adapters/test_boolean_negation.py tests/tui_group_options/test_smartbar_roundtrip.py tests/group_options/test_group_options_cli_e2e.py  # PASS
```

## Sabotage Proof

**Edit:** Changed `--output` default from `"auto"` to `"yaml"` (an invalid value).

**Test:** `tests/skills/test_api_claims.py::test_documented_output_values_match_the_flag`

**Result:** FAILED — `assert 'yaml' in frozenset({'auto', 'json', 'ndjson', 'none', 'raw'})`

**Restore:** Changed default back to `"auto"`. Test passes again.

This proves the test is wired to the flag table — a drift in the vocabulary
is caught by an existing assertion.

## New Public Names

| Name | Source |
|------|--------|
| `GLOBAL_OPTIONS_ALWAYS_VALUE` | `flag_grammar.py` |
| `GLOBAL_OPTIONS_OPTIONAL_VALUE` | `flag_grammar.py` |
| `OPTIONAL_VALUE_VALID_SET` | `flag_grammar.py` |
| `GLOBAL_OPTIONS_WITH_VALUE` | `flag_grammar.py` |
| `GLOBAL_BOOL_FLAGS` | `flag_grammar.py` |
| `flag_aliases` | `flag_grammar.py` |
| `negative_aliases` | `flag_grammar.py` |
| `match_group_flag` | `flag_grammar.py` |
| `negative_flag_for` | `flag_grammar.py` |

## Spec AC Coverage

- **AC-9:** Flag vocabulary lives in a single module (`flag_grammar.py`) ✓
- **AC-12:** `negative_flag_for` keeps its public name and import paths ✓
