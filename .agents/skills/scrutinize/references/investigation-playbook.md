# Investigation Playbook

Strategies for verifying each claim type. The investigator's job is to find *evidence* — not to form opinions. Every verdict must point to something concrete.

---

## General Principles

1. **Start fresh, not from the document's citations.** The document says "see `_engine/execution.py:42`" — but maybe the file was renamed, the function moved, or line 42 is now something else. Find it yourself.

2. **Verify the prerequisite chain.** If claim B depends on claim A being true, verify A first. If A is falsified, B may be moot.

3. **Trace, don't guess.** "This module probably doesn't import X" is not evidence. `grep -r "from functualize._engine" src/functualize/_config/` returning empty IS evidence.

4. **Record negative evidence.** "Searched for X in Y — found nothing" is a valid finding. It either confirms a negation claim or falsifies an existence claim.

5. **Check the git dimension.** A claim might be true on HEAD but was false a week ago (fragile), or it might have been true when written but HEAD has moved past it.

---

## By Claim Type

### FACT Claims

> "The thing at path X does/is Y"

**Primary strategy:**
1. Open the file. Read the relevant section.
2. Confirm or deny the specific assertion.
3. If the file doesn't exist, check if it was renamed: `git log --diff-filter=R --summary -- '**/original_name*'`

**Common failure modes:**
- File exists but the function/class has been refactored (claim about behavior is stale)
- File exists but at a different path (claim about location is stale, behavior might still be true)
- The claim conflates two things that have since been separated

**Evidence format:** `<file>:<line> — <what's actually there>`

---

### ASSUMPTION Claims

> "X is true / X never happens / X is always the case"

**Primary strategy:**
1. Identify the invariant being claimed.
2. Search for violations: `grep` for counter-patterns, check import-linter contracts, read tests that exercise the boundary.
3. Check if the invariant is *enforced* (by linting, tests, or type system) or merely *observed* (happens to be true today).

**Enforced vs. observed matters:**
- Enforced: the proposal can rely on it; it's a stable guarantee.
- Observed: the proposal should document the assumption explicitly; it might break silently.

**For "peer layers never import each other" type claims:**
```bash
# Check if _discovery imports _config (should be empty if claim holds)
grep -rn "from functualize._config" src/functualize/_discovery/
grep -rn "from functualize._engine" src/functualize/_config/
# Or use the project's import linter
uv run lint-imports
```

**Evidence format:** `Invariant enforced by <mechanism> in <file>` or `Violation found: <file>:<line> imports <prohibited>`

---

### INTERFACE Claims

> "The API will look like X" / "Module M exposes function F with signature S"

**Two sub-cases:**

**A. Claiming an existing interface:** Verify it exists with the claimed signature.
```bash
# Check __all__ exports
grep -A 20 "__all__" src/functualize/app/__init__.py
# Check actual function signature
grep -n "def function_name\|class ClassName" src/functualize/path/module.py
```

**B. Claiming a proposed interface is compatible:** The interface doesn't exist yet, but the proposal claims existing code can use it. Verify:
- The types it references exist and have the shape assumed
- The calling conventions match (async vs sync, return types, error handling patterns)
- The module placement follows layer rules (would import-linter allow it?)

**Evidence format:** `Interface exists at <file>:<line> with signature <sig>` or `Proposed interface assumes <type> has <method>, but actual type at <file>:<line> has <different shape>`

---

### ARCHITECTURE Claims

> "Module X lives in layer Y" / "Z is the composition root" / "A and B never communicate directly"

**Primary strategy:**
1. Verify module existence and location.
2. Trace actual dependency graph for the claimed relationship.
3. Check against documented architecture (`contributor/architecture/`).
4. Run `lint-imports` to see if the claimed layering is enforced.

**For new-module proposals:**
- Check if the proposed module name conflicts with existing names
- Verify the proposed layer placement is consistent with existing layer rules
- Check if the claimed "sole composition root" actually IS sole (search for other wiring sites)

**Evidence format:** `Architecture claim verified via lint-imports contracts in pyproject.toml:[importlinter:contract:<name>]` or `Claim violated: <file> imports from <prohibited layer>, discovered via <method>`

---

### MEASUREMENT Claims

> "Boot time is ~110ms" / "Socket latency is <5ms" / "~500 LOC"

