# Plan: Boolean Flag Negation

**Spec:** [`spec.md`](spec.md) · **Contracts:** [`contracts.md`](contracts.md)

---

## Approach

Five moves. The middle three are the feature; the first and last are what stop
the two surfaces drifting.

### 1. One rule for "does this boolean get a negative form?"

```python
# _types/naming.py
def negative_flag_for(name: str, siblings: Collection[str]) -> str | None:
    """``--no-x`` for ``x``, or ``None`` when a sibling is literally ``no_x``."""
```

Re-exported through `functualize.app.utils`, because `_cli/` may not import
`_`-prefixed packages and already reaches `_types/naming.py` this way
(`app/utils.py:52`, `_cli` dogfoods the public API).

**This must be shared, not reimplemented.** D2 says the literal field wins; if
`func` and an app's own entry point compute that independently, `--no-cache`
comes to mean different things on the two surfaces — the exact defect class this
repository keeps finding. One predicate, two callers.

### 2. `click_params.py` — emit the pair

- `_config_field_option` (`:391`) emits `--x/--no-x` when `is_flag` and the rule
  allows, keeping `default=None`.
- Both callers pass `short_flag` and the sibling field names. The **cold** caller
  (`:490`) passes neither today; that is B6, and the short flag is recoverable
  from the field's `Option(short=...)` marker exactly as `_option_from_marker`
  (`:536`) already reads it.
- The warm signature-bool-with-short-flag branch (`:319-330`) builds
  `[long, short]` with no pair and gains one (B3).

### 3. `dispatch.py` — the `func` mid-path parser

- `_flag_aliases` (`:699`) gains the negative spelling from the shared rule.
- `_match_group_flag` (`:715`) reports **whether the match was negative**. Its
  return becomes a 3-tuple; the shape intent's suggestion of synthesising
  `inline="false"` was rejected — it makes `--no-strict` indistinguishable from
  `--strict=false`, and D4 needs those to differ.
- The boolean branch (`:769`) sets `not negated`, and **refuses an inline
  value** (D4) with a hint naming the negative spelling.
- `_coerce_bool` (`:817`) loses its only caller and is **deleted**, per the
  pre-release stance on dead code.

### 4. The two other readers

- `smart_bar_autocomplete.py:328` — `param.opts` → `+ param.secondary_opts`.
- `tui/sync.py:99` `_group_flag_tokens` — emit `--no-x` for an explicit `False`,
  preserving the `emit(resolve(text)) == text` fixed point.

### 5. The two pinned tests that must move deliberately

- `tests/adapters/test_click_params_parity.py:204,216` — the frozen typer
  snapshot (D3). Rows updated **and** a docstring note recording that booleans
  now deliberately diverge from typer.
- `tests/tui_group_options/test_smartbar_roundtrip.py:393` — the tripwire
  (`test_a_groups_negative_boolean_spelling_is_not`), whose own docstring says
  it is the test that will say so if group booleans ever gain the pair. It is
  saying so. **Inverted, not deleted.**

---

## Files to change

| File | Change |
|---|---|
| `_types/naming.py` | `negative_flag_for` |
| `app/utils.py` | re-export it |
| `app/adapters/click_params.py` | the pair, at three sites |
| `_cli/dispatch.py` | aliases, negative match, D4 refusal, delete `_coerce_bool` |
| `_cli/tui/cli_arg_parser.py`, `_cli/tui/job_execution.py` | carry and render the D4 hint |
| `_cli/tui/smart_bar_autocomplete.py`, `_cli/tui/sync.py` | the two readers |
| `tests/adapters/test_click_params_parity.py` | frozen snapshot (D3) |
| `tests/tui_group_options/test_smartbar_roundtrip.py` | tripwire inversion |
| `tests/…` new | A1–A8 |

Plus whatever the help-output churn breaks — see RK1, whose size is measured in
T1.1 rather than guessed here.

---

## Risks

### RK1 — Help-output churn is the largest part of the diff

`--dry-run` becomes `--dry-run / --no-dry-run` for every boolean config field;
eleven ship in `examples/` alone. Any exact-help assertion and any doc-verify
scenario quoting help text sees it.

**Mitigation:** the first execute task **measures** the blast radius with a
command and writes the number into `tasks.md` before anything is changed.
Guessing this is how a task's file scope comes out wrong.

### RK2 — `_match_group_flag`'s return shape changes

It has callers beyond `walk_group_path` (`_cli/tui/cli_arg_parser.py` mirrors
this walk). **Mitigation:** enumerate callers with a grep before editing, and
make the grep's hit set the task's file scope.

### RK3 — Click's pair-plus-short-flag parse

`["--x/--no-x", "-s"]` is asserted by the shape intent to parse `-s` as the
positive form. **Mitigation:** re-verify against the installed click before
building on it. If it does not hold, B3 changes shape and the spec is amended
rather than the test.

### RK4 — Two surfaces, one rule

The whole point of move 1. **Mitigation:** a parity test that drives *both*
`func` and an app entry point over the same declaration, in the style of
`tests/group_options/test_adapter_entry_point_parity.py` — the seventh CLI probe
that already exists for exactly this reason.

### RK5 — Gates authored from prose (the lesson from the previous feature)

The workflow-launch-validation feature shipped **two** gates that did not
observe what their task changed, and one that could not run at all. Both were
written during Plan from prose rather than run.

**Mitigation, binding for this feature:** every task's gate command is **run at
authoring time during execute, before the task is started**, and its file scope
set to the command's actual hit set. A task whose sabotage does not go red is
reported as a bad gate, not worked around.

---

## Acceptance mapping

| Criterion | Task |
|---|---|
| A4 cold/warm short flag | T1.1 |
| A3 all four shapes render one way | T2.1 |
| A5 collision determinism | T2.1 |
| A1 config boolean off | T2.2 |
| A2 group boolean off, both surfaces | T3.1 |
| A6 `--flag=value` refused both | T3.1 |
| A8 shell round-trips a False | T3.2 |
| A7 absence still means absence | T2.2 |
| A9 reachability | every task |
| A10 no regression | T4.1 |
