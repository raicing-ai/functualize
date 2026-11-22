# Research — parameter contract (Specify retrieval pass)

Base: `master` @ `da912d76`. The approved shape intent is *Shape Intent — Collections Earn Repeatable
Flags (list[T], tuple[T, ...], and one verdict behind every surface)*, Confluence `SD/28901379`
version 4 (read live 2026-11-21: `Status: Approved`, `Authority: Approved`). Its measurement record
is the 166-row matrix and its kit; row ids below (`B053`, `E142`, …) are that matrix's.

This file holds what the Specify pass found that **changes the shape** or a premise. Every file named
below is on this branch: scripts in `matrix/`, recorded results in `matrix/evidence/`. Findings that are
simply true are stated in `spec.md` directly.

## R-1 · ADR-018 contradicts the page's "refused at discovery, job not registered" (DESIGN_CONFLICT DC-1)

The page binds (§7): *"the reject list in §5.1, and refusal at discovery naming the parameter and the
remedy"*. Its §5.7 shows the job absent: `Error: No such command '<name>'.`

`contributor/adr/018-unsatisfiable-jobs-are-reported-not-fatal.md` (accepted 2026-09-07) decided the
opposite for one class on that list, a parameter whose dependency has no provider. It recorded that
unregistering was **implemented and reverted**:

> **The job is left registered.** Unregistering it was implemented first and reverted, for two
> reasons: it made the cold boot disagree with the warm one, where validation is necessarily skipped
> for lazy proxies and the job still exists; and "no such command" is a worse answer than a message
> naming the parameter.

**How far each reason still holds under the contract.** For *shape* refusals (`dict`, `object`,
unions, positional-only, two markers), the verdict is computed at discovery and cached. A warm boot
therefore knows it without importing the module, and ADR-018's first reason no longer applies. Its
second reason, that "no such command" is worse than a message naming the parameter, applies to every
class. For the *missing provider* class, ADR-018's first reason still holds in full: provider
availability is known only after plugins load, and warm boot does not validate DI.

So the page's wording, as written, re-introduces a reverted decision for one class and a weaker
message for all of them. `spec.md` carries this as **DC-1**, with the ADR-018-aligned behaviour
recommended. Choosing it amends one Binding item of the page, which the page says requires returning
to it.

## R-2 · Caller-overrides-injection is documented intent today; the page reverses it

`src/functualize/_engine/validation.py:43-47`:

> This is not an *exclusion* of DI parameters — they are ordinary declared parameters, and a caller
> has always been able to supply one explicitly, since the engine injects only names the caller did
> not provide.

The page binds the reverse (§7: *"unknown and injected keys refused"*, for every surface). That is
allowed, since the page is approved and later than the docstring. It is not silent: `spec.md` B-30
states the reversal, and the docstring is part of the change.

**Measured blast radius (page risk R2).** An AST walk of every call to `RunRequest(...)`,
`*.execute(...)`, `invoke(...)` and `run(...)` in `src/`, `plugins/*/*/src`, `tests/`,
`plugins/*/*/tests` and `examples/` looked for keyword arguments, or literal `kwargs={...}` entries,
that pass a capability test double or a conventional capability name. It found **0** (`r2_census.py`
→ `r2_census.txt`). Also 0: `rg` of the same doors on one line with
`FakeShell|CapturingLog|MockInvoke|TestRunContext|AutoPrompt|NoopPerf|FakeStdout`. The documented test
pattern, `deploy(sh=fake)` (`docs/guides/shell.md:140`), calls the function directly and does not
reach the engine. **Limit:** a dynamically built kwargs dict is not visible to either query.

## R-3 · An engine-level binding step already exists; it covers only `Field()` parameters

The page's census (§3.4) said there was "nothing for signature parameters on MCP, HTTP, Lambda or the
TUI". That overstated it. The engine door already runs, for every surface:

- `unexpected_keyword_error(...)`, **only for a workflow** (`_engine/executor.py:1393-1405`);
- config-model resolution and group options;
- `ArgValidator.validate(function, call_kwargs)` (`executor.py:1486`), which builds a pydantic model of
  the **`Field()`-annotated parameters only** (`_engine/validation.py:135-177`; D107's
  `_Validate_d107` refusal is this step);
- DI filling of names the caller did not send (`executor.py:1432-1434`).

The binder the page requires generalises this existing step from `Field()` parameters to every
parameter. It is not a new door. This is consistent with ADR-020 (*proposed*), which already moved "the
config-field/kwargs split" into `engine.run(request)` and names `_cli/tui/cli_arg_parser.py:16-71` "a
third parser".

## R-4 · PEP 563 changes one verdict: `FromJob[...]` silently becomes a caller input (new finding F-32)

