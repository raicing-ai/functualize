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

---

## See also

- `contributor/guides/steering_textual_tui.md` — Textual HARD rules; claims proven by
  `tests/tui_audit/`
- `contributor/guides/tui-panels.md` — panel enforcement rules
- `contributor/guides/wiring-discipline.md` — how a capability gets wired end to end
- `contributor/reference/layer-rules.md` — import boundaries
