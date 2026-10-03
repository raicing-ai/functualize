#!/usr/bin/env python3
"""Real-OS smoke for the vault keyring adapters, on a throwaway keyring only.

Run by `.github/workflows/keyring-platforms.yml`, one platform per runner:

    python .github/scripts/keyring_smoke.py macos
    python .github/scripts/keyring_smoke.py windows
    dbus-run-session -- python .github/scripts/keyring_smoke.py linux

**Tier 1** — the claim a run depends on: a silent read of a *locked* keyring
answers LOCKED promptly. Every read runs in a child process under a hard
timeout, because on a real desktop the failure mode is not an exception but a
dialog: a read that hangs is a read that asked to unlock, and fails the job.
The silent store `vault init` uses is held to the same rule: stored and read
back when unlocked, LOCKED at once when locked.

**Tier 2** — a spike: unlock the keyring *without* a dialog ("unlocked
elsewhere") and check that a silent read then finds the key. Where no headless
unlock works the result is reported, not failed (`--tier2-required` makes it
fail).

Never run this on a real user session: on macOS it changes the default keychain
for the duration (restored at exit), and on Linux it must run inside its own
`dbus-run-session`.
"""

from __future__ import annotations

import argparse
import contextlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

SERVICE = "functualize-vault"
ACCOUNT = "vault-key"
#: Store probes write their own item, so they never collide with the read probe's.
STORE_ACCOUNT = "vault-key-store-probe"
KEY_HEX = "7e" * 32
READ_TIMEOUT = 5.0

_PROBE = """
import json, sys
from functualize._config.vault_keyring import select_adapter
adapter = select_adapter({service!r}, {account!r})
read = adapter.read_silent()
print(json.dumps({{
    "adapter": adapter.name,
    "outcome": read.outcome.value,
    "secret_ok": read.secret == {key!r},
    "state": adapter.state().value,
}}))
"""

#: What `vault init` does: a silent store, then a silent read of what it wrote.
_STORE_PROBE = """
import json, sys
from functualize._config.vault_keyring import select_adapter
adapter = select_adapter({service!r}, {account!r})
stored = adapter.store_silent({key!r})
read = adapter.read_silent()
print(json.dumps({{
    "adapter": adapter.name,
    "stored": stored.value,
    "read_after": read.outcome.value,
    "secret_ok": read.secret == {key!r},
}}))
"""


def _say(*parts: object) -> None:
    print("[keyring-smoke]", *parts, flush=True)


def _run(
    *cmd: str, stdin: str | None = None, check: bool = True
) -> subprocess.CompletedProcess[str]:
    _say("$", " ".join(cmd))
    return subprocess.run(  # noqa: S603
        list(cmd), input=stdin, capture_output=True, text=True, check=check, timeout=60
    )


def _store_probe(env: dict[str, str] | None = None) -> dict[str, object]:
    """Store through the real adapter in a child process, under the same timeout."""
    return _probe(env, template=_STORE_PROBE, account=STORE_ACCOUNT)


def _probe(
    env: dict[str, str] | None = None,
    *,
    template: str = _PROBE,
    account: str = ACCOUNT,
) -> dict[str, object]:
    """Ask the real adapter in a child process; a hang is a failure, not a wait."""
    code = template.format(service=SERVICE, account=account, key=KEY_HEX)
    started = time.monotonic()
    try:
        done = subprocess.run(  # noqa: S603
            [sys.executable, "-c", code],
            capture_output=True,
            text=True,
            timeout=READ_TIMEOUT * 3,
            env={**os.environ, **(env or {})},
            check=False,
        )
    except subprocess.TimeoutExpired:
        return {"hung": True, "elapsed": time.monotonic() - started}
    elapsed = time.monotonic() - started
    if done.returncode != 0:
        return {"error": done.stderr[-1500:], "elapsed": elapsed}
    result = json.loads(done.stdout.strip().splitlines()[-1])
    result["elapsed"] = round(elapsed, 2)
    return result