`contributor/reference/pitfalls.md` §4 says: *"compile the fixture module both ways."* The 166-row
matrix was compiled without `from __future__ import annotations`, so it was re-run with that import at
the top of every module (`PC_PEP563=1 python3 gen.py …` → `out563.json`; compared field by field
with `pycompare.py` → `pep563-cli.txt`). 165 rows are identical, apart from the order of the provider
list in error text. One is not:

```text
E142  p: FromJob[e142_up]        (documented-invalid subscript form)
  plain annotations:  module refused at load — "FromJob[...] is not a type. Write Annotated[<return type>, FromJob(...)] instead"
  under PEP 563:      module loads; help "Usage: func e142 [OPTIONS] P"; func e142 x → p='x'; info/MCP publish p as a required string
```

An injection declaration becomes an ordinary caller input, with no warning, as soon as the module gains
the future import. `spec.md` B-6 and AC-6 cover it: classification is identical under both annotation
modes.

The wire-surface half of the PEP 563 run (`v563/surfaces.json`, compared with `surf_pycompare.py`
→ `pep563-surfaces.txt`) compares 2,656 cells. 24 differ: 14 are E142, the same finding on the TUI,
MCP, HTTP and Lambda, where `p='x'` reaches the job. The other 10 are the order of a provider list in
error text (E138, E139, H165, H166).

## R-5 · Unknown keys: the same split as F-25

Measured on a one-job project (`greet(name: str = "d")`, `unknown-keys.txt`):

```text
CLI     func greet --zzz 1                          Error: No such option '--zzz'.   exit 2
TUI     "greet --zzz 1"                             Failure: TypeError: greet() got an unexpected keyword argument 'zzz'
Lambda  {"arguments": {"zzz": 1}}                   statusCode 500, "greet() got an unexpected keyword argument 'zzz'"
HTTP    POST {"arguments": {"zzz": 1}}              500, same text
MCP     tools/call greet {"zzz": 1}                 isError: true, "Unexpected keyword argument"
```

## R-6 · Cold versus warm (pitfalls.md §23: "run every end-to-end assertion twice")

The 166-row matrix ran each row in a project whose cache was already built, so it measured warm calls.
`cold.py` repeats every CLI-side command with `.functualize/cache.json` deleted before each call, one
project per row. `cold_compare.py` → `cold-vs-warm.txt` compares the result with the warm matrix:
166 rows × 13 fields, 25 differences, across 8 rows. Re-running one project cold, then warm, with
the cache as the only variable (`cold-warm-same-project.txt`), confirms the two real ones.

- **F-33 · A missing-provider job explains itself only on a warm boot.** This covers C085, C087, E138
  and H166.

  ```text
  $ func c085   # cold   Error: TypeError: c085() missing 1 required positional argument: 'p'              exit 1
  $ func c085   # warm     1. No provider for Widget (parameter 'p' of job 'c085', …)                         exit 1
  $ func e138   # cold   functualize._primitives.di.MissingProviderError: No provider for Widget (job 'w', …)  (traceback)
  $ func e138   # warm     1. No provider for Widget (parameter 'p' of job 'e138', …)
  ```

  ADR-018 promised that the guarantee holding "on *both* paths is that invoking the job explains
  itself". It holds only on the warm path today. This weighs on DC-1: option B must make that
  guarantee true on the cold path too, not only keep it.
- **F-34 · An `Enum` default is published only on a warm boot.** A046, `p: Color = Color.RED`:
  `info schema` and MCP publish `{"type": "string", "enum": [...]}` cold and add `"default": "red"`
  warm.

The rest is noise:

- the order of a provider list (E139, H165);
- the module name inside one `repr` (D105, `<d105.Widget …>` against
  `<_functualize_sync_.d105_….Widget …>`).

## R-7 · Outcome tables have no "bad argument" outcome

`_types/http_status.py:54-74` maps `RunStatus` to HTTP: `REFUSED` → 412, `FAILURE` → 500, and so on.
`_types/exit_codes.py:41-42` has `USAGE = 2` and `REFUSED = 3`. A pydantic `ValidationError` at the
engine door is a CLI exit 2 (through the click path) but a `Failure` with HTTP 500 on the wire (D107,
measured). The page requires a bad argument to be a refusal distinct from a job failure on every
surface, and leaves the HTTP code provisional (§7). Plan fixes the code against this table. The table
is "one outcome module" under ADR-020 §4, so the code belongs there and not in an adapter.

## R-8 · Further schema consumers

`func mcp schema --format markdown|openai|typescript` (`docs/guides/mcp.md:132-139`) render from the
same JSON schema through `functualize_mcp/_schema_export.py`, which keeps its own `_TS_TYPE_MAP`
(`_schema_export.py:28`). These are schema consumers too, so `spec.md` B-21 includes them.

