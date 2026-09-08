# Evidence

Runnable probes backing every **[probed]** claim in v3.

- Probes were last executed against functualize **0.2.3** — probes 01–18 at
  `a2f453d`, probe 19 at `78d9ff4` (v0.2.3-2).
- **This branch is newer than that.** It was cut from `787035e` (#30,
  "discovery correctness, job parameter types"), which touches discovery and
  parameter handling — exactly what probes 01, 02, 10 and 11 pin. Re-run before
  trusting any **[probed]** claim, and update this file's outputs and
  `transcript.md` when they move.
- Probes import functualize from *this* repository, so no external checkout is
  needed. From the repository root:

```bash
uv sync
for p in .spec/shape-intents/subject-modeling/evidence/probe_*.py; do
  echo "=== $p"
  PYTHONPATH=src uv run python "$p"
done
```

## Drift at `787035e` — re-run 2026-09-08

Five probes were re-run when this shape intent landed on this branch. **Three
are unchanged; two moved, and one of those falsifies a v3 claim.**

| Probe | At `a2f453d` | At `787035e` | Verdict |
|---|---|---|---|
| `probe_01_jobsources` | `A. registered jobs: []` — declared providers dropped | `A. registered jobs: ['start', 'status']` | **fixed upstream.** Ask 2 landed. The remaining `JobNotFoundError` on `apps.bifrost.status` is the *group-composition* question (jobs register under bare names), not the drop |
| `probe_02_prefilter` | `discovered: [('hello', None)]`, bifrost `False`, plain `True` | identical | unchanged |
| `probe_10_plugin_binding` | parameters present without the P1 patch | identical | unchanged — **`03` §1 still holds**, which is the load-bearing claim of the whole binding design |
| `probe_11_name_collision` | `jobs=[]  exits=[2, 2]`, loud `Resolution pipeline error` | `jobs=['install']  exits=[0, 2]` | **changed. See below** |
| `probe_19_display_discovery` | (first run at `78d9ff4`) | identical | unchanged |

### The one that falsifies a claim: probe 11

A duplicate bare job name used to lose **every** colliding job and say so. It
now keeps the **first** and silently drops the second — which is defect **#32**
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

| Probe | Establishes | Where |
|---|---|---|
| `probe_01_jobsources.py` | `JobSources(functions=…)` is dropped on the standard path; `job_providers` is never read; `add_job_provider` *after the constructor* is too late | `00` facts 1–3 |
| `probe_02_prefilter.py` | a class-only module is never imported by directory discovery | `00` fact 4 |
| `probe_03_binding_guards.py` | the abstract gate fires; bound methods bind; `@job(guards=Guards(status=…))` on a method skips the second run | `01` §8, `08` §1 |
| `probe_04_builtin_reserved.py` | claiming `builtin` is a hard boot error; a top-level verb is not | `00` fact 5 |
| `probe_05_tty_prompt.py` | `tty: TTY \| None` is the interactivity signal; exact off-terminal `prompt_confirm` semantics | `08` §3 |
| `probe_06_agent_surface.py` | `register_dynamic_job` records no parameters; the one-line patch restores them | `13` §1 |
| `probe_07_self_management.py` | a downstream app inherits `builtin self` / `builtin plugin`; install-mode detection and the exit-3 refusal | `00` §1, `09` §7 |
| `probe_08_bool_negation.py` | booleans on a bound method render `--flag / --no-flag` | `03` §4 check 9 |
| `probe_09_missing_dep.py` | a job whose import fails is skipped with a warning — it vanishes from the CLI | `07` §1, `13` §5 |
| **`probe_10_plugin_binding.py`** | **a plugin's `add_job_provider` reaches the registry, parameters intact — no upstream patch needed** | `03` §1 |
| **`probe_11_name_collision.py`** | `StaticProvider` keys by bare name; a duplicate loses **every** job. Qualified names fix it | `03` §3a |
| **`probe_12_dual_delivery.py`** | one plugin mounts at root (own CLI) or under a namespace (guest); `NamespaceTransform` does *not* work for this | `04` §1, §3 |
| **`probe_13_declaration_survival.py`** | `@job(tags=…)` survives plugin → `StaticProvider` → descriptor; `job_detail` **drops** it | `15` §1, §2 |
| **`probe_14_scrill_layout.py`** | a directory-scanned job's `source_file` locates its own `SKILL.md` — no manifest | `15` §1, §3A |
| **`probe_15_refusal_guidance.py`** | `Precondition(check, msg)` → `REFUSED`, message verbatim in `metadata.preflight.reason` | `15` §1 |
| **`probe_16_workflow_gates.py`** | `Gate(strategy="ai_outbound")` blocks the walk and publishes its schema; a resolver registered as `ai_inbound` resolves in-process; absent one, the ladder falls through | `16` §1 |
| **`probe_17_gate_fallback.py`** | blocking is the universal gate fallback — except an *unregistered* strategy name, which raises `ValueError` out of the walk; `Gate(strategy="ai")` is rejected outright | `16` §1a |
| **`probe_18_gate_presets.py`** | at boot only `resolve` and `prompt` are registered and no presets exist; with both plugin resolvers registered the `"ai"` ladder resolves | `16` §1a |
| **`probe_19_display_discovery.py`** | a rise-shaped `Display` satisfies `DisplayProvider` both ways; `should_show` is one `is_dir()`; **discovery is entry-points-first and the dedupe is first-wins, so a project `displays.py` cannot override an installed `display_id`** — it is dropped silently | `18` §3, §5 |

Probes 01–06 were also run against 0.1.2 and produced byte-identical output;
07–18 require functualize >= 0.2.0. Probe 19 requires >= 0.2.3 and needs no
TUI: `register_display_providers` is driven against a recording stub app.
Transcript: `transcript.md`.
