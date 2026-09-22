"""The probe's credential gate, reachability gate and marker (FUN-25 task 1.2).

One idiom, one place, used by every measurement module after it. The idiom is
not invented here — it is lifted from
`plugins/credentials/functualize-aws/tests/test_integration_floci.py:41-64`,
which already had to solve exactly this: a suite that must stay green for a
contributor with no AWS account, without ever quietly substituting a fake for
the service it claims to have measured.

Three properties every helper below shares, because each one is an acceptance
criterion rather than a taste:

- **It skips at module level, never fails.** `pytest.skip(...,
  allow_module_level=True)` runs at *import* time, so a credential-less run
  does not reach a client constructor and therefore cannot raise a collection
  error either (AC5). A gate placed inside a fixture is too late: the module
  body has already run.
- **The skip reason is the matrix cell.** It spells `NOT MEASURED (no
  credentials)` verbatim, so task 6.1 transcribes the reason a run actually
  gave instead of composing one. Never inventing a cell starts here.
- **It says what to do about it.** A reason that names the absent variables and
  where they are declared is actionable; "skipped: no credentials" is not.

Module-level gating also sidesteps a trap peculiar to this suite: the root
`tests/conftest.py::_isolate_home` strips every `FUNCTUALIZE_*` variable from
the environment, and it is an autouse *fixture*, so it runs after import. A
gate that read `FUNCTUALIZE_PROBE_*` from inside a test would see them
stripped; read at import time they are still there.
"""

from __future__ import annotations

import os
import socket
from pathlib import Path
from typing import TYPE_CHECKING
from urllib.parse import urlparse

import pytest

if TYPE_CHECKING:
    from types import ModuleType

_HERE = Path(__file__).parent

#: Files in this directory that are machinery rather than a measurement.
_NOT_A_MODULE = frozenset({"conftest.py", "__init__.py"})


def pytest_collect_file(
    file_path: Path, parent: pytest.Collector
) -> pytest.Module | None:
    """Collect the probe's measurement modules, which are not named `test_*.py`.

    Every module here is one backend's measurement — `tier_a.py`, `d1.py`,
    `s3.py` — and those names are the ticket's
    (`.spec/features/substrate-capability-probe/tasks.md`). None of them matches
    pytest's default `python_files` patterns, so without this hook a plain
    `uv run pytest` would collect **nothing** from this directory and the
    "skips, never fails" guarantee (AC4, AC5) would be a claim no run ever
    checks. `contracts.md` states that guarantee as a property of the default
    run and of CI's `test-fast`/`test-full` jobs; this hook is what makes that
    true rather than vacuous.

    `test_*.py` is left to the built-in collector — returning a second Module
    for a file pytest already collects would run it twice.
    """
    if file_path.suffix != ".py":
        return None
    if file_path.name in _NOT_A_MODULE or file_path.name.startswith("test_"):
        return None
    return pytest.Module.from_parent(parent, path=file_path)


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    """Stamp every probe item with the marker, so nobody has to remember to."""
    for item in items:
        if _HERE in item.path.parents:
            item.add_marker(pytest.mark.substrate_probe)


def missing_env(*names: str) -> tuple[str, ...]:
    """The subset of `names` that is absent or empty. Whitespace is absent."""
    return tuple(name for name in names if not os.environ.get(name, "").strip())


def require_env(backend: str, *names: str, hint: str = "") -> None:
    """Turn "these variables are absent" into a module-level skip.

    Call it in the module body, above any client construction::

        require_env("AWS S3", "AWS_ACCESS_KEY_ID", "FUNCTUALIZE_PROBE_S3_BUCKET")

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
        f"fall back to a fake, so this cell stays unmeasured until a real "
        f"account is wired in; the variable names are declared in "
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
        f"connection at {endpoint!r}. A green run that silently tested nothing "
        f"is worse than a skip that says so, so the probe does not fall back "
        f"to a fake.{tail}",
        allow_module_level=True,
    )


def require_client(backend: str, module: str, *, hint: str = "") -> ModuleType:
    """Skip at module level unless the backend's own client is importable."""
    return pytest.importorskip(
        module,
        reason=(
            f"{backend}: NOT MEASURED (client absent) — `import {module}` "
            f"failed, so the backend cannot be reached from this environment."
            + (f" {hint}" if hint else "")
        ),
    )


def reachable(endpoint: str, *, timeout: float = 1.5) -> bool:
    """Does something accept a TCP connection at `endpoint`?

    Lifted from `test_integration_floci.py:41-64`. An empty endpoint, an
    unparseable one and a refused connection are all simply "no" — a probe that
    raised here would fail where it is supposed to skip.
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
