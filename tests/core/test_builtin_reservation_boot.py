"""Boot-time rejection of any user name claiming the ``builtin`` subtree."""

from __future__ import annotations

from pathlib import Path

import pytest

from functualize._types.naming import BUILTIN_SEGMENT

# ── Helper ──────────────────────────────────────────────────────────────────


def _app_with_jobs(tmp_path: Path, module_text: str) -> None:
    """Write a job module and construct the app, raising if boot rejects it."""
    from functualize.app.core import FunctualizeApp, JobSources

    jobs = tmp_path / "jobs"
    jobs.mkdir()
    (jobs / "the_job.py").write_text(module_text)

    FunctualizeApp(
        name="test",
        job_sources=JobSources(directories=[str(jobs)]),
    )


# ── Job name ────────────────────────────────────────────────────────────────


def test_job_called_builtin_is_rejected(tmp_path: Path) -> None:
    """A job *named* ``builtin`` must not register — it shadows the CLI subtree."""
    with pytest.raises(ValueError, match=BUILTIN_SEGMENT):
        _app_with_jobs(
            tmp_path,
            "def builtin() -> None: ...\n",
        )


def test_job_in_builtin_group_is_rejected(tmp_path: Path) -> None:
    """A job whose *group* is ``builtin`` is also rejected."""
    with pytest.raises(ValueError, match=BUILTIN_SEGMENT):
        _app_with_jobs(
            tmp_path,
            "JOB_GROUP = 'builtin'\ndef migrate() -> None: ...\n",
        )


def test_job_with_builtin_as_top_level_group_segment_is_rejected(
    tmp_path: Path,
) -> None:
    """``JOB_GROUP = 'builtin.aws'`` fails — the first segment is the reserved name."""
    with pytest.raises(ValueError, match=BUILTIN_SEGMENT):
        _app_with_jobs(
            tmp_path,
            "JOB_GROUP = 'builtin.aws'\ndef deploy() -> None: ...\n",
        )


# ── Plugin command namespace ────────────────────────────────────────────────


def test_plugin_namespace_builtin_is_rejected() -> None:
    """register_plugin_command(namespace='builtin') must raise."""
    from functualize._app.impl import register_plugin_command

    app = _dummy_app()

    def _cmd() -> None: ...

    with pytest.raises(ValueError, match=BUILTIN_SEGMENT):
        register_plugin_command(app, "cmd", _cmd, namespace="builtin")


# ── helpers ─────────────────────────────────────────────────────────────────


class _DummyJobRegistry:
    _registered_jobs: dict[str, object] = {}


def _dummy_app() -> object:
    """Minimal app-like object accepted by register_plugin_command."""
    return type(
        "_DummyApp",
        (),
        {
            "_plugin_command_names": {},
            "_plugin_commands_list": [],
            "_plugin_sub_groups": {},
        },
    )()


# ── Shell sigils (C1b.4) ────────────────────────────────────────────────────
#
# A name starting with `!` or `?` is unreachable in the shell: the input bar
# dispatches on the first character, so `!deploy` selects the shell mode and
# runs `deploy` as an external program. Rejecting at boot beats shipping a job
# that works on the CLI and is invisible in the shell.


def test_job_named_with_shell_sigil_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="sigil"):
        _app_with_jobs(
            tmp_path,
            "def bang() -> None: ...\nbang.__name__ = '!bang'\n",
        )


def test_question_sigil_is_reserved_before_it_is_implemented() -> None:
    """`?` is claimed now so a name legal today does not break when ask ships.

    The reservation is what has to hold; the ask *mode* is deliberately
    unbuilt (its behaviour is asserted in `tests/_cli/test_shell_mode.py`).
    """
    from functualize._types.naming import RESERVED_SIGILS

    assert "?" in RESERVED_SIGILS
    with pytest.raises(ValueError, match="sigil"):
        _validate_groups({"?ask": None})


@pytest.mark.parametrize("group", ["!ops", "?ask", "ops.!x"])
def test_scanned_job_group_with_a_sigil_never_registers(
    tmp_path: Path, group: str
) -> None:
    """Groups take a *different* route than names, and it is stricter.

    A sigil group cannot reach the boot validator at all: `is_valid_job_group`
    requires every segment to be a Python identifier, so discovery drops the
    module first (with a warning) — including `ops.!x`, where only an inner
    segment offends. The outcome the user cares about is the same (the job
    does not exist), but it is a skip, not the reservation *error* that a
    sigil job **name** raises. Asserted here so the difference is recorded
    rather than assumed.
    """
    from functualize._types.naming import is_valid_job_group

    assert not is_valid_job_group(group)

    jobs = tmp_path / "jobs"
    jobs.mkdir()
    (jobs / "the_job.py").write_text(
        f"JOB_GROUP = {group!r}\ndef deploy() -> None: ...\n"
    )

    from functualize.app.core import FunctualizeApp, JobSources

    app = FunctualizeApp(name="test", job_sources=JobSources(directories=[str(jobs)]))
    assert [j.name for j in app.get_jobs()] == []


def test_validator_still_covers_groups_for_hand_built_descriptors() -> None:
    """The scan path filters early; a `JobProvider` does not go through it.

    That is why the validator keeps a group check even though the directory
    scan makes it unreachable — the same reason the `builtin` group check
    exists.
    """
    with pytest.raises(ValueError, match="sigil"):
        _validate_groups({"deploy": "!ops"})
    with pytest.raises(ValueError, match="sigil"):
        _validate_groups({"deploy": "ops.!x"})


def test_ordinary_names_still_boot(tmp_path: Path) -> None:
    """The guard must not reject names that merely *contain* a sigil."""
    _app_with_jobs(
        tmp_path,
        "JOB_GROUP = 'ops'\ndef deploy_now() -> None: ...\n",
    )


def test_plugin_namespace_with_sigil_is_rejected() -> None:
    """The one seam a plugin could have claimed an unreachable name through.

    Command *names* are already constrained to `^[a-z][a-z0-9-]{0,63}$`, so a
    sigil never reaches them; the namespace had no such pattern.
    """
    from functualize._app.impl import register_plugin_command

    app = _dummy_app()

    def _cmd() -> None: ...

    with pytest.raises(ValueError, match="sigil"):
        register_plugin_command(app, "cmd", _cmd, namespace="!shell")


def _validate_groups(groups: dict[str, str]) -> None:
    """Run the boot validator over hand-built (name -> group) entries."""
    from functualize._app.boot import _validate_builtin_reservation

    app = type(
        "_App",
        (),
        {
            "job_registry": type(
                "_Reg",
                (),
                {
                    "_registered_jobs": {
                        name: type("_E", (), {"group": group})()
                        for name, group in groups.items()
                    }
                },
            )(),
            "_plugin_commands_list": [],
        },
    )()
    _validate_builtin_reservation(app)
