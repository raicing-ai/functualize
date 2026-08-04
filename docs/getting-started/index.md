# Getting Started

Functualize is a Python framework for building structured, discoverable job pipelines. You write job functions — functualize handles discovery, configuration, execution, and delivery.

This section takes you from zero to running jobs in minutes, then shows how to scale up to full production projects.

## Choose your starting point

<div class="grid cards" markdown>

-   :material-file-code:{ .lg .middle } **Just run a script**

    ---

    Write a function, run it with `func`. No project setup needed.

    ```bash
    func jobs.py deploy
    ```

    [:octicons-arrow-right-24: Quickstart — Single File](quickstart.md#mode-1-single-file-script)

-   :material-folder-multiple:{ .lg .middle } **Multi-job project**

    ---

    Drop job files in a `jobs/` directory. Auto-discovery handles the rest.

    ```bash
    func deploy
    ```

    [:octicons-arrow-right-24: Quickstart — Directory Mode](quickstart.md#mode-2-project-directory-with-auto-discovery)

-   :material-rocket-launch:{ .lg .middle } **Full framework project**

    ---

    Scaffold a complete project with config, plugins, and a named CLI.

    ```bash
    func builtin scaffold init my-app
    ```

    [:octicons-arrow-right-24: Quickstart — Full Project](quickstart.md#mode-3-full-functualizeapp-project)

</div>

## Recommended path

1. **[Installation](installation.md)** — Install functualize and the `func` CLI
2. **[Quickstart](quickstart.md)** — Run your first job, then graduate to projects
3. **[Project Structure](project-structure.md)** — Understand the layout, imports, and presets

## What you need

- Python 3.11+
- `pip install "functualize[cli]"` or `uv add functualize` (add `[cli]` extras when you need the CLI)

That's it. No configuration files, no project structure — you can start with a single `.py` file.

## After the basics

Once you're running jobs, explore the [Guides](../guides/index.md) for:

- [Configuration](../guides/configuration.md) — Layered config with presets (`classic`, `twelve_factor`, `env_only`)
- [Jobs & Discovery](../guides/jobs-discovery.md) — How auto-discovery works
- [Plugins](../guides/plugins.md) — Extending functualize with custom providers
- [Architecture](../guides/architecture.md) — How the framework is structured internally