**Primary strategy:**
1. Check if the measurement is documented/benchmarked somewhere (CI artifacts, test fixtures, benchmark scripts).
2. If measurable with a safe read-only command, measure it.
3. If not directly measurable, assess plausibility by examining the code path.

**For timing claims:**
- Count the operations on the critical path
- Check if the claimed hot path is actually the hot path (no hidden lazy initialization)
- Look for things the document might have missed (middleware, hooks, event dispatch)

**For LOC/size claims:**
```bash
# Count actual LOC of a module
find src/functualize/_engine -name "*.py" | xargs wc -l
# Or for a specific file
wc -l src/functualize/_engine/execution_engine.py
```

**For "irreducible" claims:** Check if the thing claimed as irreducible actually is. "CPython startup is irreducible" — is there a `__pycache__`, a pre-compiled wheel, or a future PEP that addresses this?

**Evidence format:** `Measured: <command> → <result>` or `Plausibility: code path involves <N> operations, each <estimate>, consistent with claim` or `No benchmark exists; claim is UNTESTABLE without <what's needed>`

---

### DEPENDENCY Claims

> "This requires X" / "Uses library Y" / "Needs asyncio + thread pool"

**Primary strategy:**
1. Check if the dependency already exists in the project (`pyproject.toml`, `requirements.txt`).
2. If it's a new dependency, assess compatibility with existing constraints (license, Python version floor, conflicts).
3. If it's a pattern dependency ("needs asyncio"), verify the codebase already uses it or can adopt it without conflict.

**For "uses the same X as Y" claims:**
- Verify X has the interface both uses require
- Check if X is currently a singleton, shared instance, or newly instantiated each time — affects whether daemon sharing is feasible

**Evidence format:** `Dependency <X> present in pyproject.toml at version <V>` or `Dependency <X> not in project; would require adding <package> which conflicts with <constraint>`

---

### SCOPE Claims

> "Only touches modules A, B, C" / "HTTP adapters remain separate" / "No changes to public API"

**The most dangerous claims to get wrong.** Underestimated scope is the primary cause of proposal failure.

**Primary strategy:**
1. List every module the proposal mentions touching.
2. For each, trace its dependents: who imports it? What breaks if its interface changes?
3. Check if the proposal's new module would need to be imported from anywhere it doesn't mention.
4. Look for implicit scope expansion: new config keys need docs; new commands need CLI wiring; new events need bus registration.

**Scope expansion checklist:**
- [ ] New module → needs `__init__.py` with `__all__`, needs entry in dependency graph docs
- [ ] New CLI command → needs wiring in `_cli/main.py` or dispatch
- [ ] New config key → needs documentation, schema, defaults
- [ ] New event type → needs EventBus registration, possibly hook support
- [ ] Changed public API → needs docs update, possibly deprecation path
- [ ] New dependency → needs pyproject.toml, possibly extras group, license check
- [ ] New file format → needs test fixtures, possibly CI updates
- [ ] Platform-specific code → needs testing strategy for all platforms
- [ ] New background behavior → needs shutdown/cleanup handling

**Evidence format:** `Scope claim incomplete: proposal doesn't mention <file> but it imports from <modified module> at <line>` or `Scope claim confirmed: grep for imports of <module> shows only <listed consumers>`

---

## Investigation Order

Process claims in this order for maximum efficiency:

1. **ASSUMPTION + ARCHITECTURE** — these are preconditions. If they're false, many downstream claims may be moot. Investigate first to potentially short-circuit.
2. **SCOPE** — the second most common failure point. Investigate early so you can flag scope underestimation.
3. **INTERFACE + DEPENDENCY** — compatibility claims. These determine whether the proposal can physically connect to existing code.
4. **FACT** — usually the easiest to verify and quickest to check.
5. **MEASUREMENT** — often requires experiments or is UNTESTABLE; schedule last.

---

## When to Stop Investigating

- If you find 3+ **blocking** issues, you can stop after completing the current claim type. The document needs revision regardless — no point exhaustively verifying claims that won't survive the rewrite.
- If all ASSUMPTION and ARCHITECTURE claims are CONFIRMED, you can downgrade the investigation depth on FACT claims (they're more likely to be correct in a well-researched proposal).
- If the document's date is very recent (< 1 week) and the claims reference HEAD accurately, you can sample rather than exhaustively verify FACT claims.
