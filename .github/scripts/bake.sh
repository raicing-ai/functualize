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
    # A toolchain is not optional. PyPI publishes musl wheels for the common
    # architectures but not for every dependency on aarch64 -- several
    # tree-sitter grammars build from source there, and Alpine ships no
    # compiler.
    #
    # `clang` specifically, and this is not a preference. python-build-standalone
    # builds its aarch64-musl interpreter with clang and bakes clang-only flags
    # into the sysconfig every extension build inherits:
    #
    #   CFLAGS   = ... --rtlib=compiler-rt -fPIC
    #   LDSHARED = cc -pthread -shared ... --rtlib=compiler-rt ...
    #
    # `build-base` provides gcc as `cc`, which rejects that outright --
    # `cc: error: unrecognized command-line option '--rtlib=compiler-rt'`. The
    # x86_64-musl distribution carries no such flag, which is why exactly one of
    # the seven targets failed and why it could not be reproduced on the others.
    apk add --no-cache curl ca-certificates build-base clang compiler-rt >/dev/null
    # `cc` is gcc on Alpine no matter what is installed alongside it, so the
    # compiler has to be named rather than left to the sysconfig default.
    CC=clang
    LDSHARED="clang -shared"
    export CC LDSHARED

    # ---------------------------------------------------------------------
    # tree-sitter on aarch64-musl
    #
    # `textual[syntax]` pulls sixteen tree-sitter grammars. Every other target
    # gets wheels for all of them; aarch64-musl is the only one that has to
    # compile any, and their sdists are broken -- they ship `src/parser.c` and
    # omit the headers it includes. tree_sitter_json-0.24.8.tar.gz's entire
    # `src/` is one `.c` file. Nothing else supplies them: Alpine's
    # `tree-sitter-dev` has only the runtime `api.h`, and the `tree-sitter`
    # wheel has no headers at all.
    #
    # Core headers can be vendored (below) and that gets most of the way, but
    # not all: tree-sitter-xml's sdist wants `"../../common/scanner.h"`, and the
    # copy at its own `v0.7.0` tag then wants `"./ts_assert.h"`, a file that tag
    # does not contain -- the published sdist was built from some later commit.
    # Reconstructing a package's private source tree by guessing at its
    # provenance is not a thing to put in a release pipeline.
    #
    # So this target installs the one grammar the code actually uses instead of
    # all sixteen. `TextArea.code_editor(language="python")` in
    # `_cli/tui/shortcut_save_modal.py` is the only syntax-highlighted widget in
    # the tree, and `tree-sitter-python` publishes an aarch64-musl wheel. The
    # override strips the `[syntax]` extra; the two packages are then requested
    # directly, which keeps highlighting working rather than degrading it.
    #
    # (Without them textual does not fail -- `TextArea` falls back from
    # `SyntaxAwareDocument` to `Document` and the preview is simply uncoloured.
    # Keeping the grammar is about appearance, not function.)
    #
    # Narrowed for this target only. x86_64-musl builds all sixteen without
    # trouble, and degrading a platform that works, for symmetry with one that
    # cannot, would trade real functionality for tidiness.
    # ---------------------------------------------------------------------
    case "$TARGET" in
        aarch64-unknown-linux-musl)
            ts_override=/tmp/musl-overrides.txt
            # An override replaces the requirement outright, extras included,
            # so this is what drops `[syntax]`.
            echo "textual>=8.0" > "$ts_override"
            UV_OVERRIDE="$ts_override"
            export UV_OVERRIDE
            extra_requirements="tree-sitter tree-sitter-python"

            # `tree-sitter` itself has never published an aarch64-musl wheel at
            # any version, so it still compiles and still needs these. Upstream
            # keeps them under `lib/src/`; grammars include them as
            # `tree_sitter/...`.
            ts_root=/usr/local/share/ts-headers
            mkdir -p "$ts_root/tree_sitter"
            for header in parser alloc array; do
                curl -LsSf --retry 3 \
                    "https://raw.githubusercontent.com/tree-sitter/tree-sitter/v0.24.7/lib/src/${header}.h" \
                    -o "$ts_root/tree_sitter/${header}.h"
            done
            CFLAGS="${CFLAGS:-} -I$ts_root"
            export CFLAGS
            ;;
    esac
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
# Unquoted on purpose: `extra_requirements` is a word list, empty on every
# target but aarch64-musl (see above).
# shellcheck disable=SC2086
uv pip install --python "$python_bin" --break-system-packages \
    --find-links dist/ "functualize[all]==$FUNCTUALIZE_VERSION" \
    ${extra_requirements:-} \
    || uv pip install --python "$python_bin" --break-system-packages \
        --find-links dist/ "functualize[all]" ${extra_requirements:-}

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