class Smoke:
    def __init__(self, platform: str) -> None:
        self.platform = platform
        self.failures: list[str] = []
        self.tier2: str = "not run"

    def expect(self, label: str, result: dict[str, object], **wanted: object) -> None:
        _say(label, json.dumps(result))
        if result.get("hung"):
            self.failures.append(f"{label}: the read hung (a dialog was requested)")
            return
        for key, value in wanted.items():
            if result.get(key) != value:
                self.failures.append(
                    f"{label}: {key}={result.get(key)!r}, wanted {value!r}"
                )

    def finish(self, *, tier2_required: bool) -> int:
        _say(f"tier 2 ({self.platform}):", self.tier2)
        if tier2_required and not self.tier2.startswith("passed"):
            self.failures.append(f"tier 2: {self.tier2}")
        for failure in self.failures:
            _say("FAIL", failure)
        _say("result:", "FAIL" if self.failures else "PASS")
        return 1 if self.failures else 0


# -- macOS ---------------------------------------------------------------------


def macos(smoke: Smoke) -> None:
    workdir = Path(tempfile.mkdtemp(prefix="functualize-smoke-"))
    keychain = str(workdir / "functualize-smoke.keychain-db")
    password = "functualize-smoke"  # noqa: S105 - a throwaway keychain
    listed = _run("security", "list-keychains", "-d", "user").stdout.split()
    previous = [entry.strip().strip('"') for entry in listed]
    default = (
        _run("security", "default-keychain", "-d", "user").stdout.strip().strip('"')
    )
    try:
        _run("security", "create-keychain", "-p", password, keychain)
        _run("security", "set-keychain-settings", keychain)  # no auto-lock
        _run("security", "list-keychains", "-d", "user", "-s", keychain, *previous)
        _run("security", "default-keychain", "-d", "user", "-s", keychain)
        _run("security", "unlock-keychain", "-p", password, keychain)
        # -A: any application may read it, so an unlocked read raises no
        # access-control dialog either.
        _run(
            "security",
            "add-generic-password",
            "-A",
            "-s",
            SERVICE,
            "-a",
            ACCOUNT,
            "-w",
            KEY_HEX,
            keychain,
        )
        smoke.expect(
            "unlocked read",
            _probe(),
            adapter="macos",
            outcome="found",
            secret_ok=True,
            state="unlocked",
        )
        smoke.expect(
            "unlocked store",
            _store_probe(),
            adapter="macos",
            stored="found",
            read_after="found",
            secret_ok=True,
        )
        _run("security", "lock-keychain", keychain)
        smoke.expect(
            "locked read", _probe(), adapter="macos", outcome="locked", state="locked"
        )
        smoke.expect("locked store", _store_probe(), adapter="macos", stored="locked")
        # Tier 2: unlocked elsewhere, with no dialog.
        _run("security", "unlock-keychain", "-p", password, keychain)
        after = _probe()
        _say("after headless unlock", json.dumps(after))
        smoke.tier2 = (
            "passed: `security unlock-keychain -p` then a silent read found the key"
            if after.get("outcome") == "found" and after.get("secret_ok")
            else f"dropped: after `security unlock-keychain -p` the read was {after}"
        )
    finally:
        _run("security", "default-keychain", "-d", "user", "-s", default, check=False)
        _run("security", "list-keychains", "-d", "user", "-s", *previous, check=False)
        _run("security", "delete-keychain", keychain, check=False)
        shutil.rmtree(workdir, ignore_errors=True)


# -- Windows -------------------------------------------------------------------


def windows(smoke: Smoke) -> None:
    import keyring

    _say(
        "backend:",
        type(keyring.get_keyring()).__module__,
        type(keyring.get_keyring()).__name__,
    )
    keyring.set_password(SERVICE, ACCOUNT, KEY_HEX)
    try:
        smoke.expect(
            "stored read",
            _probe(),
            adapter="windows",
            outcome="found",
            secret_ok=True,
            state="unlocked",
        )
    finally:
        keyring.delete_password(SERVICE, ACCOUNT)
    smoke.expect("nothing stored", _probe(), adapter="windows", outcome="not_stored")
    try:
        smoke.expect(
            "store",
            _store_probe(),
            adapter="windows",
            stored="found",
            read_after="found",
            secret_ok=True,
        )
    finally:
        with contextlib.suppress(Exception):
            keyring.delete_password(SERVICE, STORE_ACCOUNT)
    smoke.tier2 = "not applicable: Credential Manager has no locked state"


