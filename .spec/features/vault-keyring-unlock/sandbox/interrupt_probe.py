"""Does a client that vanishes mid-prompt wedge gnome-keyring? (private sandbox only)

Runs INSIDE `dbus-run-session` against a private gnome-keyring-daemon whose data
lives in a temp dir. Never touches the real session bus: it refuses unless
DBUS_SESSION_BUS_ADDRESS points into the sandbox.
"""

from __future__ import annotations

import os
import signal
import subprocess
import sys
import time

from jeepney import DBusAddress, new_method_call
from jeepney.io.blocking import open_dbus_connection

SANDBOX = os.environ["SANDBOX_DIR"]
assert "/run/user/" not in os.environ["DBUS_SESSION_BUS_ADDRESS"], "refusing: real bus"
COLL = "/org/freedesktop/secrets/collection/login"
NAMES = ("org.gnome.keyring.SystemPrompter", "org.gnome.keyring.PrivatePrompter")


def _addrs(conn):
    dbus = DBusAddress(
        "/org/freedesktop/DBus",
        bus_name="org.freedesktop.DBus",
        interface="org.freedesktop.DBus",
    )
    svc = DBusAddress(
        "/org/freedesktop/secrets",
        bus_name="org.freedesktop.secrets",
        interface="org.freedesktop.Secret.Service",
    )
    return dbus, svc


def lock(conn):
    _, svc = _addrs(conn)
    conn.send_and_get_reply(new_method_call(svc, "Lock", "ao", ([COLL],)))


def start_unlock(conn):
    """Unlock + Prompt. Returns the Prompt address; the dialog is now requested."""
    _, svc = _addrs(conn)
    _, prompt_path = conn.send_and_get_reply(
        new_method_call(svc, "Unlock", "ao", ([COLL],))
    ).body
    assert prompt_path != "/", "collection was not locked"
    prompt = DBusAddress(
        prompt_path,
        bus_name="org.freedesktop.secrets",
        interface="org.freedesktop.Secret.Prompt",
    )
    conn.send_and_get_reply(new_method_call(prompt, "Prompt", "s", ("",)))
    return prompt


def prompter_appears(conn, within=4.0):
    dbus, _ = _addrs(conn)
    t0 = time.monotonic()
    while time.monotonic() - t0 < within:
        for n in NAMES:
            if conn.send_and_get_reply(
                new_method_call(dbus, "NameHasOwner", "s", (n,))
            ).body[0]:
                return round(time.monotonic() - t0, 2)
        time.sleep(0.05)
    return None


def health_check(label):
    """A brand-new client asks to unlock; does the daemon ask for a dialog?"""
    conn = open_dbus_connection(bus="SESSION")
    lock(conn)
    time.sleep(1.2)  # let any previous prompter idle out? (it idles at 10 s)
    prompt = start_unlock(conn)
    seen = prompter_appears(conn)
    conn.send_and_get_reply(new_method_call(prompt, "Dismiss"))
    conn.close()
    time.sleep(1.0)
    print(
        f"  health after [{label}]: "
        + (
            f"dialog requested (prompter up in {seen}s) -> HEALTHY"
            if seen is not None
            else "NO prompter -> WEDGED"
        ),
        flush=True,
    )
    return seen is not None


CHILD = rf"""
import os, sys, time
sys.path.insert(0, {os.path.dirname(os.path.abspath(__file__))!r})
import interrupt_probe as p
conn = p.open_dbus_connection(bus="SESSION")
p.lock(conn); time.sleep(0.5)
p.start_unlock(conn)
print("child: prompt requested, now waiting to be interrupted", flush=True)
time.sleep(60)
"""


def child_case(label, how):
    print(f"\ncase: {label}", flush=True)
    proc = subprocess.Popen(
        [sys.executable, "-c", CHILD],
        stdout=subprocess.PIPE,
        text=True,
        env=dict(os.environ, PYTHONPATH=os.path.dirname(os.path.abspath(__file__))),
    )
    proc.stdout.readline()
    time.sleep(1.5)  # dialog is on screen, client is mid-prompt
    if how == "sigint":
        proc.send_signal(signal.SIGINT)
    elif how == "sigterm":
        proc.send_signal(signal.SIGTERM)
    elif how == "sigkill":
        proc.send_signal(signal.SIGKILL)
    proc.wait(timeout=10)
    print(
        f"  client ended with returncode {proc.returncode} (no Dismiss was sent)",
        flush=True,
    )
    time.sleep(1.0)
    return health_check(label)


def discover():
    """Find the sandbox's default collection and show its state (diagnostics)."""
    global COLL
    conn = open_dbus_connection(bus="SESSION")
    _, svc = _addrs(conn)
    props = DBusAddress(
        "/org/freedesktop/secrets",
        bus_name="org.freedesktop.secrets",
        interface="org.freedesktop.DBus.Properties",
    )
    colls = conn.send_and_get_reply(
        new_method_call(
            props, "Get", "ss", ("org.freedesktop.Secret.Service", "Collections")
        )
    ).body[0][1]
    alias = conn.send_and_get_reply(
        new_method_call(svc, "ReadAlias", "s", ("default",))
    ).body[0]
    print("collections:", colls, "| default alias ->", alias, flush=True)
    if alias == "/":
        raise SystemExit(
            "sandbox has no default collection; --unlock did not create one"
        )
    COLL = alias
    cprops = DBusAddress(
        alias,
        bus_name="org.freedesktop.secrets",
        interface="org.freedesktop.DBus.Properties",
    )

    def locked_now():
        msg = new_method_call(
            cprops, "Get", "ss", ("org.freedesktop.Secret.Collection", "Locked")
        )
        return conn.send_and_get_reply(msg).body[0][1]

    print("Locked before Lock():", locked_now(), flush=True)
    reply = conn.send_and_get_reply(new_method_call(svc, "Lock", "ao", ([COLL],)))
    print("Lock() reply:", reply.body, "| Locked after:", locked_now(), flush=True)
    conn.close()


def main():
    print("sandbox bus:", os.environ["DBUS_SESSION_BUS_ADDRESS"], flush=True)
    discover()
    results = {}
    print("\ncase: baseline (clean Dismiss)", flush=True)
    results["baseline"] = health_check("baseline")
    for label, how in (
        ("Ctrl-C (SIGINT) mid-prompt", "sigint"),
        ("SIGTERM mid-prompt", "sigterm"),
        ("SIGKILL mid-prompt", "sigkill"),
    ):
        results[label] = child_case(label, how)
    print("\nSUMMARY:", flush=True)
    for k, v in results.items():
        print(
            f"  {k:32s} -> {'healthy afterwards' if v else 'WEDGED afterwards'}",
            flush=True,
        )


if __name__ == "__main__":
    main()
