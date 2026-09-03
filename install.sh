#!/bin/sh
# Install the functualize standalone binary.
#
#   curl -LsSf https://raw.githubusercontent.com/<owner>/functualize/master/install.sh | sh
#
# POSIX sh, not bash: the audience for this binary is the user with no Python,
# who is disproportionately in a container where /bin/sh is dash or busybox ash
# and bash is not installed at all. A bashism here fails exactly the people the
# binary exists for.
#
# What it does: detect platform and libc, download the matching archive, verify
# it against the published checksum, and put the binary on PATH.
set -eu

REPO="${FUNCTUALIZE_REPO:-raicing-ai/functualize}"
VERSION="${FUNCTUALIZE_VERSION:-latest}"
INSTALL_DIR="${FUNCTUALIZE_INSTALL_DIR:-$HOME/.local/bin}"

say() { printf '%s\n' "$*"; }
die() { printf 'error: %s\n' "$*" >&2; exit 1; }

need() {
    command -v "$1" >/dev/null 2>&1 || die "$1 is required but was not found"
}

# --- platform -----------------------------------------------------------------

detect_arch() {
    arch=$(uname -m)
    case "$arch" in
        x86_64 | amd64) echo "x86_64" ;;
        aarch64 | arm64) echo "aarch64" ;;
        *) die "unsupported architecture: $arch" ;;
    esac
}

# Detect libc, not distribution. A glibc check by distro name is wrong in both
# directions -- a Debian-derived image can ship musl, and a distro this script
# has never heard of can ship glibc -- and the binary that matters is the one
# whose dynamic loader is actually present.
#
# `ldd --version` naming itself is the signal: GNU ldd says "GNU libc"/"GLIBC",
# musl's says "musl". Absence of ldd entirely means musl or a static-only image,
# and musl is the safe answer there: a musl binary runs on glibc systems, while
# a glibc binary on a musl system fails at exec with a loader error that names
# nothing useful.
detect_libc() {
    if [ "$(uname -s)" != "Linux" ]; then
        echo ""
        return
    fi
    if command -v ldd >/dev/null 2>&1; then
        if ldd --version 2>&1 | grep -qi musl; then
            echo "musl"
            return
        fi
        if ldd --version 2>&1 | grep -qiE 'gnu|glibc'; then
            echo "gnu"
            return
        fi
    fi
    # No ldd, or one that identified as neither. Alpine's busybox ships no ldd.
    if [ -e /lib/ld-musl-x86_64.so.1 ] || [ -e /lib/ld-musl-aarch64.so.1 ]; then
        echo "musl"
        return
    fi
    if ls /lib/ld-linux-*.so.* >/dev/null 2>&1 ||
        ls /lib64/ld-linux-*.so.* >/dev/null 2>&1; then
        echo "gnu"
        return
    fi
    echo "musl"
}

detect_target() {
    arch=$(detect_arch)
    case "$(uname -s)" in
        Linux)
            libc=$(detect_libc)
            echo "${arch}-unknown-linux-${libc}"
            ;;
        Darwin) echo "${arch}-apple-darwin" ;;
        *) die "unsupported platform: $(uname -s). On Windows, use install.ps1." ;;
    esac
}

# --- download -----------------------------------------------------------------

fetch() {
    # $1 url, $2 destination
    if command -v curl >/dev/null 2>&1; then
        curl -fsSL "$1" -o "$2"
    elif command -v wget >/dev/null 2>&1; then
        wget -qO "$2" "$1"
    else
        die "either curl or wget is required"
    fi
}

# Verify before installing, never after. An archive that fails its checksum is
# not unpacked at all: a corrupt or substituted download must never reach the
# filesystem as an executable, even briefly.
verify() {
    # $1 archive path, $2 checksum file, $3 archive basename
    expected=$(grep -E "[ *]\.?/?${3}\$" "$2" | awk '{print $1}' | head -1)
    [ -n "$expected" ] || die "no checksum published for ${3}"

    if command -v sha256sum >/dev/null 2>&1; then
        actual=$(sha256sum "$1" | awk '{print $1}')
    elif command -v shasum >/dev/null 2>&1; then
        actual=$(shasum -a 256 "$1" | awk '{print $1}')
    else
        die "sha256sum or shasum is required to verify the download"
    fi

    [ "$actual" = "$expected" ] || die \
        "checksum mismatch for ${3}: expected $expected, got $actual"
    say "checksum ok"
}

main() {
    need uname
    need tar

    target=$(detect_target)
    archive="functualize-${target}.tar.gz"

    if [ "$VERSION" = "latest" ]; then
        base="https://github.com/${REPO}/releases/latest/download"
    else
        base="https://github.com/${REPO}/releases/download/${VERSION}"
    fi

    say "platform: ${target}"

    tmp=$(mktemp -d)
    trap 'rm -rf "$tmp"' EXIT

    say "downloading ${archive}"
    fetch "${base}/${archive}" "${tmp}/${archive}" ||
        die "could not download ${base}/${archive}"
    fetch "${base}/SHA256SUMS" "${tmp}/SHA256SUMS" ||
        die "could not download the checksum file"

    verify "${tmp}/${archive}" "${tmp}/SHA256SUMS" "${archive}"

    tar -xzf "${tmp}/${archive}" -C "$tmp"
    mkdir -p "$INSTALL_DIR"
    mv "${tmp}/func" "${INSTALL_DIR}/func"
    chmod +x "${INSTALL_DIR}/func"

    say "installed to ${INSTALL_DIR}/func"

    case ":${PATH}:" in
        *":${INSTALL_DIR}:"*) ;;
        *)
            say ""
            say "${INSTALL_DIR} is not on your PATH. Add it:"
            say "  export PATH=\"${INSTALL_DIR}:\$PATH\""
            ;;
    esac

    say ""
    say "Run 'func builtin self doctor' to check the installation."
}

main "$@"
