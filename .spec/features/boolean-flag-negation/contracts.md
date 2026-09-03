# Contracts: Boolean Flag Negation

External interfaces only — what a user or a caller outside this feature can
observe. **No Python signature in the public API changes.** The contract that
changes is the *command-line surface* a declaration produces, which is the
product's interface even though it is not a function signature.

---

## 1. The CLI surface a `bool` declaration produces

This is the whole feature. Given:

```python
class RunConfig(BaseModel):
    verbose: bool = Field(default=False, description="Chatty output")

class DeployOptions(GroupOptions, group="deploy"):
    strict: bool = Field(default=False, description="Fail on warnings")
```

| | Before | After |
|---|---|---|
| `--verbose` | sets `True` | unchanged |
| `--no-verbose` | `Error: No such option` | sets `False` |
| `--strict` (mid-path) | sets `True` | unchanged |
| `--no-strict` (mid-path) | `Error: unknown option` | sets `False` |
| neither given | resolves from env/file/default | **unchanged** |
| `--verbose=false` | `Error: does not take a value` | unchanged (still an error) |
| `--strict=false` (on `func`) | **sets `False`** | **`Error`, naming `--no-strict`** |

The last row is the only place an existing working invocation stops working.
Pre-1.0, and `--no-strict` is the direct replacement named in the error.

### Help output

Every boolean config field's help line changes shape:

```
  --dry-run                 Skip side effects        ->  --dry-run / --no-dry-run   Skip side effects
```

Eleven such fields ship in `examples/`. Any assertion on exact help text — in
tests or in a doc-verify scenario — sees this.

---

## 2. `functualize.app.utils.job_input_schema` and the MCP tool surface

Booleans already publish as JSON-schema `{"type": "boolean"}`, and that does not
change: a schema describes the *value*, not the flag spelling. An MCP client
sends `{"verbose": false}` today and still does.

**Consequence worth stating:** the negation is a CLI-surface affordance only. It
gives the command line the expressiveness the JSON surface already had, rather
than adding a capability the other surfaces lack.

---

## 3. `_config_field_option` — internal, but the single rule

`src/functualize/app/adapters/click_params.py:391`. Not public API; recorded
because it is the seam both builders share and the place the contract is
decided.

```python
def _config_field_option(
    name: str, *, click_type, is_flag: bool, multiple: bool,
    help_text: str, short_flag: str | None = None,
) -> click.Option
```

The signature is unchanged. What changes is what it returns when `is_flag` is
true — a declaration carrying a `--no-` secondary — and that **both** call sites
now pass `short_flag` (`:278` warm already does; `:490` cold does not, which is
the cold/warm divergence B6 closes).

`default=None` is preserved. That is load-bearing: `None` is how the option says
"not provided", and the resolution ladder supplies everything else. A
`--x/--no-x` pair with `default=None` yields `None` when absent, `True` for the
positive and `False` for the negative — verified before specifying.

---

## 4. `func`'s mid-path flag parser

`src/functualize/_cli/dispatch.py`. Internal, and `func`-only — an app's own
entry point never reaches it (`contributor/architecture/surface-boundary.md`).

- `_flag_aliases` (`:699`) gains `--no-<name>` spellings for `bool` fields only.
- `_match_group_flag` (`:715`) resolves a negative match to the value `False`.
- The inline-value branch (`:769`) **rejects** `--flag=value` when the field is
  a boolean, with a message naming `--no-flag`.

The third is the parity fix (D4) and is the only behavioural removal in the
feature.

---

## 5. Shell completion and TUI write-back

Both are user-visible, neither changes shape:

- **Completion** (`_cli/tui/smart_bar_autocomplete.py:328`) offers `--no-x`
  alongside `--x`. Today it reads `param.opts` only, so it would offer a flag
  set that omits the new spelling.
- **TUI write-back** (`_cli/tui/sync.py:99`, `_group_flag_tokens`) emits
  `--no-x` for an explicitly `False` group option instead of omitting it. This
  preserves the `emit(resolve(text)) == text` fixed point ADR-009 pins; without
  it, toggling a group boolean off in the TUI would round-trip to nothing.

`_render_group_option_rows` (`_cli/main.py:857`) already joins `opts +
secondary_opts` at `:870` and needs no change — verified, not assumed.

---

## 6. What is deliberately **not** promised

- **No error on a `no_x` / `x` collision.** Per D2 the literal field wins and
  `x` simply renders without a negative form. A user gets a working CLI, not a
  refusal. The guarantee is *determinism*, not detection.
- **No `--flag=value` support anywhere**, for any boolean, on any surface.
- **No change to non-boolean fields**, to positional arguments, or to the
  precedence ladder.
