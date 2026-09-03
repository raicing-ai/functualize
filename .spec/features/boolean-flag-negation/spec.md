# Spec: A Boolean You Can Turn Off

**Status: specified**
**Date: 2026-09-03**
**Base: `feat/workflow-run-params` @ `f9fe1ba`**
**Source: [`.spec/shape-intents/boolean-flag-negation.md`](../../shape-intents/boolean-flag-negation.md)**

The shape intent's assertions were re-verified at this base before specifying.
`click_params.py`, `_cli/dispatch.py` and `_cli/tui/sync.py` are **byte-identical**
to the commit it was written against (`git diff 2af8a07..HEAD` over those paths
is empty), so every GAP it records is current.

---

## Problem

**The config ladder promises CLI > env > file. For booleans it is three-quarters
true, and nothing says so.**

Every other field type can be overridden from the command line at the highest
precedence there is. A boolean that is `true` in a config file cannot be made
`false` there — not on either surface, not by any spelling.

Verified on a live project whose config sets both booleans `true`:

| Kind of boolean | Surface | `--flag=false` | `--no-flag` |
|---|---|---|---|
| `GroupOptions` field (`--strict`, mid-path) | `func` | **works** → `strict=False` | refused |
| `GroupOptions` field | app entry point | `Option '--strict' does not take a value.` | refused |
| Job config field (`--verbose`) | `func` | `Option '--verbose' does not take a value.` | refused |
| Job config field | app entry point | `Option '--verbose' does not take a value.` | refused |

**One of four works, and it is the accident.** `func` has a pre-boot parser used
only for flags typed *mid-path*; it accepts `=value` on any flag without asking
whether the flag is a boolean. Click, which handles everything else, never
accepts a value on a flag. So the identical command succeeds on one surface and
is refused on the other — a live parity defect no test covers.

The environment layer works everywhere (`DEPLOY__STRICT=false`), so **nobody is
blocked**. This is a broken promise and an ergonomic gap, not a missing
capability. That is why it was never urgent.

### One declaration, three renderings

Derived from the builders rather than asserted — four boolean shapes, two
behaviours, and no rule a reader could infer:

| Shape | Negative form today | Built by |
|---|---|---|
| plain signature `bool` | **yes** | `click_params.py:346` (warm), `:744` (cold) — `[f"--{h}/--no-{h}"]` |
| plain signature `bool` **with a short flag** | no | `click_params.py:319-330` — builds `[long, short]`, no pair |
| job config-model `bool` | no | `_config_field_option:417` — `decls = [f"--{name}"]` |
| `GroupOptions` `bool` | no | same helper |

### This is not a regression

The frozen typer-parity snapshot
(`tests/adapters/test_click_params_parity.py:204,216`) records `("--enabled",)`
and `("--opt-flag",)` with empty `secondary_opts`, captured from typer's own
output before the click migration. **Typer rendered a single flag too.** A
long-standing limitation became visible; nothing got worse.

---

## Decisions taken (2026-09-03)

The shape intent listed four questions as blocking. All four are answered, and
the answers are the spec:

| # | Question | Decision |
|---|---|---|
| D1 | Do config booleans gain a negative form? | **Yes** — emit `--x/--no-x` |
| D2 | What wins when `--no-foo` is ambiguous? | **The literal field `no_foo` wins.** `foo` then renders with no negative form |
| D3 | May the frozen typer snapshot change? | **Yes**, recorded as a deliberate departure |
| D4 | `--flag=value` for a boolean? | **Refused on both surfaces** |

---

## Behavior

### B1 — A boolean config-model field gets a negative form

A `bool` field on a job's config model renders as `--x / --no-x`. `--no-x` sets
it `False` at CLI precedence, so a config file's `true` can be overridden.

### B2 — A boolean `GroupOptions` field gets one too, on both surfaces

Both `func deploy --no-strict run` and `python main.py deploy --no-strict run`
set it `False`. The mid-path flag boundary is unchanged: the flag still belongs
to the path it was typed at.

### B3 — A short flag does not cost you the negative form

`plain_bool_short` currently renders `('--plain-bool-short', '-p')` with no
pair. It gains one: `--x / --no-x` plus `-p`, where `-p` is the positive form.
This closes the middle row of the table above, already recorded in ADR-009's
2026-08-28 amendment.

### B4 — A literal `no_x` field wins, deterministically

If a model declares **both** `x: bool` and `no_x: bool`, then:

- `--no-x` binds to the field literally named `no_x`;
- `x` renders as `--x` alone, **with no negative form**;
- the outcome does not depend on declaration order.

Today click raises nothing and binds by declaration order, so the same two
fields give opposite results depending on which was written first. That silent,
order-dependent shadowing is the defect; determinism is the fix. No error is
raised — the user gets a working CLI in which one field simply has no negative
spelling.

