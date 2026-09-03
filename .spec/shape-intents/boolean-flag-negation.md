# Shape Intent: A Boolean You Cannot Turn Off

**Status: IMPLEMENTED 2026-09-03** (`feat/workflow-run-params`).
See `.spec/STATUS.md` → *Boolean flag negation* for what shipped, the four
decisions the maintainer took, and the two tripwires that fired.
Originally: assessed, not yet specified.
**Date: 2026-08-31**
**Base: `feat/workflow-run-params` @ `2af8a07` (master after #13)**
**Scope: how a `bool` becomes a CLI flag — `_config_field_option`
(`app/adapters/click_params.py:391`), `_flag_aliases` / `_match_group_flag`
(`_cli/dispatch.py:699,715`), and the three surfaces that read them back
(listing, completion, TUI write-back).**

Every claim below carries the command that demonstrates it. A claim with no
command is not a finding. All commands were run on this base.

---

## Core Principle

**The config ladder promises CLI > env > file. A boolean breaks that promise.**

Every other field type can be overridden from the command line at the highest
precedence there is. A boolean that is `true` in the config file cannot be made
`false` there — not on either surface, not by any spelling. The ladder is
documented in `docs/guides/group-options.md` and `docs/cli/config.md`; for
booleans it is only three-quarters true, and nothing says so.

A second principle is at stake, and it is the one that makes this worth fixing
rather than documenting: **one declaration, one CLI shape.** There are four
boolean shapes today and they render three different ways, with no rule a user
could infer.

---

## The reproduction

A project whose config file sets both booleans `true`:

```toml
# config.base.toml
[deploy]
strict = true            # a GroupOptions field

[deploy.run]
verbose = true           # a job's own config-model field
```

```python
class DeployOptions(GroupOptions, group="deploy"):
    strict: bool = Field(default=False)

class RunConfig(BaseModel):
    verbose: bool = Field(default=False)

@job(group="deploy")
def run(log: Log, config: RunConfig, options: DeployOptions) -> None:
    print(f"strict={options.strict} verbose={config.verbose}")

@job(group="deploy")
def plain(log: Log, flag: bool = True) -> None:
    print(f"plain_flag={flag}")
```

### Assertion 1 — a group boolean can be set false from the CLI. **GAP**

```
$ func deploy --no-strict run
Error: unknown option '--no-strict' before a command.          [exit 2]

$ python main.py deploy --no-strict run
Error: No such option '--no-strict'. Did you mean '--strict'?   [exit 2]
```

### Assertion 2 — a job's own config boolean can be set false from the CLI. **GAP**

```
$ func deploy run --no-verbose
Error: No such option '--no-verbose'. Did you mean '--verbose'? [exit 2]

$ func deploy run --verbose=false
Error: Option '--verbose' does not take a value.                [exit 2]
```

Identical on both surfaces.

### Assertion 3 — the environment layer still reaches them. **PASS**

```
$ DEPLOY__STRICT=false func deploy run
strict=False verbose=True                                       [exit 0]

$ DEPLOY_RUN_VERBOSE=false func deploy run
strict=True verbose=False                                       [exit 0]
```

**This is the escape hatch, and it works on both surfaces.** Nobody is stuck;
the gap is one of ergonomics and of a documented promise, not of capability.
It is the reason this is not urgent.

### Assertion 4 — the two surfaces agree on what a boolean accepts. **GAP**

```
$ func deploy --strict=false run
strict=False verbose=True                                       [exit 0]

$ python main.py deploy --strict=false run
Error: Option '--strict' does not take a value.                 [exit 2]
```

A **live parity defect, independent of the rest.** `func`'s pre-boot parser
accepts `--flag=value` for a mid-path boolean (`_cli/dispatch.py:769`, the
`inline is not None` branch); click never does. One spelling works on one
surface and is refused by the other, and no test covers it.

### Assertion 5 — one rule decides a boolean's spelling. **GAP**

Derived from the builder rather than asserted — `build_click_params` over a job
carrying all four shapes:

```
param                opts                          secondary_opts          is_flag
plain_bool           ('--plain-bool',)             ('--no-plain-bool',)    True
plain_bool_short     ('--plain-bool-short', '-p')  ()                      True
cfg_bool             ('--cfg-bool',)               ()                      True
cfg_bool_short       ('--cfg-bool-short',)         ()                      True
```

Four shapes, two behaviours, and the difference is invisible in the source:

| Shape | Negative form |
|---|---|
| plain signature bool | **yes** |
| plain signature bool **with a short flag** | no |
| job config-model bool | no |
| `GroupOptions` bool | no |

ADR-009's 2026-08-28 amendment already recorded the middle row; the config-model
rows are new here.

### Assertion 6 — cold and warm render a config boolean identically. **GAP**

The same field, through both builders:

```
COLD (live signature, build_click_params):
  cfg_bool_short   opts=('--cfg-bool-short',)        secondary=() is_flag=True default=None
WARM (cached descriptor, build_click_params_from_fields):
  cfg_bool_short   opts=('--cfg-bool-short', '-s')   secondary=() is_flag=True default=None
```

**A config-model field's short flag is dropped on the cold path and kept on the
warm one.** This is a *third* defect, unrelated to negation, and it is the exact
cold/warm builder divergence #13 consolidated `_config_field_option` to end.

The cause is one omitted keyword, not a second rule. Both callers reach the same
helper; only one passes the flag:

```
click_params.py:268  (warm, from cached FieldDescriptors)
    _config_field_option(field.name, ..., short_flag=field.short_flag)

click_params.py:491  (cold, from the live signature)
    _config_field_option(field_name, click_type=..., is_flag=..., multiple=...,
                         help_text=help_text)          # <- no short_flag
```

`_config_field_option`'s own docstring (`:411-415`) explains why the parameter
exists — *"``short_flag`` stays a per-builder input because only the cached
descriptor records it"* — and that reasoning is what left the cold path with
nothing to pass. Whether the live signature can recover a marker's short flag at
all is the open question; if it cannot, the honest fix may be to drop it warm
rather than add it cold. Nothing asserts the two agree.

Consequence: `-s` works on a warm boot and is unknown on a cold one — the first
run of a project behaves differently from every run after it.

---

## This is not a regression

Worth stating plainly, because it changes the urgency. The frozen typer-parity
snapshot (`tests/adapters/test_click_params_parity.py:204,216`) records
`("--enabled",)` and `("--opt-flag",)` with empty `secondary_opts` — captured
from typer's actual output before the click migration. `opt_flag` is
`bool = True`, so it has never been settable to `false` from the CLI.

**Typer rendered a single flag too.** This is original behaviour, inherited
through the click migration and preserved by it. #13 only made the *group
listing* stop advertising a `--no-` form that never parsed. Nothing got worse;
a long-standing limitation became visible.

---

## The shape of the fix

The mechanism is verified. A click `--x/--no-x` pair with `default=None`:

```
[]                 -> value=None   (absent)
['--dry-run']      -> value=True
['--no-dry-run']   -> value=False
```

`None` still means "not provided", so `_config_field_option`'s whole contract —
*"``None`` is how it says 'not provided'; the resolution ladder supplies the
rest"* (`:402-409`) — survives intact. A short flag coexists with the pair
(`["--x/--no-x", "-s"]` parses `-s` as the positive form).

| Site | Change | Buys |
|---|---|---|
| `click_params.py:391` `_config_field_option` | emit `--x/--no-x` when `is_flag`; accept and pass `short_flag` from **both** callers | Assertions 2, 5, 6 |
| `dispatch.py:699` `_flag_aliases` | add `--no-<name>` aliases for `bool` fields only | Assertion 1 (`func`, mid-path) |
| `dispatch.py:715` `_match_group_flag` | return `inline="false"` for a negative match | — `walk_group_path`'s existing `_coerce_bool` branch (`:769`) then needs **no change** |
| `dispatch.py:769` | reject `--flag=value` for a bool, or teach click to accept it | Assertion 4 — pick one, but pick |
| `smart_bar_autocomplete.py:328` | `param.opts` → `+ param.secondary_opts` | completion offers the negative |
| `tui/sync.py:99` `_group_flag_tokens` | emit `--no-x` for an explicit `False` | TUI round-trips a false instead of dropping it |

`_render_group_option_rows` (`_cli/main.py:857`) already joins
`opts + secondary_opts` (`:870`) and needs nothing.

Roughly 35-40 lines of source across four files.

---

## What it breaks

**No command line that works today stops working.** Adding a spelling is
additive. Four real costs:

1. **Help output changes for every boolean config field.** `--dry-run` becomes
   `--dry-run / --no-dry-run`. Eleven such fields ship in `examples/` alone.
   Cosmetic, but it breaks any exact-help assertion and several doc-verify
   scenario steps.

2. **A deliberately frozen typer-parity snapshot changes.**
   `tests/adapters/test_click_params_parity.py`, rows at `:204` and `:216`. The
   file's docstring says these were captured from typer param-for-param. Editing
   them is a conscious departure from typer parity — a decision, not an edit.

3. **A silent name collision that click will not catch.** If `foo: bool` gains
   `--no-foo`, a sibling field literally named `no_foo` now contends for the
   same token. Click raises nothing and binds it by declaration order:

   ```
   --cache/--no-cache declared first, then --no-cache:  --no-cache -> no_cache_field=True
   --no-cache declared first, then --cache/--no-cache:  --no-cache -> cache=False
   ```

   Order-dependent shadowing, no error — the "two paths that drift" class this
   codebase exists to prevent. **A fix must add an explicit precedence rule and
   a test.** This is the part that needs thought; the rendering does not.

4. **The tripwire test must be inverted.**
   `tests/tui_group_options/test_smartbar_roundtrip.py:393`
   (`test_a_groups_negative_boolean_spelling_is_not`) pins the current
   behaviour, and says so deliberately: *"Whether group booleans should gain the
   pair is a dispatch-level question this feature does not answer. If they ever
   do, this test is the one that will say so."* It is saying so.

**What does not need updating:** `TestReadinessAgreesWithClick`
(`tests/tui_group_options/test_write_back_contract.py:216`) derives its expected
set from the param builder itself, so it follows the change automatically. That
is the design working.

---

## Sequencing

Ship the `click_params` and `dispatch` halves **together**. Doing only the first
fixes job-config booleans on both surfaces and group booleans on the app
surface, leaving `func` and `app` disagreeing about group booleans — worse than
today's consistent-if-limited state.

Assertion 6 (the dropped short flag) is **separable and smaller**, and does not
depend on the negation decision. It is a plain cold/warm agreement bug and could
land first, on its own, with a test asserting both builders produce identical
`opts` for a field carrying `Option("-s")`.

---

## Decisions needed before specifying — ALL ANSWERED 2026-09-03

| # | Decision taken |
|---|---|
| 1 | **Yes**, config-model booleans gain `--x/--no-x` |
| 2 | **The literal field `no_foo` wins**; `foo` then renders with no negative form. Determinism is the guarantee, not detection — no error is raised |
| 3 | **Yes**, departing from the frozen typer snapshot is acceptable; recorded in the file's docstring as decided rather than drifted |
| 4 | **Refused on both surfaces.** `--flag=value` was accepted on exactly one of four combinations, and that one was the parity defect rather than a feature |

The questions as originally written follow.

### The original questions

1. **Do config-model booleans gain the negative form at all**, or is the ladder's
   promise amended to say "except booleans, use the environment"? Everything
   above assumes the former; the latter is a legitimate, much cheaper answer.
2. **What wins when `--no-foo` is ambiguous** — the literal field `no_foo`, or
   the negation of `foo`? Or is declaring both a hard error at model definition?
3. **Is departing from the frozen typer snapshot acceptable**, given it is the
   permanent regression guard for `build_click_params`?
4. **Assertion 4**: should `--flag=value` be accepted for booleans on both
   surfaces, or refused on both? It currently works on exactly one.

---

## Prior art in this repository

- `contributor/adr/009-group-options-in-the-shell.md` — records the
  job-bool-vs-group-bool asymmetry and, in its 2026-08-28 amendment, the
  short-flag case. Its conclusion was to make the shell *match* dispatch and pin
  both, explicitly deferring whether dispatch should change.
- `tests/tui_group_options/test_smartbar_roundtrip.py:393` — the tripwire.
- `tests/group_options/test_group_options_cli_e2e.py` — asserts the listing
  shows the positive form only, and records why (the listing used to advertise a
  flag that never parsed).
