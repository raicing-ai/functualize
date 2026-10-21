# Class-based jobs — Plan

## Alignment

- **Shape:** *Shape Intent — Class-based jobs (a class declares its methods as
  jobs)* — Confluence `SD/18317314`, **version 3** (updated 2026-10-21
  11:00:32 UTC), `Status = Approved`, `Authority = Approved`. Read live on
  2026-10-21 before this plan was written.
- **Approval record:** the maintainer's comment "All recommended" on this
  feature's issue (2026-10-21T14:37:03Z) confirms D1–D6 in their recommended
  form; `spec.md` now states them as decided rather than proposed. Version 3's
  delta over version 2 is two fields and bold markers, no rule text: **F1-a**
  (an abstract class is never a job class) and **F1-b** (`@job` on a class is
  not inherited) — the Designer delta on the shape. The page's opening sentence
  "It is **not approved**" is stale draft prose; the `Authority` row governs.
- **In scope, in the shape's words** (`spec.md` F1, F4, F5, D6):
  - "A class that carries `@job` declares one job per public instance method"
  - the class's group is "`group=` when given, else the normalized class name,
    nested under the defining module's `JOB_GROUP`"
  - "`JOB_TAGS` on any base contributes tags … without making that class a job
    class"
  - collisions "name both definitions and their files"; `func builtin info`
    lists the name; invoking exits `2`; the rest of the project boots
  - `docs/guides/job-classes.md`
- **Out of scope, in the shape's words** (`spec.md` § *Out of scope*): "A new
  discovery path, loader or plugin type; any new invocation flag, request field
  or envelope key (R-4); giving any tag a built-in meaning; changing name
  normalization or the naming contract; collisions between plain functions; the
  vault identity grammar; F2 and the configuration-section half of F3."
- **Must not change, in the shape's words** (`spec.md` § *Behaviour that must not
  change*): "Plain function jobs, `JOB_GROUP`, `GroupOptions`, the configuration
  order, the existing `JobNameCollision` record and its rendering (in
  `func builtin info` and on invocation), and plugin and entry-point discovery
  for functions. … A distribution whose entry points name only functions keeps
  enumerating without importing them."
- **Shape risks answered here:** enumeration of an entry-point class without
  importing → §4.6; "an instance per run" with no second lifecycle → §4.5; two
  same-named methods in one file being one cache entry → §4.3; the CLI rendering
  a `self` argument → §4.4.
- **Related, not carried:** `SD/12779576` (scoped-vault shape: `func builtin
  vault` — scoped secrets and resolution, so the vault work this feature's
  AC-11 touches is not decided here) and `SD/19595276` (One Job Namespace:
  identity, command path and collisions on every surface, which supersedes
  `SD/17072130`), each with its own follow-up. Page Q4 — F2 and the
  configuration-section half of F3 — has no ticket, so nothing here decides it.
- **Erratum against `contracts.md`, made in this phase:** C2 shows
  `JOB_TAGS = ("database",)` inside a `pydantic.BaseModel` subclass. That is a
  hard `PydanticUserError` at class creation, before any Functualize code runs
  (verified: `A non-annotated attribute was detected: JOB_TAGS = ('database',)`).
  The documented spelling is therefore `JOB_TAGS: ClassVar[tuple[str, ...]] =
  ("database",)`; C2 and spec F4 now say so. `cls.__dict__["JOB_TAGS"]` still
  holds the value, so discovery is unaffected.

## 1. Skills consulted

- `python-design-patterns` (in-repo, `.agents/skills/python-design-patterns`,
  symlinked at `.claude/skills/python-design-patterns`) — KISS; "one reason to
  change"; "an interface with one implementation is a guess"; the rule that a
  new abstraction must replace a real duplication rather than anticipate one.
  It is the reason §3 rejects a `ClassProvider` and a second registration shape.
- `design-patterns-refactoring` (user-level, **outside this repository**:
  `~/.claude/skills/design-patterns-refactoring/chapters/ch31-smells-catalog.md`
  and its `glossary.md`) — the catalogue this plan's smell names are checked
  against, and the routing table that pairs each with its fix. The names used
  below are the catalogue's own (*Duplicate Code*, *Data Clumps*, *Long
  Method*, *Shotgun Surgery*, *Divergent Change*, *Switch Statements*,
  *Speculative Generality*). Two findings have no catalogue name — the repeated
  job-ness test (§2) and the last-write-wins cache key (§2) — so they are
  described in plain words and **not** given invented ones; a name that is not
  in the catalogue cannot be looked up or routed, which is worse than a
  description.

## 2. Architecture pass — the region today

Tools: zvec-grep (`zg index --embedding local/potion-code-16m-v2` over this
worktree: 2081 files, 41 819 entities, coverage 100 %, 0 truncated) — no
class-discovery precedent in-tree; serena (`find_referencing_symbols` on
`RegisteredJob`, `JobDescriptor`, `collision_projection`, `_entry_key`,
`claim_order`, `ExecutionContext`); graphify **exhausted** — `graph.json not
found …/graphify-out/graph.json`, so the codemaps below are the substitute
(drawn by hand from the files, with line numbers, and every claim in this plan
re-checked with `git grep`); `uv run lint-imports` → "Analyzed 395 files, 1149
dependencies… Contracts: 7 kept, 0 broken." at `8ef1381`.

Codemaps read: `contributor/architecture/codemaps/overview.md` (public/internal
split; the three conceptual layers Discovery & Metadata → Loading & Wiring →
Execution), `dependencies.md`, `data-flow.md`, `entry-points.md`. No codemap
mentions a class job; nothing in them contradicts the drawing below.

