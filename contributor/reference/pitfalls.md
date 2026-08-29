# Pitfalls — Mistakes This Codebase Already Made

Every entry below is a **defect that shipped**, was diagnosed, and was fixed. They
are recorded here because each one is easy to reintroduce: the wrong version looked
correct, passed review, and in several cases passed a test.

This is not a style guide. It is a list of traps with the shape of the trap named,
so you can recognize it in new code.

## Quick index

| # | Trap | Recognize it by |
|---|---|---|
| 1 | A setting resolves and displays but is wired to nothing | `config show` prints it; no code path reads it |
| 2 | Blanket `suppress(Exception)` hides a typo | A feature silently does nothing, no error anywhere |
| 3 | File-level filter standing in for a function-level one | "at least one X in the file" qualifying the whole file |
| 4 | Raw `param.annotation` under PEP 563 | Works until `from __future__ import annotations` appears |
| 5 | Two caches for the same data | Two files, two validation rules, two answers |
| 6 | The same list hardcoded in N places | Descriptions drift; one copy is missing an entry |
| 7 | `App.suspend()` in the inline TUI | `SuspendNotSupported` at runtime |
| 8 | Widget mounted without moving the key-routing target | Every key dead except `Esc` |
| 9 | A bound key with no footer hint | Indistinguishable from a missing feature |
| 10 | Blocking work on the Textual event loop | Whole interface freezes during a refresh |
| 11 | `sys.modules` scraping by plain module name | Breaks under lazy boot; finds the wrong file |
| 12 | Assuming boot imported everything | Hard-coded `None` where materialization should detect |
| 13 | Registering after the reader already ran | `Unknown command` for a command that exists |
| 14 | Declaring a guarantee the runtime cannot enforce | `timeout` that never fires |
| 15 | A test asserting "not the one wrong answer" | Passes on a second wrong answer |
| 16 | A syscall on the left of `and` | `x.is_file() and name_matches(x)` — one stat per candidate |
| 17 | `ast.parse` standing in for "the names resolve" | Generated code parses, then `AttributeError`s at runtime |
| 18 | A hand-written blocklist of a library's reserved names | Passes for months, fails once a wider input budget draws the missing one |
| 19 | One rule spelled independently in layers that may not import each other | Every copy is *correct*; the tool names a variable that resolves nothing |
| 20 | Cross-test pollution that the default file order happens to hide | Passes as `pytest tests/`; fails on a subset, or intermittently under `-n auto` |

---

## 1. A setting that resolves and displays is not a setting that works

`require_job_prefix` and `require_job_postfix` were resolved from config, stored,
and printed by `config show` for months. No code ever read them. Setting either had
no effect whatsoever, and the surface that should have revealed this — the settings
display — was the thing giving false assurance.

`display_auto_switch` failed the same way for a different reason: `_apply_settings`
called `set_display_auto_switch`, but the real method is `set_auto_switch_setting`.
See trap 2 for why nobody saw the `AttributeError`.

**Recognize it:** a config key with a resolver and a display, and no test asserting
the value reaches its consumer.

**How to apply:** a setting is done when a test asserts the *behavior changes*, not
when `config show` prints it. Grep for readers of the key before calling it wired.

## 2. Blanket `suppress(Exception)` converts typos into silent no-ops

The `display_auto_switch` `AttributeError` above was swallowed by a bare
`contextlib.suppress(Exception)` wrapped around the apply block. The setting
resolved correctly, displayed correctly, and did nothing.

**How to apply:** suppress specific exceptions you have a reason to expect. A bare
`suppress(Exception)` around a call you control is hiding your own bugs, not
handling someone else's.

## 3. A file-level filter is not a function-level filter

`require_job_decorators` was implemented as a *file*-level pre-filter: a file
containing at least one decorated function qualified, and then every public function
in it — decorated or not — became a job. The documented behavior was per-function.

Two follow-on facts that are easy to get wrong when reimplementing:

- **Decorator names come from the source AST**, recorded on
  `JobDescriptor.decorators`. A transparent decorator leaves nothing to introspect
  after import, so runtime inspection cannot answer the question.
- **Job-level filters apply on cache *read*.** The cache stays a superset of what
  any one filter admits, so changing a filter takes effect without `cache clear`.

The filters live in `_primitives/job_filter.py` (`JobPrefixFilter`,
`JobPostfixFilter`, `JobDecoratorFilter`), built by `build_job_filter_from_config`
in `_discovery/filter_factory.py`.

