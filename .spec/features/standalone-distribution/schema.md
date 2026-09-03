# Schema: Standalone Distribution & Self-Management

**Feature**: `standalone-distribution`
**Date**: 2026-09-03
**Scope**: internal types only. The on-disk manifest format and the `info` JSON payload are
**external** and live in `contracts.md` — this file describes what holds them in memory.

No database. No cache-format change: nothing here is serialized into `cache.json`, so the
format version in `_primitives/cache_format.py` is untouched.

---

## `_cli/runtime.py`

### `InstallMode`

A string enum, so its members serialize directly to the public vocabulary in
`contracts.md` §4 without a translation table.

```
InstallMode(str, Enum)
    STANDALONE  = "standalone"
    TOOL_UV     = "tool_uv"
    TOOL_PIPX   = "tool_pipx"
    PROJECT     = "project"
    TOOL_PIP    = "tool_pip"     # degraded
    UNKNOWN     = "unknown"      # degraded
```

**Named `InstallMode`, never `Mode`.** `_cli/dispatch.Mode` is a live enum whose members
already include `UNKNOWN`, and this module sits beside it.

`degraded` is a derived property (`TOOL_PIP`, `UNKNOWN`), not a stored field — it is the sole
input to the refusal branch, so it must have one definition.

### `Detection`

The pair returned by detection. Both axes together, because every mutating command needs
both and computing them separately invites one being resolved without the other.

```
Detection (frozen)
    mode                 : InstallMode
    owning_distribution  : str | None    # None when argv0 maps to no distribution
```

`owning_distribution` is nullable on purpose: a `python -m` invocation or a renamed script
has no distribution, and guessing `functualize` there is exactly the wrong-owner failure the
feature exists to prevent. `None` forces the refusal path.

### `detect()`

```
detect(prefix: str, base_prefix: str, environ: Mapping[str, str], argv0: str) -> Detection
```

**Pure — takes every input as an argument and reads no globals.** `sys.prefix` cannot be set
by environment, so an impure version is testable in exactly one mode (`spec.md` AC4). The
caller in `main.py` supplies `sys.prefix`, `sys.base_prefix`, `os.environ`, `sys.argv[0]`.

An unrecognised `FUNCTUALIZE_RUNTIME` value raises rather than falling back — silent fallback
would mask a CI misconfiguration as a degraded install.

---

## `_cli/manifest.py`

### `InstallRecord`

Mirrors one entry of the external file; see `contracts.md` §6 for the wire guarantees.

```
InstallRecord (frozen)
    binary_path          : str
    runtime_mode         : InstallMode
    owning_distribution  : str | None
    python_version       : str
    functualize_version  : str
    plugins              : tuple[str, ...]   # only what `plugin install` added
    packages             : tuple[str, ...]   # only what `self install` added
    first_run_at         : str               # UTC ISO 8601
```

`plugins` is a tuple, not a list — records are immutable, and "add a plugin" rewrites the
record rather than mutating one in place. `packages` is separate from `plugins` rather than a
tagged union: `plugin list` must never show a plain dependency, and `self update` restores
both in one pass, so the distinction has to survive a round-trip through the file.

### `Manifest`

```
Manifest (frozen)
    schema_version : int                       # 1
    installations  : tuple[InstallRecord, ...]
```

**Append-only is a property of the module's API, not of the type**: it exposes `append` and
`replace_record`, and no `remove`. A stale entry is *reported* by doctor, never deleted
(`contracts.md` §6).

**Which of the two an upgrade takes is part of the protocol.** A new installation appends; an
installation already present at the same `binary_path` with a different `functualize_version`
**replaces** its own record. Appending there would accumulate one record per version a single
binary has ever been, which reads as several installations that do not exist.

**Registration is voluntary and its failure is silent.** A read-only config directory, a
container without a writable `XDG_CONFIG_HOME`, a sandbox — each makes registration
impossible. No warning, no non-zero exit, no retry. A registry that interferes with the
command the user typed is worse than no registry.

### The registration marker

Registration is one-shot, and its signature is a **marker file whose existence is the whole
signal** — no content is parsed, so confirming it is a single `stat()`.

```
<user config dir>/installs/<stable key over (binary_path, functualize_version)>
```

| Path | Cost | Work |
|---|---|---|
| marker present | ~3 µs | nothing imported, nothing parsed |
| marker absent | ~1–3 ms, once | import this module, read the registry, append or refresh, write the marker |

**The key covers the version, not only the path — this is load-bearing.** Keyed on
`binary_path` alone, an in-place upgrade goes unnoticed forever: `/usr/local/bin/func` at
0.1.2 registers and writes its marker; upgraded to 0.2.0 the marker still exists, the fast
path short-circuits, and the registry reports 0.1.2 for the rest of time. Including the
version means an upgrade misses the marker, pays one cold registration, and **refreshes** that
installation's record.

The key must cover everything the record asserts that can change under a stable path — today
`binary_path` and `functualize_version`.

The marker is **not** the record. It is a cheap negative cache for "is my current identity
already recorded?", so losing it costs one redundant re-check and never a lost record; it may
be deleted safely.

