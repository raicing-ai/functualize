# Optional job parameters on the CLI

## Problem and user outcome

A job author can declare an optional value in either Python spelling, `X | None`
or `Optional[X]`. When `X` already earns a CLI parameter, the optional form is
currently omitted from the command. The user cannot discover or supply it. A
job with `greeting: str | None = None` therefore accepts the default but rejects
`--greeting hi`.

The approved product rule is: an optional form earns a CLI parameter exactly
when its inner type earns one. An absent option preserves the declared `None`
default. The change is due before the 0.5.0 tag.

## Users and scope

- A job author can express optional CLI input with either `X | None` or
  `Optional[X]`, without an explicit CLI marker.
- A CLI user can discover, supply, and omit that input using the command's
  existing naming and value grammar.
- For an eligible `bool | None`, the user can distinguish unset, true, and
  false: no flag yields `None`, `--loud` yields `True`, and `--no-loud` yields
  `False`.

The inner type `X` must already be eligible for the CLI. This includes the
built-in scalar and path types, currently accepted standard-library value
types, and enums. An optional wrapper does not make an otherwise unsupported
inner type eligible. In particular, the current classifier drops unmarked
`list[str]` as well as `list[str] | None`; this change does not introduce
unmarked list parameters. An explicit CLI marker retains its existing
precedence and supported spelling.

Ordinary job signature parameters are invocation inputs. They do not read
config-file or environment values. Fields of a separately declared Pydantic
job config model continue to use their current source-resolution behavior;
this specification does not change that behavior.

## Required behavior

1. `str | None = None` and `Optional[str] = None` both publish the same
   value-taking option that `str` publishes, with the same flag name and Click
   value conversion. Omitting either leaves the job's value as `None`.
2. For every already CLI-eligible inner type `X`, `X | None` and
   `Optional[X]` retain that type's CLI spelling and value conversion. The
   optional wrapper affects eligibility and absence, not the meaning of a
   supplied value.
3. A plain optional boolean with a `None` default publishes the positive and
   negative spellings when both names are free. They deliver `True` and
   `False`, respectively; omission delivers `None`.
4. If a sibling parameter is named `no_<name>`, that sibling owns
   `--no-<name>`. The optional boolean retains `--<name>` and its absent
   `None` state; it has no spelling for `False` on that command. The existing
   collision rule remains deterministic and does not steal the sibling's flag.
5. Existing explicit `Annotated[Optional[str], Option("--greeting")]`
   parameters retain their marker, help spelling, and invocation behavior.
   Existing non-optional parameters retain their flags and values.
6. Injected capability parameters, including `RunContext | None` and
   `TTY | None`, do not gain CLI flags. General unions with two non-`None`
   members remain outside this rule.

## Acceptance checks

| Check | Observable result |
| --- | --- |
| E1 | `func greet --help` for `greet(name: str, greeting: str | None = None, tone: Optional[str] = None, loud: bool | None = None)` lists `--greeting`, `--tone`, and `--loud/--no-loud`. |
| E2 | `func greet --greeting hi ada` prints `GREET hi ada` and exits 0. |
| E3 | Invoking the optional-boolean job without the flag, with `--loud`, and with `--no-loud` delivers `None`, `True`, and `False` to the job, respectively. |
| E4 | Example jobs in `README.md` and `docs/` with `RunContext | None` or `TTY | None` gain no corresponding CLI option. |
| E5 | Existing flag help and invocation snapshots stay unchanged for parameters that already have flags, including marked optional parameters. |
| E6 | A regression test demonstrating the missing optional flag fails on the pre-fix revision `e00d870` and passes after the change. |
| E7 | A command with siblings `loud: bool | None = None` and `no_loud` offers `--loud` and the sibling's `--no-loud` without duplicate binding; absence of `loud` is `None`. |

## Evidence and constraints

On base `91947bb`, the CLI probe above lists only `--help`; supplying
`--greeting hi` exits 2 with `No such option`; omission runs and passes
`greeting=None`, `tone=None`, and `loud=None`. `parse_annotation` on that base
classifies `str`, `bool`, `Path`, and an enum as CLI-compatible, and their
optional wrappers as incompatible. It also classifies unmarked `list[str]`
as incompatible. The repository's ADR on remote source activation states
that ordinary function parameters are invocation inputs, not vault targets.

No discovery finding is added for still-unsupported annotations. No new
config-file or environment source is added to a signature parameter. The
changelog records the user-visible fix under Unreleased → Fixed.

## Confirmation gate

This specification and its external contracts require member confirmation
before the architecture and task plan may be written.