**Also:** a filtered-out job must be *unreachable by name*, not merely hidden from
listings — the CLI's pre-boot routing applies the same filter.

## 4. Never read `param.annotation` raw

Under `from __future__ import annotations` (PEP 563) every annotation is a string.
Code reading `param.annotation` directly works fine until someone adds that import
to a job module, at which point DI silently stops matching and declared constraints
stop being enforced.

**How to apply:** use `resolved_hints()` from `functualize._types.annotations`.
When testing anything annotation-driven, compile the fixture module **both ways** —
with and without the future import.

## 5. One piece of data, one cache

The framework once maintained two parallel persisted caches of the same job
descriptors, with different validation rules and different invalidation triggers, so
`cache show` and `cache clear` could operate on different files and report
contradictory answers.

There is now exactly one: `CachedDirectoryScanProvider` owns a single `cache.json`.
The format version and path resolution are defined once in
`_primitives/cache_format.py` (`CACHE_VERSION`, `resolve_cache_path()`).

**How to apply:** bump `CACHE_VERSION` when the descriptor shape changes; caches
rebuild once, automatically. Never add a second cache file for a slice of the same
data.

**A cache must also fingerprint the *configuration* that produced it, not only the
shape of what it stores.** The header fingerprinted the format version, package
version, Python version and dependency hash — and not the discovery config, so a
cache built under one filter set was replayed under another. Adding
`[discovery] exclude_patterns` after a warm run did nothing, and one `--exclude`
invocation removed the excluded jobs *permanently*, because `PreFilterDecision`
persists negative decisions with no record of which filter produced them. See
[ADR-010](../adr/010-discovery-cache-filter-awareness.md). The general form: if a
setting changes what goes into the cache, a change to that setting has to be able
to invalidate it — and the test has to run the *transition*, because every filter
test in the suite ran cold and all of them stayed green through the defect.

## 6. A list hardcoded in five places has already drifted

The builtin command list existed in five hardcoded copies. By the time anyone
checked, `config` was documented with two different descriptions, and autocomplete
was missing `cache rebuild` entirely.

`_cli/builtins.py` now exports a single `BUILTIN_COMMANDS` registry that dispatch,
introspection, job listing, smart-bar autocomplete, provenance, and the job browser
all derive from — **and a test asserts the registry matches the real click command
tree**, so the registry cannot drift from the commands it describes.

**How to apply:** one registry, plus a test that checks it against the thing it
describes. A registry nothing verifies is just a sixth copy.

## 7. Textual cannot suspend in inline mode

`App.suspend()` raises `SuspendNotSupported` in the inline TUI. Any work that needs
the terminal — `config edit` spawning `$EDITOR`, a `tty: TTY` job, a `!` shell
command — must step aside through the **orchestrator handoff**
(`app.request_handoff(tokens)`), which runs the work on the main thread and
relaunches the shell afterward.

`CommandNode.needs_terminal` is the seam that decides this. Do not special-case
`builtin` or any other command name.

## 8. Mounting a widget does not move the key-routing target

The Config Files drill-down mounted a `RichLog` while leaving the file *list* as the
key-routing target. Every key except `Esc` was dead: `j`/`k` moved a hidden cursor
and `i`/`d`/`Ctrl+S` reached nothing. The staged-edit and atomic-save code was fully
implemented and completely unreachable.

**How to apply:** detail views are **pushed widgets** (`PanelHost.push_view`), so the
existing dispatcher routes to them. If you mount a view and keys still go somewhere
else, you have built a dead screen.

## 9. A bound key with no hint is a missing feature

The `n new file` binding shipped without a footer hint. From the user's side, a key
nobody can discover is indistinguishable from a feature that does not exist.

Check the hint names the *actual* ring, too — the Settings Files panel advertised the
inherited `Ctrl+R` instead of its own `Ctrl+E`.

## 10. Nothing that can block runs on the event loop

`DisplayProvider.refresh()` ran on the event loop, so a display shelling out to
`docker ps` or `git` froze the entire interface. This violates the HARD rule in
`contributor/guides/steering_textual_tui.md` §2.5.

It now runs on a thread worker with one in-flight refresh per display, a
per-provider `refresh_timeout` (default 10s) that abandons a hung cycle rather than
pinning a worker, and a placeholder until the first refresh returns.

**Related:** read every *optional* provider attribute with a default. A minimal
display crashed the timer loop because four optional attributes were read unguarded.

