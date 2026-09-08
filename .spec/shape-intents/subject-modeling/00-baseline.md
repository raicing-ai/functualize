# 00 — The functualize 0.2.3 Baseline

What rise consumes, what it must build, and the ten facts it must not assume
away. Derived in the (not-carried) oop-v2 scrutiny record; this file is
the conclusion, re-pinned to 0.2.3 and updated where the plugin path changed
the answer.

## 1. Consumed, verified

| Mechanism | Where | Rise use |
|---|---|---|
| Exit codes 0/1/2/3/4/5 | `_types/exit_codes.py:36` | the refusal contract (`08` §4) |
| `Guards(status=…)` → `SKIPPED` → exit 0 | `_engine/guards.py:201` | idempotency **[probed]** |
| `Guards(preconditions=…)` → `REFUSED` → exit 3 | `_engine/guards.py:259`, `_engine/executor.py:2035` | safety refusals |
| `@job(...)` on a **method** | `job/decorators.py:105` | guards/cache declared in the class body **[probed]** |
| Bound methods as job functions | `_discovery/providers.py:98` skips `self` | the whole binding **[probed]** |
| `tty: TTY \| None` | `_discovery/providers.py:285` | the interactivity signal **[probed]** |
| `--output ndjson`, `Stdout.emit` | `_cli/dispatch.py:100` | the diagnosis stream |
| Booleans render `--flag / --no-flag` | `_types/naming.py:100` (0.2.3) | free ergonomics **[probed]** |
| `builtin self update` / `plugin install` | `_cli/self_cmd.py` (0.2.3) | rise's `upgrade` verb, inherited **[probed]** |
| Plugin `__call__(app)` at boot step 4 | `_app/boot.py:535` | **the binding seam** (`03`) **[probed]** |
| Child projects, `NamespaceTransform`, `GroupTrie` | `_app/boot.py:871` | composition |

## 2. The ten facts rise must not assume away

Each cost v2 a design revision. Each still holds on 0.2.3 — all twelve probes
re-run byte-identically (`evidence/transcript.md`).

1. **`JobSources(functions=…)` is read only inside `boot_static`**
   (`_app/boot.py:242`), reachable only when `is_fully_explicit()` holds
   (`_app/impl.py:213`). A real project never qualifies; the field is silently
   dropped. **[probed]**
2. **`JobSources.job_providers` is never read** — two grep hits, both inside
   the dataclass (`app/config.py:56`). **[probed]**
3. **`add_job_provider` after the constructor returns is too late** — boot has
   already resolved and registered. **[probed]** *But from inside a plugin it
   works* (§3) — that is the v3 correction.
4. **`ASTModulePreFilter` requires a top-level public function**
   (`_primitives/pre_filter.py:110`). A class-only module is never imported by
   directory discovery. **[probed]**
5. **`builtin` is a reserved top-level segment** (`_types/naming.py:207`);
   claiming it aborts CLI construction. **[probed]**
6. **Child projects mount as a directory scan of `<child>/jobs`**
   (`_app/boot.py:871`). A child's own `main.py` never runs.
7. **`GroupOptions` specs are collected only in the directory-scan pass**
   (`_discovery/sync.py:203`) and read only from the cache
   (`app/utils.py:1547`). Provider-registered jobs get no group flags.
8. **`register_dynamic_job` hard-codes `parameters=[]`**
   (`_app/impl.py:732`), blinding every surface that reads the descriptor.
   **[probed]** — and now avoidable (§3).
9. **Workflow nodes are keyed by job name**; duplicates are a decoration-time
   `ValueError` (`_types/workflow.py:131`). "Run install twice" is not
   expressible as one graph.
10. **The scaffold template registry is a hard-coded dict**
    (`_cli/scaffold/registry.py:22`) with no registration hook.

Two smaller ones, carried: `rc.invoke` has no `namespace=` parameter
(`_engine/capabilities/runcontext.py:365`), and a job module whose import fails
is **skipped with a warning, not an error** — it vanishes from the CLI
**[probed]**, which `07` §1 treats as the dependency story's real pain.

## 3. The correction that reshapes v3

v2 concluded that no provider path reaches the registry, and fell back to
`register_dynamic_job` — inheriting fact 8, which made the agent-facing schema
empty and turned upstream patch P1 into a blocker.

That conclusion was too strong. v2 probed `add_job_provider` **after the
constructor returned**. Plugins are loaded *during* boot, at step 4, explicitly
"so they can register providers" (`_app/boot.py:531`), and job resolution does
not run until step 9 (`_app/boot.py:988`). A provider added from inside
`plugin.__call__(app)` is therefore picked up.

**[probed]** — through the plugin path, a bound method registers with its
parameters intact:

```
registered: [('apps.tool.install', ['variant', 'force']), ('apps.tool.status', [])]
info schema properties: ['force', 'variant']   <- non-empty WITHOUT the P1 patch
```

Consequences, all of them good:

- `03` binds through a provider, not the dynamic door.
- Fact 8 stops being load-bearing; P1 drops from blocker to defect (`13` §1).
- The plugin object that does the binding is the *same object* rise ships as a
  `func` plugin — which is what makes `04` possible at all.

## 4. Two mechanics the provider path imposes

Both probed, both cheap, both must be honoured by the binding adapter:

**(a) `StaticProvider` keys jobs by bare `name`, not `group.name`.** Two
classes with an `install` method collide, and the failure is *total* — the
pipeline raises and **every** job from that boot is lost, not just the pair:

```
bare name   jobs=[] exits=[2, 2]
qualified   jobs=['apps.alpha.install', 'apps.beta.install'] exits=[0, 0]
```

So the adapter always passes the fully-qualified name:
`Job(function=bound, name=f"{group}.{method}", group=group)`.

**(b) `NamespaceTransform` prefixes the descriptor's *name* only.** Group and
name then disagree and the CLI trie files the job under its un-prefixed group.
For namespaced mounting the prefix must be composed into the **group**
(`04` §3) **[probed]**.

## 5. What rise still builds

Unchanged from v2: the vocabulary, the binding adapter, meta-reflected
diagnosis, the registry router and lockfile, the safety layer, the scaffold
generator, and the agent skills. `11` §2 has the build order.
