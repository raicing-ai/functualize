# Shape Intent: Remote Config Source — Wire It Or Remove It

**Status: specified, not yet implemented**
**Date: 2026-08-29**
**Scope: `RemoteSource`, the `remote_first` preset, and the two docstrings that
describe a resolution chain the code does not build. Deferred out of the 0.1.1
cut by decision — recorded here so the decision is a decision, not an omission.**

Every claim below carries the command that demonstrates it. A claim with no
command is not a finding.

---

## Core Principle

**A public preset must describe the chain it actually builds.** `remote_first` is
reachable from `help(remote_first)` and from every IDE hover; a docstring is the
most-read documentation a public function has, and it is the one copy that cannot
be fixed by editing markdown.

---

## The state of the code

### Assertion 1 — `RemoteSource` exists and is exported. **PASS**

```
$ grep -rn "class RemoteSource" src/
src/functualize/_config/sources.py:246:class RemoteSource:
```

It is re-exported from `_config` (`_config/__init__.py:25,37`) and documented in
that package's module docstring (`:5`) as one of the five source implementations,
alongside a behaviour claim: *"Resolves `provider://ref` annotations via registry
with 30s timeout"* (`_config/sources.py:6`).

### Assertion 2 — Something constructs it. **GAP**

```
$ grep -rn "RemoteSource(" src/
$ echo $?
1
```

**Zero construction sites in `src/`.** The class is defined, exported, and
documented, and nothing in the package ever instantiates it. The only other
mention is a comment in the executor about a fetch that therefore never happens
(`_engine/executor.py:1531`).

### Assertion 3 — `remote_first` resolves CLI → Remote → Env → Files → Defaults. **GAP**

`app/presets.py:97-101`:

```python
    """CLI → Remote → Env → Files → Defaults.

    Leaves ``config_resolution_chain`` as None so that the boot path
    can wire up RemoteSource and FileSource with the discovered
    ResourceLocator and ProviderRegistry.
```

The body it heads (`:110-114`) is:

```python
    return ConfigSources(
        file_pattern=file_pattern,
        dotenv=dotenv,
        config_resolution_chain=None,
    )
```

Compare `classic` (`:45-49`) — the same three arguments, the same `None` chain.
The two presets differ only in their `file_pattern` and `dotenv` **defaults**;
they build the same chain, and it has no Remote step. `remote_first` resolves as
`classic()` with different defaults.

The second paragraph is the load-bearing false claim: the boot path does not
"wire up RemoteSource". `boot.py:548-551` uses `config_resolution_chain` only when
it is **not** None, and there is no branch that constructs a remote source.

### Assertion 4 — The TUI's rendering of the chain is accurate. **GAP**

`_cli/tui/panels/config_table.py:50`:

```python
    CONFIG: Full layered resolution chain (CLI → Env → File → Remote → Default).
```

Note this spells the chain in a *different order* from `presets.py:97`
(`Env → File → Remote` vs `Remote → Env → Files`). Two docstrings describing one
non-existent feature do not even agree with each other, which is the usual sign
that neither was checked against the code.

---

## Why this was not caught

The gate recorded for this area was:

```
$ grep -rn "→ Remote\|Remote →" --include="*.md" .
```

It returns 0 hits, and it is true. **The `--include="*.md"` scoping is what makes
it true.** Six markdown copies of the claim were removed and the two
authoritative non-markdown ones were left standing. Dropping the filter:

```
$ grep -rn "→ Remote\|Remote →" src/
src/functualize/app/presets.py:97:    """CLI → Remote → Env → Files → Defaults.
src/functualize/_cli/tui/panels/config_table.py:50:    CONFIG: ... (CLI → Env → File → Remote → Default).
```

The working rule this produces is already recorded in
`contributor/guides/docs-example-parity.md`'s terms: **a documentation gate scoped
to a file type is a scope decision and has to be argued.** A behavioural claim
lives wherever it was written, and the copy hardest to fix later is the one in the
code.

---

## The shape of the work

Two coherent end states. This intent does not pick one — that is the decision the
feature has to make, and it is a product question, not a cleanup question.

**Option A — implement it.** Give the boot path a branch that constructs
`RemoteSource` with the discovered `ResourceLocator` and `ProviderRegistry`, and
make `remote_first` mean what it says. Then the class earns its exports and the
`provider://ref` behaviour claim in `_config/sources.py:6` becomes testable. This
is a real feature with a real surface: provider registration, the 30s timeout,
failure semantics when the remote is unreachable at boot, and what a config panel
shows for a value that has not resolved yet.

**Option B — remove it.** Delete `RemoteSource`, drop it from `_config`'s
`__all__`, and either delete `remote_first` or redefine it honestly. The
pre-release stance (`.spec/CONSTITUTION.md` §Pre-Release Stance) permits this
outright: breaking changes are free before v1.0.0, and the constitution's own
Forbidden Patterns list rejects keeping code around for compatibility.

**Not an option: correcting only the docstrings.** That leaves an exported,
never-constructed class in a package whose module docstring advertises it, which
is the condition `contributor/guides/wiring-discipline.md` exists to prevent —
"three capabilities shipped built, unit-tested and unreachable under green gates".

## Acceptance, whichever option is taken

- [ ] `grep -rn "→ Remote\|Remote →" src/` returns either zero hits (Option B, or
      Option A with the chains corrected) or hits whose spelling matches a chain
      the boot path actually builds. **Run it without `--include`.**
- [ ] `grep -rn "RemoteSource(" src/` returns at least one construction site
      (Option A) or `grep -rn "RemoteSource" src/` returns zero (Option B).
- [ ] `presets.py:97` and `config_table.py:50` spell the same chain in the same
      order, or neither mentions Remote.
- [ ] Under Option A, an end-to-end test declares a `provider://ref` value and
      observes it resolve through the public entry point (`CONSTITUTION.md`
      §Quality Gates, capability coverage).
