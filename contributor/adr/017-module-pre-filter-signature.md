# ADR-017: `ModulePreFilter.should_import(source_file)`, not `accepts(path, source)`

**Status**: accepted
**Date**: 2026-09-07
**Deciders**: Hakim
**Supersedes**: the `ModulePreFilter` sketch in
`.spec/features/third-party-host-seams/contracts.md` §S1

## Context

`third-party-host-seams`/1.3 promoted `ModulePreFilter` from `_primitives` to
`functualize.plugin`, so a host whose jobs no `require_*` setting can describe
can supply its own pre-import predicate. Promoting it made the method signature
a public contract.

`contracts.md` §S1 sketched the promoted protocol as:

```python
def accepts(self, path: Path, source: str) -> bool: ...
```

What shipped is what the thirteen built-in filters have always implemented:

```python
def should_import(self, source_file: Path) -> bool: ...
```

The implementation followed the code on the contract's own reasoning — §S1 says
this seam *"promotes the existing shape rather than inventing one"* — but the
divergence was recorded rather than assumed correct (`.spec/STATUS.md` #31), and
this ADR is the decision it asked for.

The sketch bundles two independent changes: a **rename** and a **signature
change**. They have opposite answers, which is what made the question look
harder than it is.

## Decision

**Keep `should_import(source_file: Path) -> bool`. Reject `accepts(path, source)`.**

## Rationale

### The `source` parameter optimizes the wrong cost

Seven of the thirteen built-in filters each do their own `read_text()` +
`ast.parse()`, and the baseline stack can hit the same file three or four times
per candidate. Passing the source once removes the duplicated *reads*. Measured
on this repository:

| | small job file (905 B) | `_cli/builtins.py` (85 KB) |
|---|---|---|
| `read_text` alone | 19.8 µs | 151.6 µs |
| `ast.parse` alone | 75.6 µs | 23,736 µs |
| three filters, as shipped | 568.6 µs | 52,347 µs |
| **redundant reads** | 39.7 µs — **7.0%** | 303 µs — **0.6%** |
| **redundant parses** | 151 µs — **26.6%** | 47,473 µs — **90.7%** |

`source` eliminates the 0.6–7% and leaves the 27–91% untouched, because each
filter still calls `ast.parse(source)` on the string it is handed. The
optimization the signature exists for is not the cost that is being paid.

### It inverts the cheapest-first ordering

`build_pre_filter_from_config` orders the stack so filename checks run before
any file is opened, and says so:

```
1. GlobExcludePreFilter (skip excluded files first — cheapest)
2. DefaultModulePreFilter (skip _-prefixed — cheap string check)
3. FilePrefixPreFilter (filename check — cheap)
4. FilePostfixPreFilter (filename check — cheap)
5. ASTModulePreFilter (requires file read + parse)
```

An eager `source` parameter forces the caller to read **every candidate before
calling any filter**, including the ones a glob or a prefix would have rejected
without looking. Measured:

| Operation | Cost |
|---|---|
| `FilePrefixPreFilter` reject | 0.42 µs |
| `DefaultModulePreFilter` reject | 3.15 µs |
| `read_text` (small / large) | 17.5 µs / 85.3 µs |

That makes a filename rejection **20–200× more expensive** and destroys the
ordering the module is built around. Four of the thirteen filters need only the
path; handing them a `source` is not neutral, it is precisely the cost the
ordering avoids.

### A `source` string is a second copy of state

The file on disk is authoritative. A string passed beside a path can disagree
with it, and a filter selecting on file size, mtime, or a sidecar file receives
an argument that cost something to produce and answers nothing.

### The name preserves a real symmetry

The codebase already has the job-level twin:

```python
JobFilter.should_register(candidate)        # job level
ModulePreFilter.should_import(source_file)  # module level
```

Same shape, same `should_*` prefix, same boolean contract, one level apart.
`accepts` breaks a pairing a reader currently gets for free, and appears nowhere
in the tree as a method name.

`should_import` also names the *consequence*: returning `True` causes a module
import, so arbitrary code runs and import-time side effects fire. That is
load-bearing enough that `JobSources(lazy=False)` exists for it
(`contributor/architecture/developer-modes.md:48`). `accepts` is more general
than the thing it names, and hides the one fact a host writing a filter needs.

## Consequences

- `contracts.md` §S1 is wrong on both counts and is superseded by this file.
- The public surface is `functualize.plugin.ModulePreFilter`, documented in
  `docs/api/plugins.md` and `docs/guides/jobs-discovery.md`. Renaming after
  release would be a breaking change for any host that has written a filter;
  deciding now, pre-merge, costs nothing.
- The measured cost is real but is **cold-boot only**: the cached provider runs
  the filter only for files not already cached, and persists negative decisions
  keyed by mtime. If it ever becomes worth attacking, the fix is a parse
  memoized per `(path, mtime)` — 27–91% rather than `source`'s 0.6–7% — and it
  requires no protocol change at all. Tracked as `.spec/STATUS.md` #34.

## Alternatives considered

**`accepts(path, source)` as sketched.** Rejected above.

**`accepts(source_file)` — the rename alone.** Loses the `should_register`
symmetry and the named consequence, and buys only brevity. Rejected.

**Passing the AST instead of the source.** Would address the cost that actually
dominates, but makes every filter pay for a parse — including the four that
only look at the filename — and freezes an `ast` type into a public protocol.
A memoized parse behind the existing signature gets the same benefit without
either cost.
