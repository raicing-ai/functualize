# One parameter contract behind every surface

## Problem and user outcome

A job parameter is described by up to eleven surfaces:

- `func <job>` and its `--help`;
- bash and zsh completion;
- the TUI bar and its SmartBar;
- `func builtin info schema`;
- the MCP tool schema and the MCP call;
- HTTP;
- Lambda.

Today each surface decides on its own what a parameter is, how it is spelled and how a supplied value
becomes the job's argument. On `master` @ `da912d76`, 158 of 166 measured declarations behave wrongly
on at least one surface. Examples:

- an unmarked `list[str]` is unreachable from the CLI while completion offers it;
- an HTTP caller can replace a job's `Shell` with a string;
- one `str` provider breaks every `str` parameter;
- one legal signature stops the MCP server.

**Outcome.** For every declaration, every surface gives the same answer, decided once from the
declaration:

- whether the parameter is an input;
- how it is spelled;
- what type the job receives;
- what happens when it is wrong or missing.

The answer is written down as data that the parity test, the docs table and the refusal messages all
read.

## Alignment

- **Shape authority:** *Shape Intent — Collections Earn Repeatable Flags (list[T], tuple[T, ...], and
  one verdict behind every surface)*, `SD/28901379` **version 4**, `Authority: Approved` (read live
  2026-11-21). The surfaces in and out of scope are named in that page's own words, in its §5 and §8.
  Its decisions are adopted as approved:
  - **D1:** an absent optional list → `None`.
  - **D2:** the job receives the annotated container.
  - **D3:** a required `list[str]` is a required repeatable option.
  - **D4:** the schema is derived from the contract.
  - **D5 = B′:** an explicit `INVOCATION_ONLY` verdict for JSON-shaped values.
  - **D6 = Arch-2:** one contract, one binder.
  - **D7:** superseded derivers are deleted in this change.
  - **D8:** the TUI uses the CLI grammar.
- **Depends on:** `SD/17137691` (v4, Approved). `X | None` is CLI-eligible exactly when `X` is, and
  absence means `None`.
- **Supersedes, said aloud** (`research.md` R-9):
  - `optional-parameter-cli-flag/spec.md`, which added "no discovery finding" and "no unmarked list
    parameters";
  - ADR-010's `TYPE_MAP` mechanism (its intent is kept);
  - the caller-may-supply-a-DI-parameter rule in `_engine/validation.py:43-47` (R-2).
