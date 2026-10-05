# Pre-boot flag contract: arity, values, diagnostics

This contract covers `func`/`functualize` before the app boots. It records the
member's rule: a pre-boot flag is boolean or has a mandatory value. Global-flag
detection and command routing remain necessary; only optional-value lookahead
and its post-boot re-decision cease to exist.

## 1. Flag inventory

| Class | Flags | Token count when present |
|---|---|---|
| Boolean (`GLOBAL_BOOL_FLAGS`) | `--force`, `--help`, `-h`, `--no-dotenv`, `--no-prompt-gates`, `--prompt-gates` | 0 |
| Value-required (`GLOBAL_OPTIONS_ALWAYS_VALUE`) | `--log-level`, `--dotenv-file`, `--config-directory`, `--discovery-depth`, `--require-file-import`, `--require-file-prefix`, `--require-file-postfix`, `--require-file-marker`, `--require-job-prefix`, `--require-job-postfix`, `--require-job-decorators`, `--exclude`, `--perf-filter`, `--import-libs`, `--emit-format`, `--perf-report` | 1 |
| Boolean fast path | `--version` before the first positional argument | 0 |

`GLOBAL_OPTIONS_WITH_VALUE` remains a global-flag detector and has the same
members as `GLOBAL_OPTIONS_ALWAYS_VALUE` after the two flags move.
`GLOBAL_OPTIONS_OPTIONAL_VALUE` is removed. The exported
`OPTIONAL_VALUE_VALID_SET` retains its name for this fix, but its entries now
describe accepted explicit values; their legacy bare-flag defaults are unused:

| Flag | Accepted explicit values | When absent |
|---|---|---|
| `--emit-format` | `auto`, `json`, `ndjson`, `none`, `raw` | `auto` |
| `--perf-report` | `json`, `text` | no performance report |

The now-misleading `OPTIONAL_VALUE_VALID_SET` name and duplicate value-set
names receive transitional annotations in code and a separate rename task.
This change does not rename their public exports.

## 2. Value position

`func --emit-format json greet` and `func --emit-format=json greet` assign
`json`, then route `greet` as the command. In the spaced form, a job name,
group, plugin command, alias key, unknown token or unrecognized dash token
after a value-required flag is its value; no command lookup occurs there. A
negative number such as `-1` after `--discovery-depth` reaches that flag's
value parser. In the `--flag=value` form, the text after `=` is explicitly the
value, even if empty or spelled like another flag.

A **known global flag** in the spaced value position is different: it means
the preceding value is missing. The existing `GLOBAL_BOOL_FLAGS` and
`is_known_global_flag` detection determine ordinary global flags; the special
pre-boot `--version` action must be recognized in this check too. For example,
`func --emit-format --force greet` reports the missing format value; `--force`
is neither swallowed nor applied. `func --emit-format --version` reports the
missing value and does not print the version. An unrecognized `-x` remains a
value candidate, so it can receive the flag's invalid-value error.

`detect_mode`, `_extract_global_options`, the position-aware `--version` scan,
and `is_known_global_flag` remain. Their treatment of the global prefix must
agree for every value-required flag, including the two newly required values.
The optional-value lookahead branches and `refused_optional_value` are removed.

## 3. Missing and invalid values

Both are usage errors with exit status **2**. Accepted-value lists are sorted,
comma-and-space separated. The first stderr line is:

| Input | Required first stderr line | Exit |
|---|---|---|
| `func --emit-format` | `Error: --emit-format requires a value: one of {auto, json, ndjson, none, raw}.` | 2 |
| `func --emit-format --force greet` or `func --emit-format --version` | the same missing-value line | 2 |
| `func --perf-report` | `Error: --perf-report requires a value: one of {json, text}.` | 2 |
| `func --config-directory` | `Error: --config-directory requires a value.` | 2 |
| `func --emit-format shortcut` or `func --emit-format greet` | `Error: --emit-format must be one of {auto, json, ndjson, none, raw}, got 'shortcut'.` or the same line with `greet` | 2 |
| `func --emit-format=bogus greet` | `Error: --emit-format must be one of {auto, json, ndjson, none, raw}, got 'bogus'.` | 2 |
| `func --emit-format=` | `Error: --emit-format must be one of {auto, json, ndjson, none, raw}, got ''.` | 2 |
| `func --perf-report shortcut` | `Error: --perf-report must be one of {json, text}, got 'shortcut'.` | 2 |
| `func --emit-format -x greet` | `Error: --emit-format must be one of {auto, json, ndjson, none, raw}, got '-x'.` | 2 |
| `func --log-level BOGUS greet` | `Error: --log-level must be one of CRITICAL, DEBUG, ERROR, INFO, WARNING, got 'BOGUS'.` | 2 |
| `func --discovery-depth abc greet` | `Error: --discovery-depth must be a valid integer, got 'abc'.` | 2 |

The missing-value rule applies to every member of
`GLOBAL_OPTIONS_ALWAYS_VALUE`, including the members that already required a
value. Value-position errors mention neither aliases nor jobs. The last two rows
are the same rule read across the whole table: an invalid value is a usage error
for **every** value-required flag, so `--log-level` and `--discovery-depth` —
which validated their values and exited 1 before this change, and were outside
its first draft — now exit 2 like the rest (member decision of 2026-10-05).

## 4. Command position and app entry point

| Input | Required outcome | Exit |
|---|---|---|
| `func shortcut`, with `[aliases] shortcut = "absent"` and no `absent` job | `Error: Alias 'shortcut' maps to job 'absent', which was not found.` | 1 |
| `func --emit-format json shortcut` or `func --emit-format=json shortcut` | the same alias error | 1 |
| `func bogus` | `Error: Unknown command 'bogus'.` | 1 |
| `func greet --emit-format json` | job-level `No such option '--emit-format'` | 2 |
| `func --emit-format json builtin version` | builtin `No such option '--emit-format'` | 2 |
| `func --version` | version line | 0 |
| app entry point: `main.py --emit-format emit` | Click's `Option '--emit-format' requires an argument.` | 2 |
| app entry point: `main.py --emit-format json emit` | run `emit` with `json` | existing run status |

The app's `--emit-format` is value-required as well; its `--perf-report` is
unchanged. Aliases still resolve only on `func`. The alias error is reachable
whenever the alias is in command position, and `func --emit-format shortcut`
deliberately puts `shortcut` in value position instead.

## 5. Rendered and documented surfaces

`func --help` renders `--emit-format TEXT` and names its accepted values and
absent-flag default in prose. The old `[auto|json|ndjson|none|raw]` bracket,
which advertises an optional value, is removed. Documentation and the changelog
describe the new arity, exit 2 for both argument errors and for an invalid value
on any value-required flag, and the known-global-flag missing-value case.
Existing global-flag detection remains documented;
the separate public-name cleanup is identified as transitional. ADR-020's
neutral statement that the `--perf-report` lookahead is deliberately `func`-only
is marked superseded by this rule; its decision to keep the pre-boot and Click
parsers separate still holds.
