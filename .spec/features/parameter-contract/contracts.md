# External contracts — one parameter contract behind every surface

Spellings marked *(provisional)* are fixed by Plan, as page `SD/28901379` §7 allows. Everything else
here is binding on the implementation. "PROPOSED" outputs describe behaviour after the change.

## 1. Job declaration → verdict

```python
from pathlib import Path
from typing import Annotated, Optional
from functualize.job import job, Arg, Option, Stdin, Shell, FromJob

@job
def deploy(
    service: str,                                   # ACCEPTED_POSITIONAL
    targets: list[str],                             # ACCEPTED_FLAG, required, repeatable → list[str]
    paths: list[Path] | None = None,                # ACCEPTED_FLAG, repeatable; absent → None
    tags: Annotated[tuple[str, ...], Option("-t")] = (),   # ACCEPTED_FLAG, repeatable → tuple[str, ...]
    retries: int | None = None,                     # ACCEPTED_FLAG
    patch: dict[str, str] | None = None,            # INVOCATION_ONLY (MCP / HTTP / Lambda only)
    sh: Shell | None = None,                        # INJECTED (no surface accepts a value; row E119)
    dry_run: bool = False,                          # ACCEPTED_FLAG --dry-run/--no-dry-run
) -> None: ...
```

| declaration | verdict | job receives |
| --- | --- | --- |
| `T` ∈ {`str`, `int`, `float`, `bool`, `Path`, `UUID`, `date`, `datetime`, `time`, `timedelta`, `Decimal`, `Enum`}, no default | `ACCEPTED_POSITIONAL` (`bool`: `ACCEPTED_FLAG`, default `False`) | `T` |
| the same with a default, `Optional[T]`, or `T \| None` | `ACCEPTED_FLAG` | `T`, or the declared default |
| `list[T]` / `tuple[T, ...]` of the above, any optional form | `ACCEPTED_FLAG`, repeatable | `list[T]` / `tuple[T, ...]`, or the declared default |
| `Annotated[list[T], Arg()]` | `ACCEPTED_POSITIONAL`, variadic | `list[T]` |
| `Annotated[T, Option(...)]`, `Annotated[T, Arg()]`, `Annotated[T, Stdin()]` | as marked | `T` |
| `dict[str, T]`, `set[T]`, fixed `tuple[A, B, …]` of the scalars above | `INVOCATION_ONLY` | `dict` / `set` / `tuple` |
| one of the 15 capability types (bare or `\| None`), `Annotated[T, Provide("q")]`, `FromJob(...)`, an unmarked class with a registered provider | `INJECTED` | the engine's value, never the caller's |
| a field of a `BaseModel` parameter, of a supported type | `CONFIG_FIELD` | resolved CLI → env → file → `.env` → default |
| anything on the reject list (`spec.md` B-8) | `REJECTED_DISCOVERY` | — (see §8 and DC-1) |

The same table holds under `from __future__ import annotations`, and on cold and warm boots.

## 2. Command line

```console
$ func deploy --help                                                        # PROPOSED
Usage: func deploy [OPTIONS] SERVICE
Options:
  --targets TEXT          [required; repeatable]      # suffix wording (provisional)
  --paths PATH            [repeatable]
  -t, --tags TEXT         [repeatable]
  --retries INTEGER
  --dry-run / --no-dry-run
  --help                  Show this message and exit.
```

| invocation | outcome |
| --- | --- |
| `func deploy api --targets eu --targets us` | `targets=['eu', 'us']`, `paths=None`, `tags=()`; exit 0 |
| `func deploy api --targets eu -t a --tags b` | `tags=('a', 'b')`; exit 0 |
| `func deploy api` | `Error: Missing option '--targets'.`; exit 2 |
| `func deploy api --targets eu extra` | `Error: Got unexpected extra argument (extra)`; exit 2 |
| `func deploy api --targets eu --sh x` | `Error: No such option '--sh'.`; exit 2 |
| `func when --after PT1H` (`after: timedelta = timedelta(0)`) | `after=timedelta(seconds=3600)`; exit 0 |
| `func when --after soon` | `Error: Invalid value for '--after': 'soon' is not an ISO 8601 duration (e.g. PT1H30M).`; exit 2 — wording *(provisional)* |
| `func apply` (`patch: dict[str, str]`, required) | `Error: parameter 'patch' can only be supplied over MCP, HTTP or Lambda.`; exit 2 — wording *(provisional)* |

No command ends in a Python traceback or in `Error: <Name>Error: …`. Exit codes are the existing
table's (`_types/exit_codes.py`): usage refusals are 2.

## 3. Completion and SmartBar

The completion script format is unchanged; only its contents change. Each job's entry lists exactly
the accepted spellings:

```text
_func_tree[':deploy']='--targets --paths -t --tags --retries --dry-run --no-dry-run'     # PROPOSED
```

No hidden option, no injected parameter and no `INVOCATION_ONLY` parameter appears.

The SmartBar's candidates for `"deploy api --"` are the same set. Group-level flags are offered
mid-path (`"<group> --"`) with the same rule.

## 4. TUI bar

The bar text is parsed with the grammar of `func <job> …`:

```text
› deploy api --targets eu --targets us   → targets=['eu', 'us']                       # PROPOSED
› deploy api --targets eu extra          → Error: Got unexpected extra argument (extra)
› deploy --service api --targets eu      → Error: No such option '--service'.
› e136 --p x   (p: Vault)                → Error: No such option '--p'.
```

## 5. Published schema — `func builtin info schema` ≡ MCP `inputSchema`

