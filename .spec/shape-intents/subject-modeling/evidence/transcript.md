# Probe transcript

Target: functualize **0.2.3**, `origin/master` commit `a2f453d`.
Captured 2026-09-05.

## `probe_01_jobsources.py`

```
A. static_wiring fast path taken: False
A. registered jobs: []
A. execute: JobNotFoundError Job 'apps.bifrost.status' is not registered
B. registered jobs after add_job_provider: []
B. execute: JobNotFoundError Job 'apps.bifrost.status' is not registered
C. job_providers references in the package: 2
    config.py:48:    - job_providers: custom JobProvider instances with optional transforms
    config.py:56:    job_providers: list[Any] | None = (
```

## `probe_02_prefilter.py`

```
discovered: [('hello', None)]
bifrost.py   should_import: False
plain.py     should_import: True
```

## `probe_03_binding_guards.py`

```
0. abstract gate enforced: Can't instantiate abstract class Broken without an implementation for abstract method 'install'
1. StaticProvider params: [('variant', 'str', False, 'pip'), ('force', 'bool', False, False)]
2. status  -> RunStatus.SUCCESS
3. install#1 -> RunStatus.SUCCESS
4. install#2 -> RunStatus.SKIPPED   (SKIPPED == exit 0)
5. why:
      apps.tool.install → SKIP (already done)
        status  __main__.Tool.<lambda> ✓
        reason  status guards satisfied
```

## `probe_04_builtin_reserved.py`

```
adapter raised ValueError:
   job 'builtin.diagnose' claims the reserved top-level name 'builtin'. That subtree is first-party only — rename the job, group, or namespace.
top-level `rise diagnose` wired OK: True
```

## `probe_05_tty_prompt.py`

```
rc has is_interactive attribute: False
tty is None (i.e. non-interactive): True
prompt_confirm(default=False) -> False
prompt_confirm(default=True)  -> True
prompt_confirm(no default)    -> InputNotAvailable
exit: 0
```

## `probe_06_agent_surface.py`

```
UNPATCHED  info schema properties: []
UNPATCHED  CLI accepts --variant:  True
PATCHED    info schema properties: ['force', 'variant']
PATCHED    CLI accepts --variant:  True
```

## `probe_07_self_management.py`

```
top-level commands: ['builtin', 'hello']

--- builtin --help  exit=0
Usage: rise builtin [OPTIONS] COMMAND [ARGS]...

  First-party commands, kept out of the job namespace.

Options:
  --help  Show this message and exit.

Commands:
  cache       Manage the job metadata cache.
  config      Inspect and manage CLI tool configuration.
  domains     Discover and inspect domain SDKs.
  env         Export a job's resolved config as environment variables.
  history     Show recent runs, newest first.
  info        Display app state, discovered jobs, and config.
  parallel    Run several jobs concurrently and report on all of them.
  plugin      Inspect and manage inst

--- builtin self --help  exit=0
Usage: rise builtin self [OPTIONS] COMMAND [ARGS]...

  Inspect and manage this installation.

Options:
  --help  Show this message and exit.

Commands:
  doctor   Check this installation and report what is wrong with it.
  install  Install a package into this installation's environment.
  python   Run this installation's interpreter, or print its path.
  update   Upgrade this installation, then put back what you added to it.
  uv       Run the uv this installation uses, or print its path.

--- builtin plugin --help  exit=0
Usage: rise builtin plugin [OPTIONS] COMMAND [ARGS]...

  Inspect and manage installed extensions.

Options:
  --help  Show this message and exit.

Commands:
  install    Install an extension into this installation's environment.
  list       List every installed extension, with the distribution...
  uninstall  Remove an extension from this installation's environment.

--- builtin self doctor  exit=0
ok  python                  3.12.13
  ok  cli-extras              present
      install-mode            project
  !!  owning-distribution     could not be determined from the running console script
                              -> Self-management is unavailable here. Upgrade with whatever installed this interpreter.
      installations           2 registered, 0 stale
        /home/viltohmyst/code/raicing-ai/functualize/.worktrees/standalone-distribution/.venv/bin/func  0.2.1  project
        /home/viltohmyst/code/raicing-ai/functualize/.worktrees/standalone-distribution/.venv/bin/functualize  

detect(): mode= project | owning_distribution= None | degraded= True
```

## `probe_08_bool_negation.py`

