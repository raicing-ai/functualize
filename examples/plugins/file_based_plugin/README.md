# File-Based Plugin — Zero Packaging

The lightest way to extend functualize: a single `.py` file in `.functualize/plugins/`. No package, no `pyproject.toml`, no entry points — the plugin loader scans the convention directory at boot.

## Directory Structure

```
file_based_plugin/
├── README.md
├── .functualize.toml          ← Points the scan at jobs/ (no pyproject.toml)
├── .functualize/
│   └── plugins/
│       └── run_notifier.py    ← The plugin (module-level `plugin` object)
├── jobs/
│   └── hello.py               ← A job to watch the plugin react to
└── tests/
    └── test_file_plugin.py  ← Below the scan depth, so it publishes no commands
```

## Usage

```bash
cd examples/plugins/file_based_plugin

# Run the job — at boot the loader discovers run_notifier.py and the
# plugin announces the job's success on the event bus
func greet
```

## How it works

1. At boot, the loader resolves plugin directories: `[tool.functualize].plugins_directories` if configured, else the convention directory `.functualize/plugins/` in the CWD.
2. Each top-level non-underscore `.py` file is imported; the loader looks for a module-level `plugin` object (or any object) with `name`, `version`, `description` string attributes that is callable.
3. The loader invokes `plugin(app)` — the registration hook where you subscribe to events, register commands, or add providers.

Entry-point plugins win on name collisions, and file plugins participate in the same dependency ordering and config resolution as packaged plugins.

## When to graduate to a packaged plugin

File plugins are per-project. To share a plugin across projects or publish it, package it with an entry point — see [`custom_adapter/`](../custom_adapter/) and [`custom_state_backend/`](../custom_state_backend/), or scaffold one with `func builtin scaffold add plugin`.

## Related Documentation

- [Plugin development guide](../../../contributor/guides/plugin-development.md)
- [Plugins guide](../../../docs/guides/plugins.md)
