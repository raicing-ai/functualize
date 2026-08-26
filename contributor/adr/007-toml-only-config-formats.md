# ADR-007: Narrow the Default Config Formats to TOML

**Status**: proposed
**Date**: 2026-08-27
**Deciders**: Hakim

## Context

Two format providers ship registered by default, via the
`functualize.format_providers` entry-point group in `pyproject.toml`:

```toml
toml = "functualize._config.providers.toml:TomlFormatProvider"
ini  = "functualize._config.providers.ini:IniFormatProvider"
```

`ProviderRegistry.register_format_provider` loads them, so the format layer is a
genuine extension seam rather than a hardcoded branch.

INI carries costs TOML does not:

- **No types.** Every value is a string until something coerces it, which puts
  the burden on the config consumer rather than the parser.
- **Interpolation had to be actively disabled.** Both `IniFormatProvider` code
  paths construct `configparser.ConfigParser(interpolation=None)`, and
  `_config/migration.py` exists partly to *reject* `%(key)s` references when
  converting INI to TOML.
- **A second syntax to document and test.** The configuration guide is written
  largely in `.ini`, including the `settings\.(\w+)\.ini` pattern example, so
  every config feature is explained twice.

The presence of `_config/migration.py` — an INI-to-TOML migration path — already
signals that TOML is the intended destination. Python has had `tomllib` in the
standard library since 3.11, which is this project's floor, so TOML costs no
dependency.

## Decision

**Unregister the INI provider from the default entry points. Do not delete it.**

`pyproject.toml` ships only the `toml` format provider. `IniFormatProvider`
remains in the tree, importable, and registerable by a consumer who needs it:

```python
registry.register_format_provider(IniFormatProvider())
```

`_config/migration.py` stays, since its whole purpose is helping existing users
off INI.

The reasoning for keeping the code is not sentiment. **INI is the second
implementation that keeps the `FormatProvider` abstraction honest.** A protocol
with exactly one implementation stops being a seam and starts being ceremony,
and its breakage is invisible until the first third party tries to use it.
Retaining INI as an explicitly registerable provider — and as a test fixture
exercising the registry path — preserves that proof at approximately zero
maintenance cost, while removing it from what every user must learn.

## Consequences

### Positive

- One documented config syntax. The configuration guide stops explaining
  everything twice.
- Typed values from the parser, so config consumers stop compensating for
  INI's string-only model.
- The `FormatProvider` seam keeps a working second implementation and a test
  that exercises registration.

### Negative

- **Breaking change** for any project relying on `.ini` discovery by default;
  they must register the provider explicitly or migrate. Needs a deprecation
  window and a CHANGELOG entry written by hand.
- A documentation sweep is mandatory: `docs/guides/configuration.md` and every
  reference to `config.base.ini` / `settings.*.ini`.
- Anything asserting on the default registry contents needs updating.

### Neutral

- No code is deleted, so the change is reversible by restoring one line in
  `pyproject.toml`.

## Alternatives Considered

| Alternative | Pros | Cons | Why rejected |
|---|---|---|---|
| Delete `IniFormatProvider` entirely | Smallest tree | Leaves `FormatProvider` with one implementation and no proof the seam works | Rejected: the abstraction loses its only honest test |
| Keep both registered | No breakage | Every config feature documented twice; INI's untyped model persists | Rejected: the ongoing documentation and support cost is the actual problem |
| Move INI to a separate published package | Clean separation | A package to release and version for a legacy format | Rejected as disproportionate |

## Migration

1. Deprecation release: warn when a `.ini` config file is discovered, pointing
   at `func builtin config` migration.
2. Following minor: remove the entry-point registration.
3. `_config/migration.py` remains indefinitely.
