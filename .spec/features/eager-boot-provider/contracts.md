# Contracts

**This feature changes no public signature.** Everything it touches is internal
(`_app/boot.py`, `_discovery/registry.py`) or already-public behaviour reached
through an unchanged constructor. That is stated rather than left implicit,
because a fix with no contract surface is a different kind of risk from one that
adds an API: nothing to deprecate, and no host to migrate.

What follows is therefore the **behavioural** contract — the observable
guarantees a library-mode host may rely on — plus the two internal signatures
that change shape.

---

## C1 — the public surface, unchanged

```python
from functualize.app import FunctualizeApp, JobSources
from functualize.app.config import DiscoveryConfig

app = FunctualizeApp(
    "myapp",
    job_sources=JobSources(directories=["./jobs"], lazy=False),
    discovery_config=DiscoveryConfig(require_file_prefix="job_"),
)
```

`JobSources.lazy` keeps its name, its type, and its `True` default.
`DiscoveryConfig` keeps all ten fields. No new parameter, no new keyword, no
deprecation.

**The change is that the second argument now has an effect on the first's
`lazy=False` case.** Before this feature, `require_file_prefix` above was
accepted, validated, used to build a filter, and discarded.

---

## C1b — the import-count guarantee

The one a host can observe without any `DiscoveryConfig` at all:

```
imports(lazy=False, D, S)  ==  one per admitted module
```

independent of how many providers the pipeline holds. A module-level side
effect in an admitted job module runs **exactly once** per boot.

This is a behavioural fix, not an addition, and it is the contract most likely
to be relied on: `lazy=False` is documented as the path for import-time side
effects, and a side effect that fires twice is indistinguishable from a bug in
the host's own module.

Note it changes with the *presence of a second provider*, which is why it is
stated as an absolute rather than as a comparison against today: today's count
is 1 with directories alone and 2 with `functions=[...]` or a child project.

## C2 — the guarantee `lazy=False` makes

For any `DiscoveryConfig` **D** and directory set **S**:

```
jobs(lazy=False, D, S)  ==  jobs(lazy=True, D, S)
```

Set equality of `descriptor.name`, not merely "both are filtered". The two paths
differ in *when* work happens, never in *what is discovered*.

The escape hatch's own promises are unchanged and are part of this contract:

| Guarantee | Status |
|---|---|
| Every **admitted** job module is imported at boot | kept |
| Import-time side effects of admitted modules run at boot | kept |
| DI validation happens at boot, not at first use | kept |
| A module **excluded** by the configuration is imported | **withdrawn** — this is the fix |
| An admitted module is imported once, not once per provider | **new** — see C1b |

The last row is the only behavioural break, and it is the point: an excluded
module contributing import side effects is the bug, not a feature. It is called
out here because a host relying on a side effect in an excluded module would see
it stop running.

---

## C3 — `_registered_commands` key spelling

```python
# functualize/_discovery/registry.py — JobRegistry
_registered_commands: dict[str, str]      # "<group or __top__>::<name>" -> module path
```

`<name>` is the **canonical descriptor name** (`deploy-thing`) on every
registration path. The eager path currently writes the Python attribute name
(`deploy_thing`), which no consumer expects:

| Consumer | Expects |
|---|---|
| `app/core.py:496` — `refresh()` | canonical; compares against `descriptor.name` |
| `app/adapters/cli.py:1264` — `_show_job_config` | canonical; matches a user-typed job name |
| `app/adapters/cli.py:1191` — `builtin info` job table | display only; either spelling renders |

This is a behavioural change for a library-mode host that read
`_registered_commands` directly — a private attribute, so no compatibility
promise applies, but the keys visibly change spelling for underscore-named jobs.

---

## C4 — internal call shape

The eager branch of `resolve_and_register_jobs` stops calling:

```python
JobRegistry.scan_and_register_headless(jobs_paths: list[str],
                                       module_filter: set[str] | None = None) -> None
```

and instead registers the descriptors the pipeline's directory provider yields,
mirroring `_register_jobs_lazy`:

```python
provider.list_jobs() -> Sequence[JobDescriptor]   # filtered at construction
register_descriptors(app, descriptors) -> None
```

`scan_and_register_headless` **is not removed and not deprecated.** Its second
caller — the defensive fallback in `_register_jobs_lazy` when no cached provider
was wired — is out of scope, so the method keeps its signature and its
docstring gains a note that it applies no discovery filter.

`_sync_registry_to_engine` is called only by paths that use
`scan_and_register_headless`; whether it is still needed on the eager branch is
an implementation question for `plan.md`, not a contract.

---

## C5 — what a test may rely on

Two seams, so the acceptance criteria can be asserted without reaching into
boot internals:

- `app.get_jobs()` — the job set, on both paths.
- A module-level side effect (`print`, a file write, a module-scope append) —
  the only honest way to assert *"this module was not imported"*, since a job
  list cannot distinguish "imported and filtered out" from "never imported".
  A4 depends on that distinction and must use a side effect.
