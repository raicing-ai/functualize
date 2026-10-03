#!/usr/bin/env bash
# Private sandbox: own D-Bus session, own gnome-keyring-daemon, own data dir.
# Nothing here can reach the real session bus, the real daemon or ~/.local/share/keyrings.
# The temp dir is under /tmp (not the scratchpad) only because unix socket paths
# are limited to 108 bytes and the scratchpad path alone is ~100.
set -u
HERE="$(cd "$(dirname "$0")" && pwd)"
PROJECT="$1"
REAL_RT="${XDG_RUNTIME_DIR:-/run/user/$(id -u)}"
# Keep the GUI reachable after XDG_RUNTIME_DIR is overridden below.
case "${WAYLAND_DISPLAY:-}" in /*) ;; "") ;; *) export WAYLAND_DISPLAY="$REAL_RT/$WAYLAND_DISPLAY";; esac

T="$(mktemp -d /tmp/fk.XXXXXX)"
export SANDBOX_DIR="$T" PROJECT
export XDG_DATA_HOME="$T/data" XDG_CONFIG_HOME="$T/cfg" XDG_RUNTIME_DIR="$T/run"
mkdir -p -m700 "$XDG_DATA_HOME" "$XDG_CONFIG_HOME" "$XDG_RUNTIME_DIR"
unset GNOME_KEYRING_CONTROL SSH_AUTH_SOCK DBUS_SESSION_BUS_ADDRESS

cat > "$T/inner.sh" <<'INNER'
set -u
case "$DBUS_SESSION_BUS_ADDRESS" in *"/run/user/"*) echo "refusing: real bus"; exit 9;; esac
echo "private bus: $DBUS_SESSION_BUS_ADDRESS"
printf 'sandbox-pass' | gnome-keyring-daemon --login --foreground --components=secrets 2>"$SANDBOX_DIR/daemon.log" &
DPID=$!
export GNOME_KEYRING_CONTROL="$XDG_RUNTIME_DIR/keyring"
for _ in $(seq 1 50); do [ -S "$GNOME_KEYRING_CONTROL/control" ] && break; sleep 0.1; done
sleep 1.5
ls "$XDG_DATA_HOME/keyrings" 2>&1 | sed "s/^/sandbox keyrings: /"
"$PROJECT/.venv/bin/python" "$PROBE"
echo
echo "--- assertion failures in the SANDBOX daemon log:"
grep -c "assertion" "$SANDBOX_DIR/daemon.log" || true
kill "$DPID" 2>/dev/null
INNER

export PROBE="${2:-$HERE/interrupt_probe.py}"
dbus-run-session -- bash "$T/inner.sh"
rc=$?
rm -rf "$T"
exit $rc
