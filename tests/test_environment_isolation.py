"""Every test gets the environment it started with.

`tests/conftest.py::_restore_environ` is the mechanism; this module is the
proof that it is still installed. Per `contributor/guides/wiring-discipline.md`,
a fixture with no test asserting its effect is a claim, not an enforcement —
and this particular claim is one the default test order actively hides.

The failure it prevents, in full, because it is instructive:

`tests/core/test_show_info.py` passes `--dotenv-file` to an in-process
`CliRunner`, which reaches the real `load_dotenv()` and sets `MY_VAR=hello` in
the *test process*. `tests/cli/test_cli_integration.py::test_no_dotenv_flag`
then asserts `MY_VAR` is unset, to prove `--no-dotenv` suppresses loading.

Nothing caught it, for a reason worth remembering: `tests/cli/` sorts before
`tests/core/`, so in a plain `pytest tests/` the victim runs *before* the
polluter and passes. The order that fails is any subset that reorders the two —
and `-n auto`, which CI uses for the slow tier, distributes tests across
workers and does not preserve that order at all. The bug was live and
intermittent, not theoretical; it was simply never scheduled into the open.

`monkeypatch` is not an alternative here. It reverses what monkeypatch did, and
this is done by production code holding a real reference to `os.environ`.
"""

from __future__ import annotations

import os

import pytest

#: Deliberately not `FUNCTUALIZE_*` or `XDG_*`: `_isolate_home` strips those
#: at setup, so a probe under either prefix would come back clean whether or
#: not `_restore_environ` exists — passing for the wrong reason.
_PROBE = "LEAK_PROBE_ENV_ISOLATION"

_leaked_in_this_process = False


def test_a_test_may_leak_into_os_environ() -> None:
    """Stand in for any in-process `load_dotenv()`.

    Written as a direct assignment rather than a real dotenv load so the guard
    does not depend on python-dotenv's behaviour to detect a conftest
    regression.
    """
    global _leaked_in_this_process

    os.environ[_PROBE] = "leaked"
    _leaked_in_this_process = True

    assert os.environ[_PROBE] == "leaked", (
        "the probe did not take — this test proves nothing about the next one"
    )


def test_the_next_test_does_not_inherit_it() -> None:
    """Sabotage check: delete `_restore_environ` and this goes red."""
    if not _leaked_in_this_process:
        pytest.skip(
            "the leaking test ran on a different xdist worker, so there is "
            "nothing this process could have inherited — skipped rather than "
            "passed, because a vacuous pass here is exactly the shape of "
            "failure this module exists to catch"
        )

    assert _PROBE not in os.environ, (
        f"{_PROBE} survived a test boundary — os.environ is no longer being "
        "restored between tests, and every test that reads the environment is "
        "now order-dependent"
    )
