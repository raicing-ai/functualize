# FUN-24 — Plan

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
| `src/functualize/_primitives/scope_state_store.py` | 235 | add the fence; `grep -c generation` is 0 today |
| `src/functualize/_primitives/scope_store.py` | 923 | pass expect= on the guarded write (:250-266); delete the dead "state": {} field (:102) |
| `src/functualize/_primitives/lease.py` | 305 | no change expected — it is already correct; the bug is that callers bypass it |
| `src/functualize/_app/boot.py` | 2016 | install the substrate in a step that may raise, before APP_READY |
| `src/functualize/_cli/tui/shell_mode.py` | 331 | route shell history through the installed substrate |
| `src/functualize/_types/protocols.py` | 930 | Stored.revision: int -> an opaque token type |

## Surviving smells

**This section is required.** If there are none, say so explicitly and say why you
believe it — an omitted section is indistinguishable from an unexamined one.

A pattern named in `.spec/CONSTITUTION.md` → *Forbidden Patterns* is a **blocker, not an
accepted compromise**: god-object growth past ~500 LOC, peer-layer cross-imports, global
mutable state, ABC for ports, implicit `Callable` conventions for ports, `_cli/`
importing internals. If the AFTER carries one, the AFTER is wrong.

Carried forward from the research as the starting position:

- **Shotgun surgery** survives: the fence is enforced at each store rather than at one commit point. That is what FUN-17's RuntimeTransaction removes. Accepted here deliberately — this wave repairs, it does not redesign.

**Every entry marked *needs maintainer review* must be put to the maintainer by name and
with its reason, and answered, before Execute begins.** Report an explicit "none" aloud
too, so they can tell the question was asked rather than skipped.

## Design skills consulted

- [ ] `python-design-patterns` (in-repo)
- [ ] any *design patterns* / *refactoring* / *architecture* skill in this session's
      listing — these are per-user and per-machine, so check the listing rather than
      assuming. Record what you actually loaded.
