# Class-based jobs — Tasks

Base: `origin/master` `bb3aac7`. Branch: `sdd/class-based-jobs`.
Spec: `spec.md` (AC-1–AC-14). Contracts: `contracts.md` (C1–C6). Plan:
`plan.md`. Internal types: `schema.md`.

Authoring-time gate runs (2026-10-21, at `8ef1381`):

- `git grep -n "isfunction\|isclass\|getmembers" -- src/functualize/_discovery src/functualize/_app` → `registry.py:607`, `sync.py:125`, `sync.py:383`, `sync.py:410` — all `isfunction`; **no `isclass`, no `getmembers`**.
- `git grep -n "isclass" -- src/ tests/` → **2 hits**, both in tests (`tests/_cli/test_typed_message_handlers_unit.py:109`, `tests/plugin/test_module_pre_filter.py:105`).
- `git grep -n "JOB_TAGS" -- src/ tests/ docs/ examples/` → **0 hits** (exit 1).
- `git grep -c "isfunction" -- src/functualize/_discovery` → `registry.py:1`, `sync.py:3`.
- `git grep -n "decorators=" -- src/functualize/_discovery/` → **1 hit**, `sync.py:303`.
- `git grep -n "extract_function_decorators" -- src/ tests/ plugins/ examples/` → **11 hits**: definition `_primitives/pre_filter.py:436`; imports/calls `sync.py:36`, `sync.py:249`; a docstring reference at `_primitives/job_filter.py:136` (text, not a call); tests `tests/discovery/test_discovery_failures.py:38,165,171,194` and `tests/discovery/test_job_filter.py:22,137,154`.
- `grep -rn "class job\|job class\|@job on" contributor/architecture/codemaps/` → **0 hits**.
- `uv run lint-imports` → **7 kept, 0 broken** ("Analyzed 395 files, 1149 dependencies").
- Pydantic probe (`uv run python`): a bare `JOB_TAGS = (...)` in a `BaseModel` body raises `PydanticUserError: A non-annotated attribute was detected`; the `ClassVar` form is readable from `cls.__dict__`; `Database.__abstractmethods__` is `frozenset({'start','stop'})` for an abstract class and `frozenset()` for a concrete subclass.

## Wave 0

- [x] **1.1 — `ClassJobMethod`, the instance-free callable of a class job** (C1; spec F1)
  - **[F]** `src/functualize/_types/class_job.py` (new), `tests/types/test_class_job.py` (new)
  - **Inputs:** `plan.md` §4.4; `schema.md` §6; `_types/annotations.resolved_hints`.
  - **Do:** `ClassJobMethod(job_class, method_name, declaration)` exposing
    `job_class`, `method_name`, `__signature__` (the method's signature with the
    first parameter removed, every resolvable annotation replaced by its live
    type), `__name__`/`__qualname__`/`__doc__`/`__module__`/`__annotations__`/
    `__wrapped__`, `__getattr__` delegating to the underlying function for
    everything *except* the declaration, `declaration` stored as the proxy's
    **own** `__functualize_job__`, and `__call__` raising `RuntimeError` that
    names the job. `__functualize_lazy__` must not be reachable as truthy. No
    other behaviour.
  - **Tests (unit):** signature excludes `self`, keeps the rest in order and
    keeps defaults; a fixture module with `from __future__ import annotations`
    and `Annotated[int, Field(ge=0)]` yields a live `Annotated` in
    `__signature__.parameters[...].annotation`; `__getattr__` delegates
    (`__doc__`, `__functualize_workflow__`, a capability marker);
    **`proxy.__functualize_job__ is declaration`** even when the method carries
    its own `@job(tags=("mine",))`, and `proxy.__functualize_job__ is not
    method.__functualize_job__` — the whole point of an own attribute, and the
    assertion that fails if it is left to `__getattr__`;
    `getattr(proxy, "__functualize_lazy__", False)` is falsy; calling it raises
    `RuntimeError`; `resolved_hints(proxy) == {}` — asserted, because the
    proxy's own resolution is what makes that fallback harmless.
  - **Invariants:** `_types` imports stdlib plus `_types.annotations` and, for
    annotations only, `_types.job_declaration`; the proxy holds no class
    instance and no module handle.
  - **Acceptance:** new suite green; `uv run lint-imports` still 7 kept.
  - **Reachability:** `TRANSITIONAL(no production caller until 3.1 constructs a proxy)`. No sabotage: there is no path to observe yet.

