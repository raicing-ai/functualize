# T11 Handoff — Completions read the grammar

**Task:** `.spec/features/run-outcome-authority/tasks.md` lines 202–206 — make `src/functualize/_cli/completions/data.py` read the flag grammar from the public authority (`functualize.app.utils` / `functualize.types`) rather than computing flag partitions independently.

**Status:** No change made. Halted because the task description did not match what the code does.

---

## 1. Edits made

**No files changed.** I did not touch `data.py` or any other file.

---

## 2. What `data.py` actually does today

`src/functualize/_cli/completions/data.py` (212 lines) produces flag suggestions through two helper functions, both of which delegate to the **shared click-param builder** rather than computing spellings locally:

- **`_flag_opts(fields)`** — lines 58–73:
  - Imports `build_click_params_from_fields` from `functualize.app.adapters.click_params` (line 66).
  - Iterates the returned click params, collects every `opt` where `opt.startswith("-")` (lines 69–72).
  - Returns the list of `--long` / `-s` spellings.

- **`_field_choices(fields)`** — lines 76–90:
  - Same builder (line 78), builds a `params` dict keyed by field name.
  - For each field with a non-empty `choices` attribute, takes the first `--long` opt as the dict key and the choices as the value (lines 82–89).

- **`job_flags(dotted, segments)`** — lines 154–174:
  - Called per runnable node during the trie walk (line 187).
  - Gets the job's own `config_fields` from the descriptor (line 162), calls `_flag_opts` and `_field_choices` on them.
  - For inherited group options (lines 168–171), walks `trie.group_options_on_path(segments[:-1])` and calls the same two helpers on `spec.fields`.

- **`extract_completion_data(func_app)`** — lines 112–207:
  - Top-level entry point. Builds the group trie via `build_group_trie` from `functualize.app.utils` (lines 122–146), walks it, and assembles `command_tree` + `flag_choices`.

**No function in `data.py` hard-codes a flag spelling, a `--no-x` negative form, or a list of global options.** The negative spelling `--no-dry-run` is produced *inside* the click builder (`click_params.py:308–310` calls `negative_flag_for`), so `data.py` already inherits it through the shared builder.

---

## 3. Does `data.py` duplicate anything in `flag_grammar.py`?

**No direct duplication found.** `data.py` does not import from `functualize._types.flag_grammar` at all, and it does not redefine `GLOBAL_BOOL_FLAGS`, `GLOBAL_OPTIONS_ALWAYS_VALUE`, `GLOBAL_OPTIONS_OPTIONAL_VALUE`, `GLOBAL_OPTIONS_WITH_VALUE`, `OPTIONAL_VALUE_VALID_SET`, `negative_flag_for`, `flag_aliases`, `negative_aliases`, or `match_group_flag`.

The only shared piece is the **click-param builder** (`build_click_params_from_fields` in `app/adapters/click_params.py`), which is the single rendering path. `data.py` reads its flag spellings *through* that builder, not from a second copy. The negative-flag rule (`negative_flag_for`) lives in `flag_grammar.py:179–210` and is called by the builder at `click_params.py:309`, `595`, `662`, `863` — `data.py` gets its effect transitively.

There is no constant or function in `data.py` that would drift from `flag_grammar.py` because `data.py` has no local copy of any grammar rule.

---

## 4. Why I could not settle on a change

The task says data.py "computes flag partitions independently today," but my reading shows it already reads flag spellings through the shared `build_click_params_from_fields` builder — the same builder the CLI and TUI use. The T11 gate counts `negative_flag_for` in `data.py` (currently **0**) and says "after: unchanged counts, resolved through `app.utils`." Since the count is already 0 and the resolution already happens through the builder (which is reached via `functualize.app.adapters.click_params`, not directly via `functualize.app.utils`), I could not determine what concrete change the task is asking for. Adding an import of `negative_flag_for` just to make a grep count non-zero would be gate-satisfying vandalism (the function is not used there), so I stopped rather than guess. The ambiguity is: **the task describes data.py as an independent grammar consumer, but the code already consumes the grammar through the shared builder — is the intended change to import `negative_flag_for` directly (and use it where?), or is the task's premise incorrect and no change is needed?**

---

## 5. Commands run and real output

- `rg -c 'negative_flag_for' src/functualize/_cli/completions/data.py` → **0 matches** (data.py does not reference it).
- `rg -n 'negative_flag_for' src/functualize/app/adapters/click_params.py` → import at line 40 (`from functualize.types import negative_flag_for`); calls at lines 309, 595, 662, 863.
- `rg -n 'negative_flag_for' src/functualize/_cli/tui/bar.py` → import at line 277 (`from functualize.app.utils import negative_flag_for`) — already correct per T10.
- `rg -n 'negative_flag_for' src/functualize/_cli/tui/sync.py` → import at line 127 (`from functualize.app.utils import negative_flag_for`) — already correct per T10.
- `rg -n 'negative_flag_for' src/functualize/_cli/dispatch.py` → **no matches** (dispatch does not use it).
- `rg -n 'negative_flag_for' src/functualize/_types/naming.py` → lines 129–131, a thin re-export from `flag_grammar.py`.
- `rg -n 'negative_flag_for' src/functualize/app/utils.py` → re-exported from `flag_grammar` (line 75) and from `naming` (line 251).
- `rg -n 'def negative_flag_for' src/functualize/_types/flag_grammar.py` → line 179 (definition).
- `rg -n 'build_click_params_from_fields' src/functualize/_cli/completions/data.py` → lines 66, 78 (both helpers use the shared builder).
- Read full files: `data.py`, `flag_grammar.py`, `click_params.py` (relevant ranges), `app/utils.py` (imports), `tests/pipeline/test_completions_data.py` (full), `tasks.md` (T8–T12 sections), `spec.md` (full).

No `ruff`, `mypy`, `lint-imports`, or `pytest` were run — no change was made to verify.
