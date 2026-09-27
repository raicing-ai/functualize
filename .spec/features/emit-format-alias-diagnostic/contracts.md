# Pre-boot flag contract: arity, values, diagnostics

This contract covers the `func`/`functualize` console entry point's early
(pre-boot) parse: which flags exist, how many tokens each consumes, what happens
when a value is missing or wrong, and what exit status each outcome carries. It
does not define an internal Python API, and it does not cover the app's own entry
point except in the one row where that surface is explicitly aligned.

Authority: this file records the member decision of 2026-09-27T10:54:24Z — in
`func`'s early parse a flag is **either boolean, or its value is mandatory** —
and supersedes the optional-value lookahead that
`docs/api/types.md:150-187`, `contributor/architecture/surface-boundary.md:152`
and `contributor/architecture/run-model/06-outcome-authority.md:126-150` describe
as deliberate.

## 1. The three tables

The grammar publishes exactly three tables, and each answers one question.

| Table | Members | Meaning |
|---|---|---|
| `GLOBAL_BOOL_FLAGS` | 6: `--force`, `--help`, `-h`, `--no-dotenv`, `--no-prompt-gates`, `--prompt-gates` | Consumes no token. No accepted-values set. |
| `GLOBAL_OPTIONS_VALUE_REQUIRED` | 16: the 14 below, plus `--emit-format` and `--perf-report` | Consumes exactly one token: the next argv token. |
| `SELECTION_VALUES` | 2 entries | Accepted values and the absent-flag default, for the flags that have a set. |

Value-required members (the 14 already in the table, verified against
`func --help`): `--log-level`, `--dotenv-file`, `--config-directory`,
`--discovery-depth`, `--require-file-import`, `--require-file-prefix`,
`--require-file-postfix`, `--require-file-marker`, `--require-job-prefix`,
`--require-job-postfix`, `--require-job-decorators`, `--exclude`,
`--perf-filter`, `--import-libs`.

```
SELECTION_VALUES = {
    "--emit-format": (frozenset({"auto", "json", "ndjson", "none", "raw"}), "auto"),
    "--perf-report": (frozenset({"text", "json"}), "text"),
}
```

The two names being replaced — `GLOBAL_OPTIONS_ALWAYS_VALUE` and
`GLOBAL_OPTIONS_WITH_VALUE` — were two spellings of one set once the optional
members join it (`WITH_VALUE == ALWAYS_VALUE | OPTIONAL_VALUE`). They collapse
into `GLOBAL_OPTIONS_VALUE_REQUIRED`; no alias is kept (pre-release repository,
delete rather than shim). `OPTIONAL_VALUE_VALID_SET` becomes `SELECTION_VALUES`,
which is accurate for both remaining entries — a default for an *absent* flag is
not an optional value.

Export parity: `functualize.app.utils` and `functualize.types` publish the same
three names. `tests/types/test_flag_grammar_consumer_count.py` and
`tests/test_public_api_surface.py` pin the spelling set and the consumer list, so
they move with this rename rather than after it.

## 2. The arity rule

When a value-required flag appears, the **next argv token is its value**, with no
inspection of that token:

| Next token | Result |
|---|---|
| an accepted value (`json`) | value assigned; parsing continues after it |
| a job name, group, plugin command or `[aliases]` key (`greet`, `shortcut`) | value assigned; **no lookup happens**, this is the invalid-value path (§4) |
| another recognized flag (`--force`, `--no-dotenv`) | value assigned; `--force` does not take effect for this run |
| an unrecognized flag or a negative number (`-x`, `-1`) | value assigned (no leading-dash exception) |
| nothing (end of argv) | §3, usage error |
| `=` form (`--emit-format=`, `--emit-format=greet`) | the text after `=` is the value, possibly empty; the `=` form never consumes a second token |

`--emit-format` is the only flag whose value decides the pre-run *output* mode and
whose value is also a legal job-level name; the rule is the same for all 16.
`_cli/main.py`'s `--version` fast scan (`:2032-2055`) must advance by two tokens
for a value-required flag: it reads arity from the same table, and if it kept its
`+= 1  # conservative` step the scan and the parser would disagree about whether
`--version` is a value. `_cli/dispatch.py::ParsedGlobalOptions.first_positional_index`
follows the same arithmetic; it has no consumer outside `dispatch.py`.

## 3. Missing value — the usage error

New behavior for all 16 value-required flags (`func --log-level` currently lists
the jobs and exits 0; `func --emit-format` currently runs the bare route).

| Flag kind | Required first stderr line | Exit |
|---|---|---|
| declares a selection table | `Error: --emit-format requires a value: one of {auto, json, ndjson, none, raw}.` | 2 |
| no selection table | `Error: --config-directory requires a value.` | 2 |

