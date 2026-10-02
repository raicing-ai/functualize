"""Every `func` door hands its app the same `[vault] keyring_timeout`.

`func` builds a `FunctualizeApp` in five places — bare, group, job, builtin and
single-file — and the settings each one passes used to be written out five
times. The repository has already shipped "three of four doors agreeing"
(`contributor/reference/pitfalls.md` §23), so this asserts the setting through
every door, not through one and by analogy.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import pytest

from functualize.app import FunctualizeApp
from tests.conftest import surfaces

if TYPE_CHECKING:
    from pathlib import Path

_SETTINGS = '[vault]\nkeyring_timeout = "7s"\n'

_HELLO = "def hello():\n    print('hi')\n"
_GROUPED = "JOB_GROUP = 'infra'\n\ndef provision():\n    print('provisioned')\n"
_SCRIPT = "def greet():\n    print('hello')\n"


@pytest.fixture
def captured(monkeypatch: pytest.MonkeyPatch) -> list[Any]:
    """The `config_sources` every `FunctualizeApp` was constructed with."""
    seen: list[Any] = []
    original = FunctualizeApp.__init__

    def recording(self: FunctualizeApp, *args: Any, **kwargs: Any) -> None:
        seen.append(kwargs.get("config_sources"))
        original(self, *args, **kwargs)

    monkeypatch.setattr(FunctualizeApp, "__init__", recording)
    return seen


@surfaces("func")
class TestEveryDoorCarriesTheSetting:
    @pytest.mark.parametrize(
        "argv",
        [
            pytest.param([], id="bare"),
            pytest.param(["infra", "provision"], id="group"),
            pytest.param(["hello"], id="job"),
            pytest.param(["builtin", "info"], id="builtin"),
            pytest.param(["scripts/greet.py", "greet"], id="file"),
        ],
    )
    def test_the_app_receives_the_project_setting(
        self, cli_run: Any, project_tree: Any, captured: list[Any], argv: list[str]
    ) -> None:
        root: Path = project_tree(
            functualize_toml=_SETTINGS,
            jobs={"hello.py": _HELLO, "infra.py": _GROUPED},
            extra_files={"scripts/greet.py": _SCRIPT},
        )

        cli_run(argv, cwd=root)

        assert captured, f"no app was built for {argv!r}"
        timeouts = [
            getattr(sources, "vault_keyring_timeout", None) for sources in captured
        ]
        assert timeouts and all(t == "7s" for t in timeouts), timeouts
