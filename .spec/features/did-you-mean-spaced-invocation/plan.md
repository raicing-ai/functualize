# Plan — did-you-mean-spaced-invocation

## Alignment

Shape intent: **SD/17104932**, *Shape Intent — The CLI Prints the Invocation
Spelling (Did you mean under a group: spaced, not dotted)*. Its fields read
`Authority = Approved` and `Status = Approved` (v2, 2026-10-16 12:39:39 UTC,
read live this run). The member's choice on D1 was "(a) fix the hint only".

In scope, in the page's own words:
- "The *printed form* of each `Did you mean` line on the unknown-command path
  (`_cli/main.py:1466-1471`)"
- "A regression test that checks the printed line itself and shows that it runs
  as printed"
- "A `### Fixed` entry in `CHANGELOG.md` under `## [Unreleased]`, for 0.5.0"

Out of scope, in the page's own words:
- "Whether the dotted spelling should keep running. It keeps running"
- "Which names are candidates: `func inventori` gets no suggestion"
- "The spaced-typo path's `Available:` list (`_cli/main.py:1163`)"
- "Registered names, MCP tool names, `rc.invoke`, `deps=`, state keys: all stay
  dotted"
- "The TUI's spelling contract: SD/17170435 sub-decision A1"
- D1(a): the leaf usage line goes to a follow-up; the non-TTY listing "Stays
  dotted"

**One correction to the page's mechanism.** D0-A describes the fix as "replace
each `.` with a space". The page's H1 makes that conditional: "*Invalidated if*
a registered job or plugin command name can contain a dot inside one segment".
`research.md` R1 measures exactly that case (`Job(name="tools.lint")`), so this
plan takes the page's stated fallback instead: "the printed form must come from
the trie path, not from string substitution". The approved behaviour (D0-A,
printing the spaced invocation) is unchanged. Every `JOB_GROUP` job prints
exactly what substitution would print.

## Skills consulted

- `design-patterns-refactoring` (user-level; the Refactoring.Guru catalogue).
  Used for smell names: *Duplicate Code*, *Shotgun Surgery*, *Long Method*.
- The in-repo `python-design-patterns` skill was **not** loaded in this run.
  KISS and single responsibility were applied directly.

Retrieval passes run, all at `d1c7e40`:
- zvec-grep `zg query` (index built this run). Hits: ADR-009 §6,
  `_cli/tui/sync.py:build_command_line`, `docs/guides/jobs-discovery.md:204-232`.
- `rg` for every count in this package.
- Direct reads of `_types/naming.py`, `_primitives/command_paths.py`,
  `app/commands.py`, `_cli/main.py:1395-1471`, `app/adapters/cli.py:734-764`,
  and the `pyproject.toml` import-linter contracts.
- Not run: serena and graphify. The reference census for the one renamed symbol
  is an `rg` hit set of 3 (tasks T2). The settled AFTER changes no dependency
  direction, and the contracts were read directly.

## BEFORE

```
 public layer                              │ internal foundation
                                           │
 _cli/main.py  (_handle_job, 1271-1475)    │
   unknown-command branch                  │
     candidates = {j.name} ∪ plugin ∪ grp1 │
     suggest_similar_commands(...) ───────►│ app/utils.py (public)  notation-agnostic
     print(f"  func {suggestion}")         │
        ▲ prints the DOTTED identity       │
                                           │
 app/commands.py  job_trie_path(job) ─────►│ _primitives/command_paths.job_path  (dotted)
                                           │
 _cli/tui/app.py:2333  replace(".", " ")   │  ← spaced, R1-unsafe
 _cli/tui/sync.py:177  split(".")          │  ← spaced, R1-unsafe
                                           │ _types/naming.py
                                           │   GroupTrie.build ──► _job_segments(group, name)
                                           │     (group segs + prefix-stripped leaf — the truth
                                           │      dispatch walks)
 contract: _cli ─╳─► _types/_primitives (import-linter "_cli uses public API only")
```

Smells already present (named, not fixed here):
- **Long Method**: `_cli/main.py:_handle_job`, about 200 lines (1271-1475).
- **Duplicate Code**: three derivations of "the spaced command" (`research.md`
  R3), two of them unsafe under R1.
- **Shotgun Surgery** risk: a change to how a path is spelled for a person has
  no single home.

## AFTER

