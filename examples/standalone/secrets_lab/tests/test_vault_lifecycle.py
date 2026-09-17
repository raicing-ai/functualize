"""Step 6: supplying the credential, using only the published API.

The rest of this lab is about how a secret is *declared* and withheld. This is
the other half — where the value actually comes from — and it is written the way
a user's own code would write it: `functualize.app.vault` and a plain
`FunctualizeApp`, with no `func` process anywhere.

That is the point of putting it here rather than in the framework's own suite.
`_cli/` dogfoods the public API too, but `_cli/` is ours; an example is not. If
the seam were incomplete, this file could not be written without reaching into
an underscore package — and a test asserts that it does not.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from functualize.app import FunctualizeApp, JobSources
from functualize.app.core import request_for
from functualize.app.vault import (
    Readability,
    VaultOrigin,
    vault_init,
    vault_inspect,
    vault_put,
    vault_remove,
)

_ROOT = Path(__file__).parent.parent

#: Distinctive, so an assertion about absence is not satisfied by coincidence.
_TOKEN = "lab-token-7c2f91-not-a-real-credential"  # gitleaks:allow


@pytest.fixture
def project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """This lab's jobs, in a throwaway project with its own key and store.

    The **environment** key route, deliberately: it needs no OS keyring, so
    this runs identically on a laptop, in CI and in a container. `init` on a
    workstation would normally use the keychain instead, which is one
    `--key-source` away and changes nothing else.
    """
    work = tmp_path / "lab"
    (work / ".functualize").mkdir(parents=True)
    (work / "jobs").mkdir()
    for name in ("sync.py", "report.py"):
        (work / "jobs" / name).write_text((_ROOT / "jobs" / name).read_text())

    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))
    # 64 hex characters. `func builtin vault keygen` prints one.
    monkeypatch.setenv("FUNCTUALIZE_VAULT_KEY", "ab" * 32)
    monkeypatch.chdir(work)
    return work


def _app(project: Path) -> FunctualizeApp:
    """An ordinary app. No preset, no provider, no cloud account."""
    return FunctualizeApp(
        "secrets-lab",
        job_sources=JobSources(directories=[str(project / "jobs")], lazy=False),
    )


def test_init_reports_the_key_without_printing_it(project: Path) -> None:
    """Step 1. The key is user-scoped, so this is done once per machine."""
    report = vault_init(key_source="env")

    assert report.key_provider == "env"
    assert report.key_scope == "user"
    # Nothing was written: the environment already held a key, and only you
    # can put one there.
    assert report.created is False
    assert os.environ["FUNCTUALIZE_VAULT_KEY"] not in str(report)


def test_put_then_run_delivers_the_secret_to_the_job(project: Path) -> None:
    """Step 2 and 3, which is the whole feature.

    `report` declares `token: Secret[str]` with no default. Before this, the
    only ways to supply it were an environment variable or a prompt.
    """
    vault_init(key_source="env")
    app = _app(project)

    vault_put(app, "report.token", _TOKEN)

    # `refresh()` because this app booted *before* the vault existed, and the
    # resolution chain is built once at boot — that is the architecture, not an
    # oversight: configuration is read once so a run does no per-invocation file
    # I/O. From a terminal you never notice, because `vault put` and `func
    # report` are separate processes. Inside one process you do, and this is the
    # documented way to pick up a configuration change.
    app.refresh()

    result = app.execute(request_for("report"))

    assert result.return_value == "report written to ./out"


def test_the_job_still_receives_a_secret_not_a_string(project: Path) -> None:
    """Where the value came from does not change the job's contract.

    A vault that delivered a bare `str` would quietly undo everything the rest
    of this lab demonstrates about rendering.
    """
    from functualize.app.utils import job_config_fields

    vault_init(key_source="env")
    app = _app(project)
    vault_put(app, "report.token", _TOKEN)
    app.refresh()

    token = next(f for f in job_config_fields(app, "report") if f.name == "token")

    assert token.secret is True
    assert _TOKEN not in str(token.value)


def test_inspect_explains_the_entry_without_revealing_it(project: Path) -> None:
    """Step 4. What you can ask about a secret you cannot read."""
    vault_init(key_source="env")
    app = _app(project)
    vault_put(app, "report.token", _TOKEN)

    report = vault_inspect(app, "report.token")

    assert report.exists is True
    assert report.origin is VaultOrigin.DIRECT
    assert report.readability is Readability.READABLE
    assert _TOKEN not in str(report)


def test_inspect_explains_why_a_plain_field_is_refused(project: Path) -> None:
    """`sort_key` is the lab's decoy: it looks like a credential to every
    name-based heuristic and is not one. The vault follows the model too."""
    vault_init(key_source="env")

    assert vault_inspect(_app(project), "sync.sort_key").eligible is False


def test_remove_takes_it_back_and_says_what_was_lost(project: Path) -> None:
    """Step 5. A typed-in value has no upstream copy, so removing one warns."""
    vault_init(key_source="env")
    app = _app(project)
    vault_put(app, "report.token", _TOKEN)

    removed = vault_remove(app, "report.token")

    assert removed.removed is True
    assert removed.warning is not None
    assert vault_inspect(app, "report.token").exists is False


def test_the_example_uses_only_the_published_api(project: Path) -> None:
    """The claim this file exists to make.

    An example reaching into an underscore package would be documenting a layer
    violation — and would mean the public seam was incomplete for the very
    lifecycle it was built for.
    """
    import re

    offenders = [
        f"{path.name}:{n}"
        for path in _ROOT.rglob("*.py")
        for n, line in enumerate(path.read_text().splitlines(), 1)
        if re.search(r"\bfunctualize\._", line)
    ]

    assert offenders == [], offenders
