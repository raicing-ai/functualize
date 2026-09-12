# Hosting Functualize

This guide is for the case where **your** distribution is the thing the user
installed, and functualize is inside it. `CliAdapter` already mounts the whole
`builtin` subtree into your CLI, so your users get `yourapp builtin self
update`, `yourapp builtin skills list`, and the rest — commands that have to
name *your* package, not functualize.

Three seams make that work.

---

## Knowing how you were installed

`functualize.app.packaging` answers two questions about the running program,
and they are answered together because acting on one without the other is how a
command ends up naming the wrong tool:

```python
from functualize.app import packaging

detection = packaging.detect_from_process()

print(detection.mode)                  # tool_uv
print(detection.owning_distribution)   # yourapp  — not "functualize"
print(detection.degraded)              # False
```

`InstallMode` is a `StrEnum`, so it prints and serializes as the bare value
(`tool_uv`) rather than as `InstallMode.TOOL_UV` — the same spelling the
`FUNCTUALIZE_RUNTIME` override variable and the JSON output use.

`mode` is one of `standalone`, `tool_uv`, `tool_pipx`, `project`, `tool_pip`,
or `unknown`. `owning_distribution` is whichever distribution provides the
console script that is running — which is why an application built on
functualize upgrades *itself* rather than the framework underneath it.

### Degraded is a real answer

`owning_distribution` is `None` when `argv[0]` maps to no installed
distribution: a `python -m` invocation, a renamed script, a source checkout run
in place. Combined with the two unmanaged modes, that is what `degraded` means.

Guessing here is the failure the whole module exists to prevent — a wrong guess
prints commands that do not exist and runs updaters against binaries they do
not own. So check it and refuse:

```python
if detection.degraded:
    raise SystemExit(
        f"Cannot upgrade: {detection.mode.value} installations are not "
        f"self-managing. Use whatever put this interpreter here."
    )
```

### Asking what would change it

Given a **non-degraded** detection, the same module plans the command. Check
first — a degraded one raises `ValueError` here rather than producing a command:

```python
if not detection.degraded:
    commands = packaging.update_commands(detection, "/usr/local/bin/yourapp")
    # (("/home/you/.local/bin/uv", "tool", "upgrade", "yourapp"),)

    packaging.install_commands(detection, "requests")
    packaging.uninstall_commands(detection, "requests")
```

Each returns a tuple of argv tuples, in the order they must run.

**Planning never executes.** Nothing in `functualize.app.packaging` prints,
prompts, or spawns a process — it returns commands or raises. Deciding whether
to run them, showing them to the user, and running them stay in the CLI layer,
which is what makes this module safe to call from a host that has no terminal.

Three exceptions tell you a command cannot be planned:

| Exception | Means |
|---|---|
| `MissingToolError` | The mode's package manager is not installed |
| `LossyReceiptError` | A `uv` receipt carries something this version cannot reproduce faithfully |
| `StandaloneUpdateError` | A standalone binary is a file, not a package — updating it is not a subprocess |

`ValueError` is the backstop for a degraded mode, so forgetting the
`detection.degraded` check fails loudly rather than producing a command.

---

## Shipping your own agent skills