Byte-identical for every job, group options included. Property types come from the declared shape:

```json
{
  "type": "object",
  "properties": {
    "service": {"type": "string"},
    "targets": {"type": "array", "items": {"type": "string"}},
    "paths":   {"anyOf": [{"type": "array", "items": {"type": "string"}}, {"type": "null"}], "default": null},
    "tags":    {"type": "array", "items": {"type": "string"}, "default": []},
    "retries": {"anyOf": [{"type": "integer"}, {"type": "null"}], "default": null},
    "patch":   {"anyOf": [{"type": "object", "additionalProperties": {"type": "string"}}, {"type": "null"}], "default": null},
    "dry_run": {"type": "boolean", "default": false}
  },
  "required": ["service", "targets"]
}
```

- The optional spelling, `anyOf` with `null` or a bare type outside `required`, is *(provisional)*.
- `sh` (`INJECTED`) is absent.
- Formats: `datetime` → `format: date-time`, `date` → `format: date`, `UUID` → `format: uuid`,
  `timedelta` → `format: duration` *(provisional)*.
- An `Enum` publishes `enum: [values]`.
- `func mcp schema --format markdown|openai|typescript` render from this document.
- The `functualize-ai` tool scope (`ToolScope.to_tool_defs`) publishes this document as each tool's
  parameters.

## 6. MCP

- **Registration.** `func mcp serve` registers one tool per job from the §5 schema and starts for
  every legal Python signature.
- **Call accepted:** `isError: false`, structured content as today, with the job's arguments
  converted per §1.
- **Call refused** (missing required, unknown key, value for an injected parameter, value that does
  not convert): `isError: true`, and the text names the argument and the reason.
- **Run failed after starting:** `isError: true`, and the text carries the error. Today it is
  `isError: false` with no reason (F-31).

## 7. HTTP and Lambda

**The request is unchanged** (`_types/run_request.py:291-359`):

```json
{"arguments": {"service": "api", "targets": ["eu"]}, "group_option_values": {"env": "prod"}, "scope_id": "…"}
```

| outcome | HTTP | Lambda (thin and fat) |
| --- | --- | --- |
| success | 200, `{"status": "Success", "return_value": …}` (unchanged) | `statusCode` 200 (unchanged) |
| refused argument (missing, unknown, injected, does not convert) **or** a call to a job whose parameter discovery refused | **400**, `{"status": "Invalid", "error": "<argument>: <reason>"}` | `statusCode` **400**, same body |
| run failed | 500 with `error` (unchanged) | 500 with `error` (unchanged) |

**The outcome this needs.** The tables have no "bad argument" status today. `REFUSED` means "a
declared precondition … was not met" and maps to exit 3 and HTTP 412; `ExitCode.USAGE = 2` exists
with no `RunStatus` mapped to it. This change **adds one status**, `RunStatus.INVALID` (value
`"Invalid"`, name *(provisional)*): "the call could not be bound to the job's declaration — nothing
ran". It maps to exit 2, HTTP 400 and Lambda 400, and MCP reports it as `isError: true`. `REFUSED`
keeps its meaning and its codes.

- **Fat Lambda event:** `{"job": "<name>", "arguments": {…}}`. Its docstrings say `arguments`, and
  `kwargs` is not read.
- **Values** reach the job converted per §1. `"1234…"` for a `UUID` parameter arrives as `UUID`.

## 8. Discovery refusal (DC-1 decides the second half)

A warning on every boot path, naming the file, job, parameter and remedy:

```text
⚠ jobs/report.py: job 'report' — parameter 'filters: str | int' is a union of two types.
  Declare one type, or Annotated[..., Option()] with a convertible type.          # wording (provisional)
```

**DC-1 = B (decided 2026-11-22, comment `01a2012e`):** the job stays registered, and
`func builtin info` lists it among discovery failures with `error_type` `"UnsupportedParameter"`
*(provisional)*, next to ADR-018's `"UnsatisfiableParameter"`. Every call refuses with that message:
CLI and TUI exit 2, HTTP and Lambda 400 with `status` `"Invalid"`, MCP `isError: true`, with the tool
listed and declaring no inputs. This is identical on cold and warm boots.

## 9. Public Python API

- **`functualize.types.FieldDescriptor`** gains one field carrying the parameter's contract: verdict,
  value shape, requiredness, default, CLI spelling, JSON schema fragment. Field and type names are
  *(provisional)*; `contract: ParameterContract` is the page's working name.
- **`FieldDescriptor.type_annotation` and its `type` alias property are removed** (SS-3 = B,
  member comment `01a201b6`, 2026-11-22T05:24:10Z). This is a public break of
  `functualize.types.FieldDescriptor`, recorded in `CHANGELOG.md`. The type label is
  `FieldDescriptor.contract.display`.
- **The descriptor cache** rebuilds once after upgrade (`CACHE_VERSION` bump). No user action is
  needed.
- **`functualize.types.RunStatus`** gains `INVALID` (§7).
- **No new** environment variable, config key or CLI flag.

## 10. Test and documentation artifacts (repository-visible)

| artifact | file *(provisional)* |
| --- | --- |
| the declaration table | `tests/_support/parameter_matrix.py` |
| the parity test | `tests/surfaces/test_parameter_surface_parity.py` |
| the docs table | `docs/guides/jobs-discovery.md` § *Which parameters are inputs*, asserted equal to the table |
| changelog | `CHANGELOG.md` — every visible change listed in `spec.md` § *Evidence and constraints* |
