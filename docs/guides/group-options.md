# Group Options

A **group option** is a flag declared once by a job group and available to
every job beneath it. `func deploy --env prod web run` sets `--env` for
`deploy.web.run` without that job — or any of its siblings — declaring the flag
itself.

This is the shape every multi-level CLI converges on (`docker --context`,
`kubectl --namespace`, `gh --repo`): the flags that describe *where* or *how* a
whole family of commands runs belong to the family, not repeated on each
member.

## Declaring a group's options

Subclass `GroupOptions` and bind it to a group path:

```python title="jobs/_group.py"
from typing import Annotated

from functualize.job import GroupOptions, Option


class DeployOptions(GroupOptions, group="deploy"):
    """Deploy-level flags."""

    env: Annotated[str, Option("-e", help="Target environment")] = "staging"
    dry_run: Annotated[bool, Option(help="Preview only")] = False
```

It is an ordinary Pydantic model: types, defaults, `Field()` constraints and
`Option()` markers all work exactly as they do on a job's own config model.

The declaration is discovered by the same scan that finds your jobs. A module
that contains **only** a declaration is fine, and so is an underscore-prefixed
filename — `jobs/_group.py` is the conventional home, next to the jobs it
covers.

!!! warning "One declaration per group path"
    Two classes bound to `group="deploy"` is an error at discovery time, not a
    last-one-wins. Importing a declaration into another module is *not* a
    second declaration — only the module that defines the class counts.

## Receiving the values

Declare the class as a parameter on any job under that group:

```python title="jobs/web.py"
from _group import DeployOptions

JOB_GROUP = "deploy.web"


def run(image: str = "nginx", opts: DeployOptions = None) -> str:
    """Deploy the web tier."""
    print(f"Deploying {image} to {opts.env} (dry run: {opts.dry_run})")
    return image
```

The engine constructs and injects `opts` on every run, so it is never `None` in
practice — the default exists only so the function stays callable as plain
Python. A job that does not care about the group's options simply does not
declare the parameter.

A `GroupOptions` parameter is **not** the job's own config model. Its fields
stay group-level flags and do not become options on the job itself, so
`func deploy web run --help` lists only `--image`.

## Where the flags go on the command line

**Before** the group segment they belong to, and before the job name:

```console
$ func deploy --env prod web run          # ✅ --env belongs to `deploy`
$ func deploy web run --image custom      # ✅ --image belongs to the job
$ func deploy --env prod web run --image custom   # ✅ both
```

Position is what tells the two apart. A flag typed **after** the job name binds
to the job, even when a group declares the same name — the same rule
`docker`, `kubectl` and `gh` use. That is why the group's flag must come first:

```console
$ func deploy web run --env dev           # ❌ `run` has no --env
```

Options are **inherited down the path**. A flag declared on `deploy` may be
given at any point before its command is reached, and a nested group may
declare a field of the same name to override its parent's for jobs beneath it.

Anything else mid-path is still an error, with the same message as before:

```console
$ func deploy --nope x web run
Error: unknown option '--nope' before a command.
```

## Discovering them

A group's listing documents its options, including the inherited ones:

```console
$ func deploy
Usage: func deploy <command> [options]

Options:
  --env, -e TEXT           Target environment
  --dry-run, --no-dry-run  Preview only

Sub-groups:
  web

$ func deploy web          # inherited from `deploy`, and listed as such
Usage: func deploy web <command> [options]

Options:
  --env, -e TEXT           Target environment
  --dry-run, --no-dry-run  Preview only

Commands:
  run  Deploy the web tier.
```

`func deploy --help` prints the same listing.

## Where the values come from

Each field resolves through the usual ladder, with the **group path** standing
in for the job name:

| Precedence | Source | Example |
|---|---|---|
| 1 (highest) | Runtime override | `rc.config.set("env", "prod")` |
| 2 | The flag on the command line | `func deploy --env prod …` |
| 3 | Environment variable | `DEPLOY__ENV=prod` |
| 4 | Config file section | `[deploy]` → `env = "prod"` |
| 5 (lowest) | The field's declared default | `env: str = "staging"` |

`config.set()` deposits an **override**: a value written during the run, which is where that run will then find it — above everything a source supplied, the command line included.

A dotted group path flattens for the environment variable and stays dotted for
the config section: `group="deploy.web"` reads `DEPLOY_WEB__ENV` and
`[deploy.web]`.

A flag beats the environment, matching how a job's own flag does — an exported
default you cannot override from the command line would defeat the point of
typing it.

None of this depends on the CLI. A job run from Python resolves the same
file, environment and default layers:

```python
app.execute("deploy.web.run")           # opts.env comes from file/env/default
rc.invoke("deploy.web.run")             # same
```

The **mid-path flag layer is the one exception**, and it behaves the way its
name suggests: it belongs to the command line that typed it.

```python
# The facade accepts one explicitly — this is how the CLI and MCP pass on the
# flags they parsed.
app.execute("deploy.web.run", group_option_values={"env": "prod"})

# `rc.invoke` starts no command line, so it passes none. A job invoked from
# inside another job resolves its group options from its own file, environment
# and default layers — never from the flags typed at the parent.
rc.invoke("deploy.web.run")
```

A `@workflow` step behaves the same as `rc.invoke` here: the walk runs each step
as an ordinary job with no flag layer, so a step's group options come from
file, environment and defaults.

This is not a gap to route around. A flag is typed at one path, and a job the
run happens to invoke afterwards sits at a path of its own — inheriting the
parent's flags would mean a value typed for `deploy.web` silently steering a job
under `deploy.worker`. Set the value where the child reads it (its section, or
its environment variable) when it should apply to both.

## Two groups, one field

A job may declare more than one `GroupOptions` parameter — its group's and an
ancestor's. When both declare a field of the same name and the user sets it
once on the command line, **both instances see that value**: the merge is flat,
so there is no way for two objects to disagree about a flag typed once.

Their non-CLI layers stay independent, since each class reads its own config
section and environment prefix.

## Over MCP

Group options appear in a job's MCP tool schema alongside its own parameters,
with their descriptions and defaults, so an agent can set them exactly as a
shell user can. They are never marked `required` — they always resolve to
something. If a job declares a parameter with the same name as one of its
group's fields, the job's own wins, the same way position decides on the
command line.

## See also

- [Jobs and Auto-Discovery](jobs-discovery.md) — how `JOB_GROUP` forms a group
- [JobConfig with Pydantic](job-config.md) — the job's own config model
- [Configuration System](configuration.md) — the resolution chain in full
