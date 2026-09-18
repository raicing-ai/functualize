# Schema — `declared-plugin-directories`

Internal types only. The external surface is [`contracts.md`](contracts.md); no
public signature changes, and no database or on-disk format is touched.

---

## 1. `ProjectDirectories` — the one read's result

`src/functualize/_config/project_dirs.py`

```python
@dataclass(frozen=True)
class ProjectDirectories:
    """What one walk-A read of the project yields, resolved once at boot.

    Produced by `resolve_project_directories()` at boot step 3.5 and handed to
    the two consumers that run before the resolution chain exists. Frozen: the
    composition root reads it and passes parts of it on; nothing edits it.
    """

    anchor: Path
    """Nearest ancestor carrying a project config file. Relative declared
    paths resolve against this. Equals `cwd` when no config file was found."""

    project_root: Path | None
    """Walk C's answer — the nearest ancestor holding a `.functualize/`
    directory, or None in standalone mode. The convention plugin directory is
    `project_root / ".functualize" / "plugins"`, and this is what bounds the
    convention search (`spec.md` AC-3b)."""

    merged: dict[str, Any]
    """Walk-A config layers deep-merged nearest-first, `root = true` honoured
    and the key stripped. The domain registry reads `[<section>].provider`
    out of this (§6.5 of plan.md)."""

    plugin_directories: tuple[str, ...]
    """Absolute, de-duplicated, declared-before-convention. Empty tuple means
    no file-plugin discovery. A tuple rather than a list so the frozen
    dataclass is actually immutable."""
```

**Why a dataclass and not a 4-tuple.** Three of the four fields are consumed by
different call sites at different boot steps; positional unpacking at each would
be *primitive obsession* with extra steps.

**Why not reuse `DiscoveryResult`** (`app/utils.py:348`). That type lives in the
**public** package, and `_app/` may not import it — import-linter *"Internal
never imports public"*. It also carries `job_sources`, which boot step 3.5 has no
business building.

### 1.1 Field provenance

| Field | Walk | Source function |
|---|---|---|
| `anchor` | A | `ResourceLocator().search_upward(start=cwd)` + `PROJECT_CONFIG_CANDIDATES` |
| `merged` | A | `merge_config_layers(layers)` — `root = true` applied here |
| `project_root` | C | `find_functualize_dir(cwd)` (`_primitives/cache_format.py`) |
| `plugin_directories` | A + C | `resolve_effective_directories(...)["plugins_directories"]` then the convention directory appended |

---

## 2. `resolve_plugin_directories` — the composition rule

```python
def resolve_plugin_directories(
    *,
    anchor: Path,
    merged: dict[str, Any],
    project_root: Path | None,
    ambient_directory: bool = True,
    global_config: dict[str, Any] | None = None,
) -> tuple[list[str], list[str]]:
    """Return (declared, convention) as two lists, in scan order.

    Returned separately rather than pre-concatenated because the caller must
    warn about a declared directory that yields nothing (AC-6/AC-6b) and stay
    silent about an absent convention one (AC-6c). A single merged list cannot
    tell them apart.
    """
```

**Order is contractual** (`spec.md` §C.2): declared first, convention second. The
loader's existing first-wins duplicate-name rule then resolves collisions across
both without change.

**`ambient_directory=False` suppresses the convention list only.** The declared
list is untouched — which is what `PluginSources`'s own docstring already
promises and what this feature makes true.

---

## 3. `FilePluginSource` — extracted collaborator

`src/functualize/_plugins/file_source.py`

```python
class FilePluginSource:
    """Scans directories for file-based plugins.

    Extracted from `PluginLoader` (plan.md §6.6): 595 LOC exceeded the
    constitution's ~500 bar, and these three methods are one cohesive
    responsibility — the on-disk plugin file format.

    Takes no `app`. Its inputs are paths and its output is plugin objects,
    which is what makes it testable without a mock application.
    """

    def discover(self, directories: Sequence[str]) -> list[Any]: ...
    def _load_file_plugin(self, py_file: Path) -> Any | None: ...
    def _find_plugin_in_module(self, module: Any) -> Any | None: ...
```

