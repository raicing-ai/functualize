# Shared Plugins Across a Monorepo

One plugin file, shared by every app under a common root — and one app opting
into an extra directory the others don't get. No packaging, no entry points.

## Layout

```
shared_plugins/
├── .functualize.toml            root = true  (stops the config walk here)
├── .functualize/
│   └── plugins/
│       └── audit_log.py         ← shared. Nothing declares it.
├── team_plugins/
│   └── timing.py                ← an ordinary directory. Only billing/ names it.
├── billing/
│   ├── .functualize.toml        plugins_directories = ["../team_plugins"]
│   └── jobs/invoice.py
└── shipping/
    ├── .functualize.toml        declares no plugin directories
    └── jobs/dispatch.py
```

## Run it

```bash
cd examples/project/shared_plugins/billing
func invoice
```

```
[timing] armed for functualize
invoiced
[audit] invoice: success
```

Two plugins fired. Now the sibling that opts into nothing:

```bash
cd ../shipping
func dispatch
```

```
dispatched
[audit] dispatch: success
```

One plugin fired. `audit-log` reached both apps; `timing` reached only the app
that asked for it.

## The two mechanisms

**Convention — `.functualize/plugins/` at the project root.** Nothing declares
`audit_log.py`. It is found by walking up from wherever you are to the first
ancestor holding a `.functualize/` directory — the same directory `func builtin
info` reports as `Mode: project`. That is why it works from `billing/`,
`shipping/`, or a directory below either.

**Declared — `plugins_directories`.** `team_plugins/` has no `.functualize/`
wrapper and sits outside any convention path, so the loader would never find it
on its own. `billing/.functualize.toml` names it. The path is relative to *that
file*, not to your shell.

**They compose.** `billing/` gets both. Declaring a directory does not replace
the convention one.

## Precedence, if you need it

`plugins_directories` follows the same chain as `jobs_directories`:

```
CLI  +  ENV  +  File  +  Convention  +  Global  +  Defaults
```

So a directory declared in an ancestor config is inherited by its children,
`root = true` stops that inheritance, and an org-wide directory in
`~/.config/functualize/config.toml` applies to projects that declare none of
their own. Declared directories are scanned before convention ones, and the
first plugin found under a given name wins.

## If nothing loads

A directory you declared that does not exist, or that holds no loadable plugin,
is reported on a normal run:

```
Declared plugin directory does not exist: /srv/team_plugins.
  Check `plugins_directories` in your project config.
```

An absent *convention* directory is silent — most projects have none.

!!! note "Before 0.3.x this did not work"
    `plugins_directories` was documented but never read, and the convention
    directory had to be your exact working directory. If you worked around that
    by running `func` from the parent with `--discovery-depth` raised, you can
    stop.

## Why not package it?

Because you don't have to. A file plugin is the lightest option and it is
per-root: everything under this directory gets it, nothing outside does. To
share across *repositories*, or to version and publish it, package it with an
entry point — see [Hooks vs Plugins](../../../docs/guides/hooks-vs-plugins.md).

A file plugin executes arbitrary Python at boot, at the same trust level as any
local `.py` file. Shared roots are shared trust.

## Related

- [`../monorepo_children/`](../monorepo_children/) — composing *jobs* from child
  projects, the sibling concern to sharing *plugins*
- [`../../plugins/file_based_plugin/`](../../plugins/file_based_plugin/) — a
  single project, convention directory only
- [Plugins guide](../../../docs/guides/plugins.md#file-based-plugins-no-packaging)