Functualize ships [Agent Skills](https://agent-skills.io) inside its own
distribution, so what an agent reads is pinned to the version installed rather
than whatever the main branch says today. Your distribution can ship its own
the same way, through an entry point:

```toml title="pyproject.toml"
[project.entry-points."functualize.skills"]
yourapp = "yourapp._skills"
```

The value is an importable package whose directory holds skill directories —
the same shape as functualize's own. Resolution goes through
`importlib.resources`, so the package may be zipped and need not copy
functualize's layout.

Every `builtin skills` command then reports yours alongside core's:

```bash
yourapp builtin skills list
yourapp builtin skills path
yourapp builtin skills materialize
```

### Each source keeps its own version

A skill read from your directory describes **your** release. That guarantee is
the reason the stamp is per source rather than shared:

```console
$ yourapp builtin skills materialize
  functualize
1 skill(s) → ~/.local/share/functualize/skills/func-0.1.0
  yourapp-deploy
1 skill(s) → ~/.local/share/functualize/skills/yourapp-2.4.0
```

Core keeps the `func-<version>` stem because existing agent configurations
already point at it. Yours is stamped `yourapp-<your version>`, read from your
own distribution metadata — so two hosts shipping a skill of the same name land
in different trees, and `--prune` only ever deletes other versions of the
distribution it was asked about.

!!! warning "`skills path` prints one line per location"

    It used to print exactly one path, so it could be substituted:
    `npx skills add "$(yourapp builtin skills path)"`. With more than one
    hosting distribution a single path could only ever be core's, so it now
    prints one directory per line and the substitution is wrong — it passes a
    multi-line string as one argument. Loop instead:

    ```bash
    yourapp builtin skills path | while read -r dir; do
      npx skills add "$dir"
    done
    ```

### A broken entry point is skipped, never fatal

This resolution runs on the way to `yourapp --help`. One third-party package
with a missing module or a bad path earns a warning on stderr and is skipped —
it cannot take the CLI down with it.

---

## Declaring a skill from a single-file script

A script that belongs to a skill can say so in the metadata block it already
carries:

```python title="deploy.py"
#!/usr/bin/env -S func
# /// script
# dependencies = ["httpx"]
#
# [tool.functualize]
# job = "deploy"
# skill = "yourapp-deploy"
# ///
```

`job` names the function the file runs; see
[Usage Modes](modes.md#single-file-mode). `skill` names the skill the script
belongs to.

!!! note "`skill` is parsed, not yet consumed"

    It is recognised and validated — declaring it no longer earns an "unknown
    key" warning — and it is exposed on `ScriptMetadata.skill`. Nothing reads
    it yet. It ships ahead of a consumer so the file format can settle before
    anything depends on it; write it if you want your scripts ready, but do not
    expect behaviour from it.

Any *other* key under `[tool.functualize]` warns rather than failing. A newer
functualize may add keys, and refusing to run a script because of a field this
version has not heard of would be worse than the typo the warning protects
against — but silence would be worse still, because that is how a misspelled
setting looks exactly like a setting with no effect.

---

## Where your users' runtime state lives

Your distribution inherits functualize's default: a `.functualize/` directory in
whatever project the user is standing in, holding the freshness ledger, the run
log, and — the part that matters — **workflow scope records**, which are what a
paused `@workflow` is resumed from.

Fingerprints and run history are derived. Losing them costs a rebuild and some
`builtin history` output. A scope record is not derived: it holds the values a
human deposited at a gate, so losing one spends somebody's approval on a run
that no longer exists.

So the question to answer before you ship is **whether the filesystem your users
run on outlives the process**. If your distribution runs on a laptop or a
long-lived build machine, the default is correct and you need do nothing. If it
runs somewhere ephemeral or horizontally scaled — serverless, a rescheduled
container, several workers behind a load balancer — then a paused workflow
cannot be resumed without a durable store, because the process asked to resume
it never had the record.

Two things to do about it:

1. **Depend on a substrate plugin** and let it be installed alongside you:

   ```toml
   dependencies = ["functualize", "functualize-state-sqlite"]
   ```

   Then point it somewhere shared, in your own config defaults:

   ```toml
   [plugin.sqlite-state]
   db_path = "/var/lib/yourapp/state.db"
   ```

2. **Tell your users where it went.** `yourapp builtin data show` reports the
   location of every runtime document, and it is the first command to run when
   a resume reports "No workflow scope".

If your jobs never declare a `@workflow` with a `Gate`, none of this applies:
everything else in the store is recomputable and a fresh container simply does
the work again.

See [Workflows → Where a paused workflow actually lives](workflows.md) for the
failure modes in detail and for writing a substrate against another backend.

---

## Related

- **[Jobs and Auto-Discovery](jobs-discovery.md)** — supplying your own pre-import filter when the `require_*` settings cannot describe your jobs
- **[Usage Modes](modes.md)** — library mode, where you own the CLI entry point
- **[Plugins](plugins.md)** — the entry-point group for adapters, providers and transforms
- **[MCP Adapter](mcp.md)** — how an agent reads your job catalog