**Not a Protocol.** It is a concrete collaborator with one implementation, not a
port. `.spec/CONSTITUTION.md` forbids ABCs *for ports*; inventing a Protocol for
a single implementation would be speculative generality.

**Held by `PluginLoader` as a plain attribute** (`self._file_source = FilePluginSource()`),
constructed in `__init__`. Composition, not inheritance.

### 3.1 Behaviour preserved exactly

Moved verbatim, gated by the existing tests once retargeted:

| Rule | Where it lives now |
|---|---|
| top-level `*.py` only, no recursion | `discover` |
| files starting with `_` skipped | `discover` |
| case-insensitive sort by filename | `discover` |
| first plugin under a name wins; later ones warn and skip | `discover` |
| non-existent directory logs debug and continues | `discover` — **now also the caller's warning**, AC-6 |
| module-level `plugin` attribute preferred, else inspect members | `_load_file_plugin` |
| PEP 440 `version` validation via `_validate_metadata` | `_load_file_plugin` |

---

## 4. Changed signatures — internal only

```python
# _plugins/loader.py
def load_all(
    self,
    app: Any,
    *,
    directories: Sequence[str] | None = None,     # NEW, keyword-only
    event_bus: Any = None,
    perf_timeline: Any = None,
    disabled: set[str] | None = None,
    explicit: Sequence[Any] | None = None,
) -> None: ...
```

`directories=None` means **scan nothing**. Today the equivalent call reaches
`Path.cwd()`, which silently couples 38 unit-test call sites to the working
directory; the default makes that coupling explicit and absent.

```python
# _plugins/domain_registry.py
def _read_configured_provider(
    config: Mapping[str, Any],            # was: app: Any
    metadata: DomainMetadata,
) -> str | None: ...

def boot_domain_registry(
    app: Any,
    *,
    config: Mapping[str, Any] | None = None,   # NEW
) -> DomainRegistry: ...
```

### 4.1 `DiscoveryResult` is deliberately **not** changed

`research.md` §2.1a records that `auto_discover` computes
`effective["plugins_directories"]` and discards it, and an earlier draft of this
schema added the field to `DiscoveryResult` to close that.

**Reverted during the architecture gate.** Once `_config/project_dirs.py` is the
resolver and `_app/boot.py` calls it directly, nothing consumes a
`plugins_directories` field on `DiscoveryResult` — the CLI builds a
`FunctualizeApp` and boot resolves for itself. Adding it would be
**speculative generality** (`ch35`): a field created "just in case", with no
caller, in a public dataclass.

The discard stops being a defect the moment the value is no longer that
function's job. It is left exactly as it is.

---

## 5. Moved symbols

| Symbol | From | To | Left behind |
|---|---|---|---|
| `_CANDIDATES` | `app/utils.py:635` | `_config/project_dirs.py` as `PROJECT_CONFIG_CANDIDATES` | — |
| `_extract_functualize_section` | `app/utils.py:373` | `_config/project_dirs.py` | — |
| `resolve_project_config` | `app/utils.py:536` | `_config/project_dirs.py` | wrapper |
| `_collect_convention_directories` | `app/utils.py:820` | `_config/project_dirs.py` | wrapper |
| `resolve_effective_directories` / `_resolve_effective_directories` | `app/utils.py:617,685` | `_config/project_dirs.py` | wrapper (in `__all__`) |
| `_flatten_dedup_resolve`, `_convention_subdir_name` | `app/utils.py:418,408` | `_config/project_dirs.py` | — |
| `_read_toml_file` | `app/utils.py:1065` | `_config/project_dirs.py` | wrapper if referenced |
| `resolve_user_config_dir` | `app/utils.py:1033` | `_primitives/locator.py` as `xdg_config_dir` | wrapper (in `__all__`) |

`merge_config_layers` **does not move** — it is already in `_config/`, and
`app/utils.py` already imports it from there (`utils.py:24`).

**Net effect on `app/utils.py`:** ≈ −220 LOC, 2380 → ≈2160. Still a god module
(`plan.md` §8.4), but smaller, and the reduction is a side effect of putting the
logic where both layers can reach it rather than a goal pursued for its own sake.
