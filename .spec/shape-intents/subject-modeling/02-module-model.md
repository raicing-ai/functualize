# 02 — The Module Model

A rise module is one Python class. The class *is* its own declaration, and that
declaration is readable two ways — live by reflection, and from source without
executing anything.

## 1. Anatomy

```python
from risekit import Executable, Installable, Runnable, Isolation
from functualize.job import Guards, Log, Shell, job

class Jsonschema(Executable, Installable, Runnable):   # ① substrate + actions
    group = "tools.jsonschema"                          # ② identity → CLI namespace
    isolation = Isolation.PROJECT                       #    tags = typed class attrs
    config = JsonschemaConfig                           #    a plain pydantic model

    @job(guards=Guards(status=["command -v jsonschema"]))
    def install(self, sh: Shell, log: Log) -> None: ... # ③ actions = methods
    def uninstall(self, sh: Shell) -> None: ...
    def run(self, sh: Shell, args: list[str]) -> None: ...

    # ④ diagnose / validate / audit are INHERITED. There is nowhere to write them.
```

| Rise concept | Class form | Enforced by |
|---|---|---|
| substrate | a base class | inheritance; presence shape follows |
| actions | Protocol mixins | mypy, then `isinstance` at binding |
| tags | typed class attributes | binding check |
| target | a `Target` instance on `target` | model validation |
| action surface | public methods | `@abstractmethod` sets |
| required config | a pydantic model on `config` | pydantic |

## 2. The declaration lives in the class line

The intent's three anti-patterns become language-level impossibilities:

| Intent rejection (criteria 5, 6) | In Python |
|---|---|
| declaring a substrate as an *action* | substrates are classes, not Protocols; the adapter rejects two concrete substrates of conflicting shape |
| a strategy name (`pip`, `brew`) as an action | no `pip` Protocol exists — `from risekit.core.protocols import pip` is an `ImportError` |
| dot-notation `program.mise` | not an expressible base |

## 3. Methods become jobs

| Python | CLI (own binary) |
|---|---|
| `group = "tools.jsonschema"` | `rise tools jsonschema …` |
| `def install(self, …)` | `… install` |
| `def config_dir(self)` | `… config-dir` (canonical hyphenation, `_types/naming.py:45`) |
| `subgroups = {"config_dir": "output"}` in the class body | `… output config-dir` — one extra segment |
| inherited `diagnose` / `validate` | `… diagnose` / `… validate` |

Canonicalization is functualize's own `normalize_segment`, so a rise job has
exactly one spelling on every surface.

Sub-groups are declared as a **class-body literal**, not a `@job` kwarg:
`@job` has no `subgroup` parameter (`job/decorators.py:46`), and its `group=`
override is absolute — a method-level group would repeat the class prefix on
every method and desync on rename. The adapter composes the extra segment
into the job *name* (`tools.jsonschema.output.config-dir`); functualize's
trie renders dotted names as nested sub-groups, one `click.Group` per
segment (`app/adapters/cli.py:509`). The literal sits inside the AST
reader's existing scope (`§5`), and a key naming no public method is a
binding error. Sub-groups are surface-only — no binding, isolation, or
fingerprint semantics ride them.

## 4. Code reuse: `diagnose` and `validate` are inherited

`Resource` carries them once; the adapter injects them as jobs into every
group. A module author's only surface is lifecycle bodies, an optional `PROBES`
override, and an optional `config`. There is no per-module hook where
`diagnose` could be written, so it cannot drift — and this needs nothing from
functualize (`05`).

## 5. The declaration must be readable without executing — and is

Intent criterion 25 asks that declaration extraction read the module's own
file. The point is that reading a declaration must not require *running* the
module. "Import the class" is a different guarantee: importing runs
module-level code and any `__init_subclass__`.

functualize does not accept that trade for itself — it has three AST
pre-filters that answer questions about a file without importing it
(`_primitives/pre_filter.py:100`, `:126`, `:163`). risekit follows the same
discipline:

```python
def declaration_of(cls: type[Resource]) -> Declaration:
    """Live: MRO walk + class attributes. Used at binding."""

def declaration_of_source(path: Path) -> Declaration | None:
    """AST: parse the file, find the top-level ClassDef whose bases name a rise
    substrate, read the base list and literal class-body assignments. Imports
    nothing, executes nothing. None if the file declares no rise module."""
```

The two are held equal by a property test over the whole tree; a divergence is
a bug in one of them, and the test names which.

This buys: `rise info <module>` and the MCP declaration surface answer from
source (criteria 25 and 66, met literally); static analysis over a repository
of rise modules needs no environment; and it is the pre-filter signal if the
upstream route in `13` §3 is ever taken.

Its limits are stated: a dynamically built base list, or a computed
`isolation`, is invisible to it. Both are forbidden by §7 and caught by the
equality test.

## 6. mypy is layer 1, not a nicety

`runtime_checkable` verifies method *presence* only. A class with
`def backup(self, extra)` passes `isinstance(x, Backupable)` and fails at call
time. So the project template ships a mypy configuration and CI step, and the
binding check is explicitly the backstop rather than the primary.

## 7. The constructor contract

The adapter instantiates each class once at boot to bind its methods, which
makes `__init__` a boot-time execution point. That is a checked contract, not a
convention:

1. **No-argument construction.** A constructor requiring arguments is a binding
   error naming the class.
2. **No side effects.** No I/O, no network, no process spawning, no filesystem
   writes. Configuration arrives per invocation.
3. **No dynamic bases, no computed tags.** Enforced by the
   `declaration_of_source == declaration_of` property test (§5).
4. **One instance per class per process**, so bound-method identity is stable
   for the app's life — relevant because the executor keys a group-options
   cache on `id(function)` (`_engine/executor.py:207`).

Rules 1, 3 and 4 are mechanical. Rule 2 is not fully checkable, so it is
enforced three ways instead: the base-class docstring states it, the scaffold
never emits an `__init__`, and a lint rule flags overrides for human review.

## 8. `config` is a plain model, not `GroupOptions`

`GroupOptions` specs are collected only in the directory-scan pass
(`_discovery/sync.py:203`) and read only from the discovery cache
(`app/utils.py:1547`), and a class bound through a provider writes neither. So
`config` is an ordinary pydantic model, bound **per job**; values resolve
through the normal chain (file, env, `.env`, per-job flags). `Secret[str]`
redaction is a property of the annotation (`_types/redaction.py`), not of the
discovery path, so it keeps working.

Group-level flags are deferred; the upstream ask is in `13` §4.

## 9. What it costs

A rise module is **Python only**. The language-neutral module file is gone —
the intended consequence of the OOP direction, matching the scrill-design
decisions D19/D24 (schemas and interfaces as code, not files). Non-Python *tools* stay first-class: a `custom` variant shells out
through `Shell`. Non-Python *authors* are out of scope for v1, and the scaffold
docs say so in the first paragraph.
