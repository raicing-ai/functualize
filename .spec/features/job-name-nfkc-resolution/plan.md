# Plan — job-name NFKC resolution

## Alignment

Shape: **Shape Intent — NFKC-Stable Job-Name Resolution (one naming policy for
written and parsed names)**, Confluence `SD/16613377`, `Authority: Approved`
(v3, owner, 2026-10-13T06:02:44Z). The issue's `Shape intent` property points at
that page, and `Shape state` is `approved`.

- **Decided contract (D0):** "(i-a) Apply NFKC first, inside `normalize_segment`
  (`src/functualize/_types/naming.py:45-79`), before the existing
  lowercase-and-hyphenate step."
- **Rejected:** "(i-b) NFKC only inside `resolve_name._canonical`" and
  "(ii) Reject or warn at discovery".
- **D1, accepted as drafted:** "Config-file sections are in scope" and
  "Environment-variable keys are a stated exclusion".
- **D2, accepted as drafted:** "Bump `CACHE_VERSION` from 21 to 22", "Accept that
  fingerprint and step records under the old spelling become orphaned … Record
  this in `CHANGELOG.md`, and count the affected string-set names in `examples/`
  and `plugins/` during the Plan phase", "Do not write a state migration".

**In scope**, in the shape's words:

- "`invoke`, `invoke_parallel`: `rc.invoke("…")` and
  `rc.invoke_parallel([("…", {})])` resolve the written and the rewritten
  spelling to the same job"
- "The CLI job argument: `func <job>`, the click group lookup, and mode detection"
- "Other references that go through the same module: `deps=` and workflow
  references, the group trie, vault `--job` targets, `builtin info`, the MCP
  workflow tools"
- "Name-keyed config (the config-file section lookup), per D1"
- "Name-keyed state: the discovery cache is rebuilt, and handling of state
  written under an old spelling follows D2"

**Out of scope**, in the shape's words: "The property-test generator fix"; "A
second naming policy"; "Rejecting or warning on such names at discovery";
"Environment-variable keys"; "The parallel parent's exit code when a child
fails".

**Must not change** (shape): "any name that is already NFKC-stable (all ASCII
names included) keeps the same registered identity; the rule for exact match,
then normalised match, then leaf match in `resolve_name`; and the reserved-name
check at boot."

**D2 census, done here as the shape required:** 0 string-set job names in
`examples/`, `plugins/`, `src/` or `tests/` are NFKC-unstable. The walk covered
1661 files: 8 `JOB_GROUP` strings and 6 `job(name=/group=)` strings. No package
in the repo declares a job entry point. D2's orphaned-state consequence
therefore touches no name this repository ships.

## Retrieval run for this plan

| Pass | Tool | Query | Finding used |
|---|---|---|---|
| Specify | zvec-grep (index built for this worktree) | naming normalisation, unreachable-name rejection, config section spelling | `_types/naming.py` is the single policy; `_app/boot.py:2211` and ADR-018 are the rejection precedents (only relevant to rejected option ii) |
| Specify | rg | `unicodedata\|NFKC\|normalize\(`; 4 policy functions' call sites | 0 job-name NFKC; 42 call sites, 19 files |
| 3a architecture | graphify `get_neighbors normalize_segment` | callers and importers | 9 direct callers across `_discovery`, `_types`, `app/adapters`, plus `_cli` via `app.utils` (INFERRED edges `dispatch.py`, `main.py`) |
| 3a architecture | serena `get_symbols_overview _config/sources.py`; `find_referencing_symbols _section_data` | `FileSource` surface | `_section_data` has 3 callers, `FileSource.get/has/keys` (`:723`, `:736`, `:748`) |
| 3a architecture | codemaps `dependencies.md`, `overview.md`; `pyproject.toml` import-linter | layer legality | `_types` imports nothing internal; `_config` → `_types` is foundation, legal; 7 contracts |
| 3b approach | rg over `tests/` | which tests pin the touched surfaces | `tests/discovery/test_naming.py`; four `CACHE_VERSION` users (symbolic, unaffected); `tests/config/test_config_section_spelling.py`, `test_dotted_config_sections.py`, `test_env_name_rule_parity.py` |
| 3b approach | AST census | string-set job names (D2) | 0 NFKC-unstable |
| 3b approach | probe on `c03dfb72` | defect still present after #102/#106 | yes, all three surfaces |

