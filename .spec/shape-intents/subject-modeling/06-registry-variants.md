# 06 — Registry, Variants & Repositories

Rise's registry — tool → variant, smart router, lockfile — plus the thing the
three-axis vocabulary newly makes possible: **repositories as managed
subjects**.

## 1. Structure

The registry is a package of rise module classes, discovered through the same
two channels as any other rise module (`03` §6) and mounted under the
`registry` group. "The registry is a module like any other" holds literally:
the router is a rise class, bound by the same adapter, carrying the same
inherited `diagnose`/`validate`.

It is **not** a functualize child project — children mount as a directory scan
of `<child>/jobs` and never run their own wiring (`00` fact 6).

## 2. Variants are subclasses

```python
class Jsonschema(Executable, Installable, Runnable):   # the tool's contract
    group = "registry.jsonschema"

class JsonschemaPip(Jsonschema):
    variant = "pip"
    isolation = Isolation.PROJECT

    @job(guards=Guards(status=[jsonschema_present]),
         cache=Fingerprint(generates=[".risekit/lock/jsonschema.json"]))
    def install(self, sh: Shell, log: Log) -> None: ...

class JsonschemaBrew(Jsonschema):
    variant = "brew"
    isolation = Isolation.HOST                          # → the confirm flow (08 §3)
```

Variants are strategies **behind one tool group**, selected by `--variant`.
That is what keeps the listing fixed-size (criterion 33): `rise registry --help`
grows one line per tool, never per strategy.

## 3. The router

```toml
[tools.jsonschema]
host_variants    = ["brew"]      # machine-scoped, tried first
project_variants = ["pip"]       # project-scoped, second
```

```python
def resolve_variant(tool: str, explicit: str | None) -> VariantChoice:
    if explicit:
        return VariantChoice(explicit, resolved_by="user")
    lock = read_lock(tool)
    if lock and lock.resolved_by == "user":
        return VariantChoice(lock.selected_variant, resolved_by="user")
    if lock and lock_agrees_with_truth(lock, diagnose_tool(tool)):
        return VariantChoice(lock.selected_variant, resolved_by="auto")
    for name in host_variants(tool) + project_variants(tool):
        if variant_available(name):
            return VariantChoice(name, resolved_by="auto")
    raise NoVariantAvailable(tool)              # → exit 3
```

An isolation change between the lockfile and reality counts as drift and
re-detects — the subtle case the intent calls out.

## 4. Which guard is which

The rule the whole registry follows:

| Situation | Guard | Verdict | Exit |
|---|---|---|---|
| already installed | `Guards(status=[…])` | `SKIPPED` | **0** |
| lockfile fresh, outputs present | `Fingerprint(generates=[…])` | `SKIPPED` | **0** |
| no variant available | `Guards(preconditions=[…])` | `REFUSED` | **3** |
| host install declined | raise | job raised | 1 |
| destructive test outside isolation | `Guards(preconditions=[…])` | `REFUSED` | **3** |

**A status guard says "nothing to do"; a precondition says "I refuse to try."**
Getting this backwards makes `bootstrap` abort on the first already-installed
tool. **[probed]**

Install jobs declare `generates` only, no `sources`, so `has_file_signal` is
false and the status guard decides alone (`_engine/guards.py:192`) — an install
should not re-run because an unrelated source file changed.

## 5. The lockfile

```python
class Lockfile(BaseModel):
    model_config = ConfigDict(extra="forbid")
    format_version: Literal[1] = 1
    tool: str
    selected_variant: str
    isolation: Isolation
    resolved_at: datetime
    resolved_by: Literal["auto", "user"]
    user_choice: str | None = None
    installed: InstalledInfo
```

At `<project>/.risekit/lock/<tool>.json`, and also the install job's declared
`Fingerprint(generates=…)` output — so a deleted lockfile forces a run under
every fingerprint method (`_types/job_declaration.py:186`) and the ledger
cannot claim freshness the lockfile does not support.

## 6. Repositories as subjects — new in v3

A required sibling repository is a rise module like any other:

```python
class ServiceRepo(Repository, Syncable):
    group = "repos.service"
    url = "https://github.com/acme/service"
    rev = "main"
    isolation = Isolation.PROJECT
```

It needs **no new machinery** — the registry contract maps across cleanly:

| Registry concept | For a tool | For a repository |
|---|---|---|
| tool | `jsonschema` | `acme/service` |
| variant | `pip`, `brew` | `https`, `ssh`, `gh`, `worktree` |
| `install` | install the binary | clone (or add a worktree) |
| availability | is `brew` on PATH? | is `gh` authenticated? host reachable? |
| lockfile `installed` | version, path, origin | **resolved sha**, path, remote |
| idempotency | status: already installed | status: tree present **and at the declared rev** |
| `bootstrap` | install every tool | clone every declared repo |

So `rise bootstrap` in a fresh clone brings up the toolchain **and** the
declared sibling repositories, with a lockfile recording exactly which
revisions were obtained. That is an action rise did not have, and it falls
out of an existing design once `Repository` is a substrate.

The distinction from `Syncable`-as-reflexive: `ServiceRepo` **is** the
repository (substrate). A module that *acts on* a repository declares a
`target` instead (`01` §5) and claims no action at all.

## 7. Libraries

Same router contract; the installed-probe is `find_spec` so installation is
proved by import (criterion 22), and `variant_available` checks the package
manager in the project environment. But see `07` §6: a `Package` substrate
carries a `source` discriminator, and `source="project"` dependencies are
**read** from `pyproject.toml` rather than declared twice.

## 8. Command surface

| Intent (colon era) | risekit |
|---|---|
| `registry:jsonschema:install` | `rise registry jsonschema install` |
| `registry:jsonschema:install:pip` | `rise registry jsonschema install --variant pip` |
| `registry:list` / `status` / `lock` | `rise registry list` / `status` / `lock` |
| `registry:audit` | `rise registry audit` |
| `registry:scaffold item` | `rise new variant <tool> <strategy>` (`09` §4) |

In the guest delivery each is prefixed `func rise …` (`04` §3).
