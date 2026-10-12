# Research — job-name resolution misses NFKC-unstable names

Explore-phase findings only. This file is not a spec and not a plan: it carries
no `spec.md`, no contract decision, and no task graph. The contract fork it
informs (normalise on lookup vs. reject at discovery) is open with the member.

Base: `origin/master` at `36eaeabf`. Every count and negative below was taken
on that tree by the command quoted beside it.

## 1. The premise, re-measured

Python NFKC-normalises identifiers when it parses them (PEP 3131) and leaves
string literals and `argv` untouched.

| Claim | Command | Result |
|---|---|---|
| 573 of 2233 `Ll` letters change under NFKC on 3.13 | `unicodedata` sweep over `range(0x110000)`, `category == "Ll"`, `normalize("NFKC", c) != c` | 3.13.15 / Unicode 15.1.0: **2233 Ll, 573 change**. 3.12.14 / 15.0.0: 2233 / 573. 3.11.16 / 14.0.0: **2227** / 573 |
| Other categories add more | same sweep over every `c` with `("a" + c).isidentifier()` | 3.13: **3631** identifier-continue characters change under NFKC (140 089 valid); 3.12: 3630; 3.11: 3568 |
| `ǆ` and `ŉ` change | `normalize("NFKC", "job_aaǆ")`, `…("job_aaŉ")` | `'job_aadž'`, `'job_aaʼn'` on all three |
| `ast` sees the normalised name too | `ast.parse('def job_aaǆ(rc): pass')` | `FunctionDef.name == 'job_aadž'` — the string literal stays `'job_aaǆ'` |
| Only `tokenize` keeps the written spelling | `tokenize.generate_tokens` over the same line | `NAME` token `'job_aaǆ'` |
| Nothing on a job-name path applies NFKC | `rg -n "unicodedata\|NFKC\|normalize\(" src/ plugins/` | 10 hits, none on a job-name path: `app/packaging.py:436-728` is PEP 503 distribution-name normalisation; `_engine/scheduler.py:261-264` is node-result shaping. No `unicodedata` import anywhere in `src/` or `plugins/` |
| The reported observation | `git log --oneline -1 1ba75a5c` | `chore(engine): record parallel batch verification`, branch `fix/parallel-child-failure`; the Property 23 strategy there now filters to NFKC-stable `Ll` (`f5356b10`, test-only) |

## 2. End-to-end reproduction on master

A throwaway probe (not committed) wrote one jobs module into a temp project and
drove it through `FunctualizeApp.cli_command` with `click.testing.CliRunner`:

```python
def job_aaǆ(rc): return "child-ran"
def via_invoke(rc):   rc.invoke("job_aaǆ")
def via_parallel(rc): rc.invoke_parallel([("job_aaǆ", {})])
# second module: JOB_GROUP = "ǆ_ops"; def run_it(): ...
```

Observed at `36eaeabf`:

```
REGISTERED ['job-aadž', 'via-invoke', 'via-parallel', 'ǆ-ops.run-it']
CLI ['via-invoke']   exit 1 :: KeyError("Job 'job_aaǆ' not found in engine registry")
CLI ['via-parallel'] exit 0 :: PARALLEL RunStatus.FAILURE job_aaǆ KeyError("Job 'job_aaǆ' not found in engine registry")
CLI ['job_aaǆ']      exit 1 :: Error: Unknown command 'job_aaǆ'.
CLI ['job-aadž']     exit 0
app.get_job("job_aaǆ") -> None ; app.get_job("job_aadž") -> found
```

Three facts this adds to the issue body:

1. **All three named surfaces fail today** — `rc.invoke`, `rc.invoke_parallel`
   and the CLI job argument — not only the parallel path the property test hit.
2. **A string-sourced name is not NFKC-normalised at all.** `JOB_GROUP` is a
   string, so the group registers as `ǆ-ops`, in its written form. Only names
   that come from a Python identifier (`__name__`) arrive normalised. Any fix
   that changes the *canonical* form therefore renames string-sourced
   identities (§5).
3. The parent of a failed parallel child exits `0`. That is the PR #102 lane
   (parallel child-failure reporting), not this one; noted only so it is not
   mistaken for part of this defect.

## 3. Prior art

- **There is already one naming policy, and it already normalises on lookup.**
  `src/functualize/_types/naming.py:1-16` declares itself "the one place that
  answers 'what name does this denote'". `normalize_segment` (`:45-79`)
  lowercases and hyphenates; `resolve_name` (`:99-156`) does exact match, then
  *normalised* match on both sides (`_canonical`, `:138-141`), then leaf match.
  Its docstring (`:118-123`) already frames this as "normalization, not
  aliasing … a total function from what you typed to the one name that exists".
  NFKC is absent from that function — that is the whole defect at the policy
  level.
