# Contracts — tasks-local substrate example

No public API is added, removed or changed. The example consumes existing
public surface only:

| Symbol | From | Used as |
|---|---|---|
| `FunctualizeApp(name)` | `functualize.app` | boots the app in the current directory |
| `FunctualizeApp.substrate` | `functualize.app` | the storage boot selected |
| `LocalTaskProvider(substrate_source, key="tasks")` | `functualize_tasks_local` | the provider `LocalTasksPlugin` registers |
| `TaskStatus` | `functualize_tasks` | status filter and update |

## Example command line

```text
python todo_local.py add TITLE        # add a pending task, print the list
python todo_local.py done TITLE-PART  # mark pending tasks whose title contains it done, print the list
python todo_local.py list             # print the list (also the default)
```

Each printed line is `[<status>] <title>`, in insertion order. Any other
command prints a usage line to stderr and exits 2.

## Storage observed

One substrate key, `tasks`, holding `{"tasks": {<id>: {<fields>}}}`. In a
project with `.functualize/`, the default substrate writes
`.functualize/tasks.json` (and its `tasks.json.lock`).