**Why a marker rather than scanning the registry**: reading the registry is genuinely cheap
(~39 µs for ten installations), but *importing this module* is not — roughly a millisecond of
`@dataclass` codegen per record type. The marker keeps the module off the warm path entirely,
which is what `AC9` pins (`research.md` §1.9).

### Concurrency

Appends are **atomic**: serialize to a temporary file in the same directory and `rename()`
over the target. Two `func` processes starting together must both survive (`AC9b`) —
read-modify-write without atomicity silently drops one, which is exactly the failure
append-only exists to prevent.

### Failure posture

A malformed or unreadable manifest **degrades to empty and records a warning**; it never
raises into a command. The manifest is a convenience record, and a corrupted one must not
make `func` unusable. A higher `schema_version` is treated as unreadable rather than
optimistically parsed.

---

## `_cli/self_cmd.py`

### `CheckStatus` / `Check` / `DoctorReport`

```
CheckStatus(str, Enum)
    OK | WARNING | CRITICAL | INFO

Check (frozen)
    name    : str
    status  : CheckStatus
    detail  : str
    remedy  : str | None

DoctorReport (frozen)
    checks : tuple[Check, ...]
```

**There is no `SKIPPED` status, and that is deliberate.** A check that cannot be performed is
not emitted at all — the plugin-loading check is *absent* until a load-failure record exists
upstream, rather than present-and-skipped (`spec.md` AC12, B3). A skipped check reads as
health that was not observed, which is the failure mode this feature exists to avoid.

`DoctorReport` renders to text or to the `--format json` payload from one structure, so the
two cannot drift.

### Environment capture

Reconciliation compares two captures of the owned environment. A capture is a plain
`name -> version` mapping.

**Read it from `dist-info` directory names, not from package metadata.** Measured on a
214-distribution environment:

| Approach | Cost |
|---|---|
| Parse `*.dist-info` directory names | **2.4 ms** |
| `Distribution.name` / `.version` | 174 ms |
| `Distribution.metadata["Name"]` | 172 ms |

The two metadata routes open and parse every `METADATA` file, for a mapping the directory
name already encodes — 70× the cost for the same 214 entries. Serialized, a capture is ~5 KB.

Names arrive normalized (`functualize_http`, not `functualize-http`), so **both sides must be
normalized the same way** before differencing, or every hyphenated package reads as a user
addition.

Nothing on a normal invocation takes a capture. It happens only inside `self update`.

### Reconciliation

```
before = capture()          # persisted BEFORE the update runs
<update rebuilds the environment>
after  = capture()          # the new baseline the distribution ships

restore = (before.keys() - after.keys())        # by NAME
        | recorded_plugins | recorded_packages   # belt and braces
```

**The difference is over names alone.** A distribution-shipped package appears in both
captures at different versions after an upgrade; differencing over `(name, version)` pairs
would classify it as a user addition and pin it back, silently undoing the upgrade's own
dependency updates.

The manifest's `plugins` and `packages` are unioned in rather than trusted alone: the capture
catches escape-hatch installs the records never saw, and the records survive a capture that
failed. Neither source is sufficient by itself.

`before` is persisted before the update starts. Held only in memory, an update interrupted
between rebuild and restore loses every user addition — which is the failure the whole
mechanism exists to prevent.

### Boot probe

The boot-shaped check runs in a **child process** and reports one of: booted / failed with
captured diagnostics / timed out. A crash in the child is a *result*, not an exception in
doctor.

---

## `_cli/plugin_cmd.py`

### `ExtensionEntry`

```
ExtensionEntry (frozen)
    registered_name : str        # e.g. "inline"
    distribution    : str | None # e.g. "functualize-inline"
    group           : str        # the functualize.* entry-point group
```

Two names, because they differ and both are needed: `loaded_plugins` maps plugin name →
entry-point name (`_plugins/loader.py:249-256`), while `uninstall` needs the distribution.
The mapping does not exist today and is built via `importlib.metadata`.

`group` is carried per entry so `plugin list` can label which of the **eight** groups an
extension came from.

### `Requirement`

For the uv receipt merge.

```
Requirement (frozen)
    name    : str
    extras  : Mapping[str, Any]   # every other key from the receipt entry, verbatim
```

**`extras` round-trips unknown keys.** Observed shapes are `{name}`, `{name, specifier}`, and
`{name, url}`, but the merge must not drop a key it does not recognise — a receipt rewritten
through a lossy parser silently changes what is installed. Reconstruct the PEP 508 string
from every key present.

---

## What is not modelled

| Not a type | Why |
|---|---|
| A doctor "check registry" | The check list is a fixed sequence in one function. A registry would be indirection for one caller |
| A mode→command table type | Expressed as a function returning the command list per `Detection`; a table type adds no invariant |
| Anything for §5 | The binary is a CI artifact. No `src/` code knows it was baked |
| A P1 type | P1 changes a method body on the existing `BuiltinCommand`; it introduces no type and must not widen `CommandNode` |