### BEFORE

```
 layer: delivery  _cli/  (may import only public folders + _cli siblings)
 ┌──────────────────────────────────────────────────────────────────────────────
 │ _cli/main.py
 │   _materialize_for_dispatch (886-910)  ◄── engine.materialize_job(name)
 │   _warn_collisions (937-946)           ──► _cli/info.collision_notices (175-189)
 │   unknown name → "Did you mean" → return 1 (1540-1558)
 │ _cli/info.py
 │   collision_projection (111-160) — a finding whose canonical_name has no
 │   registered descriptor is DROPPED (:131-133)
 │   job_catalog (192-211), discovery_failures (413-435)
 └──────────────────────────────────┬───────────────────────────────────────────
                                    │ public API only
 ┌──────────────────────────────────▼───────────────────────────────────────────
 │ _app/boot.py  register_descriptors (2003-2059)
 │   live_fn = descriptor.function → adopt_descriptor_declaration
 │                                  → _detect_config_class(live_fn)
 │   cache-only (function=None)   → LazyJobFunction(descriptor)
 └──────────────────────────────────┬───────────────────────────────────────────
                                    │ internal packages; peers never import peers
 ┌──────────────────────────────────▼───────────────────────────────────────────
 │ _discovery/sync.py  extract_module (210-308, 99 lines)
 │   job_functions = _find_all_job_functions(module) (233)
 │   decorators_by_func = extract_function_decorators(path) (249) → decorators= (303)
 │ _discovery/sync.py  _find_all_job_functions (377-432)
 │   for attr_name in dir(module): … if not isfunction(attr): continue (410-411)
 │ _discovery/registry.py  _is_registerable_function (605-609) — isfunction again
 │ _discovery/providers.py
 │   StaticProvider (624-693)   _build_descriptor: python_name=func.__name__ (684)
 │   EntryPointProvider (700-879) — enumeration imports nothing (780-819);
 │                                  _materialize (821-851) → _import_real_function
 │ _discovery/cached_provider.py  _entry_key (545) = "file::python_name|name";
 │                                _add_entry (547-550) SILENTLY overwrites (:549)
 │ _discovery/collisions.py  claim_order (40-57) = (file, python_name|name);
 │                           resolve_name_collisions (60-96) keeps one claimant
 │ _discovery/lazy_wrapper.py  _import_real_function (64-138):
 │                           getattr(module, descriptor.attribute_name) (131-132)
 ├────────────────────────────────────────────────────────────────────────────────
 │ _engine/executor.py  _resolve_config_model (2555-2632)
 │   config_class(**values) (591 of _config/job_config.py) ; injection loop over
 │   inspect.signature(function) by annotation (2617-2632)
 │   _execute_with_lifecycle (2634+) : function = context.function (2647)
 │ _engine/context.py  ExecutionContext (94-107) — no notion of a receiver
 │ _types/descriptors.py  JobDescriptor (215+), RegisteredJob (552-579)
 │   RegisteredJob: name, function, config_class, group, module_path,
 │                  job_directory, dependencies
 │ _primitives/cache_format.py  CACHE_VERSION = 22 (160)
 └────────────────────────────────────────────────────────────────────────────────
```

**Smells the BEFORE already carries** (catalogue names where the catalogue has
one):

| Smell | Where |
|---|---|
| *Duplicate Code* — two rules, each spelled out at more than one site: "is this a job?" (`sync.py:410-411`, `registry.py:605-609`, `providers._build_descriptor`) and "what is this job's key?" (`_entry_key` 545, `claim_order` 40-57, `attribute_name`/`python_name`) |
| Last write wins, with no diagnostic (no catalogue name) — two definitions that normalise to one key become one cache entry | `cached_provider.py:545` `_entry_key` + `:547-550` `_add_entry` |
| *Data Clumps* — provenance (file, class, method) has no single field | `descriptor.python_name`, `collision.dropped/registered_*_file`, `_import_real_function` |
| *Shotgun Surgery* — every job surface assumes a `self`-free function | `click_params.build_click_params` (708-880), `_engine/validation._build_validation_model`, `executor._di_binding_errors` |
| *Long Method* | `sync.extract_module` 210-308 |
| *Divergent Change* — `collision_projection` answers "which claimant won" only | `_cli/info.py:111-160`; the "nobody won" case has no shape |

## 3. Candidate AFTERs

**A1 — a `ClassProvider`: a new pipeline stage that expands classes into
pseudo-functions before the existing providers.** Rejected: it is the "new
discovery path" the shape excludes, it duplicates provider ordering and
collision resolution for the second time, and it has to re-implement
`extract_module` per provider instead of once.

**A2 — a singleton instance built at import, with each method registered as a
bound method.** Rejected: it breaks instance-per-run (F1), it makes `--help`,
`func builtin info` and completion construct user code (AC-4: the constructor
side-effect counter must stay 0), and on a warm boot it reintroduces the import
that `LazyJobFunction` exists to avoid.

**A3 (chosen) — the class is a source of jobs, not a second job kind.** One
descriptor per (class, public instance method), with the class carried as
provenance (`owner_class`) rather than as a new descriptor type. Registration
gains one optional field (`method_name`); the engine binds the receiver from the
config instance it already builds; discovery gains one branch in the place that
already walks a module.

