# 09 — Command Surface & Scaffolding

## 1. The tree, in both deliveries

```
rise                              func rise                    (guest)
├── diagnose  [--output ndjson]   ├── diagnose
├── validate  [target]            ├── validate
├── doctor                        ├── doctor
├── new       project | module | variant | substrate | action
├── bootstrap                     ├── bootstrap
├── schema    substrates | actions | export
├── registry  list | status | lock | audit | bootstrap
│   └── <tool>  install | uninstall | run | test | diagnose | validate
├── repos     <name> clone | pull | status | diagnose
├── tools     <name> …
└── builtin   …                   (functualize's, in both — never rise's)
```

Two rules, both from `00`:

- **The tree-walk verbs are top-level**, never `… builtin diagnose`. `builtin`
  is reserved and claiming it aborts CLI construction **[probed]**.
- **`builtin` is inherited whole** in both deliveries — `self update`, `why`,
  `info schema`, `history`, `cache`, `state`, `plugin` — with no rise code.

## 2. Machine-user journey

```console
$ uv tool install risekit          # the standalone bootstrapper
$ rise new project my-project      # scaffolds a FUNC project with rise wired in
$ cd my-project
$ uv sync                          # pulls functualize + risekit

# from here, one command runs everything:
$ func build                       # the project's own job
$ func deploy                      # the project's own job
$ func rise bootstrap              # every declared tool AND repo
$ func rise tools jsonschema install
$ func rise diagnose --output ndjson
$ func rise validate
```

The standalone `rise` stays useful exactly where there is no project yet — a
bare machine, or a checkout you have not set up:

```console
$ rise tools mise install
$ rise repos service clone
$ rise diagnose
```

Config resolution, `.env` loading and upward project discovery are
functualize's, inherited.

## 3. The scaffolded project

```
my-project/
├── pyproject.toml              # depends on functualize + risekit
├── jobs/                       # the project's OWN jobs — func runs these
├── config.base.toml            # [risekit] module_packages, namespace; tool + repo lists
├── .risekit/lock/              # per-tool, per-repo lockfiles
├── .functualize/               # functualize's state ledger
├── contracts/                  # exported JSON Schemas (05 §5) — optional, committed
└── src/my_project/
    ├── main.py                 # a FUNC app: the project's jobs + the rise plugin
    └── modules/
        ├── src.py              # class Src(Nothing): build/test/lint/dev
        ├── deploy.py           # class Deploy(Process, Controllable, Loggable)
        └── repos.py            # class ServiceRepo(Repository, Syncable)
```

No `extensions.toml`: module discovery is `[risekit] module_packages`
(`03` §6), and there is no second file to keep in sync. `rise new project`
into an existing directory adds only those paths, never rewriting an existing
file (criterion 51), with a dry-run diff by default on a non-empty target.

## 4. Scaffolding is rise's

`_cli/scaffold/registry.py:22` is a hard-coded dict with no registration hook,
so `builtin scaffold` cannot learn rise templates — and `builtin` is reserved
anyway. rise ships `rise new`:

| Command | Emits |
|---|---|
| `rise new project <name>` | the layout above |
| `rise new module <substrate> <name>` | a class skeleton: correct bases, abstract methods stubbed with `raise NotImplementedError("TODO")`, required tags with placeholders |
| `rise new variant <tool> <strategy>` | a variant subclass with `variant` set |
| `rise new substrate <name>` | a project-local `Substrate` subclass (`10` §2) |
| `rise new action <name>` | a project-local `Protocol` (`10` §3) |

~200 lines over `string.Template` — no new dependency; templates are data files
in the wheel.

**Why the skeletons converge (criterion 67).** A scaffolded class is
deliberately *invalid until edited*: the stubs raise, so the class binds and
`rise validate` reports each TODO as a finding. Generate → validate → fix has a
real gradient. A scaffold emitting `pass` bodies would validate green while
doing nothing — the failure the criterion exists to prevent.

## 5. Skills

functualize ships agent skills inside its wheel (`_cli/skills.py`) and locates
them with `builtin skills`. That command is functualize-owned and will never
list rise's; what transfers is the **pattern** — a `force-include`d directory,
version-stamped on materialization, so a skill can never describe a release
other than the one installed.

risekit ships `risekit/_skills/` with one skill per persona (machine user,
project member, framework maintainer) plus the strategy reference tables
(criterion 64), exposed as `rise skills path | list | materialize`.

## 6. Surface rules carried over

| Intent rule | Realization |
|---|---|
| namespaced families, discoverable (54) | group hierarchy from the class `group`; `output` sub-groups |
| human-readable description | method docstrings become help text **[probed]** |
| fixed-size listing (33) | tools are groups; variants are `--variant` |
| default operation self-explains (53) | bare `rise` prints the curated tree |
| silent machinery, verbose outcomes | `rc.log` for humans; `Stdout.emit` + `--output` for machines |
| idempotent by default (36) | status guards (`08` §1) |

Criterion 54 names *colon* namespacing; rise uses space-separated groups. A
spelling change, not a semantic change — `12` scores it **reduced** rather
than quietly met.

## 7. Personas

| rise persona | functualize role | Touches |
|---|---|---|
| project member | job author | module classes |
| registry author | package author | variant subclasses via `risekit.modules` |
| framework maintainer | app constructor | risekit: substrates, adapter, generator |

Maintainer changes ship as risekit releases; users consume them with
`rise builtin self update` — inherited, not written (`00` §1). Project files
are never rewritten by an upgrade, because the project owns everything under
`src/` and `config.base.toml`.
