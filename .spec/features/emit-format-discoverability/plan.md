# Plan — emit-format-discoverability

## Architecture

The region is `func`'s pre-boot layer only (`contributor/architecture/surface-boundary.md` §1),
plus one help string on the adapter.

```
BEFORE

 _types/flag_grammar.py            OPTIONAL_VALUE_VALID_SET  (the one vocabulary)
        │ (via app/utils.py — _cli imports public folders only)
        ▼
 _cli/dispatch.py
   detect_mode ──lookahead──► refused token becomes first positional ─► Mode.UNKNOWN
   _assign_option  "--emit-format must be one of {…}"   (only the --flag=value path)
        │
        ▼
 _cli/main.py
   cli_app (_LeftMarginEpilogGroup)   --help: 14 globals, run options absent
   _handle_job  ──not found──► "Unknown command 'bogus'"

 app/adapters/cli.py   --emit-format click.Choice  (help: "Serialization for out.emit()")

AFTER

 _types/flag_grammar.py            unchanged
        ▼
 _cli/dispatch.py
   invalid_value_message(flag, value)   ◄── shared by _assign_option and main
   refused_optional_value(argv_tail) -> (flag, token) | None
        ▼
 _cli/main.py
   _LeftMarginEpilogGroup.format_options  + "Run options" section (valid set from grammar)
   _handle_job  ──not found──► refused_optional_value? ─yes─► invalid_value_message, 1
                                                     └no──► "Unknown command" (unchanged)

 app/adapters/cli.py   --emit-format help + the return-value sentence
```

Layers: `_types` ← `app/utils` (public corridor) ← `_cli`. No new edge; no
import-linter contract is crossed. `_cli/dispatch.py` already imports the
grammar through `functualize.app.utils`.

Why not declare the three as click options on `cli_app`: that group also serves
BUILTIN mode, which rejects run-scoped globals on purpose (ADR-020). A help
section changes rendering only; parsing stays where it is.

Why the check sits post-boot in `_handle_job` rather than in `detect_mode`: a
refused token may still name a function-level job, a group or a plugin command
that only the booted app can see. Only after all of those miss is the
"bad value" reading certain.

## Design skills consulted

- `design-patterns-refactoring` (user-level; Refactoring.Guru catalogue).
- The in-repo `python-design-patterns` skill was not loaded separately; the
  change adds no class and no module.

## Surviving smells

- **Duplicate code** (small): the return-value sentence appears in two help
  strings — `_cli/main.py` (run-options section) and `app/adapters/cli.py`
  (`--emit-format` option). Accepted: the only shared home both can import is
  a public folder, which would add a public symbol (and an `examples/` caller,
  `adding-public-api.md` step 8) for one line of help text. A test asserts both
  surfaces carry it (AC2), so drift fails rather than passes. No maintainer
  review needed.
- The `--emit-format` / `--force` / `--prompt-gates` help texts on the `func`
  section restate the adapter's. Same reason, same guard (AC1 pins the `func`
  rows; the adapter rows are click options already pinned by their own tests).

## Files

- `src/functualize/_cli/dispatch.py` — `invalid_value_message`, `refused_optional_value`.
- `src/functualize/_cli/main.py` — run-options help section; bad-value branch in `_handle_job`.
- `src/functualize/app/adapters/cli.py` — `--emit-format` help sentence.
- `tests/cli/test_emit_format_discoverability.py` — AC1–AC5.
- `CHANGELOG.md` — Unreleased entry.

## Risks

- `_handle_job`'s not-found branch is also reached by Mode.UNKNOWN after an
  alias miss; the new check runs only in the non-alias branch and only when
  the refused token equals the typed name.
