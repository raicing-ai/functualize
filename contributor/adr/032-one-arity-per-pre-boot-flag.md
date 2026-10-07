# ADR-032: One Arity per Pre-Boot Flag

**Status**: accepted
**Date**: 2026-09-27 (rule); scope confirmed 2026-09-28 and 2026-10-05
**Deciders**: maintainer

## Context

`func`'s early (pre-boot) parse used to let two of its flags take a value
**optionally**. `--emit-format` and `--perf-report` were listed in
`GLOBAL_OPTIONS_OPTIONAL_VALUE`, with their accepted values in
`OPTIONAL_VALUE_VALID_SET`, and every reader of that table decided what the
token after a bare flag meant by asking whether it belonged to the flag's
accepted set. A token outside the set was left standing as a *command
candidate*: `func --emit-format greet` ran `greet` with the default format.

That lookahead made one token mean two things at once, and the two meanings
were resolved by different code at different times:

- **pre-boot** — `_cli/dispatch.py::detect_mode` consumed the flag alone and
  classified the token as the command; `_cli/dispatch.py::_extract_global_options`
  assigned the flag's *default* value and left the token at
  `first_positional_index`.
- **post-boot** — `_cli/main.py::_handle_job` re-walked the same prefix through
  `_cli/dispatch.py::refused_optional_value`, which asked the opposite question
  and re-decided the same token as the value the flag refused.

With `[aliases] shortcut = "absent"` and no `absent` job, the consequence
(PR #51 review, finding 1) was:

```
$ func --emit-format shortcut
Error: --emit-format must be one of {auto, json, ndjson, none, raw}, got 'shortcut'.
```

Exit 1. The same token in command position reports the repair the operator
actually has to make:

```
$ func shortcut
Error: Alias 'shortcut' maps to job 'absent', which was not found.
```

The token was resolved as a command pre-boot and rejected as a flag value
post-boot, so the alias diagnostic was unreachable on exactly the spelling that
needed it. An operator was sent to repair a `--emit-format` value that was not
the setting at fault.

## Decision

**In `func`'s early (pre-boot) parse a flag is either boolean, or its value is
mandatory — never optional, never defaulted.** With no optional-value flag there
is no position in which a token might be a command, so the misdiagnosis class
cannot exist rather than being re-ordered.

1. **One arity per flag.** `GLOBAL_BOOL_FLAGS` consumes no token;
   `GLOBAL_OPTIONS_ALWAYS_VALUE` consumes one. `--perf-report` and
   `--emit-format` join the latter, and `GLOBAL_OPTIONS_OPTIONAL_VALUE` is
   removed. The global-flag detectors stay.
2. **A required value has one position.** A job name or alias key after the
   spaced flag is its value, with no command lookup. A following **known global
   flag** means the value is missing, so `--force` is not silently swallowed;
   an unrecognized dash token or a negative number remains a value candidate.
   The `--flag=value` form supplies its value explicitly, even when the value is
   empty or spells a flag.
3. **One exit code for an argument error.** A missing value and an invalid value
   are both usage errors, exit 2, for **every** value-required pre-boot flag —
   not only the two that lost their optional value. Command-position errors are
   unchanged (`func shortcut` and `func bogus` exit 1).
4. **No command or alias resolution in value position.** `func --emit-format
   shortcut` reports the invalid-value sentence and mentions no alias. The alias
   error is reachable wherever the alias is in command position
   (`func shortcut`, `func --emit-format json shortcut`), which is what meets the
   finding's requirement that the caller be told which setting to repair.
5. **The rule has one statement.** `value_required_takes_next` in
   `_cli/dispatch.py` answers "does this flag consume the next token" for all
   three pre-boot scans (`detect_mode`, `_extract_global_options`,
   `version_requested`), and `tests/_cli/test_pre_boot_arity_parity.py` holds
   them to the same answer for every value-required flag.

The two parsers stay: pre-boot and Click share a vocabulary but still parse
separately (ADR-020, *Neutral*; run-model decision J5). Only the pre-boot
parser's arity changed.

## Consequences

### Positive

- The misdiagnosis cannot recur by re-ordering: no token has two meanings, so
  no later code can re-decide one.
- A missing value is reported for every value-required flag. `func --log-level`
  used to list the jobs and exit 0, and `func --emit-format` used to run bare
  mode.
- The post-boot re-decision (`refused_optional_value` and its consumer in
  `_handle_job`) is deleted rather than kept beside a fix.

### Negative

- This deliberately changes documented spellings. `func --emit-format greet`
  no longer runs `greet`, and `func --perf-report --perf-filter=X job` and
  `func --emit-format --force job` become missing-value usage errors.
- `func --emit-format --help` is a missing-value usage error rather than a help
  render, because `--help` is a known global flag and so not consumable as a
  value.
- The invalid `--log-level` value and the non-integer `--discovery-depth` value
  move from exit 1 to exit 2; a script that tested for 1 there sees the change.
- The app's own entry point requires a value for `--emit-format` too: a bare
  `main.py --emit-format emit` gets Click's
  `Error: Option '--emit-format' requires an argument.`

### Neutral

- `OPTIONAL_VALUE_VALID_SET` ships under its now-misleading name, marked
  `# TRANSITIONAL(emit-format-alias-diagnostic)` in
  `src/functualize/_types/flag_grammar.py`. Its public rename is open as
  follow-up #35 in `.spec/STATUS.md`.
- Aliases still resolve only on `func`; extending them to an app's own entry
  point is the deferred `.spec/STATUS.md` #40.

## Alternatives Considered

| Alternative | Pros | Cons | Why rejected |
|-------------|------|------|-------------|
| **A-1.** Keep the optional value and move the diagnostics: recognize the command first, report the flag value only if command resolution misses | Keeps every existing spelling, including `func --emit-format greet` | It keeps the two-meaning token and would add a third place that decides what the token means | Withdrawn by the maintainer (2026-09-27): the fix is the flag contract, not the diagnostic order |
| **A-2 (chosen).** One arity per pre-boot flag: boolean or value-required | The misdiagnosis class cannot exist; one statement of the rule, held by a parity test | Breaking for the spellings listed under *Negative* | — |

## Accepted as-is

**Long Method / switch-on-flag — `_cli/dispatch.py::_extract_global_options`
and `_assign_option`.** `_assign_option` picks the field with one
`elif flag == …` arm per value-required flag, and `_extract_global_options`
follows its walk with one block per accumulated field. *Replace Conditional
with Polymorphism* is the standard remedy and is **not** taken: the Rule of
Three does not apply to a chain this change shortened rather than extended, and
a per-flag strategy object would move pre-boot work behind a dispatch table for
no measured gain. The smell is not on `.spec/CONSTITUTION.md`'s *Forbidden
Patterns* list. Revisit when a fourth kind of flag consumer appears.