Introduced-smell check for A3: no *Switch Statements* growth outside one named
branch per seam (`sync._find_all_jobs` class branch, `_import_real_function`
class branch, `register_descriptors` class branch, `collision_projection` third
shape) — each branch's condition is `owner_class is not None`, one predicate
carried in data rather than re-derived from types, and the check is a field, not
a `isinstance`/type-code ladder (the catalogue's *Switch Statements* is
branching on a type code; a boolean already on the record is not one). No
*Duplicate Code* — the identity rule becomes one composed string with two
readers (`_entry_key`, `claim_order`) and no third copy. No *Shotgun Surgery* —
`click_params`, `ArgValidator` and `_di_binding_errors` are **unchanged**,
because the proxy's `__signature__` already excludes `self`. No *Speculative
Generality* beyond the one proxy. No global state; no peer-layer import
(`_discovery` builds the proxy, `_engine` only rebinds by field, `_types` holds
the proxy); `extract_module` grows by one call plus one helper, not by another
99 lines.

### AFTER

```
 layer: delivery  _cli/  (unchanged import surface; one third shape)
 ┌──────────────────────────────────────────────────────────────────────────────
 │ _cli/main.py   strict collision at dispatch → print both, return 2  [NEW]
 │ _cli/info.py   collision_projection: descriptor-or-none → third shape [CHG]
 │                strict_collision_notices(app)                          [NEW]
 └──────────────────────────────────┬───────────────────────────────────────────
                                    │ public API only
 ┌──────────────────────────────────▼───────────────────────────────────────────
 │ _app/boot.py  register_descriptors: class branch → config_class=job_class,
 │               method_name, function=proxy                             [CHG]
 │ _app/impl.py  execute → the same JobNotFoundError contract            [unchanged]
 └──────────────────────────────────┬───────────────────────────────────────────
                                    │ internal packages; peers never import peers
 ┌──────────────────────────────────▼───────────────────────────────────────────
 │ _types/class_job.py  ClassJobMethod  [NEW — stdlib only]
 │   job_class, method_name, __signature__ (self/cls removed, PEP 563 resolved),
 │   __name__/__qualname__/__doc__/__module__, __getattr__ → method (workflow,
 │   markers), __functualize_job__ = the descriptor's merged declaration (own
 │   attribute, never read through); calling it without a receiver: RuntimeError
 │ _types/descriptors.py  JobDescriptor.owner_class  [NEW FIELD]
 │                        RegisteredJob.method_name   [NEW FIELD]
 │ _types/discovery_report.py  CLASS_JOB_NAME_COLLISION,
 │                             ClassJobCollisionDetail (qualified names+files)
 ├────────────────────────────────────────────────────────────────────────────────
 │ _discovery/sync.py  extract_module → _find_all_jobs   [CHG: class branch]
 │   class: own-namespace @job only (F1-b); abstract → finding, no jobs (F1-a);
 │   methods: MRO walk, nearest first, skip BaseModel/object/`_`/property/
 │   classmethod/staticmethod; descriptor carries owner_class + proxy
 │ _discovery/pre_filter bridge  extract_function_decorators: ClassDef branch,
 │   keys "<Class>.<method>" (bare names unchanged)                       [CHG]
 │ _discovery/ast_extractor.py  class_in_source(source, attribute)        [NEW]
 │ _discovery/providers.py  EntryPointProvider: source-read classify, import
 │   only for a class; StaticProvider: class fans out; Job(class) → ValueError
 │ _discovery/cached_provider.py  _entry_key composes owner_class         [CHG]
 │ _discovery/collisions.py  claim_order composes owner_class; strict branch
 │ _discovery/lazy_wrapper.py  _import_real_function: class branch        [CHG]
 ├────────────────────────────────────────────────────────────────────────────────
 │ _engine/context.py  ExecutionContext.method_name                      [NEW FIELD]
 │ _engine/executor.py  _resolve_config_model: receiver rebind from the
 │   instance it just built; context.function := partial(method, instance) [CHG]
 │ _engine/capabilities/invoke.py  C5 message on a strict collision       [CHG]
 │ _primitives/cache_format.py  CACHE_VERSION 22 → 23                     [CHG]
 └────────────────────────────────────────────────────────────────────────────────
 docs/guides/job-classes.md [NEW]     examples/standalone/job_classes_lab/ [NEW]
 tests/ … unit + integration, AC-1…AC-14 (see tasks.md)
```

Boundary check: `_types/class_job.py` imports `inspect`, `functools`,
`collections.abc`, `typing` and `functualize._types.annotations` — `_types` is
stdlib-only against *internal* packages and `annotations` is the same layer.
`_engine` imports no `_discovery` module: it rebinds through
`getattr(context.config_class, context.method_name)`, so the peer rule holds.
`_cli` still imports only public folders plus `_cli` siblings — the strict
collision shape reaches it through `_cli/info.collision_projection`, which reads
providers by attribute as it does today. `uv run lint-imports` is the proof, not
this paragraph: the AFTER shape is legal only if that command still prints
"7 kept, 0 broken", which §4.9's gate runs.

## 4. Technical approach

### 4.1 The declaration surface — `@job` on a class

`src/functualize/job/decorators.py:104-106` is the whole enforcement point:
`apply` assigns `func.__functualize_job__ = declaration` and returns the same
object, which is what makes every `@job` form identity-preserving. Three checks
are added there, all before the assignment:

- **Target type.** `isinstance(func, type)` and not
  `issubclass(func, pydantic.BaseModel)` → `ValueError` naming the target and
  `pydantic.BaseModel` (C1). Imported lazily inside `apply`; `functualize.job`
  already depends on pydantic.