- [x] **1.2 — `@job` accepts a class** (C1, D4; spec F1)
  - **[F]** `src/functualize/job/decorators.py`, `tests/job/test_job_class_decorator.py` (new)
  - **Inputs:** `plan.md` §4.1; `job/decorators.py:46-111` (`apply` at 104-106,
    bare-vs-parameterized branch at 109-111).
  - **Do:** in `apply`, before the assignment: a class target must subclass
    `pydantic.BaseModel` (`ValueError` naming the target); on a class only
    `group`, `tags`, `visibility` are accepted, one `ValueError` listing every
    offending argument; `"__functualize_job__" in func.__dict__` →
    `ValueError("@job is already applied to <qualname>; combine the arguments
    into one @job(...)")`. The assignment and the identity guarantee stay as
    they are.
  - **Tests (unit):** `@job` and `@job(group="pg")` on a model return the same
    object; `@job(config_section="x", deps=())` on a class names both arguments;
    a second `@job` on a class and on a function produce the exact D4 text; a
    non-model class is refused; a class inheriting `@job` is **not** refused at
    decoration (F1-b is discovery's rule), and `"__functualize_job__" not in
    Sub.__dict__`; the bare and parameterized function forms are unchanged.
  - **Invariants:** `decorated is original` for every accepted form; pydantic is
    imported inside `apply`, so `import functualize.job` adds no new import.
  - **Acceptance:** `tests/job` green, existing cases untouched.
  - **Reachability:** `TRANSITIONAL(declaration only; consumed by 3.1)`.

**1.3 was removed in review** (it was `[ ] 1.3 — JOB_TAGS documented and pinned
as a ClassVar`). Its content was two document spellings plus a test asserting
pydantic rejects a bare `JOB_TAGS` — a test of pydantic, not of this feature,
which could not fail for a reason this change caused. The spellings are fixed in
`spec.md` F4/AC-5 and `contracts.md` C2 during the plan phase; the falsifiable
half — that the documented `ClassVar` form is visible in `cls.__dict__` and
absent from `model_fields` — moved to task 3.1's tests, where the code that
reads `JOB_TAGS` lives. Wave 0 is therefore two tasks, and the feature is 13
tasks in five waves.

## Wave 1

- [x] **2.1 — descriptor provenance `owner_class` and cache version 23** (C3; spec AC-7, AC-10)
  - **[F]** `src/functualize/_types/descriptors.py`, `src/functualize/_primitives/cache_format.py`, `tests/types/test_descriptor_owner_class.py` (new), `tests/discovery/test_nfkc_cache_rebuild.py`, `tests/discovery/test_job_declaration_discovery.py`
  - **Inputs:** `plan.md` §4.3; `schema.md` §1, §3;
    `_types/descriptors.py:215-473` (`to_dict` 290-328, `from_dict` 331-473,
    `required_keys` 343-353, `python_name` 471); `_primitives/cache_format.py:156-160`.
  - **Do:** add `owner_class: str | None = None`; `to_dict` writes
    `"owner_class"`; `from_dict` reads `data.get("owner_class") or None`; add
    `owner_class` to `required_keys` **only if** an older payload must be
    refused by shape rather than by version — it must not be, so it stays out.
    `CACHE_VERSION` 22 → 23 with a `# v23 —` entry in the existing block.
    `attribute_name` and `python_name` semantics do not change.
  - **Tests (unit):** round trip preserves `owner_class`; a payload without the
    key deserialises to `None`; `to_dict` always writes the key; a payload with
    `version: 22` is not accepted by the cache reader; `CACHE_VERSION == 23`.
    Update the NFKC rebuild assertion from `== 22` to `== CACHE_VERSION`;
    update the declaration-cache version pin from `== CACHE_VERSION == 22`
    to `== CACHE_VERSION == 23`.
  - **Invariants:** every existing descriptor key keeps its name and type;
    `python_name` stays undotted.
  - **Acceptance:** AC-7's warm-cache half is testable from here on.
  - **Reachability:** `TRANSITIONAL(round-trip only; the cache path is exercised by 4.1)`.

- [x] **2.2 — the cache key and the claim order know the class** (C3; spec AC-10)
  - **[F]** `src/functualize/_discovery/cached_provider.py`, `src/functualize/_discovery/collisions.py`, `tests/discovery/test_class_identity.py` (new)
  - **Inputs:** `plan.md` §4.3; `schema.md` §2; `cached_provider.py:528-600`
    (`_entry_key` 545, `_add_entry` 547-550, `_claim_name` 552-570);
    `collisions.py:40-57`.
  - **Do:** `_entry_key` returns
    `f"{source_file}::{owner_class}.{python_name or name}"` when `owner_class`
    is set and the current string otherwise; `claim_order` composes the same
    string in its second slot. Both are the only readers of the identity rule;
    no third copy.
  - **Tests (unit):** two descriptors for `OtherPostgres.start` and
    `LocalPostgres.start` in one file produce two entries (the silent overwrite
    is gone); `claim_order` orders them deterministically and agrees with
    `_entry_key`; a fixture of plain function descriptors produces the exact
    strings it produced before (golden assertion on both functions).
  - **Invariants:** no behaviour change for a descriptor without `owner_class`.
  - **Acceptance:** the AC-10 precondition — two same-named methods in one file
    reach collision resolution as two claimants.
  - **Reachability:** `TRANSITIONAL(no class descriptor exists until 3.1)`;
    the golden half is reachable today through `DirectoryScanProvider`.

## Wave 2

- [ ] **3.1 — discovery: a module's job classes become descriptors** (C1, C2; spec F1, F1-a, F1-b)
  - **[F]** `src/functualize/_discovery/sync.py`, `tests/discovery/test_class_jobs.py` (new)
  - **Inputs:** `plan.md` §4.2; `sync.py:210-308`, `:377-432`;
    `_discovery/naming.py:58-64`; `_types/job_declaration.py:484-521`; the
    `Postgres`/`Database`/`TunedPostgres` examples in `contracts.md` C1–C2.
  - **Do:** rename `_find_all_job_functions` → `_find_all_jobs` (function branch
    byte-identical) and add the class branch: own-namespace
    `__functualize_job__` (F1-b), `cls.__module__ == module.__name__`,
    `issubclass(cls, BaseModel)`; `__abstractmethods__` non-empty → one
    "abstract job class" finding naming the class, its module and each
    unimplemented method, no jobs; MRO walk nearest-first skipping `BaseModel`,
    `object` and pydantic's own bases, dropping `_`-prefixed names,
    `staticmethod`, `classmethod`, `property` and `cached_property`; per method
    **first the effective declaration** — group from the class, `visibility`
    from the method else the class, `tags` merged author-first then the class
    `@job(tags=)` then `JOB_TAGS` from the job class outward along the MRO with
    duplicates removed, and `guards`/`exec`/`cache`/`deps` from the method only
    — **then** the descriptor, with
    `name=qualified_name(raw_group, method)`, `python_name=method`,
    `owner_class=cls.__name__`, `group=class group`, `config_fields` from
    `cls.model_fields`, `parameters` from
    `extract_parameters_from_signature(proxy)`, and
    `function=ClassJobMethod(cls, method, declaration=effective)`. That one
    object is passed to the proxy as its own `__functualize_job__` and is what
    `JobDescriptor.declaration` reads back — nothing after 3.1 recomputes it
    (plan.md §4.2). A method whose own
    `@job(group=...)` differs from the class group produces no job and one
    "method group conflict" finding naming the method, its class and both
    groups.
  - **Tests (unit):** C1's `Postgres` → exactly `pg.start`/`pg.stop`; a private
    method and a property are not jobs; a `classmethod`/`staticmethod` is not a
    job; `TunedPostgres` produces none (F1-b); an abstract class with its own
    `@job` produces a finding that names `start` and `stop`; an abstract class
    without `@job` produces nothing at all; a method group conflict produces a
    finding naming both groups and no descriptor; `JOB_TAGS` from a base yields
    merged tags in the declared order with duplicates removed, and the
    documented spelling is the one that works — `JOB_TAGS` is in
    `cls.__dict__`, not in `cls.model_fields`; class `visibility` applies when
    the method sets none and is overridden when it does; a class re-exported
    through a package `__init__` is not registered from that module.
  - **Declaration is computed once (F2):** the descriptor's `declaration` and
    the descriptor's `function.__functualize_job__` are the **same object**
    (`is`), and that object carries the merged tags of a class `JOB_TAGS` even
    when the method has its own `@job(tags=...)`. Recomputing at any later stage
    breaks this assertion rather than drifting silently.
  - **Invariants:** the function branch's descriptor fields are unchanged; no
    module import for a class beyond the module already being scanned; no
    instance is constructed anywhere in `_discovery` (AC-4).
  - **Acceptance:** AC-1's descriptor set and AC-5's tag order are observable
    on `app.get_jobs()` without booting a CLI.
  - **Reachability:** commit, then sabotage the own-namespace read to
    `getattr(cls, ...)` → `TunedPostgres` gains two jobs and the test fails;
    restore. `TRANSITIONAL` for the run path until 4.1.

- [ ] **3.2 — decorators recorded from a class body** (C2; spec F4, AC-5)
  - **[F]** `src/functualize/_primitives/pre_filter.py`, `src/functualize/_primitives/job_filter.py`, `src/functualize/_discovery/sync.py`, `tests/discovery/test_class_job_filter.py` (new)
  - **Inputs:** `plan.md` §4.2; `pre_filter.py:426-469` (`extract_decorator_root_name`
    426-433, the function loop 459-460); `job_filter.py:132-160`;
    `sync.py:249`, `:303`.
  - **Do:** `extract_function_decorators` returns the same dict for top-level
    functions and adds `"<Class>.<method>"` keys for methods (`ClassDef`
    branch, one level of nesting documented); `sync` looks up
    `f"{cls.__name__}.{method}"` with a bare-name fallback; for a class-method
    job the decorator set the filter sees also includes the class's own `@job`
    (D8), because that decorator is what brings the job into existence.
  - **Tests (unit):** the existing `test_job_filter.py` /
    `test_discovery_failures.py` expectations hold unchanged (bare keys); a
    method with `@cache` and a class with `@job` are recorded under
    `"Pg.start"`; `JobDecoratorFilter(["job"])` admits a class job whose method
    carries no decorator; `JobPostfixFilter("_job")` judges the method name.
  - **Invariants:** no change to the returned type; plain function keys are
    byte-identical.
  - **Acceptance:** AC-5's `descriptor.decorators` is non-empty for a class job.
  - **Reachability:** covered by 3.1's descriptors, which do carry `decorators=`.

- [ ] **3.3 — a strict collision has a record that survives "neither registered"** (C5; spec F5, AC-6)
  - **[F]** `src/functualize/_types/discovery_report.py`, `src/functualize/_discovery/collisions.py`, `tests/discovery/test_class_collisions.py` (new)
  - **Inputs:** `plan.md` §4.5; `schema.md` §7; `_types/discovery_report.py:47-206`;
    `collisions.py:57-96`.
  - **Do:** `CLASS_JOB_NAME_COLLISION = "ClassJobNameCollision"` and
    `ClassJobCollisionDetail(canonical_name, claimants)` where each claimant is
    `(qualified_name, source_file)` — `"OtherPostgres.start"` for a class job,
    the function's own name otherwise; the message is formatted from these pairs
    because `python_name` is the *method* name and would print `start` twice.
    Widen `DiscoveryFailure.collision`'s type
    without touching `as_dict`'s four keys; in `resolve_name_collisions`, when
    at least one claimant has `owner_class`, keep none, register every other
    name, and record one finding whose message names every claimant and its
    file. Two plain functions keep the existing path untouched.
  - **Tests (unit):** `OtherPostgres` vs `LocalPostgres` in one file → `postgres.start`
    and `postgres.stop` both collide, both findings name both classes and the
    file, `pg.*` from the same module still registers; the assertion is on the
    serialized `as_dict()["message"]` — that it contains `OtherPostgres` and
    `LocalPostgres` — not on the detail's tuple, so a formatter that dropped the
    class prefix fails; a class job against a
    plain function collides; two plain functions still produce
    `JobNameCollision` with its four `as_dict` keys and its existing message
    (golden).
  - **Invariants:** `JobNameCollisionDetail`, `job_name_collision(...)` and
    every rendering of them are unchanged; `as_dict` still returns exactly
    `module`, `path`, `error_type`, `message`.
  - **Acceptance:** AC-6's discovery half; AC-14's collision suite.
  - **Reachability:** reachable through a temp-project `DirectoryScanProvider`
    scan; sabotage the `owner_class` test into `False` and the strict finding
    becomes a `JobNameCollision`.

- [ ] **3.4 — providers: a class is a source, not an item** (C3; spec AC-13)
  - **[F]** `src/functualize/_discovery/providers.py`, `src/functualize/_discovery/ast_extractor.py`, `tests/discovery/test_provider_class_sources.py` (new)
  - **Inputs:** `plan.md` §4.6; `providers.py:624-693` (`StaticProvider`,
    `_build_descriptor` 658-693), `:700-879` (`EntryPointProvider`,
    `list_jobs` 780-819, `_materialize` 821-851, `_build_descriptor` 853-879);
    `ast_extractor.py` header.
  - **Do:** `StaticProvider` fans a class item out into one descriptor per
    method (same builder 3.1 uses, called through one shared helper, not a
    second copy) and raises `ValueError` at construction for
    `Job(function=<class>)` with C3's text. `EntryPointProvider.list_jobs`
    resolves `module_path` with `importlib.util.find_spec(...).origin`,
    classifies with the new `ast_extractor.class_in_source`, and imports the
    module **only** when the name is a class with its own `@job`; otherwise the
    descriptor is today's (one per entry point, `function=None`, no import). A
    source that cannot be resolved keeps today's descriptor; materialisation of
    a class it then finds raises a `JobMaterializationError` naming the entry
    point.
  - **Tests (unit):** a function-only entry point distribution performs no
    import of the job module (assert on `sys.modules` before/after);
    a class entry point yields one descriptor per method with `owner_class`
    set; `StaticProvider([Postgres])` yields the same descriptors as the
    directory scan of the same module; `StaticProvider([Job(function=Postgres)])`
    raises `ValueError`; the same class from both sources collides per 3.3; a
    malformed entry point is still warned and skipped, unchanged; an
    unlocatable-source case — a zipimport fixture: a `.whl` on `sys.path`
    whose module is the entry-point target and whose source `open()` cannot
    read (`NotADirectoryError`, errno 20) — `list_jobs()` returns exactly one
    descriptor with `function=None` and the module never enters `sys.modules`;
    first materialisation raises `JobMaterializationError` whose message names
    the entry point and the class and does not contain `failed to import
    module`.
  - **Invariants:** "enumeration imports nothing" holds for function entry
    points; `find_spec` imports parent packages only — asserted by checking the
    job module is absent from `sys.modules`.
  - **Acceptance:** AC-13's descriptor side.
  - **Reachability:** reachable through `StaticProvider` and a fixture
    distribution; sabotage the classify call to always return `False` and the
    class entry point yields one function-shaped descriptor.

- [ ] **3.5 — materialisation resolves a method, not an attribute** (C3; spec AC-13)
  - **[F]** `src/functualize/_discovery/lazy_wrapper.py`, `tests/discovery/test_materialize_class_job.py` (new)
  - **Inputs:** `plan.md` §4.6; `lazy_wrapper.py:64-138` (`_import_real_function`,
    `getattr(module, descriptor.attribute_name)` at 131-132), `:141-215`
    (`LazyJobFunction`, `materialize` 166-204).
  - **Do:** after `importlib.import_module(module_path)`, a descriptor with
    `owner_class` resolves `getattr(module, owner_class)` then the method, and
    returns `ClassJobMethod(cls, method, declaration=descriptor.declaration)` —
    built **from the descriptor**, so the warm proxy carries 3.1's merged
    declaration rather than a freshly computed one. `LazyJobFunction.materialize`
    then takes `config_class` from `real_fn.job_class` for a class descriptor —
    the unconditional `self.config_class = _detect_config_class(real_fn)` at
    `:200` becomes the function path only, so no detection runs on
    a proxy; the synthetic-source branch, the import lock and the `sys.path`
    handling above it are untouched. On the function branch, after `getattr(module,
    descriptor.attribute_name)` (`:131-132`), an `isclass` check: a class
    reached where a function was expected raises the materialisation error
    naming the entry point and the class, and is never handed to
    `_build_descriptor`, whose `callable()` test (`providers.py:853-855`,
    `func = obj if callable(obj) else lambda: None`) accepts a class because a
    class is callable.
  - **Tests (unit):** a warm descriptor (no `function`) materialises to a proxy
    whose `job_class` is the class and whose `method_name` is the method, and
    whose `__functualize_job__` is the descriptor's declaration object (`is`);
    `_ensure_materialized` keeps `config_class` as the job class; a
    missing class or method raises the existing materialisation error type with
    the descriptor's identity in the message; a plain-function descriptor takes
    the unchanged path; a plain descriptor whose attribute resolves to a class
    raises the materialisation error naming the entry point and the class —
    the `isclass` guard, with `_build_descriptor` never reached.
  - **Invariants:** no second import lock, no `sys.path` change.
  - **Acceptance:** a lazy boot reaches a class job.
  - **Reachability:** reachable from `LazyJobFunction.materialize` directly,
    before 4.1 wires it to a command.

## Wave 3

- [ ] **4.1 — registration and the receiver** (C1, C6; spec F1, AC-2, AC-3, AC-4, AC-7, AC-11)
  - **[F]** `src/functualize/_types/descriptors.py`, `src/functualize/_engine/context.py`, `src/functualize/_engine/executor.py`, `src/functualize/_app/boot.py`, `tests/engine/test_class_job_receiver.py` (new), `tests/cli/test_class_job_acceptance.py` (new)
  - **Inputs:** `plan.md` §4.4; `schema.md` §4, §5; `_types/descriptors.py:552-579`;
    `_engine/context.py:94-107`; `executor.py:1220-1259`, `:2555-2632`,
    `:2634-2648`; `_app/boot.py:1986-1987` (the early return), `:2003-2059`;
    `_app/configuration_facade.py:59-81`.
  - **Do:** `RegisteredJob.method_name`, `ExecutionContext.method_name`; boot's
    **class arm first** — `if descriptor.owner_class is not None:` →
    `function = live_fn if live_fn is not None else LazyJobFunction(descriptor)`,
    `config_class = getattr(fn, "job_class", None)` (the proxy, cold or warm,
    answers this from the class), `method_name = descriptor.python_name`. Cold
    and warm therefore take one path: neither calls `_detect_config_class`
    (`getattr(..., "job_class", None)` is the whole answer) and neither calls
    `adopt_descriptor_declaration` — it early-returns on a non-`None`
    `getattr(func, "__functualize_job__", None)` (`boot.py:1986-1987`), and the
    function arm below it stays byte-identical for function jobs. `method_name`
    comes from the descriptor, so `JobDescriptor` gains no such field. The
    context is built with `method_name`; `_resolve_config_model` ends with the
    one documented rebind.
  - **Tests (unit):** a class job registers with `config_class` = the class and
    `method_name` = the method; the rebind produces a callable whose call
    receives the resolved instance as the receiver and whose `call_kwargs`
    never contains `self`; `context.injected` is unaffected; the config section
    key is `descriptor.group` (`[pg]`), not `pg.start`; the instance count
    after `list_jobs` + `--help`-shaped introspection is 0 (AC-4).
  - **Tests (declaration, F2):** (a) through a **public** surface — `app.get_jobs()`
    and `func builtin info --json` for one class job — the tags are the merge of
    the method's `@job(tags=...)`, the class `@job(tags=)` and `JOB_TAGS` in the
    documented order, the class `visibility` is in effect, and a method
    `guards=` is present; nothing in the test reads `_discovery` internals or
    calls `descriptor.declaration` directly. (b) **warm equals cold**: a run of
    the same job against a warm cache has the same effective guards, cache flags
    and injected deps as the cold run — the assertion that catches a warm proxy
    rebuilt with the method's unmerged `@job`.
  - **Tests:** CLI-level AC-2/AC-3 in the fixture project of `spec.md` § AC
    preamble, then **AC-11**: `func builtin vault put --group pg --field
    password`, then `func pg start` and `func pg stop` each receive that one
    entry — both, not just the method that was run first, so a per-method
    config instance would show; `func builtin info` and `env` mask it; and
    `func pg <TAB>`-shaped completion for the class job returns its methods
    without constructing the class (AC-4). Re-run those CLI cases once with the
    cache warm and assert identical output (AC-7's class-job half).
  - **Invariants:** no `_discovery` import from `_engine`; `registered_job`
    shape additive; function jobs unaffected.
  - **Acceptance:** AC-1, AC-2, AC-3, AC-4, AC-7, AC-11.
  - **Reachability:** sabotage the rebind to pass the proxy → the run fails with
    the proxy's `RuntimeError`; restore.

- [ ] **4.2 — the strict collision reaches the CLI and the programmatic caller** (C5; spec AC-6)
  - **[F]** `src/functualize/_cli/info.py`, `src/functualize/_cli/main.py`, `src/functualize/_engine/capabilities/invoke.py`, `src/functualize/_app/impl.py`, `tests/cli/test_class_collision_surfaces.py` (new)
  - **Inputs:** `plan.md` §4.5; `_cli/info.py:111-211`, `:413-435`;
    `_cli/main.py:937-946`, `:1494-1502`, `:1540-1558`;
    `app/adapters/cli.py:1322-1360`, `:1605-1653`;
    `_engine/capabilities/invoke.py:234-246`, `:636-676`;
    `_app/impl.py:954-961`.
  - **Do:** `collision_projection` keeps a strict finding under its canonical
    name with empty registered fields instead of dropping it; `func builtin
    info` renders the name with both definitions and files, in the human table
    and in `--json`; `_cli/main.py` returns `2` with the C5 message before the
    "Did you mean" fallback; `invoke` and `app.execute` raise the same
    `JobNotFoundError` with that message.
  - **Tests:** `func pg stop` still runs in the collision project; the colliding
    name exits `2`, names both definitions and both files on stderr, and
    `func builtin info` lists it; `func builtin info --json` carries the
    finding's four keys plus the third collision shape; `invoke("postgres.start")`
    raises `JobNotFoundError`; a plain-function collision renders exactly as
    before (golden).
  - **Invariants:** no new envelope key or exit code; `ExitCode.USAGE` is the
    only new code in play; the four-key payload is intact.
  - **Acceptance:** AC-6, AC-8 (vocabulary review of these strings).
  - **Reachability:** sabotage the strict branch's registration skip → both
    claimants register and the name exits 0; restore.

- [ ] **4.3 — docs, examples and changelog** (D6; spec AC-8)
  - **[F]** `docs/guides/job-classes.md` (new), `docs/guides/jobs-discovery.md`,
    `docs/guides/subjects.md`, `examples/standalone/job_classes_lab/` (new:
    `README.md`, `project/`, `tests/`), `CHANGELOG.md`
  - **Inputs:** `plan.md` §4.7; `docs/guides/jobs-discovery.md:133-155`;
    `docs/guides/subjects.md:152`; `examples/standalone/discovery_lab/` as the
    shape; `AGENTS.md` public-API example rule.
  - **Do:** the guide in D6's title and vocabulary; the two sentences that
    currently teach "a class is not a job" rewritten with a cross-reference; the
    `subjects.md` constructor sentence gains the per-invocation clause; the
    example lab with a "Run → Expect" table and a test that exercises a class
    job, `JOB_TAGS`, and a collision; one `## [Unreleased]` `### Added` entry.
  - **Tests:** `uv run pytest examples/ -v`.
  - **Invariants:** R-1 vocabulary; no reference to `.spec/proposals/` or
    `.spec/scrutiny-reports/`; every command in the README is one a reader can
    type.
  - **Acceptance:** AC-8; the example project passes.
  - **Reachability:** the example test runs the real CLI.

## Wave 4

- [ ] **5.1 — Checkpoint**
  - **[F]** none (verification only).
  - **Do:** `uv run ruff check --fix src/ tests/ plugins/ examples/`,
    `uv run ruff format --check src/ tests/ plugins/ examples/`,
    `uv run mypy src/`, `uv run lint-imports`,
    `uv run pytest -x -q --no-header`,
    `uv run pytest examples/ -v`,
    `uv run python .github/scripts/dead_code_delta.py origin/master HEAD`;
    then AC-7's full sweep by hand: in the acceptance fixture project, clear
    the cache, run the AC-1/AC-2/AC-11 command set and capture
    `func builtin info jobs --json`, `func builtin info --json` and both job
    runs (cold), then run the same set again against the cache the first run
    left (warm) and capture the same four outputs — the two captures are
    byte-identical, and the vault value still reaches `self` on the warm run.
  - **Acceptance:** all green; `lint-imports` prints "7 kept, 0 broken"; the
    dead-code delta is pasted into the hand-off; the cold/warm diff is empty;
    AC-9 and AC-14 are reviewed
    against the diff rather than asserted by a new test.

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1.1", "1.2"] },
    { "id": 1, "tasks": ["2.1", "2.2"] },
    { "id": 2, "tasks": ["3.1", "3.2", "3.3", "3.4", "3.5"] },
    { "id": 3, "tasks": ["4.1", "4.2", "4.3"] },
    { "id": 4, "tasks": ["5.1"] }
  ]
}
```
