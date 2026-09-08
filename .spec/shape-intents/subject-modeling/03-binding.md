# 03 — Binding: Classes → Jobs

The one genuinely new mechanism. v2 routed it through
`FunctualizeApp.register_dynamic_job`; v3 routes it through a **plugin-supplied
job provider**, which is better in four ways and is what makes `04` possible.

## 1. Why the plugin path

Four candidate paths, all probed:

| Path | Works? | Why |
|---|---|---|
| `JobSources(functions=[Job(...)])` | ✗ | read only inside `boot_static` (`_app/boot.py:242`), unreachable for a real project **[probed]** |
| `JobSources(job_providers=[...])` | ✗ | the field is never read (`app/config.py:56`) **[probed]** |
| `app.add_job_provider(...)` after construction | ✗ | boot already resolved and registered **[probed]** |
| **`app.add_job_provider(...)` inside `plugin.__call__(app)`** | **✓** | plugins load at boot step 4, job resolution at step 9 | 

The ordering is deliberate upstream, not an accident — `_app/boot.py:531`
reads: *"Load plugins EARLY (so they can register providers)."*

**[probed]** the provider path also keeps what the dynamic door loses:

```
registered: [('apps.tool.install', ['variant', 'force']), ('apps.tool.status', [])]
info schema properties: ['force', 'variant']   <- non-empty WITHOUT the P1 patch
```

So the agent-facing schema is correct with no upstream patch, `builtin why`
works, and `--variant` / `--no-force` reach the body. Compare
`register_dynamic_job`, which hard-codes `parameters=[]`
(`_app/impl.py:732`) and publishes every rise job as taking no arguments.

## 2. The plugin

```python
class RisePlugin:
    """The whole of rise's integration with functualize."""

    name = "rise"
    version = __version__
    description = "rise module vocabulary and lifecycle"

    def __init__(self, *, namespace: str | None = None,
                 modules: Sequence[type[Resource]] | None = None) -> None:
        self.namespace = namespace              # None → mount at root (04)
        self._modules = modules                 # None → discover (§5)

    def __call__(self, app: FunctualizeApp) -> None:
        jobs, rejected = [], []
        for cls in self._modules if self._modules is not None else discover_modules(app):
            try:
                jobs.extend(ClassBinding(cls, namespace=self.namespace).jobs())
            except BindingError as exc:
                rejected.append(exc)
        if jobs:
            app.add_job_provider(StaticProvider(jobs))
        report_rejections(rejected)             # one summary line; never raises
```

It satisfies functualize's plugin protocol exactly — `name`, `version`,
`description`, `__call__(app)` (`_plugins/loader.py:76`) — and nothing else.
No private attribute is touched.

## 3. Two mechanics the provider path imposes

Both probed, both handled by the adapter.

**(a) Fully-qualified names are mandatory.** `StaticProvider` keys by bare
`name`, so two classes each declaring `install` collide. Measured at
`a2f453d`, the collision raised in `resolve_all()`, which boot caught and
logged, losing **every** job from that boot:

```
a2f453d:  bare name   jobs=[] exits=[2, 2]
          qualified   jobs=['apps.alpha.install', 'apps.beta.install'] exits=[0, 0]
```

**Re-measured at `787035e`, the failure mode changed — and got quieter:**

```
787035e:  bare name   jobs=['install'] exits=[0, 2]
          qualified   jobs=['apps.alpha.install', 'apps.beta.install'] exits=[0, 0]
```

