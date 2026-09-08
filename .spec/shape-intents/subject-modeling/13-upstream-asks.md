# 13 — What functualize Should Add

> **Read the Summary at the bottom first. Asks 1–8 have shipped.** The five
> sections below are the arguments as made against 0.2.3 (`a2f453d`) and are
> preserved as the record, not as open work — §1 through §5 all read as though
> the defect they describe is live, and four of them are visible as *fixed* in
> the probe re-run at `787035e` (`evidence/README.md`). Only **asks 9 through 12**
> are outstanding.

Five asks, re-prioritized for 0.2.3 and for the plugin binding path. **None is
a blocker any more** — v2's blocker (P1) is bypassed by binding through a
plugin provider (`03` §1), which is the single most useful thing this revision
found.

Ordered by value to any framework built on functualize, not just to rise.

> **Decided: all five land upstream.** Asks 3 and 4 are sequenced *before* the
> rise features that would otherwise need workarounds — see `11` §2 and
> `14` §5.

---

## 1. `register_dynamic_job` must extract parameters

**Severity: correctness. Was v2's blocker; now a defect rise routes around.**

`_app/impl.py:732` builds its descriptor with `parameters=[]`, hard-coded:

```diff
-        parameters=[],
+        parameters=extract_parameters_from_signature(function),
```

`extract_parameters_from_signature` (`_discovery/providers.py:64`) is what
every other registration door uses; it already skips `self`/`cls`, excludes
capability and `GroupOptions` parameters, and handles `Arg`/`Option`/`Stdin`
markers and `Secret` annotations. The dynamic door is the outlier.

The consequence is not cosmetic: the descriptor **misreports the function it
wraps**, so `builtin info schema`, completion and the MCP tool surface publish
a dynamically registered job as taking no arguments **[probed]**.

This is the third instance of one bug shape in the same file family.
`_primitives/capability_names.py` exists because "`Shell` was missing from the
discovery scan's copy"; `adopt_descriptor_declaration` (`_app/boot.py:1026`)
exists because "`declaration=JobDeclaration(cache=...)` silently did nothing"
for hand-built descriptors. Both were fixed by making the second path agree
with the first. `parameters=[]` is the same thing, unfixed.

## 2. Honour or delete `JobSources.job_providers` — and warn on dropped `functions`

**Severity: correctness of the public API surface.**

`app/config.py:56` declares `job_providers` and documents it as "custom
JobProvider instances with optional transforms". It is read **nowhere** — two
grep hits, both inside the dataclass **[probed]**, on 0.1.2 and 0.2.3 alike.

Related and worse, because it is silent: `JobSources(functions=…)` is honoured
only inside `boot_static` (`_app/boot.py:242`), reachable only when
`is_fully_explicit()` holds (`_app/impl.py:213`). A project that sets
`functions` **and** `directories` has its `functions` discarded with no
message **[probed]**.

Three options, any of which is an improvement:

1. Wire both on the standard path, beside the child-project providers.
2. Keep the restriction and **warn** at boot when a declared source is dropped.
3. Delete `job_providers` and document the restriction on `functions`.

A declared, documented, ignored configuration field is worse than an absent
one: it reads as supported, and it cost this design a full revision to
discover.

> The plugin seam (`add_job_provider` during `__call__`) already works and is
> what rise uses. This ask is about the *declared* surface matching the *real*
> one.

## 3. A pre-filter hook on `DiscoveryConfig`

**Severity: feature addition. The one that unlocks class-shaped frameworks.**

`DiscoveryConfig` (`app/config.py:126`) has nine `require_*` fields and no way
to contribute a `ModulePreFilter`, so a module declaring only classes cannot be
made discoverable from outside the package: `ASTModulePreFilter` requires a
top-level public **function** (`_primitives/pre_filter.py:110`) **[probed]**.

functualize has solved this exact shape twice for its own class-based
features — `DisplayClassPreFilter` (`:126`) and `GroupOptionsPreFilter`
(`:163`) both admit a file because a top-level *class* carries a signal. The
pattern is established; only the extension point is missing:

```python
DiscoveryConfig(extra_pre_filters=[RiseModulePreFilter()])
```

rise does not need it — explicit module lists work today (`03` §6) — but any
framework that models things as classes rather than functions hits this wall,
and rise modules stay second-class on disk without it.

## 4. Make install detection and package operations importable

**Severity: reuse. New in 0.2.3.**

`_cli/runtime.py`, `_cli/package_ops.py` and `_cli/manifest.py` implement
install-mode detection, per-mode install/uninstall/update command planning,
environment capture and restore, and a versioned voluntary registry with atomic
writes and lock handling — ~1,700 tested lines with an ADR.

They converged independently on three of rise's registry decisions:

| functualize 0.2.3 | rise concept |
|---|---|
| `InstallMode` with a `degraded` property | isolation + the refusal predicate |
| `refuse(detection, what)` → guidance, nothing run, **exit 3** | the host-guard refusal contract |
| `install_commands` / `uninstall_commands` / `update_commands` | the variant router for packages |
| `manifest.py` — one voluntary `install.json`, versioned, atomic | the lockfile |
| `LossyReceiptError` — an unreproducible receipt is *refused, not approximated* | lockfile drift detection |

All of it is private to `_cli/`, so an application built on functualize can
*invoke* it as CLI commands but cannot *use* it **[probed]** — and any
application that installs packages reimplements it.

