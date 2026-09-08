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

## Probes 13–18

Not transcribed. The probes are runnable (`evidence/probe_13..18`) and their
findings are cited from `15` and `16`, but their raw output was never captured
here. Gap recorded 2026-09-08.

## `probe_19_display_discovery.py`

Run against functualize at `78d9ff4` (v0.2.3-2), 2026-09-08.

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

`ProjectOverride` — same `display_id` as the installed provider, better
`display_priority` (10 vs 30) — never reaches the slot. `ProjectExtra`, with a
distinct id, does. Entry points register first (`display_provider_discovery.py:51-55`)
and every later path skips an id already registered (`:160-161`, `:208`), so a
project cannot replace an installed display, only add to it. See `18` §5.

---

## Re-run at `787035e` — 2026-09-08

Five probes re-executed when this shape intent landed on `spec/subject-modeling`,
cut from `787035e` (#30, "discovery correctness, job parameter types"). Full
analysis in `README.md`.

### `probe_01_jobsources.py` — CHANGED (upstream fix)

```
A. static_wiring fast path taken: False
A. registered jobs: ['start', 'status']
A. execute: JobNotFoundError Job 'apps.bifrost.status' is not registered
B. registered jobs after add_job_provider: []
B. execute: JobNotFoundError Job 'apps.bifrost.status' is not registered
C. job_providers references in the package: 11
```

`A. registered jobs` was `[]` at `a2f453d`. Declared `job_providers` are now
honoured (ask 2, landed). The remaining `JobNotFoundError` is group composition
— jobs register under bare names — not the drop.

### `probe_02_prefilter.py` — unchanged

```
discovered: [('hello', None)]
bifrost.py   should_import: False
plain.py     should_import: True
```

### `probe_10_plugin_binding.py` — unchanged

```
registered: [('apps.tool.install', ['variant', 'force']), ('apps.tool.status', [])]
run: 0
info schema properties: ['force', 'variant']   <- non-empty WITHOUT the P1 patch
```

The binding design's load-bearing claim (`03` §1) still holds.

### `probe_11_name_collision.py` — CHANGED (claim falsified)

```
bare name   jobs=['install'] exits=[0, 2]
qualified   jobs=['apps.alpha.install', 'apps.beta.install'] exits=[0, 0]
```

Was `jobs=[] exits=[2, 2]` with a loud `Resolution pipeline error`. A bare-name
collision now keeps the first job and silently drops the second — defect #32.
"Duplicate bare names are fatal" is false; qualified names remain the fix.

### `probe_19_display_discovery.py` — unchanged

```
project override applied: False
project's NEW display applied: True
```

