"""The probe's credential gate, reachability gate, marker and reporter.

The gate idiom is lifted verbatim from `tests/substrate_probe/conftest.py`,
which had to solve exactly this: a suite that stays green for a contributor
with no credential, without ever quietly substituting a recorded fixture for
the service it claims to have measured.

Three properties every gate helper below shares, because each one is an
acceptance criterion rather than a taste:

- **It skips at module level, never fails.** `pytest.skip(...,
  allow_module_level=True)` runs at *import* time, so a credential-less run
  never reaches the first request and cannot raise a collection error either.
- **The skip reason is the matrix cell.** It spells `NOT MEASURED (no
  credentials)` verbatim, so the reference transcribes the reason a run
  actually gave instead of composing one.
- **It says what to do about it.** A reason that names the absent variable and
  where it is declared is actionable; "skipped: no credentials" is not.

`pytest_terminal_summary` is this directory's own addition. `-q` prints an
item's *pass* and nothing a passing module printed, so a run whose numbers
live in captures would publish nothing to the person reading the screen. The
record in `report.py` is printed here instead, and a run that measured nothing
prints the reasons it skipped.
"""

from __future__ import annotations

import os
import socket
from pathlib import Path
from typing import TYPE_CHECKING
from urllib.parse import urlparse

import pytest

from tests.jev_probe.client import ENDPOINT, MODEL, USER_AGENT
from tests.jev_probe.report import REPORT

if TYPE_CHECKING:
    from types import ModuleType

    from _pytest.terminal import TerminalReporter

_HERE = Path(__file__).parent

#: Files in this directory that are machinery rather than a measurement: the
#: pytest glue, the transport, and the record. A measurement module is a row of
#: the matrix; these four are the instrument's parts and carry no test of their
#: own, so collecting them would only add an empty node per file.
_NOT_A_MODULE = frozenset({"conftest.py", "__init__.py", "client.py", "report.py"})


def pytest_collect_file(
    file_path: Path, parent: pytest.Collector
) -> pytest.Module | None:
    """Collect the probe's measurement modules, which are not named `test_*.py`.

    Every measurement module here is one row of the matrix — `contract.py`,
    `identities.py`, `stability.py`, `cost.py`, `errors.py` — and none of those
    names matches pytest's default `python_files` patterns. Without this hook a
    plain `uv run pytest` would collect **nothing** from this directory and the
    "skips, never fails" guarantee would be a claim no run ever checks.

    Two files are left to the built-in collector, because returning a second
    Module for something pytest already collects runs it **twice**:

    - `test_*.py`, which matches `python_files`; and
    - **any file named on the command line.** `_pytest.python.pytest_collect_file`
      collects an init path whatever its name, so `uv run pytest
      tests/jev_probe/contract.py` would otherwise collect it twice.
    """
    if file_path.suffix != ".py":
        return None
    if file_path.name in _NOT_A_MODULE or file_path.name.startswith("test_"):
        return None
    if parent.session.isinitpath(file_path):
        return None
    return pytest.Module.from_parent(parent, path=file_path)


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    """Stamp every probe item with the marker, so nobody has to remember to."""
    for item in items:
        if _HERE in item.path.parents:
            item.add_marker(pytest.mark.jev_probe)


def pytest_sessionstart(session: pytest.Session) -> None:
    """Start from an empty record, so a second session in one process is clean."""
    REPORT.clear()


def pytest_terminal_summary(
    terminalreporter: TerminalReporter,
    exitstatus: int,
    config: pytest.Config,
) -> None:
    """Print the measured values — the one place `-q` cannot hide them."""
    terminalreporter.write_line("")
    terminalreporter.write_line(_banner())
    if REPORT.facts:
        terminalreporter.write_line(REPORT.render())
        return
    terminalreporter.write_line(
        "\nNo facts recorded. Every measurement module skipped; the reasons are "
        "the matrix cells this run could not fill:"
    )
    for reason in _skip_reasons(terminalreporter):
        terminalreporter.write_line(f"  {reason}")


def _banner() -> str:
    return (
        "=== Jev / System One capability probe — measured values ===\n"
        f"endpoint {ENDPOINT} · model {MODEL} · user-agent {USER_AGENT}"
    )


def _skip_reasons(terminalreporter: TerminalReporter) -> tuple[str, ...]:
    """The first line of every skip, which is the gate's own reason string."""
    reasons = []
    for report in terminalreporter.stats.get("skipped", []):
        text = str(report.longrepr).strip().splitlines()
        if text:
            reasons.append(text[0])
    return tuple(reasons)


def missing_env(*names: str) -> tuple[str, ...]:
    """The subset of `names` that is absent or empty. Whitespace is absent."""
    return tuple(name for name in names if not os.environ.get(name, "").strip())


def require_env(backend: str, *names: str, hint: str = "") -> None:
    """Turn "these variables are absent" into a module-level skip.

    Call it in the module body, above the first request::

        require_env("Jev / System One", "OPENCODE_API_KEY")

    The reason carries the exact text the matrix cell needs, the variables that
    were actually absent, and where they are declared.
    """
    absent = missing_env(*names)
    if not absent:
        return
    tail = f" {hint}" if hint else ""
    pytest.skip(
        f"{backend}: NOT MEASURED (no credentials) — "
        f"{', '.join(absent)} not set in the environment. The probe does not "
        f"fall back to a recorded fixture, so this cell stays unmeasured until "
        f"a real credential is wired in; the variable names are declared in "
        f".env.example.{tail}",
        allow_module_level=True,
    )


def require_endpoint(backend: str, endpoint: str, *, hint: str = "") -> None:
    """Skip at module level unless `endpoint` accepts a TCP connection.

    A TCP connect rather than an API call, so a wrong credential cannot be
    mistaken for an absent service — the same distinction the prior art draws.
    """
    if reachable(endpoint):
        return
    tail = f" {hint}" if hint else ""
    pytest.skip(
        f"{backend}: NOT MEASURED (service not reachable) — nothing accepted a "
        f"connection at {endpoint!r}. A green run that silently measured nothing "
        f"is worse than a skip that says so, so the probe does not fall back to "
        f"a recorded fixture.{tail}",
        allow_module_level=True,
    )


def require_client(backend: str, module: str, *, hint: str = "") -> ModuleType:
    """Skip at module level unless the client library is importable.

    Kept for parity with the idiom this file inherits. Nothing in this probe
    needs it: the transport is the standard library, so there is no client that
    can be absent.
    """
    return pytest.importorskip(
        module,
        reason=(
            f"{backend}: NOT MEASURED (client absent) — `import {module}` "
            f"failed, so the service cannot be reached from this environment."
            + (f" {hint}" if hint else "")
        ),
    )


def reachable(endpoint: str, *, timeout: float = 1.5) -> bool:
    """Does something accept a TCP connection at `endpoint`?

    An empty endpoint, an unparseable one and a refused connection are all
    simply "no" — a probe that raised here would fail where it is supposed to
    skip.
    """
    if not endpoint:
        return False
    parsed = urlparse(endpoint)
    if parsed.hostname is None:
        return False
    try:
        with socket.create_connection(
            (parsed.hostname, parsed.port or 443), timeout=timeout
        ):
            return True
    except OSError:
        return False
