# Evidence

Runnable probes backing every **[probed]** claim in v3.

- **All 19 were re-executed against `787035e`, this branch's base, on
  2026-09-08.** Six unchanged, four moved because an upstream ask landed, two
  moved cosmetically, one falsified a claim. The drift table below is the
  authoritative record; `transcript.md` carries every output.
- Originally captured against **0.2.3** — probes 01–18 at `a2f453d`, probe 19
  at `78d9ff4`. Where a row in the table further down still describes the older
  behaviour, the drift section says so explicitly.
- Re-run again after any upstream merge that touches discovery, parameters or
  the agent surface, and update both files when outputs move.
- Probes import functualize from *this* repository, so no external checkout is
  needed. From the repository root:

```bash
uv sync
for p in .spec/shape-intents/subject-modeling/evidence/probe_*.py; do
  echo "=== $p"
  PYTHONPATH=src uv run python "$p"
done
```

## Drift at `787035e` — full re-run 2026-09-08

**All 19 probes** re-executed against this branch's base. An earlier pass in
this file reported a five-probe sample as "three unchanged, two moved"; that
undercounted. The complete result:

| | Count | Probes |
|---|---|---|
| unchanged | 6 | 02, 03, 04, 05, **10**, 12 |
| changed by an upstream fix this design asked for | 4 | 01, 06, 07, 13 |
| changed cosmetically, claim intact | 2 | 08, 09 |
| **claim falsified** | 1 | **11** |
| no prior baseline, now captured | 6 | 14, 15, 16, 17, 18, 19 |

**Probe 10 is in the unchanged column, which is the one that matters most** —
the plugin-provider path still delivers parameters intact, and that is what the
entire binding design rests on (`03` §1).

### Four asks landed, visible in probe output

| Probe | At `a2f453d` | At `787035e` | Ask |
|---|---|---|---|
| `probe_01_jobsources` | `A. registered jobs: []` — declared providers dropped | `['start', 'status']` | **2**. The remaining `JobNotFoundError` on `apps.bifrost.status` is the *group-composition* question — jobs register under bare names — not the drop |
| `probe_06_agent_surface` | `UNPATCHED  info schema properties: []` | `['force', 'variant']` | **1**. The P1 defect is fixed *on the unpatched fallback path itself*, so `register_dynamic_job` is no longer a liability and `03` §1's "no compatibility shim" is now true twice over |
| `probe_07_self_management` | imported `functualize._cli.runtime` | that module is **gone**; `detect_from_process` is public in `functualize.app.packaging.__all__` | **4**. The probe was updated to the public path — the import working *is* the ask's acceptance test. Its substantive output is unchanged: `mode=project`, `owning_distribution=None`, `degraded=True` |
| `probe_13_declaration_survival` | `job_detail` **drops** the declaration | `job_detail exposes tags? True`; keys include `tags`, `examples`, `extra_description`, `category` | **7**. The row in the probe table below still said "drops it" and is corrected |

### Two cosmetic, claim intact

- `probe_08_bool_negation` — the log line lost its `INFO:functualize.job.…:`
  prefix. The measured values are identical (`force=False cache=False`,
  `force=True cache=True`), so the `--flag / --no-flag` claim stands.
- `probe_09_missing_dep` — the warning moved from
  `functualize._discovery.registry` to `_discovery.providers` and reads better
  (`⚠ needs_dep.py not loaded — No module named …`). `discovered: ['hello']` is
  unchanged, so "a failed import is reported, not swallowed" holds, more
  legibly.

### Rebased onto `c0c921f` — a second first-party top-level name