```
--- install --help
Usage: rise apps tool install [OPTIONS]

  Install the tool.

Options:
  --variant TEXT
  --force / --no-force
  --cache / --no-cache
  --help                Show this message and exit.
--- apps tool install --no-cache exit=0: INFO:functualize.job.apps.tool.install:variant=pip force=False cache=False
--- apps tool install --force exit=0: INFO:functualize.job.apps.tool.install:variant=pip force=True cache=True
```

## `probe_09_missing_dep.py`

```
WARNING:functualize._discovery.registry:Failed to import module 'needs_dep' from '/tmp/tmp_68d1l05/jobs': No module named 'nonexistent_package_xyz'
discovered: ['hello']
`fetch` is present: False
```

## `probe_10_plugin_binding.py`

```
registered: [('apps.tool.install', ['variant', 'force']), ('apps.tool.status', [])]
run: 0
info schema properties: ['force', 'variant']   <- non-empty WITHOUT the P1 patch
```

## `probe_11_name_collision.py`

```
Resolution pipeline error: Duplicate job name 'install' from provider index 0 and 0
bare name   jobs=[] exits=[2, 2]
qualified   jobs=['apps.alpha.install', 'apps.beta.install'] exits=[0, 0]
```

## `probe_12_dual_delivery.py`

```
own CLI (root)               top=['apps', 'builtin']  `apps bifrost start` -> exit=0
guest, group-composed        top=['builtin', 'rise']  `rise apps bifrost start` -> exit=0
guest, NamespaceTransform    top=['apps', 'builtin']  `rise apps bifrost start` -> exit=2
```

---

# Full re-run at `787035e` — 2026-09-08

All 19 probes, executed against this branch's base (#30, "discovery
correctness, job parameter types") with `PYTHONPATH=src`. Analysis and the
drift summary are in `README.md`; this section is the raw record.

Six unchanged, four moved because an upstream ask landed, two moved
cosmetically, one falsified a claim.

## `probe_01_jobsources.py`

CHANGED — `A. registered jobs` was `[]`. Declared `job_providers` are now honoured (ask 2). The remaining `JobNotFoundError` is group composition, not the drop.

```
A. static_wiring fast path taken: False
A. registered jobs: ['start', 'status']
A. execute: JobNotFoundError Job 'apps.bifrost.status' is not registered
B. registered jobs after add_job_provider: []
B. execute: JobNotFoundError Job 'apps.bifrost.status' is not registered
C. job_providers references in the package: 11
    boot.py:927:    """Add ``JobSources.functions`` and ``.job_providers`` to the pipeline.
    boot.py:932:    then functions, then ``job_providers``.
    boot.py:944:    * ``job_providers`` was read by nothing at all on either path.
    boot.py:946:    ``job_providers`` accepts either a bare provider or a
    boot.py:959:        TypeError: If a ``job_providers`` entry is neither a provider nor a
    boot.py:969:    declared = getattr(app._job_sources, "job_providers", None)
    boot.py:977:                    f"job_providers[{index}] is a {len(entry)}-tuple. The tuple "
    boot.py:983:                    f"job_providers[{index}] pairs a provider with "
    config.py:53:    - job_providers: custom JobProvider instances with optional transforms
    config.py:61:    job_providers: list[JobProvider | tuple[JobProvider, list[JobTransform]]] | None = (
    config.py:74:    honoured on both paths by ``_app.boot.wire_declared_job_providers``, and the
```

## `probe_02_prefilter.py`

unchanged.

```
discovered: [('hello', None)]
bifrost.py   should_import: False
plain.py     should_import: True
```

## `probe_03_binding_guards.py`

unchanged.

```
0. abstract gate enforced: Can't instantiate abstract class Broken without an implementation for abstract method 'install'
1. StaticProvider params: [('variant', 'str', False, 'pip'), ('force', 'bool', False, False)]
2. status  -> RunStatus.SUCCESS
3. install#1 -> RunStatus.SUCCESS
4. install#2 -> RunStatus.SKIPPED   (SKIPPED == exit 0)
5. why:
      apps.tool.install → SKIP (already done)
        status  __main__.Tool.<lambda> ✓
        reason  status guards satisfied
```

## `probe_04_builtin_reserved.py`

unchanged.

```
adapter raised ValueError:
   job 'builtin.diagnose' claims the reserved top-level name 'builtin'. That subtree is first-party only — rename the job, group, or namespace.
top-level `rise diagnose` wired OK: True
```

## `probe_05_tty_prompt.py`

unchanged.