## BEFORE

```
 layer        module                                     what it does with a job name
 ───────────  ─────────────────────────────────────────  ───────────────────────────────────────────────
 public       app/utils.py  (re-exports policy) ─────────┐
              app/adapters/cli.py:136 ───────────────────┤ normalize_segment(arg)
              app/vault.py:307, app/_workflow_*.py ──────┤ resolve_name / normalize_name
 _cli         _cli/dispatch.py:217, main.py:1320 ─(via app.utils)─┤
 plugins      functualize-mcp/_workflow_tools.py:132 ────┤
 composition  _app/impl.py:765,1616 ─────────────────────┤
 peer         _discovery/{sync,registry,transforms,      │
                providers,cached_provider,naming}.py ────┤ build names (qualified_name)
              _engine/{executor:776, job_graph:197,      │
                workflow_validation:164}.py ─────────────┤ resolve_name
              _config/sources.py:650-712   ✗ no arrow    │ OWN rule: exact, -/_ swaps, dotted walk  (×2 copies)
              _config/sources.py:242-290,                │
                resolved_field.py:90-110   ✗ no arrow    │ OWN rule: upper(), -/. → _              (×3 copies)
 foundation   _types/naming.py  ◄────────────────────────┘ normalize_segment: lower + hyphenate, NO NFKC
              _types/job_declaration.py:58-69 ──► _types/naming.py
 primitives   _primitives/cache_format.py  CACHE_VERSION = 21 ◄── _discovery/cached_provider.py:329
              _primitives/{fingerprint,scope_store}.py  keys "<job_name>::…" (registered name)

 Python parser ──NFKC──► __name__ ──► qualified_name     argv / string literal ──(raw)──► lookup   ✗ mismatch
```

Smells the BEFORE already carries, by catalogue name
(Refactoring.Guru, `design-patterns-refactoring` skill, ch34–ch35):

- **Duplicate Code**: the config section spelling list is written twice,
  `(section, section.replace("-", "_"), section.replace("_", "-"))` at
  `_config/sources.py:695`, and the same swaps at `:663-669`.
- **Duplicate Code**: the env-var spelling rule is kept in three places "by
  matching their rule exactly, not by importing across a peer layer"
  (`_config/resolved_field.py:90-98`; `EnvSource.keys` and `_build_env_key`,
  `_config/sources.py:242-290`; `_engine/missing_value.py:55`).
- **Shotgun Surgery (latent)**: a change to "what spells this job" has to land
  in `_types/naming.py` *and* in `_config/sources.py`'s private copy. This
  defect is that hazard happening: the policy and the config layer would
  disagree the moment only one of them learned NFKC.

## AFTER

```
 layer        module                                     change
 ───────────  ─────────────────────────────────────────  ───────────────────────────────────────────────
 public/_cli/plugins/composition/_discovery/_engine     no code change — inherit NFKC through the policy
 peer         _config/sources.py  ── NEW import ──┐       one private `_find_section(config, section)` used by
                                                  │       _section_data AND reject_inline_provider; steps 1-3
                                                  │       verbatim, step 4 = normalize_name equality
              _config/sources.py:242-290,          │       unchanged (D1 exclusion), documented
                resolved_field.py:90-110          │
 foundation   _types/naming.py  ◄─────────────────┘       normalize_segment = rule(NFKC(s));
                 ▲ import unicodedata (stdlib)            normalize_name / resolve_name._canonical NFKC the
                                                          whole name before split
 primitives   _primitives/cache_format.py  CACHE_VERSION = 22 (+ v22 log line)
              _primitives/{fingerprint,scope_store}.py  unchanged (D2: no migration)

 Python parser ──NFKC──► __name__ ──► qualified_name ──► NFKC(no-op) ─┐
 argv / string literal ─────────────────────────────────► NFKC ──────┴─► same key   ✓
```