The branch was later rebased onto `c0c921f` (#33, plugin visibility) and
`6541f8b` (#32, agent retrieval indexes). All 19 probes re-ran; 14 byte-identical,
three differed only in nondeterministic output (tempdirs, durations, scope ids),
`probe_01`'s grep line numbers moved as `boot.py` grew, and **`probe_07`
surfaced a real change**:

```
top-level commands: ['builtin', 'hello']          # 787035e
top-level commands: ['builtin', 'hello', 'mcp']   # c0c921f
```

`mcp` is now a first-party top-level command, and `probe_20` shows it is **not
protected the way `builtin` is**:

```
first-party top level (no rise jobs): ['builtin', 'mcp']
group='builtin'  -> REFUSED   ValueError: ... claims the reserved top-level name
group='mcp'      -> ACCEPTED  top-level=['builtin', 'mcp']
```

A rise module declaring `group = "mcp"` collides silently — the same failure
class as #32, one layer up.

**Consequence for the design.** `00` fact 5 and `09` §1 state the reserved-name
rule as a fact about *one name*, which was true when `builtin` was the only
first-party top-level command. It is now a fact about a **set that grew
upstream once and can grow again**. Binding check 10 (`03` §4, "reserved
names") must therefore derive the protected set from the adapter — the two
lines `probe_20` uses — rather than hardcoding `builtin`, and
`test_no_builtin_namespace` (`11` §3) should assert against that derived set.

This is **upstream ask 11**: protect the whole first-party top level, or at
minimum warn on a collision instead of accepting it. Rise can route around it
by deriving the set, so it does not block.

### The one that falsifies a claim: probe 11

A duplicate bare job name used to lose **every** colliding job and say so. It
now keeps the **first** and silently drops the second — defect **#32**
("two functions normalizing to the same job name silently become one job on the
default path"), recorded-not-fixed in #29.

So the v3 sentence *"duplicate bare names are fatal"* (`03` §3a, and the
`test_qualified_names_required` row in `11` §3) is **no longer true**. What
survives, and is what actually mattered: **qualified names still produce
distinct, individually runnable jobs** — the mitigation is unchanged and still
correct. Only the failure mode of *not* doing it got quieter, and therefore
worse.

Consequence for the test that pins this: it can no longer assert "the bare-name
case errors." It must assert `len(jobs) == 2` and catch a *silent* collapse.
That is recorded in `11` §3.

## What each probe establishes

| Probe | Establishes | Where |
|---|---|---|
| `probe_01_jobsources.py` | `JobSources(functions=…)` is dropped on the standard path; `job_providers` was never read (**fixed at `787035e`** — ask 2); `add_job_provider` *after the constructor* is still too late | `00` facts 1–3 |
| `probe_02_prefilter.py` | a class-only module is never imported by directory discovery | `00` fact 4 |
| `probe_03_binding_guards.py` | the abstract gate fires; bound methods bind; `@job(guards=Guards(status=…))` on a method skips the second run | `01` §8, `08` §1 |
| `probe_04_builtin_reserved.py` | claiming `builtin` is a hard boot error; a top-level verb is not | `00` fact 5 |
| `probe_05_tty_prompt.py` | `tty: TTY \| None` is the interactivity signal; exact off-terminal `prompt_confirm` semantics | `08` §3 |
| `probe_06_agent_surface.py` | `register_dynamic_job` recorded no parameters, so agents saw an empty `inputSchema`; **fixed at `787035e`** without the patch — ask 1 | `13` §1 |
| `probe_07_self_management.py` | a downstream app inherits `builtin self` / `builtin plugin`; install-mode detection and the exit-3 refusal | `00` §1, `09` §7 |
| `probe_08_bool_negation.py` | booleans on a bound method render `--flag / --no-flag` | `03` §4 check 9 |
| `probe_09_missing_dep.py` | a job whose import fails is skipped with a warning — it vanishes from the CLI | `07` §1, `13` §5 |
| **`probe_10_plugin_binding.py`** | **a plugin's `add_job_provider` reaches the registry, parameters intact — no upstream patch needed** | `03` §1 |
| **`probe_11_name_collision.py`** | `StaticProvider` keys by bare name. A duplicate lost **every** job at `a2f453d`; at `787035e` it keeps the first and **silently drops** the second (#32). Qualified names fix it either way, and are now load-bearing | `03` §3a |
| **`probe_12_dual_delivery.py`** | one plugin mounts at root (own CLI) or under a namespace (guest); `NamespaceTransform` does *not* work for this | `04` §1, §3 |
| **`probe_13_declaration_survival.py`** | `@job(tags=…)` survives plugin → `StaticProvider` → descriptor. `job_detail` **dropped** it at `a2f453d`; at `787035e` it exposes `tags`, `examples`, `extra_description`, `category` — ask 7 landed | `15` §1, §2 |
| **`probe_14_scrill_layout.py`** | a directory-scanned job's `source_file` locates its own `SKILL.md` — no manifest | `15` §1, §3A |
| **`probe_15_refusal_guidance.py`** | `Precondition(check, msg)` → `REFUSED`, message verbatim in `metadata.preflight.reason` | `15` §1 |
| **`probe_16_workflow_gates.py`** | `Gate(strategy="ai_outbound")` blocks the walk and publishes its schema; a resolver registered as `ai_inbound` resolves in-process; absent one, the ladder falls through | `16` §1 |
| **`probe_17_gate_fallback.py`** | blocking is the universal gate fallback — except an *unregistered* strategy name, which raises `ValueError` out of the walk; `Gate(strategy="ai")` is rejected outright | `16` §1a |
| **`probe_18_gate_presets.py`** | at boot only `resolve` and `prompt` are registered and no presets exist; with both plugin resolvers registered the `"ai"` ladder resolves | `16` §1a |
| **`probe_19_display_discovery.py`** | a rise-shaped `Display` satisfies `DisplayProvider` both ways; `should_show` is one `is_dir()`; **discovery is entry-points-first and the dedupe is first-wins, so a project `displays.py` cannot override an installed `display_id`** — it is dropped silently | `18` §3, §5 |
| **`probe_20_reserved_top_level.py`** | `builtin` is refused as a rise group; **`mcp` is accepted and collides silently.** The protected top-level set is derived, not fixed — it grew at `c0c921f` | `00` fact 5, `03` §4 check 10 |

Probes 01–06 were also run against 0.1.2 and produced byte-identical output;
07–18 require functualize >= 0.2.0. Probe 19 requires >= 0.2.3 and needs no
TUI: `register_display_providers` is driven against a recording stub app.
Transcript: `transcript.md`.
