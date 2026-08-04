# ADR-002: True-Lazy-Boot Follow-Ups (Warm --help Fidelity + Child Mounting)

**Status**: accepted
**Date**: 2026-07-16
**Deciders**: Core team

## Context

The true-lazy-boot refactor (commit `c913669`) made warm boot import zero job modules —
jobs register as `LazyJobFunction` proxies. Dispatch fidelity was perfect (materialization
rebuilds the real command), but the warm `func --help` tree — rendered from cached metadata
without importing — had three cosmetic gaps:

- **Stdin markers not cached**: a `Stdin(flag="--data")` param rendered as a plain option
- **Rich types collapsed to `str`**: `Path`, `list[int]`, `Optional[...]` all showed as `str`
- **Child-project lazy mounting**: warm-cached child jobs (with `function is None`) silently
  vanished from mounted sub-apps

These affected only the `--help` display, never runtime behavior.

## Decision

Ship three follow-ups while preserving the zero-import invariant:

**A. Cache Stdin markers.** Added `is_stdin: bool` and `stdin_flag: str | None` fields to
`FieldDescriptor`. Extraction detects `Stdin` by class name (no typer import in `_discovery`).
Synthesis renders the correct flag in the warm `--help` tree.

**B. Rich type resolver.** Replaced the flat `_TYPE_MAP.get(..., str)` with a string→type
parser that handles `Path`, `list[X]`, `X | None`, and enum/Choice. Unknown types (datetime,
custom classes) collapse to `str` — a documented limitation that doesn't affect dispatch.

**C. Child discovery consolidation.** The original plan assumed `_mount_child` was the path
to fix. A live trace proved `wire_children_to_pipeline` already surfaces child jobs — wiring
`_mount_child` would have double-registered. So C shipped as lazy child discovery
(cache-first provider), validation on the live path, and removal of the redundant
`mount_children` pass + unused `ChildProjectComposer` mounting API.

**Cache version bump**: `CACHE_VERSION` 3 → 4 to force rebuild on first boot after upgrade.

## Consequences

### Positive

- Warm `--help` now faithfully renders Stdin flags, Path/list/Optional types, and variadic positionals
- Child jobs appear in warm boot without importing their modules
- Zero-import invariant preserved (verified by existing guardrail test)
- All import-linter contracts (especially typer-isolation) pass

### Negative

- `datetime`/`date` and arbitrary custom types still collapse to `str` in warm `--help`
  (documented limitation; dispatch unaffected)
- Cache version bump forces a one-time rebuild for existing users

### Neutral

- Old-format caches deserialize cleanly (new fields use `.get()` with defaults)
- Dispatch/materialization behavior completely unchanged

## Alternatives Considered

| Alternative | Pros | Cons | Why rejected |
|-------------|------|------|-------------|
| Import modules for accurate `--help` | Perfect fidelity | Breaks the zero-import invariant (~110ms boot regression) | Core design principle |
| Special-case datetime/custom types | Complete coverage | Unbounded complexity; can't reconstruct arbitrary types from strings | Diminishing returns; documented limitation |
| Skip cache version bump (rely on natural invalidation) | No user-visible rebuild | Stale `--help` until natural invalidation triggers | Bad UX for a one-time cost |

## References

- Implementation: `src/functualize/_types/descriptors.py` (FieldDescriptor fields),
  `src/functualize/_discovery/providers.py` (Stdin extraction),
  `src/functualize/app/adapters/lazy_command.py` (rich type resolver),
  `src/functualize/_app/boot.py` (child wiring via `wire_children_to_pipeline`)