## 11. `sys.modules` scraping is broken under lazy boot

`show-info --job <name>` resolved a job's config class by scraping `sys.modules` for
the plain module name. Under lazy boot the module is not imported, so this finds
nothing — or worse, finds a **same-named module from a different directory** left
over from an earlier scan, possibly a since-deleted path.

**How to apply:** ask the engine for its registered entry. When reloading, reload
only if the cached module's file matches the expected source; otherwise load fresh.

## 12. Under lazy boot, "it was imported at boot" is false

`RegisteredJob.config_class` was hard-coded to `None` on the lazy path, so
`rc.invoke()` of a lazily-registered job never resolved or injected its Pydantic
config. The eager path worked, which is why it survived review.

**How to apply:** anything the eager path learned *by importing* must be detected at
**materialization** on the lazy path. Test both paths, or the lazy one is untested.

## 13. Registration order versus reader order

Plugin CLI commands register at `APP_READY` — *after* pre-boot mode detection has
already run. Global `func` therefore never dispatched them, and `func mcp serve`
failed with `Unknown command 'mcp'` while the docs documented it.

They are now resolved post-boot: `GROUP` mode and the `UNKNOWN` fallback both consult
`app.get_plugin_commands()` alongside jobs, with a job winning an exact-name conflict.

**How to apply:** when adding a registry, check *when* it is populated relative to
every reader. A reader that runs first sees an empty registry.

## 14. Do not declare what the runtime cannot enforce

`Exec(timeout=...)` was removed because it could not be enforced: Python cannot
interrupt a running thread. The declaration promised something no implementation
could deliver, which is worse than not offering it — users wrote it and believed it.

(`rc.invoke(..., timeout=...)` is a different mechanism and does work.)

**Related:** `$ENV` is validated as a filename segment before use, because POSIX
`sh`/`ksh` set `ENV` to a *startup-file path*. Taken as an environment name, it
silently made every config overlay inert.

## 15. Assert the right answer, not the absence of one wrong answer

A test asserted `mode != "subcommand"`. The bug produced `"command"`, which
satisfies that assertion perfectly. The test passed for the entire life of the
defect.

A second instance: `tests/config/test_env_overlay_properties.py` passed throughout a
period when the environment overlay **did not exist at all**, because it hand-built
two `FileSource`s with globs it constructed itself instead of driving the real
kernel.

**How to apply:** assert the exact expected value. Drive the real component, not a
hand-assembled stand-in of it. If a test cannot fail when the feature is deleted, it
is not testing the feature.

## 16. A syscall on the left of `and` runs for every candidate

`discover_config_path` walks from the CWD up to `$HOME` looking for a config file.
Per directory it ran:

```python
if not (entry.is_file() and regex.match(entry.name)):
    continue
```

`is_file()` is a `stat()` syscall. `regex.match(entry.name)` is pure string work.
Python evaluates left to right, so every entry in every ancestor directory was
stat'd *before* anything looked at its name. From a CWD under a busy `/tmp` that
measured **17,249 stat calls per boot** to find nothing, and it was 63% of total
boot time.

Both name predicates are pure, so ordering them first cannot change which directory
is chosen. Reordering took `boot.config_resolution` from 158.67ms to 41.02ms and
total boot from 250.87ms to 125.00ms.

**How to apply:** in a compound condition, order the tests by cost, cheapest first —
string and in-memory checks before anything that touches the filesystem, the network,
or an import. The cost is invisible at the call site: `entry.is_file()` reads like an
attribute lookup. It scales with the *user's* filesystem, not with your input, so it
will not show up in a small test fixture.

## 17. `ast.parse` proves syntax, and nothing else

`scaffold/templates/full-interactivity/workflow_job.py.j2` referenced
`RunStatus.FAILED` on four lines. The enum spells it `FAILURE`; there is no `FAILED`
member. Every generated project raised `AttributeError` the moment the user's job hit
a failure path — and only then, because the success path used members that exist.

`tests/scaffold/` already rendered the template and ran `ast.parse` on the output.
`RunStatus.FAILED` is syntactically perfect, so `test_workflow_job_parses` asserted
precisely the property that cannot catch this. **Importing** the rendered module would
not have caught it either: the reference sits in a function body and is never
evaluated at import time.

Templates are also invisible to `ruff`, `mypy` and `lint-imports`, which do not read
`.j2` files at all.