### B5 — `--flag=value` is refused for a boolean, on both surfaces

`func deploy --strict=false run` becomes an error naming `--no-strict` as the
replacement, matching what click already does everywhere else. This closes the
one leaky spelling and is what makes the two surfaces agree.

### B6 — Cold and warm agree on a config field's short flag

`_config_field_option` takes `short_flag`, and today only the **warm** caller
passes it (`click_params.py:278`); the cold caller (`:490`) does not. So `-s`
works on a warm boot and is unknown on a cold one — the first run of a project
behaves differently from every run after it.

The short flag originates in an `Option(short=...)` marker in the field's
`Annotated` metadata. Both builders must recover the same value. This is
**separable from negation** and may land first.

### B7 — The resolution ladder is unchanged

`--x/--no-x` is declared with `default=None`, so absence still resolves to
`None` and `_config_field_option`'s contract — *"`None` is how it says 'not
provided'; the resolution ladder supplies the rest"* — survives intact. Only an
explicitly typed flag reaches the CLI layer.

### B8 — The other readers of these flags follow

- **Completion** offers the negative form (`smart_bar_autocomplete.py:328`
  reads `param.opts` and must also read `param.secondary_opts`).
- **TUI write-back** emits `--no-x` for an explicitly `False` group option
  rather than dropping it (`_cli/tui/sync.py:99`).

Without these the shell would offer a flag it cannot complete and round-trip a
`False` into nothing — the `emit(resolve(text)) == text` fixed point ADR-009
pins.

---

## Out of scope

- **Non-boolean fields.** Nothing about `str`, `int`, `Enum` or `multiple`
  rendering changes.
- **The ladder itself.** No precedence changes; `Override > CLI > Env > File >
  Default` is untouched.
- **Positional arguments.** A config field is never a positional and stays so.

---

## Acceptance criteria

Gates, run at authoring time.

- [ ] **A1 — A config boolean can be turned off.** On a project whose config
      sets `verbose = true`, `func deploy run --no-verbose` exits 0 and the job
      observes `verbose=False`. The same on the app's own entry point.

- [ ] **A2 — A group boolean can be turned off, on both surfaces.**
      `func deploy --no-strict run` and `python main.py deploy --no-strict run`
      both exit 0 and observe `strict=False`. Both surfaces asserted, because
      the group flag reaches them through different parsers.

- [ ] **A3 — All four boolean shapes render one way.** Derived from the
      builders, not asserted by hand: every shape in the table above emits a
      `secondary_opts` containing `--no-<name>`, except a field suppressed by
      B4. The gate is a test that walks the builder's own output.

- [ ] **A4 — Cold and warm agree.** For a field carrying `Option(short="-s")`,
      `build_click_params` and `build_click_params_from_fields` produce
      identical `opts` and `secondary_opts`. Currently they differ.

- [ ] **A5 — The collision is deterministic.** A model declaring `cache` and
      `no_cache` binds `--no-cache` to `no_cache`, and `cache` carries no
      secondary form — asserted with the two fields declared in **both orders**,
      because order-dependence is the defect.

- [ ] **A6 — `--flag=value` is refused on both surfaces.**
      `func deploy --strict=false run` and the app entry point both exit
      non-zero, and the `func` message names `--no-strict`.

- [ ] **A7 — Absence still means absence.** A boolean neither set nor negated
      resolves from the config file exactly as it does today. This is the cell
      that catches a `--x/--no-x` pair declared with the wrong default.

- [ ] **A8 — The shell round-trips a False.** `emit(resolve(text)) == text`
      holds for a command line containing `--no-strict`.

- [ ] **A9 — Reachability.** For each of the four call sites, name the
      production path and break it once; a test must fail.

- [ ] **A10 — No regression.** Full suite under `HYPOTHESIS_PROFILE=ci
      --run-slow -n auto`, `pytest examples/`, all 11 plugin suites, `ruff`,
      `mypy src/`, `lint-imports`.

---

## Known cost, accepted

**Help output changes for every boolean config field** — `--dry-run` becomes
`--dry-run / --no-dry-run`. Eleven such fields ship in `examples/` alone, so
doc-verify scenarios asserting exact help text will need updating. Cosmetic, but
it is the largest part of the diff by line count.

**The frozen typer snapshot changes** (D3). Two rows, and the file's docstring
gains a note saying the departure was decided rather than drifted into.

**A tripwire test inverts.**
`tests/tui_group_options/test_smartbar_roundtrip.py:393`
(`test_a_groups_negative_boolean_spelling_is_not`) pins today's behaviour and
says so deliberately: *"Whether group booleans should gain the pair is a
dispatch-level question this feature does not answer. If they ever do, this test
is the one that will say so."* It is saying so.
