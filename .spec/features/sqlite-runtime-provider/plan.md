# FUN-19 — Plan

**Status:** pre-loaded scaffold. The architecture gate below is **not yet satisfied** —
you must complete it before writing code.

## The architecture gate is NOT done

`.claude/rules/spec-workflow.md` requires, before any file is named for change:

1. Map the region with **all three** retrieval tools — zvec-grep, serena
   `get_symbols_overview`, graphify `get_neighbors`. Address each by **absolute path**;
   a bare project name binds to whichever checkout is registered, and a branch then gets
   told about master.
2. Read `contributor/architecture/codemaps/`. A diagram contradicting one is a finding,
   not a drawing error.
3. Draw **BEFORE and AFTER** ASCII diagrams here, carrying every module by real path,
   the direction of each dependency, the layer each sits in, and what crosses a boundary.
4. Iterate against `spec.md`, consulting the design-pattern and refactoring skills, and
   record which you loaded.
5. Declare the surviving smells (section below).

**Do this first.** The diagrams are the cheapest instrument that finds a simplification;
tracing call sites tells you where a change lands, drawing both shapes tells you whether
it is the right change.

## BEFORE

```
TODO — draw it. Do not skip this.
```

## AFTER

```
TODO — draw it. Check it for the smells it INTRODUCES, not only those it removes.
```

## Files expected to change

From the research's change inventory. **Verify each with `wc -l` before trusting the
size** — four of these numbers were wrong in an earlier draft and were corrected only
because someone measured.

| File | Size | Change |
|---|---|---|
| `src/functualize/_primitives/sqlite_store.py` | new ~700 | the SqliteRuntimeStore |
| `src/functualize/_primitives/migrate_legacy.py` | new ~300 | offline cutover from the five JSON documents |
| `tests/conformance/` | new | the tiered suite: baseline tier plus capability tiers gated on profile fields |

## Surviving smells

**This section is required.** If there are none, say so explicitly and say why you
believe it — an omitted section is indistinguishable from an unexamined one.

A pattern named in `.spec/CONSTITUTION.md` → *Forbidden Patterns* is a **blocker, not an
accepted compromise**: god-object growth past ~500 LOC, peer-layer cross-imports, global
mutable state, ABC for ports, implicit `Callable` conventions for ports, `_cli/`
importing internals. If the AFTER carries one, the AFTER is wrong.

Carried forward from the research as the starting position:

- **Large class** on SqliteRuntimeStore at ~700 lines, over the CONSTITUTION's ~500 god-object threshold. THIS NEEDS MAINTAINER REVIEW. Options: split by aggregate (runs / workflows / inputs) behind one facade, or accept it as one cohesive backend. Do not silently ship it over the threshold.

**Every entry marked *needs maintainer review* must be put to the maintainer by name and
with its reason, and answered, before Execute begins.** Report an explicit "none" aloud
too, so they can tell the question was asked rather than skipped.

## Design skills consulted

- [ ] `python-design-patterns` (in-repo)
- [ ] any *design patterns* / *refactoring* / *architecture* skill in this session's
      listing — these are per-user and per-machine, so check the listing rather than
      assuming. Record what you actually loaded.