Shape: `Error: <flag> requires a value` + `: one of {<sorted values>}` when a set
exists + `.`. The values are the flag's own, sorted, comma-and-space separated —
composed by the same code path as the invalid-value message so the two cannot
drift.

## 4. Wrong value

Unchanged text and unchanged exit status.

| Input | Required first stderr line | Exit |
|---|---|---|
| `func --emit-format shortcut` (alias with missing target) | `Error: --emit-format must be one of {auto, json, ndjson, none, raw}, got 'shortcut'.` | 1 |
| `func --emit-format greet` (`greet` exists) | `Error: --emit-format must be one of {auto, json, ndjson, none, raw}, got 'greet'.` | 1 |
| `func --emit-format=` | `Error: --emit-format must be one of {auto, json, ndjson, none, raw}, got ''.` | 1 |
| `func --perf-report shortcut` | `Error: --perf-report must be one of {json, text}, got 'shortcut'.` | 1 |
| `func --emit-format --force greet` | `Error: --emit-format must be one of {…}, got '--force'.` | 1 |
| `func --emit-format -x greet` | `Error: --emit-format must be one of {…}, got '-x'.` | 1 |

No line mentioning an alias, a job, a group or a plugin command may appear in
value position. The alias/unknown-command diagnostics are unchanged and remain
reachable in command position (§5).

**Known asymmetry, deliberate:** a missing value exits 2, a wrong value exits 1.
Flattening both to 2 is one line plus four test updates and is what
`docs/cli/modes.md:144-148` and `contributor/reference/pitfalls.md:485-490`
describe as the doctrine; it is decision (a) of the confirmation list.

## 5. Command position — preserved

| Input | Required first stderr line | Exit |
|---|---|---|
| `func shortcut` (`shortcut = "absent"`, no `absent` job) | `Error: Alias 'shortcut' maps to job 'absent', which was not found.` | 1 |
| `func --emit-format json shortcut` / `func --emit-format=json shortcut` | the same alias error | 1 |
| `func bogus` | `Error: Unknown command 'bogus'.` | 1 |
| `func greet --emit-format json` | `Error: No such option '--emit-format'.` (job-level) | 2 |
| `func --emit-format json builtin version` | `Error: No such option '--emit-format'.` (builtin boundary, ADR-020) | 2 |
| `func --version` | version line | 0 |
| absent `--emit-format` / `--perf-report` | run proceeds, `auto` / `text`, as today | — |

`func --emit-format auto greet` stays valid: `auto` is a public accepted value,
not only an internal default.

## 6. The app's own surface

`functualize.app.adapters.cli` declares its own `--emit-format` for the embedded
app (`:1117-1118`), on a Click command that also takes a positional `cmd`. It
loses `is_flag=False, flag_value=_OUTPUT_DEFAULT` and becomes a plain
value-required option, so the two surfaces state the same arity:

| Input (app surface) | Result |
|---|---|
| `main.py --emit-format emit` | `Error: Option '--emit-format' requires an argument.`, exit 2 |
| `main.py --emit-format json emit` | unchanged |
| `main.py --perf-report emit` | unchanged (already value-required there) |

`flag_value` appears in exactly two places in `src/**` (`app/adapters/cli.py:1117`,
`app/adapters/workflow_flags.py:95,124`); no other module — including
`_cli/completions/` — reads it, so the change is two lines and needs no
follow-up. `app/adapters/workflow_flags.py`'s `flag_value=_OMITTED` is **out of
scope**: it is a job-level workflow flag parsed by Click after the command is
known, where no command candidate can follow.

## 7. Rendered and documented surfaces

| Surface | Requirement |
|---|---|
| `func --help` run-options row | `--emit-format TEXT`, accepted values in the prose (`Format: auto, json, ndjson, none or raw.`), default named. No `[auto|json|ndjson|none|raw]` bracket — brackets advertise the optional value this contract removes. `--perf-report TEXT` is the existing precedent. |
| `docs/api/types.md` | the four-table section (5 + 2 mentions) rewritten to the three-table vocabulary, and the lookahead rationale removed. |
| `contributor/architecture/surface-boundary.md`, `run-model/06-outcome-authority.md:126-150`, `run-model/14-decisions.md:48` (J5), `run-model/07-surface-parity.md:82-95` | the records that call the lookahead deliberate are marked superseded. |
| `contributor/architecture/codemaps/data-flow.md:57` | precedence list unchanged; the alias row stays where it is. |
| `CHANGELOG.md` | entry for the behavior change, naming the two flags and the `--flag` + flag-token spellings that now exit 1. |

## 8. Non-goals

No alias resolution in value position (that is the point of the contract), no
change to the `[aliases]` configuration format, no change to accepted values'
meaning at run time, no change to `--flag=value` splitting, no shim for any
removed name, and no extension of `[aliases]` to an app's own entry point
(`.spec/STATUS.md` #40 stays deferred).
