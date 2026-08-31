# ADR-007: Narrow the Default Config Formats to TOML

**Status**: accepted
**Date**: 2026-08-27
**Deciders**: Hakim

## Context

Two format providers shipped registered by default. The original draft of this
ADR attributed that to the `functualize.format_providers` entry-point group in
`pyproject.toml`:

```toml
toml = "functualize._config.providers.toml:TomlFormatProvider"
ini  = "functualize._config.providers.ini:IniFormatProvider"
```

**That attribution was wrong, and it mattered.** `_app/boot.py` registered both
providers directly, before `discover_entry_points()` ran:

```python
app.config_registry = ProviderRegistry()
app.config_registry.register_format_provider(TomlFormatProvider())
app.config_registry.register_format_provider(IniFormatProvider())   # unconditional
```

Removing the `ini` entry point alone would have changed nothing — the effective
extension set stays `['.cfg', '.ini', '.toml']`. The decision as first written
was a no-op, and no test would have caught it, because the tests that existed
asserted on entry points rather than on what the registry ended up holding.

INI carries costs TOML does not:

- **No types.** Every value is a string until something coerces it, which puts
  the burden on the config consumer rather than the parser.
- **Interpolation had to be actively disabled.** Both `IniFormatProvider` code
  paths construct `configparser.ConfigParser(interpolation=None)`, and the
  INI-to-TOML migration helper that then existed had to *reject* `%(key)s`
  references outright, because TOML has no equivalent to convert them into.
- **A second syntax to document and test.** The configuration guide was written
  largely in `.ini`, including the `settings\.(\w+)\.ini` pattern example, so
  every config feature was explained twice.

The presence of `_config/migration.py` — an INI-to-TOML migration path, written
long before this ADR and never called by anything — already signalled that TOML
is the intended destination. Python has had `tomllib` in the standard library
since 3.11, which is this project's floor, so TOML costs no dependency.

## Decision

**TOML is the only format registered by default. Do not delete the INI
provider.**

Both halves are removed: the unconditional `register_format_provider(
IniFormatProvider())` in `_app/boot.py`, and the `ini` entry point in
`pyproject.toml`. `IniFormatProvider` remains in the tree and importable.

The reasoning for keeping the code is not sentiment. **INI is the second
implementation that keeps the `FormatProvider` abstraction honest.** A protocol
with exactly one implementation stops being a seam and starts being ceremony,
and its breakage is invisible until the first third party tries to use it.

### The escape hatch is a plugin, not a post-construction call

The original draft named this as the way back:

```python
registry.register_format_provider(IniFormatProvider())
```

**It does not work.** By the time a `FunctualizeApp` object exists, boot has
already built the resolution chain from whatever was registered during boot. A
call on `app.config_registry` afterwards updates the registry and changes
nothing about which files are discovered or read — a user following the ADR
would have been left with a `.ini` file that is parseable and never read. This
is the same class of defect the ADR itself was written to fix, one level down.

Boot loads plugins *before* it builds the chain, precisely so they can register
providers. That is the supported path:

```python
# .functualize/plugins/ini_format.py
from functualize._config.providers.ini import IniFormatProvider


class _Plugin:
    name = "ini-format"
    version = "1.0.0"
    description = "Restores INI config parsing"

    def __call__(self, app):
        app.config_registry.register_format_provider(IniFormatProvider())


plugin = _Plugin()
```

A package declaring the provider in the `functualize.format_providers`
entry-point group works too, for the same reason: entry-point discovery also
runs before the chain is built.

`tests/config/test_toml_only_formats.py` pins both directions with a control
case, and asserts the *effective* extension set rather than the entry points, so
a test can no longer pass against a build where the decision did not take.

### There is no migration command — the module is deleted instead

The first draft of this ADR pointed users at a `func builtin config migrate`
that did not exist (`config` had `show`, `path`, `edit`), while
`migrate_ini_to_toml` sat in `_config/migration.py` with zero callers and zero
tests. That is a migration path with no entrance, and the disposition was always
one of two things: **give it an entrance, or give it an exit.**

Implementation took the entrance — the command was built, tested, and shipped.
It was then **removed**, and the module with it, on the maintainer's call
(2026-08-28). The reasoning:

- **A conversion command exists to carry a user population across a break.**
  Pre-1.0, with the format narrowed by hard removal and no deprecation window,
  there is no such population. The command served a migration nobody was
  performing.
- **Keeping it re-created the shape it was built to fix, one level up.** The
  entrance justified the module; the module justified the entrance; the only
  external caller was the test suite. `migrate_ini_to_toml` with a command in
  front of it is still code whose reason to exist is that it exists.
- **The conversion it automated is not the hard part.** Its whole non-trivial
  behaviour was *refusing* `%(key)s` — the one case it could not convert. What
  remains is quoting strings, which a person does by hand in a minute for a
  config file small enough to have been an INI file.

What the narrowing owes its users is unchanged and still enforced: a project the
framework can no longer read must **say so** rather than run on model defaults,
and the remedy it names must work. Boot warns once per unreadable file, naming
both ways out — convert to TOML, or register the provider from a plugin — and
`builtin info` reports the file rather than "No config files found".
`tests/config/test_legacy_ini_project.py` starts from an INI-only project and
holds that end to end.

`_config/migration.py` and `MigrationError` are deleted.

## Consequences

### Positive

- One documented config syntax. The configuration guide stops explaining
  everything twice.
- Typed values from the parser, so config consumers stop compensating for
  INI's string-only model.
- The `FormatProvider` seam keeps a working second implementation, and now has
  an end-to-end test proving a plugin can register one.
- One less unreachable module: `_config/migration.py` is gone rather than
  propped up by a command written to give it a caller.

### Negative

- **Breaking change**, with no deprecation window — pre-1.0, and
  `.spec/CONSTITUTION.md` forbids compat shims. A project relying on `.ini`
  discovery must register the provider from a plugin or migrate. CHANGELOG entry
  written by hand.
- `.cfg` no longer anchors a config directory. The anchoring rule is unchanged —
  it still delegates the extension question to the registered providers — but
  the provider set is smaller.
- A documentation sweep was mandatory: `docs/guides/configuration.md` and every
  reference to `config.base.ini` / `settings.*.ini`, plus the runtime hint in
  `app/adapters/cli.py`, which named `.toml, .ini, .cfg` as the defaults.

### Neutral

- `IniFormatProvider` is not deleted — only unregistered. `_config/migration.py`
  and `MigrationError` **are** deleted; they were never part of the provider
  seam and had no users.

## Alternatives Considered

| Alternative | Pros | Cons | Why rejected |
|---|---|---|---|
| Delete `IniFormatProvider` entirely | Smallest tree | Leaves `FormatProvider` with one implementation and no proof the seam works | Rejected: the abstraction loses its only honest test |
| Keep both registered | No breakage | Every config feature documented twice; INI's untyped model persists | Rejected: the ongoing documentation and support cost is the actual problem |
| Move INI to a separate published package | Clean separation | A package to release and version for a legacy format | Rejected as disproportionate |
| Drop only the entry point | Looked like the whole decision | Is a no-op — `boot.py` registers it directly | Rejected on evidence; see Context |

## Migration

1. Convert `config.base.ini` to `config.base.toml` by hand — section headers are
   identical; values need quoting. There is no conversion command, deliberately
   (see above).
2. A project that must keep reading INI registers `IniFormatProvider` from a
   plugin (see above), which is the supported path because plugins load before
   the resolution chain is built.
3. Either way you are told: an unreadable config file warns at boot and is
   listed by `builtin info`. Neither is silent, which is the property that
   matters.