- **Accepted arguments on a class.** `group`, `tags`, `visibility` only (C1).
  The other names (`deps`, `cache`, `guards`, `exec`, `examples`, `category`,
  `extra_description`, `config_section`) are rejected with one `ValueError` that
  lists every offending argument, not the first one: a user who wrote two gets
  told about two.
- **D4 — one `@job` per definition.** `"__functualize_job__" in func.__dict__`
  → `ValueError` with the exact text from C1: `"@job is already applied to
  <qualname>; combine the arguments into one @job(...)"`. `__dict__`, not
  `getattr`: an inherited declaration must not make a subclass look declared
  (that is F1-b, and the check has to agree with discovery's own rule).

`visibility` on a class is stored, not applied here; §4.5 reads it.

### 4.2 Discovery — the methods of a job class

`sync.extract_module` (210-308) stays the single place a module becomes
descriptors. `_find_all_job_functions` (377-432) becomes `_find_all_jobs`, and
after the existing `dir(module)` loop over functions (unchanged, including the
`isfunction` gate and the module-identity check at 417-419) it walks classes:

- a class qualifies when `"__functualize_job__" in cls.__dict__` (own
  namespace — F1-b), `cls.__module__ == module.__name__`, and
  `issubclass(cls, BaseModel)`;
- **F1-a first:** `cls.__abstractmethods__` non-empty → no jobs, one finding
  ("abstract job class", C4) naming the class, its module and each
  unimplemented method names. `__abstractmethods__` is a live, tested hook:
  verified, `class Database(BaseModel)` with two `@abstractmethod`s reports
  `frozenset({'start', 'stop'})` and a concrete subclass reports `frozenset()`.
  The check runs whether or not the abstract class also carries its own `@job`,
  because an abstract job class is a mistake either way;
- **methods:** walk `cls.__mro__` nearest-first, skipping `BaseModel` and
  `object` and every base in pydantic's own module; per class in the MRO read
  `base.__dict__.items()`, drop `_`-prefixed names, drop
  `staticmethod`/`classmethod`/`property` (and `cached_property`), keep the
  nearest definition of a name. This is `inspect.getattr_static`'s answer
  without its per-attribute cost, and it is the only way to see the
  descriptor-vs-function distinction `getmembers(cls, isfunction)` erases
  (`staticmethod` comes back as a plain function);
- **group:** `group=` from the class's own declaration, else
  `normalize_segment(cls.__name__)`; nested under the module's `JOB_GROUP`
  exactly as a function's group is (`sync.py:214-231`, `:278-283` stays the one
  implementation);
- **method-level group conflict (C4):** a method's own `@job(group=...)`
  differing from the class group produces no job for that method and one
  "method group conflict" finding naming the method, its class and both groups;
- **descriptor:** `name=qualified_name(raw_group, method_name)`,
  `python_name=method_name`, `owner_class=cls.__name__`, `group=class group`,
  `config_fields` from `cls.model_fields` (via the existing
  `FieldDescriptor` conversion `_detect_config_class` feeding `sync` uses),
  `parameters` from `extract_parameters_from_signature(proxy)`,
  `function=ClassJobMethod(cls, method_name, declaration=effective)`,
  `decorators` from the class-aware AST map (§4.4), and
  `source_file`/`mtime`/`content_hash` from the module file — unchanged.

**`effective` is computed here, once** — group from the class, `visibility` from
the method else the class, `tags` merged author-first then the class
`@job(tags=)` then `JOB_TAGS` from the job class outward along the MRO with
duplicates removed, `guards`/`exec`/`cache`/`deps` from the method only (task
3.1 states the merge; this paragraph states where it happens). It is passed to
the proxy as `__functualize_job__`, and `JobDescriptor.declaration`
(`_types/descriptors.py:244-248`) reads exactly that attribute off
`func.__functualize_job__` at extraction — so the cache, registration and the
warm proxy all hold one object, computed once, and no later stage may
recompute or replace it (§4.4, §4.6).

`extract_function_decorators` (`_primitives/pre_filter.py:436-469`) gains a
`ClassDef` branch: for each class in the tree, for each `FunctionDef`/
`AsyncFunctionDef` in its body, record the same decorator root names under
`"<Class>.<method>"`. Top-level functions keep bare-name keys, so
`tests/discovery/test_job_filter.py` and `test_discovery_failures.py` stay
green, and `sync` looks up `f"{cls.__name__}.{method_name}"` with a bare-name
fallback. `JobDecoratorFilter` (`_primitives/job_filter.py:132-160`) then needs
one rule: for a class-method job the recorded set also includes the class's own
`@job`, because that decorator is what brings the job into existence — a filter
configured with `job` must not silently drop every class job.

### 4.3 Identity: `owner_class` on the descriptor, and the cache key

`_entry_key` (`cached_provider.py:545`) is
`f"{descriptor.source_file}::{descriptor.python_name or descriptor.name}"`, and
`_add_entry` (`:547-550`) overwrites without a word. Two classes in one file
with a `start` method — AC-10's `OtherPostgres` vs `LocalPostgres` — therefore
collapse into one cache entry **before** `resolve_name_collisions` ever sees
them. `claim_order` (`collisions.py:40-57`) re-derives the same pair, so both
readers must learn the same identity.

One new descriptor field carries it: `owner_class: str | None = None`, with

- `to_dict` writing `"owner_class"` and `from_dict` reading
  `data.get("owner_class") or None` (an old cache deserialises with `None`,
  which is exactly the function case);
- `_entry_key` composing `f"{owner_class}.{python_name or name}"` when
  `owner_class` is set, and the current string, byte for byte, when it is not;
