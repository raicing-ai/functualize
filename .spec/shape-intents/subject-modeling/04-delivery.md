# 04 — Two Deliveries, One Binding

rise ships as **a `func` plugin** and as **its own `rise` CLI**, from one
object. This is not two integrations kept in sync; it is one `RisePlugin`
(`03` §2) hosted two ways.

## 1. The two shapes

### A — rise as a `func` plugin (guest)

The user already has functualize. They add risekit; rise's vocabulary appears
inside their existing `func`.

```toml
# risekit's pyproject.toml
[project.entry-points."functualize.plugins"]
rise = "risekit.plugin:RISE"
```

```python
# risekit/plugin.py
RISE = RisePlugin(namespace="rise")     # mounts under `func rise …`
```

```console
$ pip install risekit
$ func rise tools jsonschema install
$ func rise diagnose
$ func build                      # the host's own jobs, untouched
```

Entry-point discovery loads it at boot step 4; nothing else in the host project
changes. **[probed]** rise jobs and directory-discovered host jobs coexist:

```
registered: ['apps.bifrost.start', 'apps.bifrost.status', 'build']
top-level: ['apps', 'build', 'builtin']
```

### B — rise as its own CLI (host)

The user wants rise, not functualize. `rise` is a console script over a
`FunctualizeApp` that loads the same plugin explicitly, un-namespaced.

```python
# risekit/_cli/main.py
def main() -> None:
    app = FunctualizeApp(
        "rise",
        # NO job directories. `rise` surfaces rise modules only — it is not a
        # general task runner, and does not scan or run a project's jobs/*.py.
        job_sources=JobSources(directories=[], lazy=False),
        plugin_sources=PluginSources(explicit_plugins=[RisePlugin(namespace=None)]),
    )
    adapter = CliAdapter()
    adapter(app)
    adapter.run()
```

**`rise` deliberately cannot run your project's jobs.** It scans no `jobs/`
directory and registers nothing but rise modules. That is a scoping decision,
not a limitation to work around: it keeps rise from becoming a second task
runner competing with `func`, so there is exactly one job runner and no
opportunity for the two to drift.

```console
$ uv tool install risekit
$ rise tools jsonschema install
$ rise diagnose
$ rise builtin self update        # inherited from functualize 0.2.3
```

**[probed]** both mountings work from the one plugin class:

```
own CLI (root)          top=['apps','builtin']   `apps bifrost start`      -> exit=0
guest, group-composed   top=['builtin','rise']   `rise apps bifrost start` -> exit=0
```

## 2. What differs, and it is only three things

| | Guest (`func rise …`) | Host (`rise …`) |
|---|---|---|
| Plugin discovery | entry point `functualize.plugins` | `explicit_plugins=[...]` |
| Namespace | `"rise"` | `None` |
| App name / console script | the host's | `rise` |
| Binding, vocabulary, diagnosis, registry, safety | **identical** | **identical** |

`PluginSources(explicit_plugins=…)` is honoured on the standard boot path in
0.2.3 — a bug fixed upstream, whose comment says handing an object in "is an
instruction, not a hint" (`_app/boot.py:544`). Before that fix, delivery B
would have needed a different mechanism from delivery A, and the two would
have drifted.

## 3. Namespacing is composed into the group

The namespace must not go through `NamespaceTransform`, which prefixes the
descriptor's **name** only, leaving group and name disagreeing so the trie
files the job under its un-prefixed group **[probed]**:

```
guest, NamespaceTransform    top=['apps','builtin']  `rise apps bifrost start` -> exit=2
```

So `ClassBinding` composes `effective_group = f"{namespace}.{cls.group}"`
(`03` §3b). One consequence worth stating: **a module's `group` is relative,
not absolute.** `group = "tools.jsonschema"` means "under wherever rise is
mounted", and the AST reader (`02` §5) reports the relative form — the absolute
path is a property of the delivery, not of the module.

## 3a. Decided: what `rise new project` wires up

`rise new project` scaffolds a **func project with rise wired in** — the
project's own jobs under `jobs/`, and risekit as a dependency so the plugin
loads. One command runs everything afterwards:

```console
$ func build            # the project's job
$ func rise diagnose    # rise's vocabulary
```

The standalone `rise` is not the project's entry point; it is the
**bootstrapper for where no project exists yet** — a bare machine, or a
checkout you have not set up. That division keeps `rise` out of the project's
job graph entirely: it never runs `func build`, and never scans `jobs/`.

It does run **its own modules' methods** — `rise tools mise install` is the
bootstrap case and the reason the standalone delivery exists at all (`09` §2).
Those methods are jobs, created by rise's own `ClassBinding` (`03` §4); they are
just never *the project's* jobs. An earlier draft of this paragraph said the
division "keeps `rise` from needing to run jobs at all," which was wrong and
contradicted §1B's own example list.

## 4. Why both, rather than picking one

**The guest delivery is the honest default for a functualize user.** They have
a `func` and a project; rise is a vocabulary they add, and forcing a second
binary to get it would be a tax on the framework's own users. It also means
rise composes with everything else in the host — its jobs sit beside the host's
`build` and `deploy`, share one config chain, one state store, one run history.

**The host delivery is the honest default where there is no project.** A bare
machine, a fresh checkout, a CI runner that needs tools before it can do
anything: `uv tool install risekit && rise tools mise install` requires nobody
to know what functualize is. The standalone binary story (functualize 0.2.3's
PyApp targets) applies unchanged, so `rise` can ship for machines with no
Python at all.

Because `rise` runs no project jobs, the two never compete: the moment a
project exists, `func` owns the verbs and rise's vocabulary rides along inside
it.

The cost of supporting both is one constructor parameter, because the plugin
protocol is the only integration point either delivery uses.

## 5. What the guest delivery inherits, and what it must not claim

`CliAdapter` mounts the whole `builtin` subtree by default, in both
deliveries — so `rise builtin self update`, `builtin why`, `builtin info
schema`, `builtin history` all work with no rise code (`00` §1).

The reciprocal constraint: **rise may never claim the `builtin` namespace.**
It is reserved and claiming it aborts CLI construction, in either delivery
(`00` fact 5). Hence the tree-walk verbs are top-level `rise diagnose` /
`rise validate` in the host, and `func rise diagnose` in the guest — never
`… builtin diagnose`.

## 6. One risk the dual delivery adds

**Group collisions in the guest delivery.** A host project with its own
top-level `rise` group, or with jobs whose names collide with rise's, breaks
in a way the host owns and rise cannot fix — and `StaticProvider`'s duplicate
handling makes collisions total rather than local (`03` §3a).

Mitigations, in order:

1. The namespace defaults to `"rise"` and is **configurable** —
   `[risekit] namespace = "risekit"` — so a collision is one config line to
   resolve.
2. `ClassBinding` check 8 tests the composed group against the host's existing
   names at bind time and rejects the *module* with a message naming both, so
   the failure is local and legible instead of taking the boot down.
3. `rise doctor` reports the resolved mount point and any near-collisions.

## 7. Testing both

Every acceptance test in `12` runs against **both** deliveries, parameterized
on the namespace. That is the only way the "one binding" claim stays true: a
divergence shows up as a test failing in exactly one parameterization.

```python
@pytest.fixture(params=[None, "rise"], ids=["host", "guest"])
def rise_app(request): ...
```
