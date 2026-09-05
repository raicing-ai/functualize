# Contracts — Seams for a third-party host package

Every item here is new public surface. Signatures are the contract; module
placement follows the constitution's audience split (public folders only:
`app/`, `job/`, `plugin/`, `types/`, `testing/`).

## S1 — discovery pre-filter hook

```python
# functualize/plugin  (protocol lives with the other extension protocols)
@runtime_checkable
class ModulePreFilter(Protocol):
    def accepts(self, path: Path, source: str) -> bool:
        """Return whether this module should be imported for discovery."""

    def fingerprint(self) -> str:
        """Stable identity of this filter's logic, for cache invalidation.

        Must be identical across processes for identical behaviour, and must
        change when the predicate's behaviour changes.
        """
```

**`fingerprint()` is load-bearing, not decorative** (decided 2026-09-05). The
discovery cache persists negative pre-filter decisions and replays them,
trusting them only while the discovery fingerprint matches. A caller-supplied
predicate cannot participate in that hash by identity:
`_normalize_discovery_value` renders an unknown value with `str()`, and
`str()` of a function is `'<function p at 0x7fd949036160>'` — address-bearing
and different in every process. Hashing the object invalidates the cache on
every boot; omitting it reproduces the X1–X4 replay bug that `CACHE_VERSION`
15→16→17 and ADR-010/ADR-011 exist to close.

A host that forgets to bump its fingerprint gets a stale cache — the same
contract as any cache key, and the same failure the `require_*` fields already
have when a config is edited without invalidation.

```python
# functualize/app/config.py
@dataclass(frozen=True)
class DiscoveryConfig:
    exclude_patterns: tuple[str, ...] = ()
    extra_directories: tuple[str, ...] = ()
    require_file_prefix: str | None = None
    require_file_postfix: str | None = None
    require_file_import: str | None = None
    require_file_marker: str | None = None
    require_job_decorators: tuple[str, ...] | None = None
    require_job_prefix: str | None = None
    require_job_postfix: str | None = None
    pre_filter: ModulePreFilter | None = None      # NEW — the tenth field
```

The tenth field is not free. `_DISCOVERY_FINGERPRINT_FIELDS`
(`_discovery/filter_factory.py:187`) mirrors these names exactly, and
`tests/discovery/test_discovery_hash.py:101` asserts set equality between the
two with the docstring *"Guard against a tenth setting being added and silently
uncovered."* The field contributes `pre_filter.fingerprint()` to the digest —
never the object.

Composition is AND, matching the docstring's existing rule: a module is
imported when every set constraint accepts it. `None` means no constraint.

`ModulePreFilter` is the name `_primitives/pre_filter.py` already uses
internally (`ASTModulePreFilter`, `DisplayClassPreFilter`,
`GroupOptionsPreFilter` implement it) — this promotes the existing shape
rather than inventing one.

## S2 — install detection and package operations

```python
# functualize/app/packaging.py  (new public module)

class InstallMode(StrEnum):
    """How a tool is installed. Serializes to the documented spelling."""

@dataclass(frozen=True)
class Detection:
    """The answer to 'is it installed, how, and where'."""

def detect(tool: str = "functualize") -> Detection: ...

@dataclass(frozen=True)
class Requirement: ...

def install_commands(req: Requirement, mode: InstallMode) -> list[list[str]]: ...
def update_commands(req: Requirement, mode: InstallMode) -> list[list[str]]: ...
def uninstall_commands(req: Requirement, mode: InstallMode) -> list[list[str]]: ...
```

These names already exist and are already `__all__`-listed in their private
modules — `_cli/runtime.py:34` exports `Detection`, `InstallMode`,
`RuntimeOverrideError`, `detect`; `_cli/package_ops.py:43` exports
`Requirement`, `install_commands`, `update_commands`, `uninstall_commands`,
`plan_or_exit`, `refuse`, `capture_environment`, `announce`,
`names_to_restore`, `normalize`, plus three error types.

