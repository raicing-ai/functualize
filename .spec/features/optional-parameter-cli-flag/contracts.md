# External contracts: optional job parameters

## Job declaration

The public job signature accepts both Python optional annotation spellings
without requiring a marker:

```python
from typing import Optional

from functualize.job import job


@job
def greet(
    name: str,
    greeting: str | None = None,
    tone: Optional[str] = None,
    loud: bool | None = None,
) -> None:
    ...
```

The author's declared default is preserved when the user omits the option.
An inner type that has no implicit CLI form does not acquire one through
`Optional`. Explicit `Annotated[..., Option(...)]` declarations continue to
use their declared marker.

## Command surface

For the declaration above, the command publishes these relevant spellings:

```text
func greet --help
  --greeting TEXT
  --tone TEXT
  --loud / --no-loud
```

The concrete help layout may follow Click's existing formatting; the flag
names, accepted arguments, and delivered values are the contract.

| Invocation | Value received by `greeting` | Value received by `tone` | Value received by `loud` |
| --- | --- | --- | --- |
| `func greet ada` | `None` | `None` | `None` |
| `func greet --greeting hi ada` | `"hi"` | `None` | `None` |
| `func greet --tone warm --loud ada` | `None` | `"warm"` | `True` |
| `func greet --no-loud ada` | `None` | `None` | `False` |

The job's own output for `--greeting hi ada` is `GREET hi ada` in the
minimal reproduction. The command exits 0. Existing invalid-value and
unknown-option errors retain their current CLI behavior.

## Name collision

If the same command declares `loud: bool | None = None` and a separate
`no_loud` parameter, `--no-loud` belongs to `no_loud`. The `loud` parameter
offers `--loud` and can be omitted; this command has no `False` spelling for
`loud`. The sibling's own CLI type and behavior are unchanged.

## Other externally visible surfaces

- Generated help, completion, and any published job parameter schema must
  agree on which optional signature parameters are CLI inputs.
- Capability injection remains separate. The documented
  `RunContext | None` and `TTY | None` examples expose no `--rc` or `--tty`
  option.
- Config model fields retain their existing CLI, environment, and config-file
  source precedence. A plain `greeting` signature parameter does not become
  addressable from a config file.
- No new public exception, payload, environment variable, or config key is
  introduced.
