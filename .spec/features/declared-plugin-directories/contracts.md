# Contracts — `declared-plugin-directories`

External interfaces only: what a user or a plugin author writes, and what the
package exports. Internal helper shapes are Plan's (`schema.md`) and are
deliberately absent here.

---

## 1. Config surface — `[tool.functualize] plugins_directories`

**Already declared, already documented, currently inert.** This feature changes
its *behaviour*, not its spelling. No key is renamed and no key is added.

### 1.1 The declaration

```toml
# pyproject.toml
[tool.functualize]
plugins_directories = ["/srv/shared/.functualize/plugins", "../team-plugins"]
```

```toml
# .functualize.toml  (standalone form — keys at the root, no [tool.functualize])
plugins_directories = ["plugins"]
```

| Property | Value |
|---|---|
| Key | `plugins_directories` |
| Section | `tool.functualize` (in `pyproject.toml`); root (in `.functualize.toml`) |
| Type | `list[str]`; a bare `str` is accepted and wrapped — **unchanged**, `loader.py:733` does this today |
| Default | unset |
| Relative paths | resolved against the config anchor (walk A's anchor: the nearest ancestor carrying a config file) |
| `..` segments | permitted, per ADR-013 |
| Absolute paths | permitted |
| Inherited from an ancestor | yes — walk A merges layers nearest-first up the tree |
| `root = true` | stops that inheritance at the declaring directory, as it already does for `jobs_directories` |
| Composition | **additive** with the convention directory, declared scanned first (`spec.md` §C.2) — this is a **change**; today a declared value returns early and suppresses the convention directory |

### 1.2 Precedence

`plugins_directories` joins the list-key precedence chain that
`resolve_effective_directories` already implements for `jobs_directories` and
`import_libs`:

```
CLI  +  ENV  +  File  +  Convention  +  Global  +  Defaults
```

*File* is walk A's merged layers; *Global* is `~/.config/functualize/config.toml`.
Both already produce the right answer for this key today — measured — and are
then discarded (`research.md` §6.1, §5.5). This feature connects that result to
the loader; it does not re-invent the ordering.

**`root = true` bounds the File layer, not the Global one.** Measured: with
`root = true` set at an intermediate level and `plugins_directories` declared in
the XDG config, the XDG value still resolves. That is existing, deliberate
behaviour shared with every other list key, and it is stated here because it is
not obvious from the key name.

Whether a CLI flag and an environment variable are *exposed* for this key is
Plan's call.

### 1.3 Convention directory

| Before | After |
|---|---|
| `Path.cwd() / ".functualize" / "plugins"` — exact match only | `<project root>/.functualize/plugins/`, where `<project root>` is walk C's anchor (`find_functualize_dir`) |

**Bound: the project root.** The search stops at the first ancestor holding a
`.functualize/` directory — the same one the app already reports as
`Mode: project (.functualize/ found at …)` and already writes `fresh.json`,
`scopes.json` and `cache.json` into. It does not continue to the filesystem root.

A project with no `.functualize/` above it has **no** convention directory,
rather than one picked from an arbitrary ancestor.

---

## 2. `PluginSources` — public dataclass

`functualize.app.config.PluginSources`, re-exported publicly.

```python
@dataclass(frozen=True)
class PluginSources:
    entry_point_group: str = PLUGINS
    explicit_plugins: list[Any] | None = None
    disabled: list[str] | None = None
    ambient_directory: bool = True
```

**No field is added, removed, renamed or re-typed.** The signature is frozen by
this feature.

`ambient_directory` keeps its meaning and gains reach: `False` declines the
convention directory **at every level of the upward walk**, not only at the
literal cwd. That is the same rule applied to a wider search, and it is what the
field's own docstring already promises —

> `[tool.functualize] plugins_directories` is declared and is unaffected; only
> the convention fallback is refused.

— a sentence that is false today, because the declared half never loads at all.

---

## 3. Plugin-author surface — unchanged

A file plugin is any object carrying `name`, `version`, `description` as
strings and being callable, exposed either as a module-level `plugin` attribute
or found by module inspection (`loader.py:803-872`).

```python
class RunNotifier:
    name = "run-notifier"
    version = "1.0.0"
    description = "Announces job success and failure on the event bus."

    def __call__(self, app) -> None: ...

plugin = RunNotifier()
```

| Rule | Status |
|---|---|
| Files starting with `_` are skipped | unchanged |
| `*.py` at the directory's top level only, no recursion | unchanged |
| Files sorted case-insensitively by name | unchanged |
| Entry-point plugin outranks a file plugin of the same name | unchanged |
| First file plugin loaded under a name wins; later ones warn and skip | unchanged — now applies **across** directories, declared before convention |
| `depends_on` topological ordering | unchanged |
| PEP 440 `version` validation | unchanged |
| A plugin whose `__call__` raises is warned about and skipped; boot continues | unchanged |

---

## 4. Domain config surface — `[<domain>] provider`

```toml
[storage]
provider = "sqlite"
```

| Property | Value |
|---|---|
| Key | `provider` |
| Section | the domain's declared `config_section` |
| Type | `str`, stripped; empty or whitespace-only is treated as unset |
| Before | **never read** — `_read_configured_provider` is guarded by an always-`False` `hasattr`, measured |
| After | read at boot; selects that provider |

No key changes. This is a dead branch coming alive, and it is a **behaviour
change for any project that already wrote the key and has been silently getting
the default** — the same shape as the `functualize-ai` precedent
(`research.md` §2.4), which was accepted on those terms.

---

## 5. Diagnostic output

New observable output, per `spec.md` AC-6 / AC-6b / AC-6c.

**Level: `WARNING`**, on a default run with no flags — following the precedent
at `_app/boot.py:775-786` for an unreadable config file.

```
WARNING  Declared plugin directory does not exist: /srv/shared/.functualize/plugins
WARNING  Declared plugin directory contains no loadable plugin: /srv/shared/.functualize/plugins
```

| Case | Output |
|---|---|
| declared directory missing | `WARNING`, names the path |
| declared directory present, no loadable plugin | `WARNING`, names the path |
| convention directory absent | **silent** — the ordinary case, must not warn |
| convention directory present but empty | silent |

Contractual: the level, the fact that the message **names the path**, and that a
declared directory yielding nothing is distinguishable from no directory being
configured. Exact wording is not contractual.

---

## 6. Exported symbols

No addition to or removal from any `__all__` in the public surface is required
by this spec.

Two internal call sites change behaviour behind that surface:

| Symbol | Module | Change |
|---|---|---|
| `PluginLoader._resolve_plugin_directories` | `functualize._plugins.loader` | private; body changes, may be replaced entirely (`spec.md` AC-9) |
| `_read_configured_provider` | `functualize._plugins.domain_registry` | private; guard removed |

`functualize.app.utils.resolve_effective_directories` is currently exported in
`__all__` with **zero production callers**. If AC-9 is satisfied by routing the
loader through it (or through a primitive extracted from it), its export status
changes from decorative to load-bearing. Whether the symbol itself moves is
Plan's decision and will be recorded there; **this spec does not authorise
removing it from the public surface.**

---

## 7. Layer constraints on any implementation

Not an interface, but binding on what the contracts above may be implemented
with — stated here because it eliminates the obvious shortcut.

`_plugins/loader.py:11`: *"Only imports from `_types/`, `_primitives/`,
`_events/`, and Python stdlib."*

| Target | Legal from `_plugins`? | Why |
|---|---|---|
| `functualize._config` | **no** | import-linter *"Peer layers are independent"* (`pyproject.toml:244`) |
| `functualize.app.utils` | **no** | import-linter *"Internal never imports public"* (`pyproject.toml:303`) |
| `functualize._primitives` | yes | foundation; already hosts **both** primitives this feature needs — `ResourceLocator` (`locator.py:74`), which walk A is built on, and `find_functualize_dir` (`cache_format.py:289`), which is walk C. The likely home for the extracted shared resolver. |
| `functualize._types` | yes | foundation |
| stdlib `tomllib` | yes | — |

`AC-13` gates this: `uv run lint-imports` must pass with no new edge.
