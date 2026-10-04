"""No platform's keyring code loads on another platform (spec B9, A16).

Each case runs in a fresh interpreter, because it is a claim about
`sys.modules` after importing and using the provider. `sys.platform` is forced,
and an import hook makes the other platform's libraries impossible to import,
so the check fails loudly if any code path even tries.
"""

from __future__ import annotations

import json
import subprocess
import sys

import pytest

_PROBE = """
import importlib.abc, json, sys

BLOCKED = {blocked!r}

class _Block(importlib.abc.MetaPathFinder):
    def find_spec(self, name, path=None, target=None):
        if name.split(".")[0] in BLOCKED or name in BLOCKED:
            raise ImportError(f"blocked on this platform: {{name}}")
        return None

sys.meta_path.insert(0, _Block())

from functualize._config.vault_keyring import select_adapter
from functualize._config.vault_keys import KeychainKeyProvider

# Forced after the imports: the stdlib reads it during its own start-up.
sys.platform = {platform!r}

def backend(module, name):
    kind = type(name, (), {{}})
    kind.__module__ = module
    kind.__qualname__ = name
    return kind()

adapter = select_adapter(
    "functualize-vault", "vault-key", platform={platform!r}, backend=backend(*{backend!r})
)
provider = KeychainKeyProvider(adapter=adapter)
outcome = adapter.read_silent().outcome.value
state = provider.probe().value
loaded = sorted(m for m in sys.modules if m.split(".")[0] in BLOCKED or m in BLOCKED)
print(json.dumps({{"adapter": adapter.name, "outcome": outcome, "state": state, "loaded": loaded}}))
"""


def _probe(
    platform: str, backend: tuple[str, str], blocked: set[str]
) -> dict[str, object]:
    code = _PROBE.format(platform=platform, backend=backend, blocked=sorted(blocked))
    completed = subprocess.run(  # noqa: S603
        [sys.executable, "-c", code], capture_output=True, text=True, check=False
    )
    assert completed.returncode == 0, completed.stderr[-2000:]
    return json.loads(completed.stdout.strip().splitlines()[-1])


_LINUX_ONLY = {
    "secretstorage",
    "jeepney",
    "functualize._config.vault_keyring_secretservice",
}
_NOT_LINUX = {
    "functualize._config.vault_keyring_macos",
    "functualize._config.vault_keyring_windows",
    "win32ctypes",
}


class TestNoLinuxCodeElsewhere:
    @pytest.mark.parametrize(
        ("platform", "backend", "adapter"),
        [
            ("darwin", ("keyring.backends.macOS", "Keyring"), "macos"),
            ("win32", ("keyring.backends.Windows", "WinVaultKeyring"), "windows"),
        ],
    )
    def test_the_provider_builds_and_answers_without_linux_libraries(
        self, platform: str, backend: tuple[str, str], adapter: str
    ) -> None:
        result = _probe(platform, backend, _LINUX_ONLY)
        assert result["adapter"] == adapter
        assert result["loaded"] == []


class TestNoOtherPlatformCodeOnLinux:
    def test_the_linux_adapter_loads_no_macos_or_windows_module(self) -> None:
        result = _probe(
            "linux", ("keyring.backends.SecretService", "Keyring"), _NOT_LINUX
        )
        assert result["adapter"] == "linux"
        assert result["loaded"] == []
