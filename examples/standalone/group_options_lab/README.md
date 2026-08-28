# group_options_lab

Flags that belong to a **group**, not a job.

```
glab deploy --env prod web --region eu-west-1 run v1.2
       │      │        │     │                 │   │
       │      │        │     │                 │   └── the job's own positional
       │      │        │     │                 └────── the job
       │      │        │     └──────────────────────── deeper group's flag
       │      │        └────────────────────────────── deeper group
       │      └─────────────────────────────────────── outer group's flag
       └────────────────────────────────────────────── outer group
```

`run` never declares `env` or `region`. It asks for the options classes and the
engine hands them over, filled from each group's own resolved layer. The
substitution is the whole idea: a group option reads the **group path** as its
config section and env prefix, where a job option would read the job name.

## Layout

| File | Why it looks like this |
|---|---|
| `jobs/_options.py` | Two `GroupOptions` subclasses, at `deploy` and `deploy.web`. Underscore-prefixed because it holds no jobs — the scan still reads it for group declarations. |
| `jobs/web.py` | `deploy.web.run` — sits under **both** levels. `image` is positional and required; `replicas` is named. Both spellings, one job. |
| `jobs/worker.py` | `deploy.worker.run` — under `deploy` only. `--env` reaches it, `--region` does not. |
| `jobs/status.py` | Ungrouped, no options. **The control.** Nothing in this example is allowed to change how it renders. |
| `config.base.toml` | `[deploy]` and `[deploy.web]` — sections keyed by group path. |

## Every invocation, and what it proves

Run from this directory. `func` and `glab` are interchangeable here — including
for the mid-path flags, which reach an app's own click tree as well as the
`func` dispatcher (ADR-009 decision 11). `.functualize.toml` exists so plain
`func` works without installing the script.

| Invocation | What to look at |
|---|---|
| `func deploy web run v1.2` | The baseline. No group flags; both groups still resolve from the config file. |
| `func deploy --env prod web run v1.2` | A mid-path flag beats the file. `env = prod`. |
| `func deploy --env prod web --region eu-west-1 run v1.2` | **Two levels at once.** Each flag is claimed by the group that declared it. |
| `func deploy --dry-run web run v1` | A bool presence flag must **not** eat `web`. If it did, the path would break rather than the flag. |
| `func deploy web run v1 --env prod` | Must **error**. `--env` belongs to `deploy` and does not become a job flag by being written after the job. |
| `func deploy --region eu-west-1 worker run` | Must **error at the group**. `worker` does not inherit `deploy.web`'s flags. |
| `func status --verbose` | The control. Byte-identical output whether or not any of the above exists. |
| `func deploy web run --image v1.2` | Must **error**. `image` is declared `Arg()`, so it is a click *argument* — `--image` is not a spelling of it. The shell greys the line out rather than letting it reach a click error unannounced. |
| `glab deploy --env prod web run v1.2` | The same line through the app's **own** script. It went to `No such option '--env'` until ADR-009 decision 11; the two entry points are one surface now, and `tests/group_options/test_adapter_entry_point_parity.py` keeps them that way. |

In the interactive shell (`func` with no arguments at a TTY), each of these is
also the **canonical SmartBar text** for its command — which is the property the
TUI has to preserve. Type one, edit a field in the config table, and the bar
must come back reading the same thing.

## Two sharp edges, documented rather than fixed

**Shortcuts saved before this example existed may be broken.** A shortcut is a
generated `.py` file calling `invoke("<name>", …)`. Anything that saved a
*group* name there — `invoke("deploy", …)` — fails loudly when run, because a
group is not invocable. There is no migration and none is planned; the failure
is the correct one.

**The same field name at two levels, with different types, is pathological.**
If `deploy` declares `flag: str` and `deploy.web` declares `flag: bool`, then
where the flag is written changes how the line tokenizes — a bool presence flag
consumes no following token, a string does. The CLI has always behaved this
way; nothing here makes it worse, and nothing here tries to make it better.
Declare a name once.

## Secrets

`DeployOptions.token` is declared `Secret[str]`. A group option is a config
field like any other, so it is a credential like any other: it masks in the
job's log line above, and it must mask in every panel that renders it. The
detection follows the declaration, never the name — see
`examples/standalone/secrets_lab/` for that story on its own.

One consequence worth knowing: a secret's default is **not** written to the
cache, so a surface that omits a value "because it equals the default" cannot
make that comparison for a secret field. It renders the flag explicitly
instead.