- **Consolidation history.** `executor.get_job` (`_engine/executor.py:736-778`)
  records that it was once the *fifth* resolver and drifted; `_discovery/naming.py:5-8`
  and `_types/naming.py:14-15` both cite "three dependency resolvers that
  disagreed in production". A fix that adds NFKC at one consumer instead of in
  the policy would recreate that class.
- **Boot-time rejection of unreachable names exists.**
  `_app/boot.py:2211-2225` (`_validate_builtin_reservation`) rejects names that
  "can never be typed … as themselves" — the same argument option (ii) makes.
- **ADR-018** (`contributor/adr/018-unsatisfiable-jobs-are-reported-not-fatal.md:50-66`):
  a per-job defect is recorded as a `DiscoveryFailure` and the rest of the app
  keeps running. A reject-at-discovery contract would land in that list rather
  than fail boot.
- **`contributor/architecture/group-trie.md:75-77`** describes
  `normalize_segment` as "lowercase, strip non-alphanumeric", which does not
  match the code (`:65-79` keeps non-alphanumerics other than `_` and space).
  A stale codemap, not a decision; it will need correcting whichever way the
  fork goes.
- No ADR, guide, `pitfalls.md` entry or `STATUS.md` line mentions NFKC, PEP 3131
  or Unicode identifier spelling: `rg -n -i "nfkc|pep 3131|unicodedata|non-ascii|unicode (job|name|identifier)" contributor/ .spec/ docs/ CHANGELOG.md AGENTS.md`
  returns one unrelated hit (`CHANGELOG.md:338`, a non-ASCII *file* name).
  zvec-grep prose queries (index built for this worktree) surfaced the policy
  module, `group-trie.md`, the reserved-name check and ADR-018 — nothing that
  decides this question.

## 4. Every name-keyed path

`rg -n "\b(normalize_segment|normalize_name|resolve_name|qualified_name)\(" src/ plugins/ --type py -g '!**/tests/**'`,
less definitions, comments, docstrings and the policy's internal self-calls:
**42 call sites in 19 files**, all funnelling into the three functions in
`_types/naming.py`.

### 4a. Registration — builds the name of record

| Path | Name source | NFKC today |
|---|---|---|
| `_discovery/sync.py:283,290` cold discovery → `qualified_name(raw_group, job_func.__name__)` | `__name__` + `JOB_GROUP` | leaf yes (parser), group **no** |
| `_discovery/registry.py:412,419` module registration | attribute name + `JOB_GROUP` | leaf yes, group **no** |
| `_discovery/transforms.py:57,138,139` group transform | function name + group value | leaf yes, group **no** |
| `_discovery/providers.py:671-675` `@job(name=…, group=…)` declaration | **string** override | **no** |
| `_discovery/providers.py:797,809` entry-point jobs | **`ep.name`** string from package metadata | **no** |
| `_discovery/providers.py:862,864` programmatic registration | string `name`, declaration group | **no** |
| `_types/job_declaration.py:58,67,69` workflow/`FromJob`/deps references | string ref or `__name__` | string **no**, `__name__` yes |

### 4b. Lookup — resolves what a caller wrote

| Surface | Path | Mechanism |
|---|---|---|
| `rc.invoke("…")` | `capabilities/runcontext.py:509-518` → `capabilities/invoke.py:366,399` → `executor.get_job` `:736-778` | exact, then `resolve_name` |
| `rc.invoke_parallel([("…", {})])` | `runcontext.py:520-524` → `invoke.py:583,659` → `executor.get_job` | same |
| CLI job argument, mode detection | `_cli/dispatch.py:207-218` | exact, then `normalize_segment(arg) in job_names` |
| CLI job argument, canonicalisation | `_cli/main.py:1320` | `normalize_name` |
| CLI click group | `app/adapters/cli.py:129-138` `get_command` | exact, then `normalize_segment` |
| Warm-boot descriptor lookup | `_discovery/cached_provider.py:1083-1092` `_resolve_entry` | exact, then `normalize_segment` per part |
| Provider `get_job` | `_discovery/providers.py:545,654,769` | `normalize_name` |
| Discovery registry | `_discovery/registry.py:100,138` | `resolve_name` |
| Dependency graph / `deps=` | `_engine/job_graph.py:197` | `resolve_name` |
| Workflow validation | `_engine/workflow_validation.py:164` | `resolve_name` |
| Group trie (dispatch, completion) | `_types/naming.py:536,547` | `resolve_name` per segment |
| Workflow resume / control | `app/_workflow_resume.py:87`, `app/_workflow_control.py:67` | `resolve_name`, `normalize_name` |
| Vault `--job` target | `app/vault.py:291-320` | `app.get_job`, then `resolve_name` |
| `builtin info` | `_cli/info.py:558,570` | `normalize_name` |
| App facade | `_app/impl.py:765,767,1616` | `normalize_name` |
| MCP workflow tools | `plugins/adapters/functualize-mcp/src/functualize_mcp/_workflow_tools.py:132` | `normalize_name` |
| Shortcut file | `_cli/main.py:1555` | `normalize_segment(fn_name)` |