```
 public layer                              │ internal foundation
                                           │
 _cli/main.py  unknown-command branch      │
   suggestions = suggest_similar_commands  │   (unchanged)
   for s: job = by_name.get(s)             │
     print("  func " + (job_invocation(job)│
                        if job else s))    │
        │                                  │
        ▼                                  │
 app/commands.py  job_invocation(job) ────►│ _types/naming.py
   " ".join(job_segments(group, name))     │   job_segments(group, name)   (renamed public)
                                           │     ▲
                                           │   GroupTrie.build ─┘  (same derivation)
 _cli → app.commands  (public → allowed)   │ app → _types  (allowed; app.commands already
                                           │                reaches _primitives the same way)
```

What crosses a boundary: `_cli/main.py` imports `job_invocation` from
`functualize.app.commands`, a public module. That is legal under "_cli uses
public API only". `app/commands.py` imports `job_segments` from
`functualize._types.naming`. Public importing internal is allowed: the contract
"Internal never imports public" forbids only the other direction.
`app/commands.py` already reaches `_primitives` the same way (`:419`, `:432`).
No new edge between peer layers.

### Candidates considered

1. **`suggestion.replace(".", " ")` inline at the print site.** One line, and
   it matches the TUI precedent. **Rejected**: R1 shows it prints `tools lint`,
   which exits 1. It also adds a fourth unsafe derivation, more *Duplicate
   Code*.
2. **A new string helper in `_primitives/command_paths.py`.** Pure, and it sits
   next to `job_path`. **Rejected**: it re-implements the prefix-strip rule that
   `_types/naming._job_segments` already owns. That is *Duplicate Code*, with
   one copy feeding dispatch and one feeding the printer, which could drift.
3. **Make `_job_segments` public as `job_segments`, and add an object wrapper
   `job_invocation` in `app/commands.py` (chosen).** The printer and the trie
   share one derivation, so a printed line names the path that dispatch walks.
   It adds no new rule. The rename is a 3-hit census, and `__all__` grows by
   one.

Smells the chosen AFTER **introduces**: none found. It does not make
`_handle_job` longer in a meaningful way (net about +2 lines). It adds no peer
import, no global state and no shim (the old private name is removed, not
aliased; CONSTITUTION forbids shims).

## Approach

- **T1 (tests only).** Write the regression test first. At base its
  printed-line assertions are red, and its byte-identity assertions are green.
- **T2.** Rename `_job_segments` → `job_segments` (`_types/naming.py:385`,
  `:561`, plus `__all__`), and update the docstring reference in
  `tests/discovery/test_group_trie.py:89`. Add `job_invocation` to
  `app/commands.py` and its `__all__`, with unit tests for AC6.
- **T3.** At `_cli/main.py:1467-1471`, build `{j.name: j for j in jobs}` once,
  then print `job_invocation(job)` for a job hit and the raw hit otherwise. Add
  the `CHANGELOG.md` entry.
- **T4.** Validation checkpoint and durable-half migration.

## Risks

- **A hit that is both a job name and a group first segment.** Today a group
  and a job cannot share a top-level path without a collision report. The
  lookup prefers the job, which prints the same path either way.
- **`job_segments` raises `ValueError` on an empty segment.** Every job that
  reaches the hint was already placed in the trie by the same function, so the
  raise cannot newly fire. The print site adds no `try`.
- **Two doors, two spellings.** After this change `func` prints spaced while an
  app prints dotted (R2). That is outside the approved scope and goes to the
  member as a follow-up decision.

## Surviving smells

| Smell (catalogue) | Where | Why accepted | Maintainer review |
| --- | --- | --- | --- |
| *Duplicate Code* | `_cli/tui/app.py:2333` and `_cli/tui/sync.py:177` keep their own `.`-based spaced rendering, unsafe under R1 | The TUI's spelling contract is owned by SD/17170435 (A1). Touching it here would widen an approved one-run fix into the shell. `job_segments` is now public, so a follow-up can adopt it | **Yes**: confirm it is a follow-up, not folded into this change |
| *Long Method* | `_cli/main.py:_handle_job` (about 200 lines) | Pre-existing. Splitting it is a refactor with its own blast radius, and the refactoring discipline says not to mix a refactor into a fix commit | No |
| Door divergence (not a catalogue smell; plain description) | `app/adapters/cli.py:754-764` still prints the dotted identity | Outside SD/17104932's scope (R2) | **Yes**: put to the member as a follow-up decision |

None of these is on CONSTITUTION's *Forbidden Patterns* list. The god-object
rule there concerns classes. The touched code is module-level functions, and
this change adds no class.
