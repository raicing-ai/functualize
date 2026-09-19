# File-Based Plugin — Zero Packaging

The lightest way to extend functualize: a single `.py` file in `.functualize/plugins/`. No package, no entry points — the plugin loader scans the convention directory at boot.

## Source

[`examples/plugins/file_based_plugin/`](https://github.com/raicing-ai/functualize/tree/master/examples/plugins/file_based_plugin)

## Running

```bash
cd examples/plugins/file_based_plugin

# The loader discovers .functualize/plugins/run_notifier.py at boot;
# the plugin announces the job's success on the event bus
func greet
```

## How it works

1. At boot, the composition root resolves plugin directories once, before plugins load: every `[tool.functualize] plugins_directories` declared up the config walk (with `root = true` and the XDG global layer honoured, same as `jobs_directories`), **plus** the convention directory `.functualize/plugins/` at the project root — the directory `func builtin info` reports as `Mode: project`, found by walking up rather than by matching the CWD exactly. Declared directories are scanned first.
2. Each top-level non-underscore `.py` file is imported; the loader looks for a module-level `plugin` object with `name`, `version`, and `description` string attributes that is callable.
3. The loader invokes `plugin(app)` — the registration hook for subscribing to events, registering commands, or adding providers.

Entry-point plugins win on name collisions; file plugins participate in the same dependency ordering and config resolution as packaged plugins.

## When to graduate

File plugins are per-project. To share across projects or publish, package with an entry point — see [Custom Adapter](custom-adapter.md) and [Custom State Backend](custom-state-backend.md), or run `func builtin scaffold add plugin`.