```
rc has is_interactive attribute: False
tty is None (i.e. non-interactive): True
prompt_confirm(default=False) -> False
prompt_confirm(default=True)  -> True
prompt_confirm(no default)    -> InputNotAvailable
exit: 0
```

## `probe_06_agent_surface.py`

CHANGED — `UNPATCHED info schema properties` was `[]`. The P1 defect is fixed on the unpatched path itself (ask 1), so `register_dynamic_job` is no longer a liability.

```
UNPATCHED  info schema properties: ['force', 'variant']
UNPATCHED  CLI accepts --variant:  True
PATCHED    info schema properties: ['force', 'variant']
PATCHED    CLI accepts --variant:  True
```

## `probe_07_self_management.py`

CHANGED, and the probe was edited to run at all: it imported `functualize._cli.runtime`, which no longer exists. `detect_from_process` is now public in `functualize.app.packaging` (ask 4) — the import working is that ask's acceptance test. Substantive output unchanged; the `installations` list is local machine state.

```
top-level commands: ['builtin', 'hello']

--- builtin --help  exit=0
Usage: rise builtin [OPTIONS] COMMAND [ARGS]...

  First-party commands, kept out of the job namespace.

Options:
  --help  Show this message and exit.

Commands:
  cache       Manage the job metadata cache.
  config      Inspect and manage CLI tool configuration.
  domains     Discover and inspect domain SDKs.
    … 33 lines elided (CLI --help output) …

--- builtin self doctor  exit=0
ok  python                  3.12.13
  ok  cli-extras              present
      install-mode            project
  !!  owning-distribution     could not be determined from the running console script
                              -> Self-management is unavailable here. Upgrade with whatever installed this interpreter.
      installations           12 registered, 8 stale
  !!    /home/viltohmyst/code/raicing-ai/functualize/.worktrees/standalone-distribution/.venv/bin/func  0.2.1  project [stale]
                              -> This binary no longer exists. The record is kept because the registry

detect(): mode= project | owning_distribution= None | degraded= True
```

## `probe_08_bool_negation.py`

CHANGED cosmetically — the log line lost its `INFO:functualize.job.…:` prefix. Values identical; the claim stands.

```
--- install --help
Usage: rise apps tool install [OPTIONS]

  Install the tool.

Options:
  --variant TEXT
  --force / --no-force
  --cache / --no-cache
  --help                Show this message and exit.
--- apps tool install --no-cache exit=0: variant=pip force=False cache=False
--- apps tool install --force exit=0: variant=pip force=True cache=True
```

## `probe_09_missing_dep.py`

CHANGED cosmetically — the warning moved to `_discovery.providers` and reads better. `discovered: ['hello']` unchanged; the claim holds.

```
WARNING:functualize._discovery.providers:⚠ needs_dep.py not loaded — No module named 'nonexistent_package_xyz'
discovered: ['hello']
`fetch` is present: False
```

## `probe_10_plugin_binding.py`

unchanged — the load-bearing claim of the binding design (`03` §1).

```
registered: [('apps.tool.install', ['variant', 'force']), ('apps.tool.status', [])]
run: 0
info schema properties: ['force', 'variant']   <- non-empty WITHOUT the P1 patch
```

## `probe_11_name_collision.py`