# -- Linux ---------------------------------------------------------------------


def _prompt_objects() -> list[str]:
    """The Secret Service's prompt objects; a run must never add one."""
    done = _run(
        "busctl", "--user", "tree", "--list", "org.freedesktop.secrets", check=False
    )
    return sorted(line for line in done.stdout.split() if "/prompt/" in line)


def linux(smoke: Smoke) -> None:
    # Two locks, because a real desktop session has a session bus too: the
    # workflow opts in explicitly, and the standard per-user bus is refused.
    address = os.environ.get("DBUS_SESSION_BUS_ADDRESS", "")
    if os.environ.get("KEYRING_SMOKE_PRIVATE_BUS") != "1" or not address:
        sys.exit(
            "refusing: run as `KEYRING_SMOKE_PRIVATE_BUS=1 dbus-run-session -- ...`, "
            "never on a real session"
        )
    if "/run/user/" in address:
        sys.exit(f"refusing: {address} is a user session bus, not a private one")
    password = "functualize-smoke"  # noqa: S105 - a throwaway keyring
    home = Path(tempfile.mkdtemp(prefix="functualize-smoke-home-"))
    os.environ["HOME"] = str(home)
    os.environ["XDG_DATA_HOME"] = str(home / "data")
    started = _run(
        "gnome-keyring-daemon", "--unlock", "--components=secrets", stdin=password
    )
    for line in started.stdout.splitlines():
        name, _, value = line.partition("=")
        if name and value:
            os.environ[name] = value
    time.sleep(1.0)

    import secretstorage

    connection = secretstorage.dbus_init()
    collections = list(secretstorage.get_all_collections(connection))
    _say("collections:", [c.collection_path for c in collections])
    collection = next(c for c in collections if "login" in c.collection_path)
    if collection.is_locked():
        # `--unlock` should have left it unlocked. Asking it to unlock here would
        # be a prompt — exactly what this smoke must never create.
        smoke.failures.append("the login collection is locked after --unlock")
        return
    collection.create_item(
        "functualize smoke",
        {"username": ACCOUNT, "service": SERVICE},
        KEY_HEX.encode(),
        replace=True,
    )
    env = {
        "PYTHON_KEYRING_BACKEND": "keyring.backends.SecretService.Keyring",
        "KEYRING_PROPERTY_PREFERRED_COLLECTION": collection.collection_path,
    }
    smoke.expect(
        "unlocked read",
        _probe(env),
        adapter="linux",
        outcome="found",
        secret_ok=True,
        state="unlocked",
    )
    smoke.expect(
        "unlocked store",
        _store_probe(env),
        adapter="linux",
        stored="found",
        read_after="found",
        secret_ok=True,
    )
    collection.lock()
    before = _prompt_objects()
    smoke.expect(
        "locked read", _probe(env), adapter="linux", outcome="locked", state="locked"
    )
    smoke.expect("locked store", _store_probe(env), adapter="linux", stored="locked")
    after = _prompt_objects()
    _say("prompt objects before/after:", before, after)
    if after != before:
        smoke.failures.append(f"a silent read or store created prompt objects: {after}")
    # Tier 2 spike: unlock without a dialog, through the running daemon.
    _run(
        "gnome-keyring-daemon",
        "--unlock",
        "--components=secrets",
        stdin=password,
        check=False,
    )
    time.sleep(1.0)
    relocked = collection.is_locked()
    result = _probe(env)
    _say("after headless unlock", json.dumps(result), "still locked:", relocked)
    smoke.tier2 = (
        "passed: `gnome-keyring-daemon --unlock` then a silent read found the key"
        if result.get("outcome") == "found" and result.get("secret_ok")
        else f"dropped: after `gnome-keyring-daemon --unlock` the read was {result}"
    )
    connection.close()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("platform", choices=["macos", "windows", "linux"])
    parser.add_argument("--tier2-required", action="store_true")
    args = parser.parse_args()
    smoke = Smoke(args.platform)
    {"macos": macos, "windows": windows, "linux": linux}[args.platform](smoke)
    return smoke.finish(tier2_required=args.tier2_required)


if __name__ == "__main__":
    sys.exit(main())