**How to apply:** "it parses" and "it imports" are much weaker than they look for
generated code. To check that names *resolve*, either execute the paths or resolve the
references statically — `tests/scaffold/test_template_symbols_resolve.py` does the
latter for every registered template.

## 18. A blocklist of another library's reserved names is incomplete by construction

Two gate-strategy property tests built dynamic pydantic models from generated field
names, guarding against reserved names with a hand-written `frozenset` that listed
`"model"` but not `"model_dump"`. The `ci` profile draws 200 examples where `default`
draws 100; it eventually drew `model_dump`, and `create_model` raised
`ValueError: Field 'model_dump' conflicts with member ... of protected namespace`.

**How to apply:** ask the library, do not restate it. `not s.startswith("model_") and
not hasattr(BaseModel, s)` is derived from the actual class and cannot fall behind it.

The same shape bit twice more in generated identifiers: `str.isidentifier()` returns
`True` for keywords, so `as` and `match` pass an "is this a valid name" check and then
fail to compile in a `def`. Use `keyword.iskeyword` / `keyword.issoftkeyword` as well.

## 19. A rule that cannot be shared needs a parity test, not a comment

Trap 6 is "one registry, plus a test". Sometimes there is no registry to have.

The environment-variable name rule — join the job name and the field name with a
single underscore, uppercase, flatten hyphens and dots — is spelled **five
times**: twice in `_config/resolved_field.py`, once in `_config/sources.py`, and
twice in `_engine/missing_value.py`. `_config` and `_engine` are peers, and
`layer-rules.md` forbids the import that would let them share one. Every copy
carried a docstring promising it "matches the rule rather than importing", which
reads as diligence and is in fact the whole problem: a comment is not a
mechanism, and five hand-copied implementations of a rule have already started
drifting by the time anyone counts them.

What makes this class worse than ordinary duplication is the failure mode. Only
`EnvSource._build_env_key` actually *reads* the environment; the other four only
*print* names — in `builtin env`, in `info --job`, in a validation error, in the
TUI. So a drift does not break resolution. It makes the tool confidently tell an
operator to `export SYNC_API_URL=…` when the resolver is looking for something
else, and they will believe it, because the tool said so. Silence would be
better.

**How to apply:** when a layer boundary genuinely forbids the shared import, the
enforcement is a test that asserts every copy agrees, named so the next person
adding a sixth copy finds it. `tests/config/test_env_name_rule_parity.py` derives
the name from each producer and asserts they are equal, for the same input. A
docstring claiming parity is a claim; a parity test is the parity.

## 20. Alphabetical order is not test isolation

`tests/core/test_show_info.py` passes `--dotenv-file` to an in-process
`CliRunner`, which reaches the real `load_dotenv()` and sets `MY_VAR=hello` in
the **test process**. `tests/cli/test_cli_integration.py::test_no_dotenv_flag`
asserts `MY_VAR` is unset, to prove `--no-dotenv` suppresses loading. One test
armed the trap the other was written to detect.

It never failed, and the reason is the whole point: `tests/cli/` sorts before
`tests/core/`, so a plain `pytest tests/` runs the victim first. The bug was
real, live, and simply never scheduled into the open — until a subset run put
the two directories in the other order. CI's slow tier runs `-n auto`, which
distributes across workers and does not preserve that order at all, so it was
an intermittent failure waiting for the right shard split.

`monkeypatch` does not cover this. It reverses what *monkeypatch* did; this was
done by production code holding a real reference to `os.environ`.

**How to apply:** process-global state that production code mutates —
`os.environ`, `sys.path`, a module-level cache, a registry singleton — is
restored by an autouse fixture in `tests/conftest.py`, on both sides of every
test, not in the handful that look like they need it. `_restore_environ`,
`_reset_entry_point_cache` and `_isolate_home` are the three that exist.
And when you add one, add the two-test pair that goes red without it —
`tests/test_environment_isolation.py` is the worked example, including why its
probe deliberately avoids the `FUNCTUALIZE_*` prefix that another fixture
already strips.

Corollary for reading a green suite: "passes as `pytest tests/`" is one
schedule out of many. A test whose subject *is* isolation deserves to be run
out of order once, on purpose.

---

## See also

- `contributor/guides/steering_textual_tui.md` — Textual HARD rules; claims proven by
  `tests/tui_audit/`
- `contributor/guides/tui-panels.md` — panel enforcement rules
- `contributor/guides/wiring-discipline.md` — how a capability gets wired end to end
- `contributor/reference/layer-rules.md` — import boundaries