Boundaries crossed: one new import edge, `_config` → `_types.naming`, from a
peer to the foundation. Legal under *"Peer layers are independent"* and already
taken by `_config/sources.py:31-32`. One stdlib edge, `_types` → `unicodedata`.
Legal under *"Types import nothing internal"*. No `_cli` → internal edge. No
peer ↔ peer edge.

### Candidates and the smells each introduces (gate step 4)

1. **NFKC at each consumer** (option i-b, or one per surface): introduces
   **Shotgun Surgery** across 19 files and a second policy. Rejected by the
   shape.
2. **NFKC in `normalize_segment` only**: leaves a typed compatibility dot
   (31 code points NFKC to a string containing `.`) inside one segment, so
   `ａ．ｂ` would canonicalise to one segment `a.b` instead of group `a`, job `b`.
   That is a correctness hole in the policy, not a smell. Rejected.
3. **NFKC in `normalize_segment`, and on the whole name in `normalize_name` and
   `resolve_name._canonical`** (chosen). All three live in one module. It
   applies NFKC twice on the dotted path, which is redundant but idempotent
   (measured, 0 failures). See *Surviving smells*.
4. **Config:** a fifth spelling appended to the two existing copies would deepen
   the **Duplicate Code**. Instead, *Extract Method* folds both copies into one
   private lookup that calls the policy. The copy count goes from 2 to 1 and the
   private rule gives way to the shared one, so the latent **Shotgun Surgery**
   is removed for config.

## Design skills consulted

- `python-design-patterns` (in repo, `.claude/skills/python-design-patterns`):
  KISS and single responsibility. One policy owns "what name does this denote".
- `design-patterns-refactoring` (user-level, Refactoring.Guru catalogue),
  loaded this session. Used: ch34 *Change Preventers* (Shotgun Surgery,
  Divergent Change), ch35 *Dispensables* (Duplicate Code), and the
  *Extract Method* technique.

## Surviving smells

1. **Duplicate Code: the env-var spelling rule, three copies** (`_config/resolved_field.py:90-98`,
   `_config/sources.py:242-290`, `_engine/missing_value.py:55` `env_var_for`).
   - *Why it survives:* D1 makes env keys a stated exclusion, so this change
     does not touch them. The copies exist to avoid a peer-layer import, and
     `tests/config/test_env_name_rule_parity.py` pins them equal.
   - *Review:* no maintainer review needed. The owner accepted D1 as drafted.
2. **Redundant computation: NFKC applied at name level and again per segment**
   (`_types/naming.py`, `normalize_name` → `normalize_segment`).
   - *Why it survives:* `normalize_segment` is called directly by 9 callers, so
     it must carry NFKC itself. The whole-name pass is what makes a compatibility
     dot split a group. NFKC is idempotent, so the second pass changes nothing.
   - *Cost:* one extra `unicodedata.normalize` per segment, on paths that are not
     hot loops.
   - *Review:* no maintainer review needed.

Neither is on `.spec/CONSTITUTION.md` → *Forbidden Patterns*. The AFTER adds
no peer cross-import, no module-level mutable state, no new file over ~500 LOC
(`_types/naming.py` is 610 lines and grows by about 10), and no `_cli` →
internal import.

**`_types/naming.py` is already past the ~500 LOC god-object threshold** (610
lines: the policy plus the group trie). This change adds about 10 lines and
does not create that condition. Splitting the trie out is not this issue's job.
It is reported here as a pre-existing finding for the board, not fixed.

## Technical approach