CHANGED, CLAIM FALSIFIED — was `jobs=[] exits=[2, 2]` with a loud `Resolution pipeline error`. A collision now keeps the first job and silently drops the second (#32). Qualified names remain the fix.

```
bare name   jobs=['install'] exits=[0, 2]
qualified   jobs=['apps.alpha.install', 'apps.beta.install'] exits=[0, 0]
```

## `probe_12_dual_delivery.py`

unchanged.

```
own CLI (root)               top=['apps', 'builtin']  `apps bifrost start` -> exit=0
guest, group-composed        top=['builtin', 'rise']  `rise apps bifrost start` -> exit=0
guest, NamespaceTransform    top=['apps', 'builtin']  `rise apps bifrost start` -> exit=2
```

## `probe_13_declaration_survival.py`

First transcribed here. `job_detail exposes tags? True` — at `a2f453d` it dropped the declaration; ask 7 has landed.

```
jobs: ['demo.backup']
declaration present: True
  tags: ('scrill:pgops',)
  extra_description: see the pgops skill
  examples: ('func demo backup --to /tmp',)
params: ['to']
job_detail keys: ['category', 'dependencies', 'docstring', 'examples', 'extra_description', 'group', 'inputSchema', 'module_path', 'name', 'parameters', 'python_name', 'requires_tty', 'source_file', 'summary', 'tags', 'uses_live']
job_detail exposes tags? True
inputSchema: {'type': 'object', 'properties': {'to': {'type': 'string', 'default': '/tmp'}}}
```

## `probe_14_scrill_layout.py`

First transcribed here.

```
pg.backup | group: pg
  source_file: /tmp/tmp6lq1rbon/pgops/scripts/jobs.py
  declaration.tags: ('scrill:pgops',)
  derived skill path: /tmp/tmp6lq1rbon/pgops/SKILL.md
  skill exists: True
```

## `probe_15_refusal_guidance.py`

First transcribed here.

```
status: RunStatus.REFUSED
JobResult(status=<RunStatus.REFUSED: 'Refused'>, return_value=None, duration_ms=10.866463009733707, metadata={'resolved_inputs': {}, 'preflight': {'state': 'error', 'reason': "Postgres is not initialised. Read the pgops skill, section 'first run', then run `func pg init`.", 'checks': ['preconditions  test -f /nonexistent-xyz ✗']}, 'skip_reason': "Postgres is not initialised. Read the pgops skill, section 'first run', then run `func pg init`."}, exception=None, job_name='backup')
```

## `probe_16_workflow_gates.py`

First transcribed here.

```
=== declaration ===
  Step  collect
  Gate  triage strategy='ai_outbound' tools=['collect']
  Step  apply-label

=== the schema published at the gate (what an agent is handed) ===
  {'description': 'What the intelligent step must decide.', 'properties': {'severity': {'title': 'Severity', 'type': 'string'}, 'owner': {'title': 'Owner', 'type': 'string'}, 'rationale': {'title': 'Rationale', 'type': 'string'}}, 'required': ['severity', 'owner', 'rationale'], 'title': 'Triage', 'type': 'object'}

=== A: ai_outbound — run the workflow ===
  [collect] ran
  status: RunStatus.BLOCKED
  blocked_on: triage
  workflow_scope: triage_issue-e2740c43
  workflow_status: blocked

=== B: ai_inbound — a registered resolver answers in-process ===
    [ai_inbound] asked for: ['severity', 'owner', 'rationale']
  resolved: severity='high' owner='platform' rationale='stack trace names the router'

=== B2: the ladder — ai_inbound absent, falls through to resolve ===
  resolved: severity='low' owner='unassigned' rationale='no model configured'
```

## `probe_17_gate_fallback.py`

First transcribed here.

```

--- A  ai_outbound, nothing installed: strategy='ai_outbound' ---
   status: RunStatus.BLOCKED
   blocked_on: triage
   workflow_status: blocked

--- B  ai_inbound, nothing installed: strategy='ai_inbound' ---
   status: RunStatus.BLOCKED
   blocked_on: triage
   workflow_status: blocked

--- D  default: strategy=None ---
   status: RunStatus.BLOCKED
   blocked_on: triage
   workflow_status: blocked

--- C: ai_inbound registered but failing (no provider) ---
   status: RunStatus.BLOCKED
   blocked_on: triage

--- E: the 'ai' preset through the imperative path ---
   RAISED ValueError: Unregistered gate strategy 'ai_outbound' referenced in preset 'ai'. Register the strategy before using the preset.

--- F: is 'ai' even accepted as a Gate strategy? ---
   RAISED ValueError: Gate strategy must be one of ['ai_inbound', 'ai_outbound', 'prompt', 'resolve'], got 'ai'
```

## `probe_18_gate_presets.py`

First transcribed here.

```
registered strategies at boot: ['prompt', 'resolve']
registered presets at boot:    []

preset 'ai'      -> severity='high' owner='platform'
preset 'ai_inbound' -> severity='high' owner='platform'
preset 'ai_outbound' -> GateResolutionError: Gate 'g': all 3 strategies failed. Last error: Cannot resolve model Triage from config chain: unresolved field
```

## `probe_19_display_discovery.py`

Unchanged from its first run at `78d9ff4`.

```
is_display_provider(class):    True
isinstance(inst, Protocol):    True
Display.refresh_timeout default: 10.0
Display.display_priority default: 100
should_show(rise project):     True
should_show(plain dir):        False

pre-seeded (as an entry point would): ['RiseProjectDisplay(rise-project)']
after full discovery:                ['RiseProjectDisplay(rise-project)', 'ProjectExtra(rise-risks)']

registered display_ids: ['rise-project', 'rise-risks']
project override applied: False
project's NEW display applied: True
```
