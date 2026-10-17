# Contracts — job-name NFKC resolution

What this change alters at a boundary. Behaviour is in `spec.md`; this file
states signatures, values and compatibility.

## Public API surface

`functualize.app.utils` re-exports the naming policy
(`src/functualize/app/utils.py:96-106`, `__all__` at `:325-327`). Signatures do
not change. Their return values do:

| Symbol | Signature (unchanged) | Contract after this change |
|---|---|---|
| `normalize_segment` | `(segment: str) -> str` | `rule(unicodedata.normalize("NFKC", segment))`, where `rule` is today's lowercase-and-hyphenate body (`_types/naming.py:45-79`). Idempotent. Equal to today's output when `NFKC(segment) == segment` |
| `normalize_name` | `(name: str \| None) -> str \| None` | `None` passes through. Otherwise NFKC the whole string, **then** split on `.`, then `normalize_segment` each part |
| `resolve_name` | `(candidate: str, known: Iterable[str]) -> str` | Steps unchanged: exact match, then canonical match, then leaf match, then `LookupError`. `_canonical` (`:138-139`) NFKCs the whole name before splitting. Step 3's "candidate has no group" test reads the NFKC'd candidate, so a compatibility dot states a group just as `.` does |
| `qualified_name` (`_discovery/naming.py:25`, internal) | unchanged | Inherits B1 through `normalize_segment`. The `isidentifier()` check on group segments still runs on the raw group, before normalisation |

No new public symbol. No new exception type.

**Cost contract (B10, AC10).** For ASCII input, none of the three functions
calls `unicodedata.normalize`. `normalize_segment` calls it once for non-ASCII
input. `normalize_name(n)` calls it `[n non-ASCII] + (non-ASCII segments of NFKC(n))`
times. NFKC-stable input is returned as the identical object. The contract
counts calls; it does not set a time budget.

## Registered identity

- A job or group name that comes from a Python identifier: **unchanged**,
  because it is already NFKC (PEP 3131).
- A name set as a string (`JOB_GROUP`, `@job(name=, group=)` and `StaticProvider` items
  (`_discovery/providers.py:671-675`), entry-point names in `EntryPointProvider`
  (`:797`, `:862`)): becomes its NFKC form. Census in
  this repo: 0 affected (`spec.md` § *Evidence baseline*).

## Config-file sections — `FileSource` (`_config/sources.py`)

`_section_data(section)` uses the ordered private lookup in `spec.md` B7:

1. exact;
2. `-`↔`_` swaps;
3. dotted walk;
4. `normalize_name(key) == normalize_name(section)`, top level or per level of
   a dotted walk.

- More than one distinct key at step 4 raises
  `functualize._config.errors.ConfigurationError` (existing type,
  `_config/errors.py:14`). The message names the section and the sorted keys.
- `reject_inline_provider` applies the same normalization rule to **every**
  equivalent flat or dotted table in each parsed file. Value lookup precedence
  does not suppress validation of a shadowed table. It keeps raising
  `ValueError` for an inline provider; only the set of spellings it inspects
  grows.

## Environment variables — unchanged by design

`EnvSource._build_env_key` (`_config/sources.py:262-290`), `EnvSource.keys`
(`:242-260`) and `env_name_for` / `group_env_name_for`
(`_config/resolved_field.py:90-110`): no code change. The variable name is
derived from the registered name, so `job-aadž` reads `JOB_AADŽ_<FIELD>`. This
is the stated exclusion (D1). It is documented in `docs/guides/jobs-discovery.md`
§ *Job names are canonical*.

## Persisted formats

| Format | Before | After | Migration |
|---|---|---|---|
| Discovery cache `CACHE_VERSION` (`_primitives/cache_format.py:156`) | `21` | `22`, with a `# v22 (date):` line in the version log above it (`:129-155` style) | None. A v21 file is discarded and rebuilt on first boot (the existing version-mismatch path) |
| State-store fingerprint key `<job_name>::<args_hash>::<method>` (`_primitives/fingerprint.py:139-145`) | unchanged shape | unchanged shape | None (D2). A string-set name that changed identity re-runs once |
| Scope step record key `<job_name>::<args_hash>` (`_primitives/scope_store.py:425-428`) | unchanged shape | unchanged shape | None (D2) |

## Import-linter contracts

`pyproject.toml` declares seven contracts. This change adds two imports:

- `_types/naming.py` → `unicodedata` (stdlib). Contract *"Types import nothing
  internal"* forbids internal modules only, so this is allowed.
- `_config/sources.py` → `functualize._types.naming`. `_config` already imports
  `_types` (`sources.py:31-32`), and `_types` is the foundation layer, not a
  peer. Contract *"Peer layers are independent"* is unaffected.

No `_cli` → internal import is added. `_cli/dispatch.py:217` and `_cli/main.py:1320`
already import the policy through `functualize.app.utils`.

## Backward compatibility

- **Every NFKC-stable name, including all ASCII names:** identical registration,
  lookup, config, env and persisted keys (B3, B7 steps 1–3).
- **Newly accepted, and deliberate:** a config table spelled with case or
  separators that only the shared rule equates (`[Build_Wheel]` for
  `build-wheel`), and only when no exact or swapped spelling exists. This
  matches what `func Build_Wheel` already accepts.
- **Changed identity:** a string-set name containing an NFKC-unstable character
  (0 in this repo). The `CHANGELOG.md` entry states it, and states that its
  history re-runs once (D2).
