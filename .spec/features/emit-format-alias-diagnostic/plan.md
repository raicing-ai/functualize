# Plan — emit-format-alias-diagnostic

Phase: **Plan** (`.spec/README.md` stage 3). Contract of record:
`.spec/features/emit-format-alias-diagnostic/spec.md` (B1–B8, AC1–AC9) and
`contracts.md` §1–§5, both confirmed by the member on 2026-10-02 against
`sdd/emit-format-alias-diagnostic` @ `3cb96a598e3b2e749bc9f00c4e8f64ea681a1b87`.

- Workflow mode: `REPOSITORY_NATIVE`
- Authority: `AGENTS.md`, `.claude/rules/spec-workflow.md`,
  `.claude/commands/agentic-plan.md`, `.spec/CONSTITUTION.md`,
  `.spec/ARCHITECTURE.md`, `.spec/TESTING.md`
- `.spec/STATE.md` absent → no work in flight.
- Scope: **one arity per pre-boot flag.** The optional-value lookahead and its
  post-boot re-decision cease to exist; `--perf-report` and `--emit-format`
  become value-required like the other fourteen.
- Out of scope (spec §Scope boundary, B1, §Confirmed decisions): extending
  `[aliases]` to an app entry point (`.spec/STATUS.md` #40); alias config
  syntax; what an accepted value *does* at run time; the global-flag
  detectors; the public rename of `OPTIONAL_VALUE_VALID_SET` (a separate
  follow-up, annotated `# TRANSITIONAL(...)` here).
- `schema.md`: **not written.** The change alters no table, type or
  aggregation shape — it deletes a table, adds two pure predicates and two
  message helpers, all specified in §"Approach" below. `agentic-plan` step 9
  is conditional on "implementation internals are complex"; they are not.

---

## 1. Architecture pass — what this region is

Consulted, per `agentic-plan` step 2–3:

| Tool | Question | Answer used here |
|---|---|---|
| **zvec-grep** (`zg query`, index 838/838 files, 13 308 entities) | what does the surrounding prose say this is for? | `contributor/architecture/audit-engine-encapsulation.md:363-379` (Extract Class, §3.5) owns the "which flags take values" question; `docs/api/types.md:162-187` is the live account of the four tables; `contributor/architecture/run-model/07-surface-parity.md:82-95` places the lookahead in the pre-boot-only row; `src/functualize/_cli/dispatch.py:97-235` and `:572-611` are the two enforcement sites |
| **graphify** `get_neighbors` (project_path = repo root; graph is stale for line numbers, used for *shape* only) | what depends on this? | `detect_mode` ← `_run_cli()` (`_cli/main.py:2101`), imported at `_cli/main.py:2023`; calls `_names_a_group()` (`:209`), `normalize_segment()` (`:224`). `_extract_global_options` ← `_run_cli` (`:2111`) **and** `builtins.py:781` (the `builtin cache` provider build) |
| **codemaps** `contributor/architecture/codemaps/` | which layer is each module in? | `overview.md` §*Audience-Separated Package Structure*: `_types/`, `_cli/` internal; `app/`, `types/` public. `entry-points.md`/`data-flow.md` confirm `func`'s pre-boot order: extract globals → discover → detect mode → route |
| **serena** | LSP-accurate references | **unavailable** — the MCP server refuses on a project-name collision. Substituted by `rg` hit sets plus graphify; every `[F]` list in `tasks.md` is an `rg` hit set, not a list from memory |

### Existing smells, by catalogue name

The vocabulary is `design-patterns-refactoring` (cheat-sheet §*smell → technique*,
`:53-66`) and `.agents/skills/python-design-patterns`.

1. **Duplicated knowledge — the global-prefix arity rule is spelled three
   times.** `detect_mode` (`dispatch.py:142-181`), `_extract_global_options`
   (`:271-376`) and the `--version` prefix scan (`main.py:2029-2054`) each walk
   argv and each decide, independently, whether a token is consumed as a value.
   *(catalogue: Duplicated Code / Divergent Change.)* Pitfall 19
   (`contributor/reference/pitfalls.md:318-346`) already names the enforcement
   for this class: when a rule cannot be shared, a **parity test** is the
   mechanism, not a docstring. Under this change the three copies must agree on
   the new arity — so the plan carries a shared predicate (§Approach A1) *and*
   the parity test AC8 requires (§Approach A4).
2. **Mysterious Name.** After the change `OPTIONAL_VALUE_VALID_SET` no longer
   describes optional values — every member of it is value-*required*. The
   remedy is Rename; it is deliberately deferred by the member (their separate
   follow-up), so the entry moves to §Surviving smells with a
   `# TRANSITIONAL(...)` annotation rather than a rename.
3. **Long Method / switch-on-flag.** `_extract_global_options` is a 170-line
   walk with a 21-arm `elif flag == ...` chain, and `_assign_option` another
   60-line one. *Replace Conditional with Polymorphism* would dissolve it, but
   the skill's Rule of Three does not license it here — we are deleting arms,
   not adding a fourth kind of flag consumer. Recorded, not fixed.
4. **Divergent Change (inherent).** `_cli` and Click must keep two parsers
   (J5, `contributor/architecture/run-model/14-decisions.md:48`). This plan
   keeps that decision; only the *arity* of the pre-boot parser changes.

---

## 2. Skills consulted (named, per `agentic-plan` step 5)

- **`design-patterns-refactoring`** (`/home/ubuntu/.claude/skills/design-patterns-refactoring/SKILL.md`
  and `cheatsheet.md`) — smell vocabulary and the Rule-of-Three test applied to
  smell 3 above; the "Remove Middle Man / Rename" remedies for smells 1–2.
- **`python-design-patterns`** (`.agents/skills/python-design-patterns/SKILL.md`)
  — Python-specific guidance: pure functions over classes for a two-line rule
  (`Function` over `Strategy` at this size); no ABC for a predicate.
- **`code-intel`** (`.claude/skills/code-intel/SKILL.md`) — routing table for
  the three retrieval tools; `zg` is at `/usr/local/bin/zg`.
- **`contributor/architecture/audit-engine-encapsulation.md:355-379`** (§3.5
  *Extract Class*) — the precedent that the grammar's *data* belongs in
  `_types/flag_grammar.py` while its *enforcement* stays in `_cli/dispatch.py`.
  This plan preserves exactly that split.

---

## 3. BEFORE

```
PUBLIC  types/__init__.py ── re-exports GLOBAL_OPTIONS_{ALWAYS,OPTIONAL}_VALUE,
        app/utils.py          GLOBAL_OPTIONS_WITH_VALUE, OPTIONAL_VALUE_VALID_SET
            ▲
            │ import  (the sanctioned corridor: `_cli` may import public folders only)
            │
INTERNAL  _types/flag_grammar.py        pure data, stdlib-only
_cli/       GLOBAL_OPTIONS_ALWAYS_VALUE      = 14 members
            GLOBAL_OPTIONS_OPTIONAL_VALUE    = {--perf-report, --emit-format}   ← lookahead vocabulary
            GLOBAL_OPTIONS_WITH_VALUE        = ALWAYS | OPTIONAL  (16)
            OPTIONAL_VALUE_VALID_SET         = flag -> (valid_set, default)
            ▲
            │ import via functualize.app.utils
            │
          _cli/dispatch.py
            detect_mode()            :97-235   lookahead branch :159-167
            _extract_global_options():271-444  missing-value "break, don't consume" :347-352
                                               lookahead branch :354-368
            _assign_option()         :494-555  invalid value -> SystemExit(1) :547,554
            refused_optional_value() :572-611  post-boot re-decision  <──┐
            is_known_global_flag()   :791-801  (BOOL ∪ WITH_VALUE; no --version)
            ▲                                                             │
            │ same module                                                   │
          _cli/main.py                                                        │
            help rows                       :79-96  uses OPTIONAL_VALUE_VALID_SET["--emit-format"]
            _handle_unknown_command         :1478-1500  refused_optional_value consumer ──┘
            _run_cli() --version prefix scan:2029-2054  `elif _tok in OPTIONAL_VALUE_VALID_VALUE: _i += 1`
            ────────────────────────────────────────────────────────────────────
PUBLIC  app/adapters/cli.py  :1113-1132  click.Option(--emit-format, type=Choice,
                                          is_flag=False, flag_value=_OUTPUT_DEFAULT)
                              :49        _OUTPUT_VALUES, _OUTPUT_DEFAULT = OPTIONAL_VALUE_VALID_SET["--emit-format"]

Boundaries: `_cli` → public (`app.utils`, `types`) only; `_types` → stdlib only;
app adapter → public `types` only. No internal `_cli` import crosses into `_types/`.
```

The lookahead is what makes `func --emit-format shortcut` reach the *alias*
diagnostic path: `shortcut` is not in the valid set, so it is not consumed,
so it becomes the first positional, so `detect_mode` classifies it as a
command and the operator is told to go fix `[aliases]`. That is the bug in the
issue title — a *value* mistake reported as a *command* mistake.

---

## 4. AFTER

```
PUBLIC  types/__init__.py ── re-exports GLOBAL_OPTIONS_ALWAYS_VALUE,
        app/utils.py          GLOBAL_OPTIONS_WITH_VALUE, OPTIONAL_VALUE_VALID_SET
            ▲                 (GLOBAL_OPTIONS_OPTIONAL_VALUE GONE from both)
            │ import
INTERNAL  _types/flag_grammar.py        pure data, stdlib-only
_cli/       GLOBAL_OPTIONS_ALWAYS_VALUE   = 16 members  (--perf-report, --emit-format moved in)
            GLOBAL_OPTIONS_OPTIONAL_VALUE = DELETED
            GLOBAL_OPTIONS_WITH_VALUE     = same 16 (kept name, detector vocabulary)
            OPTIONAL_VALUE_VALID_SET      = unchanged table, name kept, annotated
                                           # TRANSITIONAL(emit-format-alias-diagnostic)
            ▲
            │ import via functualize.app.utils   (+ ExitCode, from the same corridor)
          _cli/dispatch.py            ← the ONE place the arity rule is stated
            is_known_global_flag()   :791-801   (unchanged)
            is_reserved_pre_boot_token()  NEW   is_known_global_flag(t) or --version
            value_required_takes_next()   NEW   (flag, nxt) -> bool   ── the rule
            detect_mode()                        ALWAYS branch: `+2 if rule else +1`
                                                 lookahead branch DELETED
            _extract_global_options()            no value -> missing_value_message(), exit 2
                                                 lookahead branch DELETED
            _assign_option()                     invalid value -> exit 2  (was 1)
            missing_value_message()       NEW    + selection set when the flag has one
            invalid_value_message()              kept (docstring corrected)
            refused_optional_value()             DELETED
            version_requested()           NEW    pure prefix scan, same `rule`
            ▲                     ▲
            │                     │
          _cli/main.py            └──────────── _cli/builtins.py:781 (unchanged call)
            help row  →  `--emit-format TEXT` + accepted values in the description
            _handle_unknown_command: refused_optional_value block DELETED (dead)
            _run_cli: `if version_requested(sys.argv[1:]): print; return`
            ────────────────────────────────────────────────────────────────────
PUBLIC  app/adapters/cli.py  :1113-1132  flag_value=_OUTPUT_DEFAULT REMOVED
                                          (is_flag=False + Click => "requires an argument")
```

**What the AFTER removes:** one public table, one enforcement branch duplicated
in two places, one post-boot re-decision function and its consumer block, one
dead `--version`-scan branch. **What it adds:** one predicate, one arity
function, one message helper, one extracted pure scan — each replacing a
re-derivation rather than sitting beside one.

### 4.1 AFTER vs the seven `[[tool.importlinter.contracts]]` (`pyproject.toml:262-400`)

| Contract | Effect of AFTER |
|---|---|
| (1) peer layers independent | untouched — no `_discovery`/`_config`/`_engine`/`_plugins` change |
| (2) `_events` foundation-only | untouched |
| (3) `_primitives` imports nothing internal | untouched |
| (4) `_types` imports nothing internal | **holds**: `flag_grammar.py` deletes members; it gains no import at all |
| (5) internal never imports public | **holds**: `_cli` is already a source module of (5) and already imports `functualize.app.utils`; the new `ExitCode` import takes the same corridor |
| (6) `_cli` uses public API only | **holds**: the new helpers live *inside* `_cli/dispatch.py`; `main.py` imports them from `_cli.dispatch`, which is intra-`_cli`, not an internal `_`-package crossing. `ExitCode` arrives through `functualize.app.utils` (`app/utils.py:203`), never `functualize._types` |
| (7) delivery adapters go through the request | untouched |

No contract is added, weakened or bypassed; no new module is created. `_types`
gains nothing to import, so the AFTER cannot introduce an `_types → _cli` edge.
Verification: `uv run lint-imports` must report 7/7 kept (task T7.1).

### 4.2 AFTER vs `.spec/CONSTITUTION.md` → *Forbidden Patterns*

Walked entry by entry, `CONSTITUTION.md:88-101`:

- circular imports between subpackages — **no**; the AFTER removes a name from
  the public surface rather than adding an edge.
- peer-layer cross-imports — **no**.
- runtime CLI imports in kernel layers — **no**; `click` is still touched only in
  `app/adapters/cli.py`, and the only edit there deletes a keyword argument.
- `_cli/` importing internals — **no**; `_cli.dispatch` ← `_cli.main` is the
  same package, and the public corridor is unchanged.
- god-object growth (>500 LOC) — **no**; `dispatch.py` shrinks by ~40 lines and
  gains ~25. `main.py` loses the inline scan and the consumer block.
- ABC as a port, global mutable state, implicit `Callable` ports — **no**; the
  new API is two pure functions.
- `DeprecationWarning` / backward-compat shims — **no**; `GLOBAL_OPTIONS_OPTIONAL_VALUE`
  is *deleted*, not aliased. Nothing re-exports it "for compatibility".
- pointer/lambda-doesn't-need-to-be-a-pointer, fire-and-forget threads,
  hard-coded config paths — **no**.

Nothing on the list appears in the AFTER, so no step-6 iteration is owed.

---

## 5. Approach

### A1 — One statement of the arity rule

In `_cli/dispatch.py`, beside `is_known_global_flag`:

```python
def is_reserved_pre_boot_token(token: str) -> bool:
    """A token the pre-boot layer owns, which no value flag may consume (B2/B3).

    `is_known_global_flag` plus `--version`: the version fast path is a pre-boot
    flag, but is deliberately absent from `GLOBAL_BOOL_FLAGS` (which Click also
    reads), so it is named here instead.
    """
    return is_known_global_flag(token) or token.split("=", 1)[0] == "--version"

def value_required_takes_next(flag_token: str, next_token: str | None) -> bool:
    """Does `--flag` consume `next_token` as its value?  One answer for all three scans."""
    return next_token is not None and not is_reserved_pre_boot_token(next_token)
```

`is_known_global_flag` and `GLOBAL_BOOL_FLAGS` are **not** widened: `--version`
must keep meaning "not a global flag I can advise you to move before the group"
in `_dispatch_group`, and `func infra --version` must keep its current message.

### A2 — Arity in the three scans

- `detect_mode`, ALWAYS_VALUE branch: `i += 2 if value_required_takes_next(arg, args[i+1] if i+1 < len(args) else None) else 1`. The lookahead branch and its `OPTIONAL_VALUE_VALID_SET` import are deleted.
- `_extract_global_options`: when a value-required flag takes no next token, print `missing_value_message(arg)` and `raise SystemExit(ExitCode.USAGE)`. `--flag=value` (the `=`-split branch at `:335-344`) is untouched and keeps supplying its value — including the empty one, so `--emit-format=` still reaches `_assign_option`.
- `version_requested(argv_tail)`: walks the prefix; `--version` → `True`; a
  value-required flag with no consumable value → `False` (the invocation is a
  usage error, so `--version` must not fire — AC6); first positional → `False`;
  end of argv → `False`. `_run_cli` becomes
  `if version_requested(sys.argv[1:]): print(...); return`.

**The invariant AC8 asserts**, and the exact words the parity test uses:

> For every `F` in `GLOBAL_OPTIONS_ALWAYS_VALUE` and every token `T`:
> `detect_mode` consumes `T` as `F`'s value **iff** `_extract_global_options`
> assigns `T` to `F` **iff** `version_requested` skips `T` as `F`'s value.
> For every `F`, a missing value (no `T`, or `T == "--version"`, or `T` a known
> global flag) makes `_extract_global_options` exit 2 with the missing-value
> sentence, never assigns a value, and makes `version_requested` reject the
> prefix rather than treat the following `--version` as the command.

### A3 — Messages and exit codes (contracts §3, §4)

| Helper | Shape |
|---|---|
| `missing_value_message(F)` | `Error: {F} requires a value: one of {a, b, c}.` when `F in OPTIONAL_VALUE_VALID_SET`, else `Error: {F} requires a value.` |
| `invalid_value_message(F, v)` | unchanged text: `Error: {F} must be one of {a, b, c}, got '{v}'.` — docstring rewritten, since its second caller is gone |

Values are `sorted()` and joined `", "` in both, as today.
Exit codes: missing value **2**; invalid value for a flag in
`OPTIONAL_VALUE_VALID_SET` **2** (`ExitCode.USAGE`, not the literal `2`);
command-position errors unchanged (`func shortcut` 1, `func bogus` 1).
**Unchanged, deliberately**: `--log-level BOGUS` and `--discovery-depth abc`
keep their exit 1. See §7 Q1.

### A4 — The help row (AC7, contracts §5)

`_cli/main.py:79-96`: the row becomes
`("--emit-format TEXT", "Serialization for out.emit(): auto, json, ndjson, none or raw (default auto). A job's return value is never printed: …")`
built from `sorted(values)` and `default` read out of `OPTIONAL_VALUE_VALID_SET`
— the table stays the single source, only the *rendering of arity* changes from
`[a|b|c]` to `TEXT`. The app adapter's help text already reads as prose and keeps
`(default auto)`; Click's own usage line for a `click.Choice` valued option
legitimately still shows the choices — the flag now *requires* a value, which
is exactly what that bracket means there.

### A5 — The app surface (AC9)

`app/adapters/cli.py:1113-1132`: drop `flag_value=_OUTPUT_DEFAULT`. Keep
`is_flag=False`, `type=click.Choice(sorted(_OUTPUT_VALUES))`, `default=None`,
and the help string (its `default {_OUTPUT_DEFAULT}` is still true: absence
means `auto`). Update the comment above the option, which currently claims "A
bare `--emit-format` means the default, matching func's optional-value
lookahead". `--perf-report` is not declared on this surface and is unchanged.

### A6 — What is deliberately *not* done

- `OPTIONAL_VALUE_VALID_SET` keeps its name, its `(valid_set, default)` tuple
  shape and its two public re-exports. Only the *feeding back* of `default`
  stops. This keeps `app/adapters/cli.py:49`, `_cli/main.py:81` and the two
  `__all__` lists structurally untouched, which is why the public-API surface
  delta is exactly one removed name.
- The two parsers stay (J5).
- Alias resolution stays command-position-only.

---

## 6. Files to change

Counts are `rg`/`grep` hit counts from this checkout; the per-task `[F]` lists in
`tasks.md` are those hit sets.

### Source — 6 files

| File | Change |
|---|---|
| `src/functualize/_types/flag_grammar.py` | `+2` members into `GLOBAL_OPTIONS_ALWAYS_VALUE`; delete `GLOBAL_OPTIONS_OPTIONAL_VALUE` (`:68-73`) and its `__all__` entry (`:31`); `GLOBAL_OPTIONS_WITH_VALUE` becomes an alias of the 16-member table; `# TRANSITIONAL(...)` on `OPTIONAL_VALUE_VALID_SET`; module docstring `:1-18` rewritten (the "lookahead deliberately stays" paragraph is now false) |
| `src/functualize/_cli/dispatch.py` | import block `:35` (−OPTIONAL, +`ExitCode`); `detect_mode` ALWAYS branch + lookahead branch `:154-167`; `_extract_global_options` missing-value branch `:347-352` + lookahead `:354-368`; `_assign_option` exits `:547`,`:554` → `ExitCode.USAGE`; `invalid_value_message` docstring `:558-570`; delete `refused_optional_value` `:572-611`; add `is_reserved_pre_boot_token`, `value_required_takes_next`, `missing_value_message`, `version_requested` |
| `src/functualize/_cli/main.py` | help rows `:78-96`; delete the `refused_optional_value` block `:1478-1500` (and its local import `:1484-1487`); `--version` scan `:2024-2056` → `version_requested` (+ drop the OPTIONAL import) |
| `src/functualize/app/utils.py` | drop `GLOBAL_OPTIONS_OPTIONAL_VALUE` from the import `:88` and from `__all__` `:303` |
| `src/functualize/types/__init__.py` | drop it from the import `:35` and `__all__` `:87` |
| `src/functualize/app/adapters/cli.py` | remove `flag_value=_OUTPUT_DEFAULT` `:1118`; correct the comment `:1107-1110` |

### Tests — 12 files (3 groups)

**(a) Delete / invert — the 6 files that pin the withdrawn behaviour** (spec
§Blast radius, 15 assertion sites):

| File | Action |
|---|---|
| `tests/_cli/test_dispatch_bug_condition.py` | **delete the file** — its entire premise is the withdrawn release behaviour (`:109,:128,:154,:194,:214,:227,:249`, docstring `:1-14`) |
| `tests/cli/test_early_parse_integration.py` | rewrite `:42,:62,:85` (`--perf-report --no-dotenv forecast` becomes a missing-value usage error) |
| `tests/_cli/test_perf_report_integration.py` | rewrite `TestPerfReportDefaultWithJob` `:63` and `TestPerfReportBareMode` `:79`; module docstring `:16-17` |
| `tests/cli/test_emit_format_rename.py` | `TestTheOldNameIsSimplyGone::test_a_bare_flag_still_falls_back_to_the_default` `:87-96` → asserts the missing-value error instead |
| `tests/cli/test_emit_format_discoverability.py` | `TestTheLookaheadIsUnchanged::test_a_bare_flag_before_a_job_still_runs_it` `:106-111`; the five `exit_code == 1` assertions `:74,:82,:91,:100,:117` → `2` |
| `tests/cli/test_dispatch_characterization.py` | `TestGlobalOptionSkipping::test_optional_value_flag_releases_an_invalid_value` `:71-73` |

**(b) Invert the grammar assertions — 5 files**:

| File | Action |
|---|---|
| `tests/types/test_flag_grammar_roundtrip.py` | imports `:37,:39`; `test_always_and_optional_value_tables_partition_the_union` `:91-98` and `test_optional_valid_set_covers_exactly_the_optional_table` `:108-118` become "one table, 16 members, no optional set"; `test_optional_lookahead_follows_the_grammar_valid_set` `:195-212` **inverts into the parity test's core**; `:120-131,:133-145,:155-160,:162-172` keep working (`is_known_global_flag` unchanged) |
| `tests/types/test_flag_grammar_consumer_count.py` | `_PATTERN` drops `GLOBAL_OPTIONS_OPTIONAL_VALUE` `:69`; `EXPECTED_CONSUMERS` recount |
| `tests/test_public_api_surface.py` | drop `"GLOBAL_OPTIONS_OPTIONAL_VALUE"` `:207-210` |
| `tests/cli/test_app_surface_output_format.py` | docstring `:1-11`; imports `OPTIONAL_VALUE_VALID_SET` (kept) — assert the app's bare-flag error now |
| `tests/skills/test_api_claims.py` | `:22`, `:285-300` — the claims table reads the tables |

**(c) Keep working, add coverage**:

| File | Action |
|---|---|
| `tests/cli/test_version_flag_position.py` | add the arity cases AC8 needs (`:30,:36,:42,:68` unchanged) |
| `tests/_cli/test_dispatch_preservation.py` | **not a delete site** — imports `OPTIONAL_VALUE_VALID_SET` `:28`, uses `:333,:354,:374`, all `=`-style; its table-set membership must keep passing |
| `tests/cli/test_global_options.py` | `:35,:43` assert *that* `--log-level BOGUS` exits, not *with what*; unchanged whether or not Q1 is taken |
| new `tests/_cli/test_pre_boot_arity_parity.py` | the AC8 parity test, named after the rule it enforces |

**Verified unaffected**: `tests/perf/test_cli_perf_report.py`,
`tests/cli/test_global_options_properties.py` (mentions `--emit-format` only as
a flag-name in a list at `:102`), `tests/cli/test_pre_boot_resolution.py`,
`tests/cli/test_early_dispatch.py`.

### Docs — 7 files + a sweep

| File | Change |
|---|---|
| `docs/api/types.md:150-187` | rewrite §*Global flag vocabulary*: three tables, no optional set, `OPTIONAL_VALUE_VALID_SET` described as "accepted explicit values for the value-required flags that have a selection table"; the two lookahead examples `:176,:178` become the missing-value/invalid-value rules |
| `contributor/architecture/surface-boundary.md:197` | the row `--perf-report with no value → optional-value lookahead` becomes "value-required like every other; no lookahead" |
| `contributor/adr/020-engine-entrypoint-encapsulation.md:146` | mark the `--perf-report` lookahead sentence **superseded**; the two-parser decision stays |
| `contributor/architecture/run-model/06-outcome-authority.md:136-142` | same sentence, same supersede pointer |
| `contributor/architecture/run-model/07-surface-parity.md:90` | §E table row |
| `contributor/architecture/run-model/14-decisions.md:48` (J5) | the lookahead half is superseded; "two parsers remain" still holds |
| `contributor/architecture/audit-engine-encapsulation.md:611` | supersede pointer (the `:169,:367,:370,:377` hits sit inside the §3.5 *proposal*'s conditions and stay as written) |
| `CHANGELOG.md` | `## [Unreleased]` entry: new arity, exit 2 for both argument errors, the known-global-flag missing-value case, the help row, the transitional name |

**Sweep gate**: `rg -n "optional-value|lookahead" docs/ contributor/ README.md`
must return only lines that state the rule is gone or superseded.

---

## 7. Risks

| # | Risk | Mitigation |
|---|---|---|
| R1 | The `--version` scan and `detect_mode` could disagree on the malformed input `[F, "--version"]`. They do not need identical advancement (the version scan must *stop*), but they must agree on the invariant in A2. | The parity test asserts the invariant directly, for all 16 members, plus the `--version`-specific case. |
| R2 | `builtins.py:781` also calls `_extract_global_options` with the *full* `sys.argv` (`… builtin cache rebuild`). The new missing-value `SystemExit(2)` could fire where it previously did not. | It fires only when a value-required flag ends the argv or is followed by a known global flag — already a usage error on the `func` path. Covered by an explicit case in the parity test. |
| R3 | `func --emit-format --help`: under the rule, `--help` is a known global flag, so this becomes exit 2 missing-value instead of printing help. Behaviour change not enumerated in contracts §3's examples. | Deliberate and consistent with B2; pinned by a test so it is a decision rather than an accident. Raised as §8 Q2. |
| R4 | Deleting a public name (`GLOBAL_OPTIONS_OPTIONAL_VALUE`) breaks any out-of-tree importer. | Pre-release, `CONSTITUTION.md:99` forbids compatibility shims; the name is transitional by the spec's own words. `tests/test_public_api_surface.py` is the repo's own list and gets updated. |
| R5 | `expect`ed message text drifts between `missing_value_message` and `invalid_value_message`. | Both read `OPTIONAL_VALUE_VALID_SET` and use the same `sorted(...)`/`", "` join; a single unit test asserts both sentences against the table. |
| R6 | 15 assertion sites across 6 files plus 5 grammar-reading files: a mechanical wave that lands half-done leaves the suite red in a way that looks like a source bug. | `tasks.md` wave 3 is one file per task with the file's own test as the gate; the whole-suite run is T7.2. |

## 8. Surviving smells

Required section. Catalogue names are the refactoring skill's.

1. **Mysterious Name — `OPTIONAL_VALUE_VALID_SET`, `src/functualize/_types/flag_grammar.py:76`.**
   After this change the set describes *required* values; "optional" is a lie in
   the name, and the spec's §Blast radius says so explicitly ("Its name … marked
   transitional"). **Accepted, deferred by the member**: the public rename is a
   separate follow-up (spec §Confirmed decisions). Remedy recorded: Rename to
   something like `GLOBAL_OPTION_ACCEPTED_VALUES`, which the follow-up owns.
   Marked `# TRANSITIONAL(emit-format-alias-diagnostic)` in code so the next
   reader finds the reason rather than the smell.
   **Needs maintainer review: yes** — the member is being asked to accept a
   knowingly-misleading public name as a shipped state (Q3).
2. **Duplicated Code / Divergent Change — the global-prefix arity walk, three
   copies** (`_cli/dispatch.py::detect_mode`, `_cli/dispatch.py::_extract_global_options`,
   `_cli/dispatch.py::version_requested`). After this change all three call the
   *one* predicate `value_required_takes_next`, so the rule has a single
   statement; what remains duplicated is the walk, not the rule. A layer
   boundary does not forbid sharing here, but a shared *walker* would have to
   own three different products (a mode, a value map, a boolean), which is the
   abstraction this codebase does not need. Enforcement is the parity test
   (pitfall 19's remedy). **Accepted; needs maintainer review: no.**
3. **Long Method / switch-on-flag — `_extract_global_options` (`:271-444`) and
   `_assign_option` (`:494-555`).** Both shed arms in this change; the
   `elif flag == …` chain survives. *Replace Conditional with Polymorphism* is
   the standard remedy and is **not** taken here: the Rule of Three does not
   apply to a chain we are shortening, and a per-flag strategy object would
   move pre-boot work behind a dispatch table for no measured gain.
   **Accepted as-is; needs maintainer review: no** (recorded so a reviewer sees
   the choice, per the required-section discipline).
4. **Inconsistent invalid-value exit codes — `_cli/dispatch.py`.** After this
   change a bad `--emit-format` value exits 2 while a bad `--log-level` value
   (`:385-389`) and a bad `--discovery-depth` value (`:523`) exit 1. The
   inconsistency pre-dates this change (all three were 1); this change makes it
   *visible*. contracts §3's table enumerates only the two selection-table
   flags, and spec §Blast radius does not mention the other two, so the plan
   leaves them alone rather than widening scope silently.
   **Needs maintainer review: yes** — Q1 below.

Nothing in this section is on `.spec/CONSTITUTION.md`'s *Forbidden Patterns*
list; those were removed in the AFTER, per §4.2.

## 9. Questions put to the member at the gate

- **Q1.** Facet 4 above: leave `--log-level BOGUS` / `--discovery-depth abc` at
  exit 1, or unify them to 2 under "use exit 2 for both missing and wrong
  values" (spec §Confirmed decisions)? Default in this plan: **leave at 1**
  (minimal, matches the ACs and the Blast-radius enumeration).
- **Q2.** Facet R3: `func --emit-format --help` becomes exit 2 missing-value
  rather than rendering help. Confirm that is intended (it follows from B2's
  "a following known global flag means the value is missing").
- **Q3.** Facet 1: accept the knowingly-misleading `OPTIONAL_VALUE_VALID_SET`
  name as a shipped state, with the rename owned by the separate follow-up.

Approval of this plan and its task list (`.spec/features/emit-format-alias-diagnostic/tasks.md`)
is the Plan gate; Execute does not begin until it is given.
