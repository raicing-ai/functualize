# ADR-041: A Setting Is Declared Once, and the Schema Is the Read Door

**Status**: accepted
**Date**: 2026-10-28
**Deciders**: maintainer, through the triage that accepted the unknown-key
report (2026-10-13) and the scope ruling of 2026-10-19 that put every
vocabulary restatement found on the way inside the fix.

## Context

A key in `.functualize.toml` that no setting declares was accepted in
silence: `func builtin config path` reported the file *used*, and a typo such
as `roots = true` never surfaced. The check that should catch it needs one
answer to "which keys exist". The code had several:

- the vocabulary was stated five times, in thirteen collection literals across
  six files, with 91 more key names read as bare strings;
- three resolvers read the same settings and disagreed. The CLI honoured
  `root = true` and the settings store walked past it, so `cli.output` read
  `rich` in one and `json` in the other;
- a setting could be declared, displayed and documented for one file kind while
  its consumer read it from another (`[shell] program` in `.functualize.toml`
  was shown by the store and ignored by the engine);
- the catalog was a module-level mutable registry. The shell registered its
  `tui.*` settings as an import side effect, a pre-boot scan wrote flag values
  into a second process-global map, and whether a setting existed depended on
  which modules happened to be imported first;
- a second app could not declare its own settings through public API, so the
  only standalone example reached into `functualize._cli` to do it.

A vocabulary check built on any one of these would have been one more
statement of the vocabulary, not the statement.

## Decision

Every setting name is declared exactly once, as data, and every reader asks
the declaration.

- **One declaration.** `functualize`'s settings are the `Setting` values in
  `_types/functualize_settings.py`, collected into `FUNCTUALIZE_SETTINGS`, an
  `AppSettingsSchema` re-exported from `functualize.plugin`. A setting's name,
  type, default, choices, accepted file sections, environment name, root flag
  and `phase` live on that one value. Nothing else lists setting names. The
  vocabulary check, `config path`, `config show`, `info --json`, the generated
  root flags, the pre-boot flag scan, the TUI settings panel and the docs
  reference all derive from it.
- **Extension never redefines.** An app adds settings with
  `FUNCTUALIZE_SETTINGS.extend(*own)`. `extend` returns a new schema and raises
  `ValueError` when a name is already declared, including a clash within the
  added settings themselves. An app passes the complete extended tuple into its
  own `AppSettingsSchema` (its env prefix, file names and `pyproject.toml`
  table) through `ConfigSources(settings=...)`. A schema holding only the
  app's own settings would silently drop every built-in key.
- **The schema is the read door, not a process registry.** Values come from
  `resolve_settings(schema, cwd, flags=..., env=...)`, which applies one
  precedence ladder (flag > environment > nearest project file > global >
  default) over the layers the schema's sources name. The result is an
  immutable `ResolvedSettings` snapshot carrying provenance. A `FunctualizeApp`
  resolves once and hands that snapshot (`app.settings`, with
  `app.settings_schema`) to every surface. Flags read before boot, through
  `early_setting_flags(schema, argv)`, enter the same resolver and travel per
  invocation as a snapshot, never through module-level state. There is no
  registration API and no import-time side effect that changes which settings
  exist.
- **Readers name declared settings.** A consumer reads a value through the
  snapshot or `schema.value_in(...)` by the declared name. It never indexes a
  file table by a string key it restates.

## Consequences

### Positive

- An unknown key is now a fact the declaration can answer. `config path` names
  it beside its file, with a close match where one exists, and `info --json`
  carries it as `config.unknown_keys`. The check stays off the job-run path,
  so a typo costs a run nothing and blocks nothing.
- The surfaces cannot disagree about a value: one resolver, one snapshot, one
  source of provenance. The `root = true` and `[shell] program` disagreements
  have nowhere left to come from.
- Import order no longer decides whether a setting exists, and tests construct
  explicit schemas instead of saving and restoring a global registry.
- A second app has a public way to declare settings, and the example does it
  without importing `functualize._*`.

### Negative

- Adding a setting is a deliberate edit to the declaration, never a
  registration from wherever the consumer lives. A component that once
  contributed its own knobs at import time must have them declared up front.
- Pre-boot flags have to be passed explicitly into the first snapshot, so every
  app entry point has to call the pre-boot helper and hand its result to the
  resolver.

### Neutral

- Ratchets keep the rule from eroding. `tests/spec/test_settings_ratchet.py`
  fails on a process registry or second file reader for declared settings, on a
  catalog name the declaration does not carry, on a second schema source for
  generated flags, and on a `func` app door that does not receive the
  invocation's settings. `tests/config/test_settings_pin.py` pins the declared
  vocabulary itself.
- The legacy `FuncSetting` projection in `_cli/data/func_settings.py` survives
  only as catalog data for that pin. Nothing resolves, displays or registers
  through it.

## Alternatives Considered

| Alternative | Pros | Cons | Why rejected |
|-------------|------|------|-------------|
| Validate keys against the existing CLI catalog, change nothing else | Smallest diff | The catalog was one of five statements and disagreed with the resolvers; the check would have reported keys the engine reads as unknown, and the reverse | Adds a sixth statement instead of removing five |
| Keep a registration API, made idempotent and order-independent | Lets components contribute settings where they live | Still process-global state; which settings exist still depends on what was imported; tests still have to save and restore it | Forbidden module-level mutable state, and the root cause of the shell-only `tui.*` defect |
| One declaration per app, without extending the base | Apps fully independent | Every app restates `discovery.*`, `cli.*`, and the rest, and drifts | Re-creates the duplication across apps |
