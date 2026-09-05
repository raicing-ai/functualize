# Spec — Seams for a third-party host package

Five additions that let a package built *on* functualize reach capabilities
functualize already has, instead of reimplementing them. Driven by an external
host (`risekit`) but none of it is host-specific: each seam is the general
version of a thing core already does for itself.

Sibling feature `discovery-and-gate-defects` covers the plain bugs. This one
adds public API, so every item is a contract decision.

## Problem statement

Functualize solves five problems privately and exposes none of them:

1. **Filtering discovery.** `DiscoveryConfig` offers seven `require_*`
   predicates over filenames, imports, markers and decorator names. A host
   whose jobs are *methods on classes* cannot express itself in any of them.
2. **Detecting how a tool is installed.** `_cli/runtime.py`,
   `_cli/package_ops.py` and `_cli/manifest.py` are 1,683 lines that answer
   "is this installed, how, and what command changes it" — for functualize
   itself only.
3. **Hosting agent skills.** `resolve_skills_dir()` looks in exactly two
   places, both inside the functualize distribution. `builtin skills list`
   will never show anyone else's.
4. **Reaching a job's own metadata.** `@job(tags=…, examples=…,
   extra_description=…, category=…)` survives discovery and the cache onto
   `descriptor.declaration` — and `job_detail`, the payload the CLI and MCP
   both render, drops it.
5. **Declaring a single-file script's skill.** `[tool.functualize]` accepts
   exactly one key. Anything else warns on every run.

Each forces the same bad choice on a host: reimplement, or reach into an
underscore package the constitution forbids `_cli` itself from touching.

## User stories

- **As a host-package author**, I filter discovery with my own predicate
  instead of contorting my layout to match a filename convention.
- **As a host-package author**, I ask functualize whether a tool is installed
  and how, rather than shipping a second detector that disagrees with it.
- **As a host-package author**, the skills in my wheel appear in
  `func builtin skills list` next to functualize's, version-stamped the same
  way.
- **As an AI agent**, a job I discovered through `builtin info` or MCP tells
  me its tags and examples, so I can walk from the job to the document that
  explains it.
- **As a script author**, my one-file job declares the skill it belongs to
  without a warning.

## Behavior

### S1 — a discovery pre-filter hook

`DiscoveryConfig` gains a field taking a caller-supplied predicate, consulted
alongside the existing `require_*` fields. The predicate sees what the
existing AST pre-filter sees — a module path and its parsed source — and
returns whether to import it.

The existing seven `require_*` fields are unchanged; the hook is an
additional AND-ed constraint, consistent with the documented composition rule.

The predicate also declares a `fingerprint()`, because the discovery cache
replays persisted pre-filter decisions and must know when the predicate that
produced them has changed. A callable has no stable identity across processes,
so the caller supplies one. `contracts.md` §S1 carries the verification of why
neither alternative works.

### S2 — install detection and package operations become public

The capability behind `builtin self doctor` / `install` / `update` becomes
importable from a public module: given a tool name, report whether it is
installed, by which mode, at which path, and what command would install,
update or remove it.

Nothing about the *semantics* changes. This is a re-export and a stable
signature over code that already exists, so `_cli` continues to consume it
through the public door like every other capability.

### S3 — third-party skill hosting

A `functualize.skills` entry-point group. Each entry names a package resource
directory holding skill directories. `resolve_skills_dir()` becomes a
plural resolution: core's own location first, then every registered entry.

`builtin skills list`, `path`, `materialize` and `install` all iterate. The
version stamp on materialization is per-source, so a third-party skill is
stamped with *its* distribution's version, not functualize's — the guarantee
that a skill cannot describe a release other than the one installed must hold
for the skill's own package.

### S4 — `job_detail` exposes the declaration

The payload gains the four declaration fields it currently drops:
`tags`, `examples`, `extra_description`, `category`. Additive; the twelve
existing keys are unchanged.

This is the seam that lets an agent go *from a job it found to the judgment
that explains it* — the direction that matters, and the only one currently
impossible.

### S5 — `[tool.functualize] skill`

`_KNOWN_TOOL_KEYS` gains `skill`, naming the skill a single-file script
belongs to. Reading it is out of scope; accepting it without a warning is not.

## Acceptance criteria

Executable; hit counts from running each against `a2f453d` at authoring time.

| # | Criterion | Authoring-time state |
|---|---|---|
| A1 | A test registers a predicate that rejects one module of two and asserts only the other's jobs appear | `grep -c "pre_filter" src/functualize/app/config.py` = **0** |
| A1b | The predicate participates in the discovery-cache fingerprint via `fingerprint()`: a changed fingerprint re-scans, and the same filter in a fresh process yields the same hash | the field does not exist; hashing the object would differ every process |
| A2 | A test imports the detection API from a public module and reports on a known tool; `grep -rn "from functualize._cli" src/functualize/app/` stays **0** | 1,683 private lines, 0 public re-exports |
| A3 | A test installs a fixture distribution declaring `functualize.skills` and asserts its skill appears in `list_skills` output | `resolve_skills_dir` has **3** call sites (`info.py:325`, `builtins.py:1482`, `builtins.py:1723`) and returns one location |
| A4 | `job_detail(app, name)` contains `tags`, `examples`, `extra_description`, `category` | 12 keys, none of the four |
| A5 | A PEP 723 script with `skill = "x"` runs with no unknown-key warning | `_KNOWN_TOOL_KEYS = frozenset({"job"})` at `pep723.py:53` |
| A6 | Full gates green, `lint-imports` included | — |

## Out of scope

- **Consuming** `[tool.functualize] skill` (S5 accepts the key only).
- A skill *format* beyond the Agent Skills spec's six portable fields —
  `parse_frontmatter` already reads exactly those and stays authoritative.
- Any host-package code. Everything here ships in functualize.
- The MCP surface's rendering of S4's new fields. `job_detail` is shared, so
  MCP gets them for free, but asserting that end to end needs a live MCP
  client and is tracked as a follow-up, not a task here.