The first colliding job now survives and the second is silently unreachable
(defect **#32**, recorded-not-fixed in #29). So "a bare-name collision is
fatal" is no longer true; what is true is worse for an author, because nothing
announces the loss.

Either way the conclusion for rise is **unchanged and now more important**: two
rise classes with an `install` method is the *normal* case, so the adapter
always emits `Job(function=bound, name=f"{group}.{method}", group=group)`.
Qualified names are not a nicety here — they are the only thing standing
between a normal rise project and a job that vanishes without a message.
See `evidence/README.md` for the full drift table.

**(b) Namespacing goes in the group, not through `NamespaceTransform`.** That
transform prefixes the descriptor's *name* only; group and name then disagree
and the trie files the job under its un-prefixed group **[probed]**:

```
guest, group-composed        top=['builtin','rise']  `rise apps bifrost start` -> exit=0
guest, NamespaceTransform    top=['apps','builtin']  `rise apps bifrost start` -> exit=2
```

So `effective_group = f"{namespace}.{cls.group}"` when a namespace is set
(`04` §3).

## 4. The adapter

```python
class ClassBinding:
    RESERVED = ("diagnose", "validate", "audit")

    def __init__(self, cls: type[Resource], *, namespace: str | None = None):
        self.substrates = resolve_substrates(cls)   # 1: ≥1, mutually compatible
        self.instance   = cls()                     # 2: abstract gate → TypeError
        check_required_attrs(cls, self.substrates)  # 3
        check_actions(self.instance)             # 4: isinstance per action Protocol
        check_supported(cls, self.substrates)    # 5: action legal for substrate
        check_target(cls)                           # 6: `target` is a Target
        check_config(cls)                           # 7: BaseModel subclass
        check_group_name(cls.group, namespace)      # 8: not `builtin`, no sigil
        check_bool_flags(cls)                       # 9: no `x` beside `no_x`
        check_no_shadowing(cls, self.RESERVED)      # 10
        self.group = f"{namespace}.{cls.group}" if namespace else cls.group

    def jobs(self) -> list[Job]:
        out = [
            Job(function=bound, name=f"{self.group}.{surface_name(n)}", group=self.group)
            for n, bound in self.surface_methods()
        ]
        out += [
            Job(function=getattr(self.instance, v), name=f"{self.group}.{v}", group=self.group)
            for v in ("diagnose", "validate")        # the universal vocabulary
        ]
        return out
```

Check order is chosen so the **first** failure is the right message. Substrate
resolution precedes instantiation, because two incompatible substrates
otherwise surface as an abstract-method error pointing at the wrong problem.

Check 8 asks functualize's own trie rules rather than hard-coding `builtin`, so
a future reservation surfaces as a rise binding error naming the class instead
of a whole-CLI `ValueError` (`00` fact 5). Check 9 is new in 0.2.3: booleans
render `--flag / --no-flag`, and `negative_flag_for` (`_types/naming.py:100`)
returns `None` when a sibling is literally named `no_<name>` — so `cache`
beside `no_cache` silently loses its negative spelling. functualize guarantees
determinism, not detection; rise detects.

A failure means **this module's jobs do not register**; the adapter reports it
and continues, matching how functualize treats a broken job file. `rise
validate` exits non-zero while any module is rejected.

## 5. Guards ride the method

```python
@job(guards=Guards(status=[jsonschema_present]),
     cache=Fingerprint(generates=[".risekit/lock/jsonschema.json"]))
def install(self, sh: Shell, log: Log) -> None: ...
```

`@job` sets `__functualize_job__` on the function (`job/decorators.py:105`) and
is identity-preserving, so it applies to a method like any callable; a bound
method proxies attribute access to `__func__`, so both the descriptor builder
and the executor's declaration read-sites find it. **[probed]** — a status
guard declared this way skipped a second `install`.

Do **not** attach a `JobDeclaration` to the descriptor instead:
`adopt_descriptor_declaration` (`_app/boot.py:1026`) bridges that gap by
*setting* `live_fn.__functualize_job__`, and a bound method rejects attribute
assignment — the function catches it and warns "decorate the function with
`@job(...)` instead". The upstream code states the answer; rise takes it.

So rise invents **no** guard concept of its own.

## 6. Finding the classes

Directory discovery cannot see class-only modules (`00` fact 4), so rise owns
discovery, with two channels converging on one deduplicated, deterministically
ordered list:

```toml
[risekit]
module_packages = ["my_project.modules"]     # walked
modules = ["my_project.extras.special"]      # explicit escape hatch
```

plus an entry-point group for installed packages:

```toml
[project.entry-points."risekit.modules"]
jsonschema-nix = "acme_risekit_nix.jsonschema"
```

The value names a **module**, not a class, and risekit's own loader imports it.
Deliberately not `EntryPointProvider`: that wraps a loaded object as a callable
and falls back to `lambda: None` for non-callables
(`_discovery/providers.py:781`), so a class-valued entry point would register a
job that does nothing.

## 7. What the adapter does not do

- **One functualize internal, corrected.** Every call is a public facade
  method — `add_job_provider` — and `Job` is re-exported from
  `functualize.plugin`. **`StaticProvider` is not** (`plugin/__init__.py:56`;
  it lives at `_discovery/providers.py:651`) — probe 10 imports it from the
  private path. Re-exporting it is upstream ask 9 (`17` §3); until then that
  one import is private-but-stable.
- **No second discovery cache.** Rise modules are imported every boot. At
  project scale that is milliseconds; if it ever is not, the answer is the
  upstream pre-filter hook (`13` §3), not a rise-owned cache with its own
  invalidation rules.
- **No re-derived naming.** Canonicalization is `normalize_segment`.