The narrow ask, in preference order:

1. Re-export the read-only, dependency-light core through a public module —
   `Detection`, `InstallMode`, `detect_from_process`, and the manifest record
   types. Pure classification and file I/O; no CLI dependency.
2. Optionally the command **planners** (`install_commands` and friends), which
   return argv tuples and execute nothing — the module's own docstring notes
   that `_call` is the single execution seam.

Not asked for: `self_cmd` / `self_update` / `plugin_cmd`. Those are commands
and correctly private.

## 5. Diagnose a job module that fails to import

**Severity: usability. Cheapest item here, and the one users hit most.**

A job module whose import fails is skipped with a `logger.warning` and
**vanishes from the CLI** **[probed]**:

```
WARNING:functualize._discovery.registry:Failed to import module 'needs_dep' …
discovered: ['hello']
`fetch` is present: False
```

`func fetch` then reports "No such command". The user's model says "my job is
broken"; the CLI says it never existed — and on a warm boot the warning may not
be re-emitted at all.

The information already exists; it needs a surface. `builtin self doctor`
(0.2.3) is the natural host and already reports installation health in exactly
this shape:

```
!!  jobs/audit.py   not loaded — No module named 'httpx'
    3 jobs in this file are missing from the CLI
```

This is the highest value-per-line change on the list, it needs no format or
policy decision, and it is what makes the dependency question (`07`) tractable
without adding a dependency system.

---

## Not asked for

**Group options for provider-registered jobs.** Restoring group-level flags off
the scan path means collecting `GroupOptionsSpec`s outside
`_discovery/sync.py:203` and writing them where
`read_group_options_from_cache` (`app/utils.py:1547`) looks. That is a real
change to the cache contract, and the benefit is typing a flag at the group
node instead of the job node. Deferred deliberately (`14` §4).

**Native method-jobs.** functualize could grow class binding itself, which
would delete `risekit.binding`. **Deferred, seam preserved — no longer
declined (`17` §2):** the adapter's own factoring (`03` §4) shows the asset
is narrower than "the binding" — checks 2, 4, 7, 9, 10 and the `Job`
emission shape are vocabulary-blind mechanism, and only checks 5/6/8
(`supports` legality, the concrete `Target`, substrate tables) are policy.
If a generic class→jobs binding ever lands upstream, `risekit.binding`
shrinks to the policy checks; the descriptor shape would not change, so
nothing downstream breaks either way. Not asked for now — nothing needs it,
and `17` keeps the pattern at guide level first.

---

## Summary

This file argues asks **1–5**. Asks 6–8 are argued in `15` §6, ask 9 in
`17` §3, and ask 10 in `18` §5; all ten are indexed here so there is one place
to look.

| # | Ask | Kind | Blocks rise? | Argued in |
|---|---|---|---|---|
| 1 | `register_dynamic_job` parameters | fix | no — routed around (`03` §1) | here §1 |
| 2 | `job_providers` / dropped `functions` | fix | no | here §2 |
| 3 | `DiscoveryConfig` pre-filter hook | feature | no | here §3 |
| 4 | public install detection + package ops | feature | no — rise reimplements | here §4 |
| 5 | diagnose failed job-module imports | feature | no | here §5 |
| 6 | `functualize.skills` entry-point group; `resolve_skills_dir` → a list | feature | no — badly routed around | `15` §6 |
| 7 | `job_detail` exposes `declaration` | fix | no — the agent surface is functualize's | `15` §6 |
| 8 | `_KNOWN_TOOL_KEYS` gains `skill` | feature | no | `15` §6 |
| 9 | re-export `StaticProvider` from `functualize.plugin` | fix | no — probe 10 imports the private path | `17` §3 |
| 10 | display dedupe: last-wins, or warn on a discarded provider | fix | no — rise documents around it | `18` §5 |
| 11 | protect the whole first-party top level, or warn — `mcp` is claimable, `builtin` is not | fix | no — rise derives the set | `evidence/README.md` |
| 12 | surface `FromJob` edges in `job_detail` — a working data-flow graph is invisible to agents | fix | no — but it defeats the agent-legibility thesis | `19` §3 G1 |

Nothing blocks. That is a materially better position than v2 reported, and the
reason is one probe: plugins load before job resolution.

> **Status note (2026-09-08).** Asks **1–8 have landed** in functualize
> `78d9ff4` (v0.2.3-2, "remote config, discovery and gate fixes, and seams for
> hosting functualize"), verified in source: `ModulePreFilter` +
> `DiscoveryConfig.pre_filter` (ask 3/4-shaped), public `functualize.app.packaging`
> (`__all__` at `app/packaging.py:58`), `SKILLS_ENTRY_POINT_GROUP` +
> `resolve_skills_locations` (`_cli/skills.py:135,50`), `declaration` fields on
> `builtin info --job` (`_cli/info.py:165-168`), and
> `_KNOWN_TOOL_KEYS = {"job", "skill"}` (`_cli/pep723.py:53`). Two breaking
> changes to absorb: `builtin skills path` prints one line per location, and
> `builtin info --json`'s `skills` key is always a list. Defect **#32** is
> recorded-not-fixed — two functions normalizing to the same job name silently
> become one job on the default path, which is what `test_qualified_names_required`
> (`11` §3) exists to catch. **Asks 9, 10, 11 and 12 are outstanding.**