### 4c. Name-keyed paths **outside** the policy

These carry their own spelling rule and would not inherit a change to
`_types/naming.py`:

| Path | Rule | Consequence for an NFKC-unstable name |
|---|---|---|
| Config file section `_config/sources.py:650-685` `_section_data` | exact, then `-`↔`_` swaps, then dotted walk | `[job_aaǆ]` in `functualize.toml` does not configure `job-aadž` (code reading; not executed) |
| Inline-provider rejection `_config/sources.py:687-700` | the same three spellings | same |
| Env var keys `_config/sources.py:262-290`, `_config/resolved_field.py:90-98` | `upper()` + `-`/`.` → `_` | `ǆ`.upper() is `Ǆ`, `dž`.upper() is `DŽ`: two env var names for one job. Non-ASCII env var names are themselves unusual |

### 4d. Persisted state keyed by the registered name

Written and read with the *resolved* name, so internally consistent today; they
matter only if the canonical form of an existing name changes.

- `_primitives/fingerprint.py:139-145` — state-store key `<job_name>::<args_hash>::<method>`.
- `_primitives/scope_store.py:425-428` — step records keyed `<job_name>::<args_hash>` in `scopes.json`.
- `_primitives/cache_format.py:129-156` — warm-boot discovery cache, `CACHE_VERSION = 21`;
  descriptors carry `name`. The v20 note shows the convention: a change to what
  a name resolves to bumps the version so the cache is rebuilt, not trusted.

## 5. What the fork actually changes

**(i) Normalise on lookup.** Two placements, with different blast radii:

- **(i-a) inside `normalize_segment`** — NFKC first, then the existing
  lowercase/hyphenate. Measured: applying NFKC before `normalize_segment` is
  idempotent over every identifier-continue character (0 counter-examples in
  the full sweep). Registration and all 42 call sites agree by construction, so
  `invoke`, `invoke_parallel`, the CLI, deps, workflows, vault and MCP are all
  covered by one edit. `__name__`-sourced names do not change (already NFKC).
  String-sourced names that contain an NFKC-unstable character **do** change
  identity (`ǆ-ops` → `dž-ops`): the discovery cache must be bumped (v22) and
  any state/scope records under the old spelling are orphaned. Config sections
  and env vars (§4c) still need their own change or an explicit exclusion.
- **(i-b) inside `resolve_name._canonical` only** — fixes `invoke`,
  `invoke_parallel`, deps and the trie, but **not** the CLI (`dispatch.py:217`,
  `adapters/cli.py:136`, `cached_provider.py:1091` compare
  `normalize_segment(arg)` against stored keys directly) and not config. It
  splits the one policy into two — the drift the module's docstring exists to
  prevent.

**(ii) Reject at discovery.** A `def` name's written spelling is not
recoverable from `__name__` or from `ast` (both already normalised, §1); it
needs `tokenize` over the source file, i.e. a new source-reading step in cold
discovery and something the warm-boot cache must carry. It does not make any
typed spelling resolve — it moves the error from call time to boot, as a
`DiscoveryFailure` per ADR-018 or a hard reject per `_validate_builtin_reservation`.
String-sourced names (group, `@job(name=)`, entry points) are already
consistent with what a caller types and would need no check. Callers writing
the normalised form (`"job_aadž"`) keep working.

## 6. Unknowns carried forward

- Whether any committed example, plugin or test registers a string-sourced name
  containing an NFKC-unstable character (would be renamed by (i-a)).
  `rg -nP "[^\x00-\x7F]" examples/ plugins/*/src` was not run as a census of
  *job names*; it is a Plan-phase 3b blast-radius query.
- Whether config sections and env vars are in scope for this issue or a
  sibling; the issue says "any name-keyed config", which reads as in scope.
- Whether the shell (`_cli/tui/**`) input bar passes typed text through
  `normalize_segment` before the trie; the trie path (`naming.py:536,547`) does,
  the TUI autocomplete's `get_job` calls were not traced.