- `claim_order` composing the same string in its second tuple slot;
- `CACHE_VERSION` 22 → 23 in `_primitives/cache_format.py:160`, with a
  `# v23 —` comment-block entry in the style of the block that runs `# v10`
  (64) to `# v22` (156-159), because AC-7 re-runs AC-1/2/6/9/10 on a warm cache
  and the field must survive the round trip.

`attribute_name` (`_types/descriptors.py:285-288`) is **not** changed and
`python_name` is **not** made dotted: `_discovery/naming.py:62-64`
`qualified_name` raises on a dot, and `lazy_wrapper._import_real_function`
(`:131-132`) does `getattr(module, descriptor.attribute_name)`. The class path
gets its own branch instead (§4.6).

### 4.4 Registration and the receiver

`RegisteredJob` (`_types/descriptors.py:552-579`) gains
`method_name: str | None = None`; `ExecutionContext` (`_engine/context.py:94-107`)
gains the same field. Those two fields are the entire engine-side surface: the
engine never learns what discovery is.

**The proxy.** `RegisteredJob.function` for a class job is
`_types/class_job.py:ClassJobMethod`, and it exists for one measured reason:
`build_click_params` (`app/adapters/click_params.py:708-880`) does **not** drop
`self` — an unannotated parameter reaches `:795-814` and becomes a required
positional click argument. The proxy exposes

- `__signature__` = the method's signature with the first parameter removed and
  every PEP 563 string annotation replaced by its resolved type (built with
  `resolved_hints` from `_types/annotations.py`, so the `{}`-on-failure fallback
  cannot degrade `Annotated[...]` markers);
- `__name__`, `__qualname__`, `__doc__`, `__module__`, `__annotations__`,
  `__wrapped__` from the underlying function, and `__getattr__` delegating to it
  (`__functualize_workflow__`, capability markers — everything the descriptor
  already carries);
- `__functualize_job__` as an **own attribute**, set at construction from the
  descriptor's effective merged declaration — *not* left to `__getattr__`. Left
  to `__getattr__` it would answer with the method's own unmerged `@job`, which
  is exactly the object `adopt_descriptor_declaration`'s early return would then
  treat as already-correct (§4.4);
- `__functualize_lazy__` **not** set, so `executor`'s lazy branch
  (`:1220-1238`) does not treat it as a cache stand-in;
- `job_class` and `method_name` for registration, and a call that raises
  `RuntimeError` naming the job — a proxy must never run, because the receiver
  is the run's config instance and calling without one would silently construct
  a second one.

**Why the proxy is enough.** `extract_parameters_from_signature`
(`providers.py:65-99`) and `_build_validation_model`
(`_engine/validation.py:135-166`) both skip unannotated parameters and
`self`/`cls` by name, and `_di_binding_errors` (`executor.py:617-629`) skips
`self`/`cls` explicitly — that is why an unbound method would have survived
every surface *except* click. The proxy makes the one surface that would not
agree with the others agree, and leaves the other three untouched.

**The bind.** `_resolve_config_model` ends at the injection loop
(`executor.py:2617-2632`). One documented branch after it:

```python
if context.method_name is not None:
    # F1 "instance per run": the instance `_config` just built from the
    # resolved values *is* the receiver. Rebinding here — the only place that
    # holds both the instance and the function — is what keeps the engine from
    # growing a second lifecycle for jobs that happen to be methods.
    context.function = functools.partial(
        getattr(context.config_class, context.method_name), config_instance
    )
```

`context.function` is what `_execute_with_lifecycle` reads at `:2647`, so no
other line moves. `context.injected` is untouched: the receiver never enters
`call_kwargs`, so it is correctly absent from
`call_kwargs - injected` — the fingerprint keeps meaning "arguments a caller
passed". "For each run" in F1 is the invocation the run performed:
`_config/job_config.py:591` already builds the resolved model once per
invocation, and `config_class` comes from `RegisteredJob`, not from
`descriptor.function`.

**Registration — one path, one declaration.** `_app/boot.register_descriptors`
(`2003-2059`) gains one branch, and it is the branch the rest of the feature
already keys on — `descriptor.owner_class is not None`. `RegisteredJob` is still
constructed once, in the loop it is constructed in today:

```python
for descriptor in descriptors:
    live_fn = getattr(descriptor, "function", None)
    if descriptor.owner_class is not None:          # class job, cold or warm
        fn = live_fn if live_fn is not None else LazyJobFunction(descriptor)
        config_class = getattr(fn, "job_class", None)   # proxy: the class; lazy: None
        method_name = descriptor.python_name
    elif live_fn is not None and callable(live_fn):  # function job, cold
        fn = live_fn
        adopt_descriptor_declaration(descriptor, live_fn)
        config_class = _detect_config_class(live_fn)
        method_name = None
    else:                                            # function job, warm
        fn = LazyJobFunction(descriptor)
        config_class = None
        method_name = None
```

The class arm comes first, so `adopt_descriptor_declaration` and
`_detect_config_class` are *unreachable* for a class job rather than merely
unnecessary — a reviewer can see there is no second door.

Three decisions inside that branch are load-bearing:

- **`method_name` is read from the descriptor, not from the proxy.** The
  descriptor already separates the two halves — `python_name` is the method,
  `owner_class` is the class — so `JobDescriptor` gains no `method_name` field
  (schema §8), and the proxy's own `method_name` is derived from that same
  `python_name` at construction. Two spells of one identity, both computed from
  `python_name`, cannot disagree; a third would be able to. `RegisteredJob` and
  `ExecutionContext` carry the field because the engine never sees a descriptor.