- **Prior art reconciled:** ADR-018, as **DC-1** below, decided **B** (ADR-018's model) by the
  member on 2026-11-22.

## Users and scope

| actor | wants |
| --- | --- |
| job author | to declare a parameter in plain Python (`targets: list[str]`, `when: datetime \| None = None`) and have every surface treat it the same; an explicit refusal, naming the parameter and the fix, for anything unsupported |
| CLI user | `--help`, completion and the parser to agree; repeatable flags for lists; one-line usage errors, never tracebacks |
| TUI user | the bar to parse exactly as `func <job> …` does, and the SmartBar to offer exactly what parses |
| agent over MCP | a schema whose types are the real ones, a server that starts, calls that accept what the schema says, and the reason when a run fails |
| HTTP / Lambda service | values coerced to the declared type, defaults applied, wrong or missing or injected keys refused with a 4xx and the reason |
| plugin author | to register a DI provider without changing how any other parameter is classified |
| CI | a parity test that fails, naming the row and the surface, when any surface drifts |

**In scope:** signature parameters of `@job` functions and `@job` class methods; config-model fields
(their flag, their refusal, their binding); `GroupOptions` fields (repeatable lists, schema parity).
The surfaces are the eleven above, plus `func mcp schema --format markdown|openai|typescript` and,
*(revised in Plan, S-1)*, the `functualize-ai` tool scope. DI
*classification* is in scope, as is the deletion of the superseded derivers (D7).

**Out of scope** (page §8):

- workflow `Step` / `AgentStep` inputs;
- Textual rendering and key handling (only the TUI's parse-and-execute door is in);
- the AWS Lambda runtime;
- the config ladder's precedence, which is measured correct (`rungs.txt`) and unchanged;
- DI provider registration and lifetimes;
- Windows (`NOT_MEASURED`, page §3.3);
- the copied-cache observation (page §3.2).

## Required behaviour

Each behaviour cites the page findings it closes. "Every surface" means the eleven above plus the
`functualize-ai` tool scope (S-1).

### A. Classification — one verdict per parameter

- **B-1.** Every parameter receives exactly one verdict from the page's vocabulary (§5.1):
  `ACCEPTED_FLAG`, `ACCEPTED_POSITIONAL`, `INJECTED`, `CONFIG_FIELD`, `INVOCATION_ONLY`,
  `REJECTED_DISCOVERY`. `REJECTED_USAGE` describes a call, not a parameter. The verdict is decided
  once, at discovery, from the declaration, and every surface reads that one decision.
- **B-2** *(revised in Execute, 2026-11-22)*. A parameter's **kind** depends only on its
  declaration: annotation, markers, default, signature kind. Kind means caller-supplied (flag or
  positional), `INVOCATION_ONLY`, `CONFIG_FIELD`, `INJECTED`, or refused for its shape. No DI
  registry is read to decide it (F-21). Registering a provider, `str` included, therefore changes the
  verdict of **no other** parameter: `p: str` and `Annotated[str, Option()]` stay caller inputs
  (UC-6).
  - **The one availability rule.** A parameter whose kind is `INJECTED` through `Provide("q")` or
    as an unmarked class that is not a value type has one dependency of its own: its declared type
    together with its qualifier (`None` for an unmarked class).
    - If a provider is registered for **exactly** that pair, the verdict is `INJECTED`.
    - Otherwise it is `REJECTED_DISCOVERY` (B-8, B-9, DC-1).
    - "Exactly" means the pair that resolution would use. A type registered only under other
      qualifiers does not satisfy an unqualified dependency, because resolving it is ambiguous
      (F-21).
  - **Where and when it applies.** This rule is the only registry input to any verdict. It is
    applied once per boot, after plugins have registered their providers, and identically on cold
    and warm boots (B-7). It is never cached, because the cache holds only the declaration-derived
    contract.
  - **What it does not cover.** The 15 capability types and `FromJob(...)` are always `INJECTED`.
    Their values come from the engine and from another job, not from a registered provider.
  - The page's source: §5.1 "`INJECTED` … an unmarked class that is not a value type (a provider
    must exist, otherwise `REJECTED_DISCOVERY`)", and the reject list "an unmarked class with no
    registered provider (C085, C087, E138, H166)". Both sit beside "Never from what the DI registry
    happens to hold (F-21)", which §7 scopes as "F-21: kind is decided from the declaration only".
- **B-3.** These types are caller-supplied scalars: `str`, `int`, `float`, `bool`, `Path`, `UUID`,
  `date`, `datetime`, `time`, `timedelta`, `Decimal`, and any `Enum`. Each is also caller-supplied
  when wrapped in `Optional[T]` or `T | None`.
- **B-4.** `list[T]` and `tuple[T, ...]` of a supported scalar `T`, in any optional form, are
  caller-supplied **repeatable** inputs (C-extended; F-01).
- **B-5.** `INVOCATION_ONLY` (D5 = B′) applies to `dict[str, T]`, `set[T]`, and fixed `tuple[A, B, …]`
  of supported scalars. These are supplied over MCP, HTTP and Lambda only.
- **B-6.** The verdict, and every behaviour below, is identical whether or not the job module uses
  `from __future__ import annotations`. Under PEP 563 the documented-invalid `FromJob[...]` subscript
  form is refused exactly as it is without it (F-32, `research.md` R-4).
- **B-7.** The verdict, and every behaviour below, is identical on a cold boot (no cache) and a warm
  boot (from cache) (`pitfalls.md` §23). Today two behaviours differ: a missing-provider job explains
  itself only on a warm boot (F-33), and an `Enum` default is published only on a warm boot (F-34)
  (`research.md` R-6).
- **B-8.** `REJECTED_DISCOVERY` applies to the page's reject list (§5.1):
  - `object`;
  - unions of two non-`None` types;
  - `list[list[…]]` and `list[Secret[str]]`;
  - `Secret[str]` as a signature parameter;
  - positional-only parameters;
  - two CLI markers on one parameter;
  - a CLI marker on a type nothing converts;
  - an unmarked class, or an `Annotated[T, Provide("q")]`, with no provider registered for its own
    type and qualifier (B-2's availability rule; page rows C085, C087, E138, H166);
  - config fields of an unsupported type (`dict`, nested model; F-29, the refusal
    `docs/guides/job-config.md:47` already documents).
- **B-9 (DC-1).** A `REJECTED_DISCOVERY` verdict is reported with a warning naming the file, the job,
  the parameter declaration and the remedy, on every boot path (cold and warm, directory mode and
  library mode). What happens to the job itself is DC-1.
  - **One report per parameter** *(ruled in Execute, wave 2, 2026-11-22)*. A parameter that carries a
    contract is reported only through its contract: `error_type` `"UnsupportedParameter"`, on cold
    **and** warm boots. The warm half is F-33's fix. ADR-018's `"UnsatisfiableParameter"` is not
    emitted for it as well.
  - **Why.**
    - B-2 makes availability "the only registry input to any verdict".
    - 5.1 reads that decision at the door, and "there is no second availability check".
    - D105 refuses `Annotated[Widget, Option()]`. So ADR-018's old remedy, "annotate the parameter
      with Arg()/Option()", is now itself refused, and cannot be the error message.
  - **What still reports `"UnsatisfiableParameter"`** is exactly a DI error that no contract covers
    (`contract_covers`, `_app/boot.py`):
    1. an error on a job that has no retained descriptor (`job_registry.get_descriptors()`);
    2. an error on a parameter whose descriptor carries no contract: the classifier-crash fallback
       (`_discovery/providers.py:224-228`, logged; the parameter keeps today's fields);
    3. a factory-resolution error. It names no parameter, and its type is no contract's
       `provider_type`: a registered factory's own dependency is missing.

    Its remedy reads "Register a provider for the type or correct the declaration." A function
    registered with `register_dynamic_job` is **not** a survivor: it builds its descriptor through
    the same extraction and retains it (`_app/impl.py:820`, `:856`). After task 3.2, a contract
    in `JobDescriptor.omitted_contracts` covers its parameter in the same way.

### B. Command line

- **B-10.** A required `list[T]` is a required repeatable option (`--targets a --targets b`, D3). When
  it is absent the call is refused: `Error: Missing option '--targets'.`, exit 2.
  `Annotated[list[T], Arg()]` stays a variadic positional.
- **B-11.** The job receives the container it annotated (D2). A `list[T]` arrives as a `list`, a
  `tuple[T, ...]` as a `tuple`, each element converted to `T`. This includes repeatable group-option
  fields, which today keep only the last value (F-10).
- **B-12.** An absent optional list arrives as the declared default. With `= None` that is `None`
  (D1; SD/17137691).
- **B-13.** Every admitted scalar parses and every default survives absence:
  - `timedelta` accepts an ISO 8601 duration (`PT1H30M`) and refuses anything else with a usage error
    (F-05; spelling provisional per page §7);
  - a `UUID` or `timedelta` default is delivered unchanged when the flag is absent (F-04).
- **B-14.** Requiredness is enforced. A required `Annotated[T, Option()]` absent from the call is a
  usage error, exit 2 (F-07). A required `Annotated[str, Stdin()]` with no flag and a stream that
  carries nothing is a usage error, exit 2; that is ADR-033's "nothing there", with no default to fall
  back to (F-09). A `bool` with no default is a flag that defaults to `False` and is not required
  (F-08).
- **B-15.** A parameter the CLI cannot spell (`INVOCATION_ONLY`) has no flag and no positional. When
  it is required, calling the job from the CLI or TUI is a usage error naming the surfaces that accept
  it, exit 2 (D5 = B′).
- **B-16.** No CLI call ends in a Python traceback or in `Error: <Name>Error: …`. A refusal raised
  below `engine.run()` renders like its neighbours (`pitfalls.md` §25).

### C. Completion and SmartBar

- **B-17.** Bash completion, zsh completion and the SmartBar offer exactly the spellings the command
  accepts: long, short and `--no-` forms, with hidden options and injected parameters left out. That
  holds for the job's own flags and for group-level flags mid-path (F-06, F-27).

### D. The inline TUI

- **B-18.** The TUI bar parses with the CLI's grammar (D8). Given the same tokens, the TUI either
  produces the same arguments with the same types, or refuses with the same message as
  `func <job> <tokens>`. That covers repeated flags, stray tokens, positionals and short flags (F-26).

### E. Published schema

- **B-19.** `func builtin info schema` and the MCP tool `inputSchema` are byte-identical for every
  job, group options included (F-13).
- **B-20.** Each property's JSON type comes from the parameter's declared shape, never from a fallback
  to `"string"` (D4; F-02). For example:
  - an array for every list and tuple;
  - `integer`, `number` and `boolean` for `Optional[int|float|bool]`;
  - `format: date-time` for an optional `datetime`;
  - an object for `INVOCATION_ONLY` mappings.
- **B-21** *(revised in Plan, S-1)*. The `markdown`, `openai` and `typescript` exports of
  `func mcp schema` derive from that same schema (`research.md` R-8). So does the AI plugin's tool
  scope: `functualize-ai` `ToolScope.to_tool_defs` publishes job parameters to LLM tool calls, and
  today renders them through its own type map (`_tool_scope.py:408`). Its calls reach jobs through
  the engine door like every other `invoke`.
- **B-22.** `required` equals CLI requiredness (F-08). `INJECTED` parameters never appear in any
  schema, `Provide(...)` and provider-backed classes included (F-14).

### F. Binding — one door for every surface

- **B-23** *(revised in Plan, S-2)*. Every surface hands its raw values to one binding step before
  the job runs: the CLI's parsed values, the TUI's, MCP's arguments, the AI tool scope's, and the
  HTTP and Lambda envelope's `arguments` and `group_option_values`. Binding is the only place a
  **value supplied by a surface** becomes the job's argument. In-process `PRE_EXECUTE` hooks keep
  their documented ability to modify kwargs after binding (`contributor/architecture/codemaps/data-flow.md`
  §2). That is a plugin's decision, not a caller's.
- **B-24.** Binding converts every supplied value to the declared type. A `UUID` arrives as `UUID`,
  `Path` as `Path`, `Enum` as the member, `Secret[str]` (on a config field) as `Secret`, `list` as
  `list`, `tuple` as `tuple` (F-22). The same input produces the same job argument on every surface.
- **B-25.** Binding applies the declared default to every absent parameter, `Field(...)`-constrained
  parameters included (F-23).
- **B-26.** Binding refuses, before the job is called, a call that:
  - is missing a required argument (F-25);
  - supplies an unknown key (`research.md` R-5);
  - supplies a value for an `INJECTED` parameter (F-20; B-30);
  - supplies a value that does not convert.

  Each refusal names the argument and the reason. The surface renders it:
  - CLI and TUI: one-line usage error, exit 2;
  - HTTP and Lambda: a 4xx status with the reason in the body, never 500;
  - MCP: `isError: true` with the reason.
- **B-27.** A run that starts and then fails reports its reason on every surface. MCP included
  (`isError: true` and the error text; F-31).
- **B-28.** Lambda accepts the shared envelope (`{"arguments": …}`) on both handlers. Its docstrings
  describe that envelope; the `kwargs` spelling is not accepted (F-28).
- **B-29.** DI fills only `INJECTED` parameters. A caller-supplied key never reaches an `INJECTED`
  parameter on any surface (F-20).
- **B-30.** This reverses the documented rule at `_engine/validation.py:43-47` ("a caller has always
  been able to supply one explicitly"). The reversal holds for every `RunSurface`, in-process doors
  included. Measured in-process uses that pass a value for an injected parameter: 0 (`research.md`
  R-2).

### G. MCP registration

- **B-31.** `func mcp serve` registers every job whose verdicts permit it, from the published schema,
  and starts for every legal Python signature. One job's signature never prevents the server from
  starting (F-12, F-24).

### H. Boot consistency

- **B-32.** Project plugins load with the same import environment on every command, `.functualize/lib`
  included, so a provider a plugin registers exists for every command or for none (F-30).

### I. One place, and nothing beside it (D7)

- **B-33.** No surface reaches any parameter classification, type mapping, flag derivation or binding
  other than the contract's. The superseded derivers and the dead code the page lists (§3.4, D7) no
  longer exist in production code.

## Acceptance checks

Each gate is a command. It **was run at authoring time on `da912d76`**, and its result there is
recorded so the gate is known to fail before the change. The kit is on this branch at
`.spec/features/parameter-contract/matrix/`; each command runs from there with
`F="$(command -v func)"`, and the recorded results are in its `evidence/` directory.
AC-11 runs the same kit with `func` wrapped in `coverage run --parallel-mode` (the wrapper is described
in the kit's `README.md`).

| id | gate | must show after the change | on `da912d76` (authoring-time run) |
| --- | --- | --- | --- |
| AC-1 | `python3 gen.py "$F" ../proj out.json && python3 check.py` | `166 rows; 0 fail the proposed shape` | `166 rows; 73 fail` (`check.txt`) |
| AC-2 | `python3 surfaces.py "$F" ../proj out.json surfaces.json && python3 surf_check.py` | every W-predicate `0 rows` | W-inject 35, W-type 49, W-default 14, W-crash 50, W-accept 92, W-fat 158, W-bar 65, W-collapse 34 (`surf_check.txt`) |
| AC-3 | `python3 tui_extra.py` | `0 rows` | `91 rows` (`tui-extra.txt`) |
| AC-4 | `python3 rungs.py "$F" ../rung rungs.json` | identical to `rungs.txt`, except F150/F151, which are refused per B-8 | `rungs.txt` |
| AC-5 | `./probes.sh "$F" ../proj` | no `Traceback`; `func mcp serve` starts with G156 present; `g160g --p a --p b run` → `['a', 'b']` | 3 tracebacks (timedelta); server `SyntaxError`; `['b']` (`probes.txt`) |
| AC-6 | `PC_PEP563=1 python3 gen.py "$F" ../proj563 out563.json && python3 pycompare.py out563.json` | 0 differences, provider-list ordering excepted | CLI: 1 row differs, E142; surfaces: 14 E142 cells, the rest ordering (`pep563-cli.txt`, `pep563-surfaces.txt`) |
| AC-7 | `python3 cold.py "$F" ../proj_cold out_cold.json && python3 cold_compare.py` | 0 cold/warm differences, apart from provider-list order and the module name inside a `repr` | 25 differences in 8 rows; real: C085, C087, E138, H166 (F-33) and A046 (F-34) (`cold-vs-warm.txt`, `cold-warm-same-project.txt`) |
| AC-8 | the `str`-provider experiment (`str-provider.txt`) | every `str` job runs as without the provider | 4 of 5 jobs `AmbiguousProviderError` |
| AC-9 | unknown-key probe (`unknown-keys.txt`) | CLI, TUI, HTTP, Lambda and MCP all refuse naming `zzz`; HTTP and Lambda 4xx | TUI, HTTP and Lambda: raw `TypeError`, 500 |
| AC-10 | `tests/surfaces/test_parameter_surface_parity.py` (name provisional, page §5.8), in the repository's suite | green on all three CI Python versions, from a declaration table that is also the docs table's source | does not exist |
| AC-11 | the whole matrix under `coverage run` (`cov/rc`, `cov/func`), then `cov_census.py` | 0 executed statements in every function the plan lists for deletion (B-33) | e.g. `_resolve_type_string` 22/25, `parse_cli_args_to_kwargs` 33/36, `_build_tool_function` 28/29 (`cov_census.txt`) |
| AC-12 | `rg -n` for each deleted symbol over `src/` and `plugins/*/*/src`, and the dead-code delta (`uv run python .github/scripts/dead_code_delta.py origin/master HEAD`) | no hit, and no `NEW_DEAD` the plan does not account for | the symbols are present (`census_static.txt`) |
| AC-13 | the repository's five checks (`ruff check`, `ruff format --check`, `mypy src/`, `lint-imports`, `pytest`) | all pass; `lint-imports` with zero contract violations | pass on `da912d76` (repository state) |

AC-10 is the durable gate, and AC-1 to AC-9 are its prototype. The plan decides which kit predicates
become rows of the parity test and which stay external measurements.

## Evidence and constraints

- **Measurement base:** the page's 166-row matrix on `da912d76`, CPython 3.13.15, with 3.11.16 and
  3.12.14 compared (no behavioural difference). Every number above names its file in the matrix kit
  attached to the page.
- **The constitution forbids `DeprecationWarning` and backward-compat shims** ("pre-release, no users
  to deprecate toward"). The visible changes land without a compatibility path and are recorded in
  `CHANGELOG.md`:
  - D1: `()` → `None`;
  - D2: tuple → list for marked lists;
  - D5 refusals;
  - D8 TUI grammar;
  - coerced wire values;
  - refused injected keys.
- **The descriptor cache's shape changes**, so `CACHE_VERSION` is bumped (`pitfalls.md` §5).
- **Kernel layers must not import `click`** (constitution, *Forbidden Patterns*). The contract carries
  spellings as data.
- **Every acceptance run is executed twice, cold and warm** (`pitfalls.md` §23), and **compiled both
  ways for PEP 563** (§4).

## DC-1 · What happens to a job whose parameter is refused at discovery — decided: B

**The decision.** When discovery refuses a parameter, for example `filters: str | int`, `p: object`, or an unmarked
class with no registered provider, does the *job* disappear, or stay listed and
refuse when called? Either way, users see the warning naming the parameter.

**Effect on the plan.** This decides one row of the parity test and the refusal wording. It amends
one Binding item of the page (§7: *"refusal at discovery naming the parameter and the remedy"*,
§5.7: *"calling the job → `Error: No such command '<name>'.`"*), so the page's §7 and §5.7 are revised
before Plan, as the page itself requires.

**Evidence.** ADR-018 (accepted), quoted in `research.md` R-1: unregistering was implemented and
reverted, because cold and warm boots disagreed and because *"'no such command' is a worse answer
than a message naming the parameter."* Measured today, ADR-018's own guarantee holds only warm: cold,
the same missing-provider job fails with a `TypeError` or a traceback (F-33, `research.md` R-6). B
therefore includes making it hold cold.

**Options.**

- **A — as the page is worded: not registered.** `func report` → `Error: No such command 'report'.`
  For shape refusals, cold and warm can agree, because the verdict is cached. For a missing provider
  they cannot, because warm boot does not validate DI. So A splits one verdict into two behaviours, and
  re-opens the case ADR-018 closed.
- **B — ADR-018's model (recommended).** Found at discovery and reported at boot (warning, `builtin
  info` discovery failures), and the job stays registered. Every call on every surface refuses before
  running, with the message naming the job, the parameter and the remedy. No schema publishes inputs
  for it. Cold and warm agree for every class, and the message is the better one.

**Recommendation: B.** It keeps an accepted ADR, gives one behaviour for every reject class, and gives
the better message.

```console
$ func report            # B   (def report(filters: str | int))
Error: job 'report' cannot run — parameter 'filters: str | int' is a union of two types.
       Declare one type, or Annotated[..., Option()] with a convertible type.                      # exit 2
$ func report            # A
Error: No such command 'report'.                                                                   # exit 2
```

**What proceeds regardless:** every behaviour above not marked *(DC-1)*.

**Decision record.** **B** — the job is reported, stays registered, publishes no inputs, and refuses
on every call, naming the job, the parameter and the remedy. Decided by the member in comment
`01a2012e-723d-7822-9fc6-b4dcc3ab1ec6`, 2026-11-22T02:55:50Z, verbatim: *"spec confirmed, DC-1 = B"*.
Page `SD/28901379` v5 (2026-11-22 02:57:48Z) carries it as its §5.7 v5 amendment. B-9's open half
therefore reads: the job stays registered; `func builtin info` lists it with its reason; every surface
refuses a call to it with that reason (CLI and TUI exit 2, HTTP and Lambda 400, MCP `isError`) and
publishes no inputs for it; and this holds on cold and warm boots alike (F-33).

## Confirmation gate

**Confirmed** by the member, with DC-1 = B, in comment `01a2012e-723d-7822-9fc6-b4dcc3ab1ec6` at
2026-11-22T02:55:50Z (`.claude/commands/agentic-specify.md` step 6).

**Revised by Plan's architecture gate,** in two places marked *(revised in Plan)*: S-1 (B-21) and S-2
(B-23). The revisions are re-confirmed with the task list before Execute (`plan.md` § *Spec
revisions*).

**Revised in Execute (2026-11-22),** in one place marked *(revised in Execute)*: B-2, with B-8's
provider item worded to match. Wave 1 found that the old B-2 ("it never depends on what the DI
registry holds") contradicted B-8 ("an unmarked class with no registered provider" is refused) and
the page's §5.1 `INJECTED` row. The revision resolves that contradiction in the page's own terms: kind
comes from the declaration, plus one availability rule. It does not overrule the page.
The revision is reported to the member with the corrected task list (`plan.md` § *Spec revisions*).