## R-9 · Prior decisions this feature supersedes, said aloud

- **`optional-parameter-cli-flag/spec.md`** (commit `38ee5934`). It said: *"No discovery finding is
  added for still-unsupported annotations"*, and that the change *"does not introduce unmarked list
  parameters"*. Both are superseded by the approved page (D5 and the C-extended direction).
  SD/17137691's candidate C ("make any dropped parameter loud"), recorded there as an unapproved
  follow-up, is what D5 now approves.
- **ADR-010** (*one job-schema renderer, in core*). The intent is kept and strengthened: one renderer,
  and now one input to it. The mechanism it names (`TYPE_MAP`, `job_schema.py:53`) is replaced by
  schema derived from the contract (D4). ADR-010 is amended, not contradicted.
- **ADR-018.** See R-1, which is open as DC-1.
- **`docs/guides/job-config.md:47-69`** promises a registration-time `TypeError` that does not run
  under `func` (F-29). The behaviour is made true rather than the doc made false.

## Retrieval record

- **zvec-grep:** index built for this worktree (968 files, 1 m 21 s). Queries, with their top hits, are
  in `zg-queries.txt`: repeatable list flags; caller overrides injected capability; unsupported type
  refused at discovery; type annotation string in the cache; MCP tool function generated from the
  schema; SmartBar parsing; wire coercion; DI provider for a builtin type. The hits that changed this
  file were `_engine/validation.py:135-177` (R-2, R-3) and `docs/guides/job-config.md:25-71` (F-29).
- **ADRs read in full:** 004, 010, 018, 020, 033 (all relevant to a decision here); 016 §270 (signature
  parameters are invocation inputs).
- **pitfalls.md sections applied:** §4 (PEP 563, R-4), §5 (bump `CACHE_VERSION` when the descriptor
  shape changes), §6 and §19 (one registry plus a parity test), §23 (cold and warm, R-6), §25 (a new
  error below `engine.run()` needs a `prelude_refusal` arm).
- **Counts and negatives:** every number in `spec.md` comes from the matrix kit or from a command named
  next to it.

## Plan-phase findings (architecture gate and blast radius, 2026-11-22)

These are recorded here because they reshaped the approach (`.claude/commands/agentic-plan.md`
step 7). Each one's evidence is in `matrix/evidence/`.

- **P-1 · F-07 located** (`f07-trace.txt`, `f07-click.txt`). Click 8.4.1 ignores `required=True` when
  `default=None` is passed explicitly, and `_option_from_marker` always passes it
  (`click_params.py:693`).
- **P-2 · F-34 located.** On a cold boot the descriptor holds the `Enum` member, which
  `job_schema._is_json_native` drops. On a warm boot `_serialize_default` (`descriptors.py:650`) has
  already encoded it as `"red"`.
- **P-3 · H3 measured** (`binder-cost.txt`).

  | | measured |
  | --- | --- |
  | first `TypeAdapter` inside a real `func` process, after boot | 0.3–0.6 ms |
  | seven more adapters | 1.2–2.3 ms |
  | binding 15 arguments per call | ~18 µs median |
  | a whole invocation | ~1.7 s |

  In a fresh interpreter that has built no pydantic schema, the first adapter costs 450–1,100 ms, and
  boot already pays that today.
- **P-4 · A seventh schema renderer.** `functualize-ai` `ToolScope._fields_to_schema`
  (`_tool_scope.py:408`) publishes job parameters to LLM tool calls through its own type map. This is
  spec revision S-1.
- **P-5 · `PRE_EXECUTE` hooks may modify kwargs after any binding** (`data-flow.md` §2). This is spec
  revision S-2.
- **P-6 · The codemap contradicts the code.** `data-flow.md` §2 says "Resolution priority … DI >
  RunContext > Config > Default". `executor.py:1432-1434` lets the caller win (F-20). It is corrected
  in task 11.1.
- **P-7 · More derivation sites than the page's census listed.**
  - `app/utils.py::coerce_kwargs` and `_resolve_type`: a public export with **no production caller**
    (serena `find_referencing_symbols`: tests only).
  - `_cli/dispatch.walk_group_path` (`:715`): the pre-boot group-flag walk decides arity by
    `type_annotation == "bool"`, and is the likely seat of F-10's group-list collapse.
  - `_cli/tui/sync.build_command_line`: the bar emitter (`data-flow.md` §7).
  - `create_callback_click_command` (`click_params.py:1571`): plugin command callbacks share the live
    builder.
- **P-8 · `JobExecutionEngine` measures 2,747 lines** (`executor.py:213-2959`, `ast` walk). That is
  already past the constitution's ~500-LOC cap, and is surviving smell SS-4 ("not grown").
