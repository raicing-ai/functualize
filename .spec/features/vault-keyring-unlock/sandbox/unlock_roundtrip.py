"""Headless lock -> silent read -> out-of-band unlock -> silent read (private sandbox only).

No dialog is ever requested: the unlock is `gnome-keyring-daemon --unlock` (the
pam_gnome_keyring mechanism), standing in for "the human unlocked it elsewhere".
"""

from __future__ import annotations

import os
import re
import subprocess

import secretstorage
from jeepney import DBusAddress, new_method_call
from jeepney.io.blocking import open_dbus_connection

assert "/run/user/" not in os.environ["DBUS_SESSION_BUS_ADDRESS"], "refusing: real bus"

bus = secretstorage.dbus_init()
coll = secretstorage.get_default_collection(bus)
print("default collection:", coll.collection_path, "| locked:", coll.is_locked())

ATTRS = {"service": "functualize-vault", "username": "vault-key"}
coll.create_item("functualize test key", ATTRS, b"the-secret", replace=True)


def prompt_objects():
    conn = open_dbus_connection(bus="SESSION")
    intro = DBusAddress(
        "/org/freedesktop/secrets/prompt",
        bus_name="org.freedesktop.secrets",
        interface="org.freedesktop.DBus.Introspectable",
    )
    xml = conn.send_and_get_reply(new_method_call(intro, "Introspect")).body[0]
    conn.close()
    return set(re.findall(r'<node name="([pu]\d+)"', xml))


before = prompt_objects()
coll.lock()
print("after lock: locked =", coll.is_locked())

item = next(iter(coll.search_items(ATTRS)))
try:
    item.get_secret()
    print("silent read: UNEXPECTEDLY returned a secret while locked")
except secretstorage.exceptions.LockedException:
    print("silent read on a locked collection -> LockedException (no unlock attempted)")
print(
    "prompt objects created by the silent read:",
    sorted(prompt_objects() - before) or "none",
)

r = subprocess.run(
    ["gnome-keyring-daemon", "--unlock", "--components=secrets"],
    input=b"sandbox-pass",
    capture_output=True,
    timeout=15,
)
print("out-of-band unlock exit:", r.returncode)
print("after --unlock: locked =", coll.is_locked())
try:
    print("silent read after unlock ->", item.get_secret())
except Exception as e:  # noqa: BLE001
    print("silent read after unlock FAILED:", type(e).__name__, e)
print("prompt objects created in total:", sorted(prompt_objects() - before) or "none")
