# Installation

## Requirements

Functualize requires **Python 3.11** or higher.

```bash
python --version
# Python 3.11.x or higher
```

## Install Functualize

=== "CLI (uv, recommended)"

    ```bash
    uv tool install "functualize[cli]"
    ```

=== "CLI (pip)"

    ```bash
    pip install "functualize[cli]"
    ```

=== "Library only (uv)"

    ```bash
    uv add functualize
    ```

=== "Library only (pip)"

    ```bash
    pip install functualize
    ```

=== "Standalone binary (no Python)"

    ```bash
    curl -LsSf https://raw.githubusercontent.com/raicing-ai/functualize/master/install.sh | sh
    ```

    Windows:

    ```powershell
    irm https://raw.githubusercontent.com/raicing-ai/functualize/master/install.ps1 | iex
    ```

Use the **CLI** variants to get the `func` command and TUI (includes Click, Rich, Textual). Use the **Library only** variants when embedding functualize in a project that doesn't need the CLI — the core engine has zero CLI dependencies at runtime.

## The standalone binary

A single executable with Python and every first-party plugin already inside it. **It has no
prerequisites at all** — not even Python — and its first run needs no network, because the
distribution is baked into the binary rather than downloaded on first launch.

Reach for it when you are on a machine where installing Python is not your call: a CI image,
a container, a locked-down server, someone else's laptop. If you already have Python, the
`uv tool install` route above is smaller and updates faster.

### Manual download

The install script only automates this; nothing stops you doing it yourself.

```bash
# Pick the archive matching your platform, from the latest release:
#   functualize-x86_64-unknown-linux-gnu.tar.gz
#   functualize-aarch64-unknown-linux-gnu.tar.gz
#   functualize-x86_64-unknown-linux-musl.tar.gz     <- Alpine, distroless
#   functualize-aarch64-unknown-linux-musl.tar.gz
#   functualize-x86_64-apple-darwin.tar.gz
#   functualize-aarch64-apple-darwin.tar.gz
#   functualize-x86_64-pc-windows-msvc.zip
tar -xzf functualize-x86_64-unknown-linux-gnu.tar.gz
chmod +x func
./func builtin version
```

Every release also publishes `SHA256SUMS` covering all of them. Verify before you run it:

```bash
sha256sum -c SHA256SUMS --ignore-missing
```

**On Alpine or a distroless image, take the `musl` archive.** The install script works this
out by looking at which dynamic loader is present, not at the distribution name — a
Debian-derived image can ship musl, and a distribution the script has never heard of can
ship glibc.

### Managing a standalone install

```bash
func builtin self doctor    # how was this installed, and is anything wrong with it?
func builtin self update    # fetch the newer release and replace this binary
func builtin self install <package>   # add a dependency your jobs import
func builtin plugin list    # what extends this installation
```

`self update` on a standalone binary does not call a package manager — there is none. It
reads the release source baked into the binary, asks that repository for its latest
release, and shows you what it will do before doing it:

```
This will replace:
  /usr/local/bin/func
  0.2.1 -> 0.3.0
  from https://github.com/.../functualize-x86_64-unknown-linux-gnu.tar.gz
  verified against https://github.com/.../SHA256SUMS
Proceed? [y/N]
```

The archive is checked against `SHA256SUMS` **before it is unpacked**, and an archive the
checksums file does not mention is refused exactly like one that fails to match. The new
executable is written beside the old one and moved into place, so an interrupted update
leaves you with one working binary or the other, never a truncated file.

Packages you added with `self install` are reinstalled into the new distribution once the
swap is done. They do not carry over on their own: a new binary unpacks a new environment
at a new path, and the old one is simply no longer consulted.

!!! note "A binary somebody else built"

    If you built your own PyApp binary over functualize, `self update` refuses and exits
    `3` rather than offering functualize's own release. Bake a `standalone-release.json`
    into your distribution root — `{"repo": ..., "asset_prefix": ..., "target": ...}` — and
    it will follow your releases instead.

!!! note "`self uv` is not available on a standalone install"

    The baked distribution ships pip, not uv, so `self install` uses the bundled
    interpreter's own pip. `self python -- ...` is the escape hatch that works everywhere.

On the package-manager install methods, `self update` prints the exact command it will run
before running it, and restores packages you added — including ones installed through the
`self python` / `self uv` escape hatch, which it never recorded.

!!! note "Install method decides whether self-update works"

    `func builtin self update` only manages installations functualize itself placed: the
    standalone binary, a `uv tool` install, a `pipx` install, or a project checkout. A bare
    `pip install` into a system interpreter is **not** self-managing — `self update` prints
    guidance, changes nothing, and exits `3`. `func builtin self doctor` tells you which
    kind you have.

!!! tip "Minimal install for serverless/library use"

    If you're embedding functualize in a Lambda, HTTP service, or library (no CLI needed), install the bare package:

    ```bash
    pip install functualize  # core only — no CLI deps
    ```

    The core engine (`functualize.app`, `functualize.job`) has zero CLI dependencies at runtime — Click, Rich, and Textual are only imported when you install `[cli]` and use the `func` CLI or inline TUI.

## Verify Installation

```bash
func --version
```

## What's Installed

| Command | Purpose |
|---------|---------|
| `func` | The primary CLI — run jobs, scaffold projects, manage cache |
| `functualize` | Alias for `func` (same entry point) |

## Next Steps

Head to the [Quickstart](quickstart.md) to run your first job — no project setup required.
