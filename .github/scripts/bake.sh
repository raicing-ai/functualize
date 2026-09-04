#!/bin/sh
# Bake a relocatable Python distribution with functualize[all] installed into it.
#
# POSIX `sh`, not bash: this runs directly on the GitHub runner for the gnu,
# macOS and Windows targets, and *inside an Alpine container* for the musl ones,
# where bash does not exist.
#
# The artifact is a **python-build-standalone installation**, not a virtual
# environment. A venv's `bin/python` is a symlink to the interpreter it was
# created from and its stdlib lives in that interpreter's prefix, so a venv
# tarred up and unpacked on another machine has no Python in it at all. That is
# not a subtle failure: the binary built over one dies on first launch with
# `project execution failed / No such file or directory (os error 2)`, which is
# what shipped as v0.2.1's seven failed targets.
set -eu

: "${PYTHON_VERSION:?PYTHON_VERSION must be set}"
: "${TARGET:?TARGET must be set}"

# Inside the musl container there is no uv: the runner's copy is a glibc binary
# and cannot execute here. Bootstrapping is cheap and keeps the two paths
# running the same script rather than two drifting copies.
if ! command -v uv >/dev/null 2>&1; then
    apk add --no-cache curl ca-certificates >/dev/null
    curl -LsSf https://astral.sh/uv/install.sh -o /tmp/uv-install.sh
    sh /tmp/uv-install.sh >/dev/null
    PATH="$HOME/.local/bin:$PATH"
    export PATH
fi

uv --version
uv python install "$PYTHON_VERSION"

# `uv python find` hands back the executable; the interpreter itself is asked
# for its prefix rather than deriving it by stripping path components, because
# that differs between the POSIX layout (`bin/python`) and the Windows one
# (`python.exe` at the root).
managed_python=$(uv python find "$PYTHON_VERSION")
source_root=$("$managed_python" -c 'import sys; print(sys.prefix)')

root="bake/$TARGET"
rm -rf "$root"
mkdir -p "$root"

# `"$source_root"/.` rather than `"$source_root"` -- uv's `cpython-3.12-<plat>`
# path is itself a symlink to the patch-versioned directory, and copying the
# symlink makes `$root` a link back into uv's store. Everything then installs
# into the *original* interpreter and the archive ships an empty one.
cp -a "$source_root"/. "$root"/
test ! -L "$root"

# The distribution is ours now; the marker exists to protect a system Python
# from a package manager, which is not this.
find "$root" -name EXTERNALLY-MANAGED -delete

if [ "${RUNNER_OS:-}" = "Windows" ]; then
    python_bin="$root/python.exe"
else
    python_bin="$root/bin/python"
fi

# From the wheels this release built, not from the index: the binary must
# contain exactly what `publish` uploaded, and a resolver reaching PyPI could
# pick a different build of a plugin.
uv pip install --python "$python_bin" --break-system-packages \
    --find-links dist/ "functualize[all]==$FUNCTUALIZE_VERSION" \
    || uv pip install --python "$python_bin" --break-system-packages \
        --find-links dist/ "functualize[all]"

# An editable install would leave a `.pth` pointing at a build-machine path and
# no package at all in site-packages -- a binary that starts, then imports
# nothing. Cheap to assert, and it caught exactly that in the local scenario.
if find "$root" -name '_editable_impl_*.pth' | grep -q .; then
    echo "editable install leaked into the distribution" >&2
    exit 1
fi

# `self update` replaces the binary from a release, so it has to know which
# releases. Baked in rather than hard-coded in the framework: an application
# that builds its own PyApp binary over functualize writes its own file here and
# points its users at its own releases, instead of being handed ours.
cat > "$root/standalone-release.json" <<JSON
{
  "repo": "${GITHUB_REPOSITORY:-raicing-ai/functualize}",
  "asset_prefix": "functualize",
  "target": "$TARGET"
}
JSON

# The standalone install path adds packages with the bundled interpreter's own
# pip -- a binary is the install method for machines with no Python toolchain,
# so requiring uv on PATH to add a dependency would defeat it. Asserted here so
# a future change to how the distribution is seeded fails in the build rather
# than in somebody's `self install`.
"$python_bin" -c "import pip" || { echo "no pip in the distribution" >&2; exit 1; }

"$python_bin" -c "import functualize; print(functualize.__version__)"