- **`_detect_config_class` is not called for a class job**, cold or warm. Cold,
  the answer is the class the proxy already names; running the detector on the
  method's constructor asks "which class carries this method's configuration",
  which has no answer that is not the class itself. Warm, `config_class` is
  either already on the entry or set at materialisation (§4.6), and the lazy
  stand-in is never passed to the detector for a class job.
- **`adopt_descriptor_declaration` is not applied to a class job.** It exists
  for one job: fill an **absent** `__functualize_job__` on a function that has
  none (`boot.py:1986-1987` returns early when `getattr(live_fn,
  "__functualize_job__", None) is not None`). A `ClassJobMethod` is constructed
  with the descriptor's **effective, already-merged** declaration as its own
  attribute (§4.2, task 3.1), so on the proxy the call is a no-op — and worse, a
  no-op for the wrong reason: because `__getattr__` delegates to the method, a
  proxy *without* the own attribute would answer with the method's **unmerged**
  `@job`, the early return would fire, and the merged declaration would be
  silently replaced by the method's. Skipping the call is what makes the single
  source real; the proxy's own attribute is what makes skipping it safe.

So the declaration has exactly one origin. `_discovery` computes the effective
declaration once (author tags and class `@job(tags=)`, `JOB_TAGS` along the MRO,
`visibility`, method guards — task 3.1) and stores it on the descriptor;
`descriptor.declaration` (`_types/descriptors.py:244-248`, read off
`func.__functualize_job__` at extraction and cached) carries it in the cache;
registration takes it from the descriptor through the proxy, not through a
lookup; and after materialisation the five `executor` read sites see the same
object, because the warm proxy is built *from* the descriptor that carries it.
Cold and warm therefore run the same guards with the same cache flags and the
same deps, which is what AC-7's warm half asserts (§4.9, task 4.1).

### 4.5 Surfaces — listing, collisions, exit codes

**Strict collision has to survive "neither claimant registered".**
`_cli/info.collision_projection` (`:131-133`) drops exactly that case today, so
C5's shape is unrepresentable with the current record. The record is therefore
a *different* one:

- `_types/discovery_report.py`: `CLASS_JOB_NAME_COLLISION =
  "ClassJobNameCollision"` and `ClassJobCollisionDetail(canonical_name,
  claimants: tuple[tuple[str, str], ...])` — each claimant a
  `(qualified_name, source_file)` pair, `"OtherPostgres.start"` for a class
  job and the function's own name for a module function. The qualified name is
  not decoration: `python_name` is the *method* name, so two claimants of
  `postgres.start` are both `start`, and a message built from it would name
  neither class. The message is formatted **from these pairs** — not
  re-derived from descriptors, which no longer exist once neither claimant is
  registered. `JobNameCollisionDetail`, its four `as_dict` keys and its
  rendering are **not touched** (C5's last line, and AC-14);
- `collisions.resolve_name_collisions` (60-96) gains the third case: at least
  one claimant has `owner_class` → none of them is kept, every other name still
  registers, and one `CLASS_JOB_NAME_COLLISION` finding is recorded. Two plain
  functions keep today's `job_name_collision(...)` path unchanged;
- `_cli/info.collision_projection` stops requiring a registered descriptor: a
  strict finding is projected under its canonical name with an empty
  `registered_python_name`/`registered_source_file`. `func builtin info`'s job
  rows and the human notice both read the projection, so the name appears with
  both definitions even though no job row exists;
- `_cli/main.py`: before the "Did you mean" fallback (`:1540-1558`), a typed
  name that is a strict-collision name prints the C5 message to stderr and
  returns `2` (`ExitCode.USAGE`). The rest of the project still boots, because
  nothing about the collision is fatal to discovery — ADR-018's posture;
- `invoke` (`_engine/capabilities/invoke.py:234-246`, `:636-676`) and
  `app.execute` (`_app/impl.py:954-961`) raise/return the same
  `JobNotFoundError`, with the C5 message as its text, so a programmatic caller
  sees one contract rather than a new exception type (C5's "the same
  `JobNotFoundError` it raises today").

**`func builtin info` and completion** read descriptors, never instances, so
AC-4 holds by construction: `ClassJobMethod` is built from the class object and
its signature, and nothing in the listing path calls it.

### 4.6 Entry points and static providers

- **`StaticProvider`** receives the class object, so there is no import
  question: `_build_descriptor` (`providers.py:658-693`) becomes a fan-out for a
  class item (one descriptor per method, `owner_class` set), and
  `StaticProvider.__init__` (`:637-644`) raises `ValueError` for
  `Job(function=<class>)` with C3's text. A class and a `StaticProvider` are
  the same source, so a class listed twice is an ordinary claim collision.
- **`EntryPointProvider`** must keep "enumeration imports nothing" for function
  entry points, and it cannot know function-from-class without looking.
  Resolution: `_discovery/ast_extractor.py` gains `class_in_source(source,
  attribute)`, and `list_jobs` (`:780-819`) resolves the module's origin with
  `importlib.util.find_spec(module_path).origin` (this imports **parent
  packages** only, never the job module), parses it, and classifies:
  - the name is a `ClassDef` with its own `@job` → **import that one module**
    and enumerate by live reflection, so inherited methods are complete. The
    must-not-change sentence is about function entry points, and a class entry
    point is not one;
  - the name is a `FunctionDef`, or the source cannot be resolved → today's
    path exactly: one descriptor, `function=None`, no import. If
    materialisation then finds a class, it raises a `JobMaterializationError`
    naming the entry point rather than registering a function-shaped job for a
    class — a finding, never a wrong job.
- **Materialisation.** `_import_real_function` (`lazy_wrapper.py:64-138`) gets a
  class branch after `module = importlib.import_module(module_path)` (`:129`):
  `getattr(module, descriptor.owner_class)` then the method, then
  `ClassJobMethod(cls, method_name, declaration=descriptor.declaration)` — the
  proxy is built **from the descriptor**, so the warm run's `__functualize_job__`
  is the same merged object the cold run registered (this is the sub-decision
  §4.4 depends on: without it, the five `executor` sites
  (`_engine/executor.py`, readers of `function.__functualize_job__`) would read
  the method's unmerged declaration after materialisation and a warm run would
  skip guards the cold run ran). `LazyJobFunction.materialize` then sets
  `config_class = real_fn.job_class` for a class job and leaves
  `_detect_config_class` to the function path; `_ensure_materialized`
  (`executor.py:463-500`) already keeps `entry.config_class or detected_config`,
  so the value boot left `None` is filled once and never re-derived. The
  synthetic-source, lock and `sys.path` handling above the branch is untouched.

### 4.7 Docs, examples, changelog — last

- `docs/guides/job-classes.md` (D6's rename, "Job classes"): the class form,
  the group rule, F1-a/F1-b, `JOB_TAGS` **with the `ClassVar` annotation**,
  the config-section equivalence, what a collision does, and the two things a
  class cannot do (extend a function job's declaration; inherit `@job`).
- `docs/guides/jobs-discovery.md:133-141` currently teaches the opposite
  (`class DataProcessor:` — "Not registered — it's a class, not a function"),
  and `:143-155` offers "methods on a class" as a `pre_filter` idea. Both get a
  cross-reference; the sentence that is now false is rewritten, not deleted.
  `docs/guides/subjects.md:152` "Constructors are inert. … one instance per
  process" gains the one clause that makes it true here: a job class is
  constructed once per invocation from resolved configuration, and never
  during discovery.
- `examples/standalone/job_classes_lab/` — `README.md` as a numbered
  "Run → Expect" table, `project/`, `tests/`; the shape `discovery_lab` already
  has. `AGENTS.md`'s public-API rule makes this mandatory: `JOB_TAGS` and the
  class form of `@job` have no caller in `examples/` today (0 hits for
  `JOB_TAGS` under `src/`, `tests/`, `docs/`, `examples/`), and a public
  surface with no caller in the examples tree is a surface nobody exercises.
- `CHANGELOG.md` `## [Unreleased]`, an `### Added` entry in the style of the
  newest entry (§ Fixed, at `:10`): what a class job is, the two rules
  (abstract, not-inherited), the collision behaviour, and the `ClassVar`
  requirement.

### 4.8 What this plan deliberately does not do

No new invocation flag, request field or envelope key (R-4); no new tag
meaning; no change to `qualified_name`, `normalize_name` or `normalize_segment`;
no `_config` change (the section key rides `descriptor.group`, which
`_app/configuration_facade.py:59-81` already returns for a grouped job); no
change to `JobNameCollision`; no new provider type.

### 4.9 Gate

Per `.spec/TESTING.md`: `uv run ruff check --fix src/ tests/ plugins/ examples/`,
`uv run ruff format --check src/ tests/ plugins/ examples/`, `uv run mypy src/`,
`uv run lint-imports` (7 kept, 0 broken is the pass condition for §3's boundary
claim), the step tier from the diff, then the fast tier, then
`uv run python .github/scripts/dead_code_delta.py origin/master HEAD` with its
output pasted into the hand-off. Example projects run separately:
`uv run pytest examples/ -v`.

## 5. Blast radius

| Symbol | References (serena / git grep) | Effect |
|---|---|---|
| `job.decorators.apply` | 1 definition; every `@job` call site at import time | class target now accepted; three `ValueError` paths added; identity preservation unchanged |
| `sync._find_all_job_functions` | 1 definition, 1 call (`sync.py:233`) | renamed and extended; function branch byte-identical |
| `sync.extract_module` | 1 definition (`sync.py:117`), 3 calls (`cached_provider.py:914`, `providers.py:613`, `sync.py:332` — the `full_import_and_extract` wrapper) | new class branch; the function path keeps its 99 lines |
| `JobDescriptor.owner_class` | new field; 8 `JobDescriptor(` sites are keyword-based | additive; `to_dict`/`from_dict` must round-trip it |
| `_entry_key` / `claim_order` | 5 + 5 references, all in `_discovery` | identity string composed with `owner_class`; unchanged for functions |
| `RegisteredJob(` | 4 construction sites (`boot`, `impl`, `registry`, `lazy_command`) | each gains `method_name` when a class job is registered; default `None` makes the other three compile and behave |
| `ExecutionContext(` | 1 construction site (`executor.py:1247-1259`) | `method_name` threaded from `RegisteredJob` |
| `_resolve_config_model` | 1 caller (`executor.py:1357`), 1 definition | one branch appended after the injection loop |
| `_import_real_function` | 1 call (`providers._materialize`), 1 in `LazyJobFunction.materialize` | class branch; function branch unchanged |
| `collision_projection` | 7 references (`_cli`, `app/adapters/cli.py`) | third shape; function-collision output identical |
| `JobNameCollisionDetail` / `as_dict` | 4 JSON keys, rendered by `_cli/info` and `app/adapters/cli` | untouched, pinned by test |
| `CACHE_VERSION` | 1 definition, readers in `cached_provider` and `cache_format` | 22 → 23; every existing cache is invalidated once |
| `pytest` suites | `tests/discovery`, `tests/engine`, `tests/cli`, `tests/app`, `tests/spec` | AC-14: the plain-function and collision suites must pass unchanged |

## 6. Decisions

- **D1–D6 (taken, from the shape, confirmed by the maintainer "All
  recommended", 2026-10-21T14:37:03Z):** Model A; invoked once under the
  class's group; strict collisions; refuse at decoration time; `JOB_TAGS`;
  `docs/guides/job-classes.md` titled "Job classes".
- **D7 (taken here, from the evidence):** `JOB_TAGS` is documented as
  `ClassVar[tuple[str, ...]]`. A bare class attribute on a pydantic model is a
  hard `PydanticUserError`, so the un-annotated spelling in `contracts.md` C2
  could never have run. The erratum is recorded in `## Alignment`.
- **D8 (taken here):** a class-method job's `JobDecoratorFilter` input is the
  method's decorators **plus its class's own `@job`**. The filter's purpose is
  "this job is written with `@job`"; for a class job, that decorator is on the
  class.
- **D9 (taken here):** an entry-point class is classified by reading the
  module's source and imported only when the source says it is a class. The
  alternative — importing to classify — would falsify the must-not-change
  sentence about function entry points.
- **D10 (needs maintainer review):** methods inherited from a base that lives in
  **another module** are enumerated live at materialisation and are therefore
  complete for a job-directory class and for `StaticProvider`, but for an
  entry-point class they are enumerated from the live import too (§4.6 imports
  on the class branch) — so the only residual gap is a distribution whose
  module source cannot be located at all. *Recommendation:* accept; the
  fallback is a finding, not a wrong job.

## Surviving smells

| Smell (catalogue) | Where | Why accepted | Maintainer review? |
|---|---|---|---|
| *Duplicate Code* — identity composed twice | `_entry_key` and `claim_order` | They live in peer modules of one layer and answer different questions (a dict key vs a sort order). One composed string, two readers, pinned by a test that asserts both agree on the `OtherPostgres`/`LocalPostgres` shape. | No |
| *Switch Statements* (avoided) — four `owner_class` branches | `sync`, `boot`, `_import_real_function`, `collision_projection` | Four sites, one condition each: `descriptor.owner_class is not None` (or `cls.owner_class is not None`), read off the record, never a type code or `isinstance` ladder. The catalogue's *Switch Statements* is branching on a type code; a field cannot drift the way a repeated `isinstance` chain does. The branches cannot be merged regardless: each lives in a layer that may not import the other's module. | No |
| *Speculative Generality* avoided, not carried | — | The proxy exposes only what a surface already reads (`signature`, `doc`, `name`, markers). No `__getstate__`, no pickling, no `__call__` fallback. | No |
| *Long Method* | `sync.extract_module` | The class branch moves to `_find_all_jobs`; `extract_module` grows by one call and stays under its current 99 lines. | No |

## 7. Risks

- **`ClassJobMethod` and `get_type_hints`.** `resolved_hints(proxy)` returns
  `{}` because `typing.get_type_hints` needs `__globals__`. The proxy resolves
  its own `__signature__` annotations at construction, so the fallback is
  harmless — but this is the one place a PEP 563 class job could regress
  silently, so a task asserts an `Annotated[..., Field(...)]` parameter on a
  class method survives into click params and into `ArgValidator`.
- **`_detect_config_class` on a class job.** Neither boot nor materialisation
  calls it: it looks at a constructor's parameters and would ask an ordinary
  function job's question about a job class. §4.4's class arm is reached first,
  so the call is unreachable cold; §4.6 sets `config_class` from
  `real_fn.job_class` warm. A test pins that a class job's config section is the
  class itself on both paths.
- **The declaration is read once.** `ClassJobMethod.__functualize_job__` is set
  at construction and `JobDescriptor.declaration` reads it; nothing may write a
  different one afterwards. The trap is that `adopt_descriptor_declaration`
  early-returns on a non-`None` `getattr`, and a read-through proxy would answer
  with the *method's* unmerged `@job` — a real object, so the guard would look
  satisfied and the merged declaration would be lost silently. §4.4 skips the
  call and §4.6 builds the warm proxy from the descriptor; a test asserts a warm
  run's guards, cache flags and deps equal the cold run's.
- **Model-identity checks.** `sync.py:417-419` and `registry.py:605-609` compare
  `inspect.getmodule(attr)` with the scanned module. `ModelMetaclass` preserves
  `__module__`, but a class re-exported through a package `__init__` must not be
  re-registered from it (C3 row 1); the class branch uses
  `cls.__module__ == module.__name__` for that reason, and a test pins a
  re-export.
- **Warm cache.** `CACHE_VERSION` 22 → 23 discards every existing cache once.
  That is the intended cost of `owner_class`; a test asserts a v22 payload is
  rejected rather than partially read.
- **Collision message stability.** C5 requires both definitions and both files.
  A message built from `python_name` would print `start` twice for two classes;
  the detail therefore carries `(qualified_name, source_file)` pairs with the
  class prefix already composed (`"OtherPostgres.start"`), and the test asserts
  on the serialized `as_dict()["message"]` — the string a reader actually sees
  — that both class names appear, rather than on a tuple a formatter could
  ignore.
- **`graphify` was unavailable** (`graph.json` absent), so cross-module impact
  rests on serena references plus `git grep` counts in §5. The counts are
  recorded per symbol so a reviewer can re-run them.