**Not** promoted: `plan_or_exit`, `refuse`, `announce`. They call `SystemExit`
and write to a terminal — delivery concerns that belong in `_cli`. A host
composes its own refusal from `Detection` plus the command lists.

The manifest API (`_cli/manifest.py:39` — `Manifest`, `InstallRecord`,
`record_addition`, `recorded_additions`, `forget_addition`, `register`,
`manifest_path`, `marker_path`, `SCHEMA_VERSION`) is **deferred**: it records
what *functualize* installed into its own environment, and a host recording
into that same manifest is a decision this feature does not make. Tracked in
`plan.md` §4.

## S3 — third-party skill hosting

```toml
[project.entry-points."functualize.skills"]
mypackage = "mypackage._skills"
```

The value is an importable package whose directory holds skill directories —
the same shape as functualize's own `_skills/`, resolved with
`importlib.resources` rather than a path relative to `__file__`.

```python
# functualize/_cli/skills.py — signature changes

@dataclass(frozen=True)
class SkillsLocation:
    path: Path
    origin: str          # "package" | "checkout" | "entry-point"
    distribution: str    # NEW: the distribution that provided it
    version: str         # NEW: that distribution's version, for stamping

def resolve_skills_locations() -> list[SkillsLocation]:
    """Core's own location first, then every registered entry point."""

def resolve_skills_dir() -> SkillsLocation | None:
    """Core's own location. Retained — 3 call sites migrate to the plural."""
```

### `skills path` becomes multi-line — breaking, and deliberate

Decided 2026-09-05. `path` iterates like `list`, `materialize` and `install`,
printing one location per line.

This breaks two shipped single-value consumers, which change in the same task:

| Site | Today | Why it breaks |
|---|---|---|
| `_cli/builtins.py:1496` docstring | *"one path, no decoration, so it composes: `npx skills add "$(func builtin skills path)"`"* | the promise is no longer true |
| `README.md:924` | `cp -R "$(func builtin skills path)"/* .claude/skills/` | two lines substitute as one argument; `cp` fails with "No such file or directory" |

Replacement idiom:

```bash
func builtin skills path | while read -r d; do
  cp -R "$d"/* .claude/skills/
done
```

The pre-release stance permits the break; leaving the README publishing a
command that no longer works does not.

`materialize_skills` stamps per source:
`$XDG_DATA_HOME/functualize/skills/<distribution>-<version>/<skill-name>/`.
Core's own tree keeps its current `func-<version>` spelling so existing agent
configs pointing at it do not break.

A malformed or missing entry point is skipped with a warning, never fatal —
one broken third-party package must not take `func --help` down with it.

## S4 — `job_detail` declaration fields

```python
{
    # ... the 12 existing keys, unchanged ...
    "tags": ["deploy", "safe"],           # NEW
    "examples": ["func deploy --env prod"],  # NEW
    "extra_description": "…" | None,      # NEW
    "category": "deployment" | None,      # NEW
}
```

Additive. `tags` and `examples` are lists (never `None`) — empty when the job
has none, so a consumer need not guard. `extra_description` and `category` are
`None` when unset, matching `JobDeclaration`'s own defaults.

A job discovered by convention has `declaration is None`; it renders as
`[]`, `[]`, `None`, `None`.

`job_catalog` — the shallow listing — is **unchanged**. It is documented as
"deliberately shallow"; tags belong in the deep view.

## S5 — `[tool.functualize] skill`

```python
# functualize/_cli/pep723.py
_KNOWN_TOOL_KEYS = frozenset({"job", "skill"})
```

```python
@dataclass(frozen=True)
class ScriptMetadata:
    job: str | None
    skill: str | None    # NEW — parsed, exposed, not yet consumed
```

Accepting the key is the contract. What reads it is out of scope
(`spec.md`).