1. **`_types/naming.py`.** `import unicodedata`. Add a private
   `_nfkc(s) = unicodedata.normalize("NFKC", s)`. `normalize_segment` runs its
   existing loop over `_nfkc(segment)`. `normalize_name` and
   `resolve_name._canonical` NFKC the whole name before `split(".")`.
   `resolve_name`'s step-3 dot test reads the NFKC'd candidate. Docstrings name
   PEP 3131 and say why NFKC comes first.
2. **`_primitives/cache_format.py`.** `CACHE_VERSION = 22`, plus a
   `# v22 (2026-10-…)` log line in the existing style: a cached descriptor may
   carry a pre-NFKC string-set name.
3. **`_config/sources.py`.** Extract `_find_section(config: Mapping, section) -> dict | None`
   holding steps 1–4. `_section_data` calls it with `self._merged_config`;
   `reject_inline_provider` calls it per file. Step 4 compares
   `normalize_name(k)` with `normalize_name(section)`. More than one distinct
   match raises `ConfigurationError`.
4. **Tests**: per task, in `tasks.md`.
5. **Docs**:
   - `docs/guides/jobs-discovery.md` § *Job names are canonical*: one row for a
     ligature name, one sentence on NFKC, and the env-var exclusion.
   - `CHANGELOG.md` `[Unreleased]`: a *Fixed* entry, plus the D2 re-run note.
   - `contributor/architecture/group-trie.md:75-77`: correct the stale
     "strip non-alphanumeric" line.

## Files expected to change

The hit set of the retrieval above, and nothing else:

| File | Task | Why (hit) |
|---|---|---|
| `src/functualize/_types/naming.py` | 1.1 | the policy, `:45-156` |
| `tests/discovery/test_naming.py` | 1.1 | the policy's own tests |
| `src/functualize/_primitives/cache_format.py` | 2.1 | `CACHE_VERSION`, `:129-156` |
| `tests/discovery/test_nfkc_cache_rebuild.py` (new) | 2.1 | E4 |
| `src/functualize/_config/sources.py` | 2.2 | `_section_data` `:650-685`, `reject_inline_provider` `:687-712` |
| `tests/config/test_config_section_spelling.py` | 2.2 | existing spelling tests, extended |
| `tests/integration/test_nfkc_job_names.py` (new) | 2.3 | E1, E3: invoke, parallel, CLI, deps, group, collision |
| `docs/guides/jobs-discovery.md` | 3.1 | user-facing naming rule, `:30-62` |
| `CHANGELOG.md` | 3.1 | D2 note |
| `contributor/architecture/group-trie.md` | 3.1 | stale codemap, `:75-77` |

**Not changed, by evidence:** `_cli/dispatch.py`, `_cli/main.py`,
`app/adapters/cli.py`, `_discovery/cached_provider.py`, `_engine/executor.py`,
`_engine/capabilities/invoke.py`, `app/vault.py`, the MCP plugin. Each reaches
the policy through `normalize_segment`, `normalize_name` or `resolve_name`
(`research.md` §4b). Task 2.3 proves each named surface end to end rather than
trusting this table.

## Risks

- **R1: a property test that draws unstable letters changes behaviour.**
  `tests/context/test_invoke_properties.py:61` draws `Ll` suffixes without an
  NFKC filter. Today those names can fail to resolve; after the change they
  resolve. This can only turn a latent flake green. It is not modified.
  PR #102's NFKC-stable alphabet in `test_parallel_and_log_properties.py` stays,
  as the shape requires.
- **R2: the config step-4 broadening.** `[Build_Wheel]` starts configuring
  `build-wheel` when no exact or swapped key exists. The shape asks for config
  to "go through the shared naming rule", and this is that rule. Pinned by
  AC7's "existing cases still pass".
- **R3: collision reporting across string-set groups.** AC5 asserts
  `_discovery/collisions.py` reports `ǆ_ops`/`dž_ops`. If that registration
  path bypasses the collision rule, task 2.3 fails. That is a finding to report,
  not a gate to weaken.
