"""`func builtin self doctor` — and specifically, what it refuses to claim.

Two properties carry this suite. Doctor must still produce a report when the
application cannot boot, because that is the case it exists for. And it must
not report health it did not observe: a plugin that raises at import is
swallowed by the loader with no record kept, so there is no plugin check at all
rather than a green one.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from functualize._cli.self_cmd import (
    CheckStatus,
    build_report,
    render_report_text,
)


def _names(report: object) -> list[str]:
    return [c.name for c in report.checks]  # type: ignore[attr-defined]


def _by_name(report: object, name: str) -> object:
    return next(c for c in report.checks if c.name == name)  # type: ignore[attr-defined]


class TestTheReportIsProducedAtAll:
    def test_a_recognised_installation_reports_ok(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        """Pinned on **both** axes, because the suite's own environment is not a
        recognised installation on either of them.

        *Mode*: `_isolate_home` strips `XDG_*` and `tmp_path` declares no
        project, so an unpinned run legitimately detects `unknown` — a degraded
        mode doctor is right to warn about.

        *Owner*: resolved by reverse-mapping `argv[0]` through installed console
        scripts. Under plain pytest that is `.../bin/pytest`, which resolves to
        the `pytest` distribution and quietly satisfies the check — but under
        `pytest -n auto` a worker's `argv[0]` is execnet's bootstrap, which maps
        to nothing, and doctor correctly warns that self-management is
        unavailable. **CI caught this and a local run could not**, which is the
        same environment-dependence `runtime.detect` takes its inputs as
        parameters to avoid; this test had inherited it through `argv[0]`.

        Pinning `argv[0]` to a real console script keeps the actual resolver in
        the loop rather than stubbing detection out.
        """
        monkeypatch.setenv("FUNCTUALIZE_RUNTIME", "tool_uv")
        monkeypatch.setattr(sys, "argv", ["func"])
        report = build_report(cwd=tmp_path)
        assert report.worst is CheckStatus.OK, "unexpected non-OK checks: " + "; ".join(
            f"{c.name}={c.status.value} ({c.detail})"
            for c in report.checks
            if c.status in (CheckStatus.WARNING, CheckStatus.CRITICAL)
        )

    def test_a_degraded_mode_is_reported_as_a_warning(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        """The other half — and the one that would silently rot.

        A doctor whose worst-case is always OK is the failure mode this module
        is shaped against, so the degraded path is asserted directly.
        """
        monkeypatch.setenv("FUNCTUALIZE_RUNTIME", "unknown")
        report = build_report(cwd=tmp_path)
        assert report.worst is CheckStatus.WARNING
        assert _by_name(report, "self-management") is not None

    def test_every_check_carries_a_status_and_a_detail(self, tmp_path: Path) -> None:
        report = build_report(cwd=tmp_path)
        assert report.checks
        for check in report.checks:
            assert isinstance(check.status, CheckStatus)
            assert check.detail


class TestItReportsWhatItCannotAssume:
    def test_a_project_whose_plugin_raises_still_produces_a_report(
        self, tmp_path: Path
    ) -> None:
        """AC10 — the report survives a project that is broken in this way."""
        plugins = tmp_path / ".functualize" / "plugins"
        plugins.mkdir(parents=True)
        (plugins / "bad_plugin.py").write_text('raise RuntimeError("boom-from-plugin")')
        (tmp_path / "noop.py").write_text("def noop():\n    pass\n")

        report = build_report(cwd=tmp_path)
        assert report.checks

    def test_there_is_no_plugin_check(self, tmp_path: Path) -> None:
        """AC12, stated as an assertion rather than as a comment.

        `_load_file_plugin` catches, logs and returns None, keeping no record,
        so nothing in-process can observe that a plugin failed. A "plugins: ok"
        line would therefore be true by construction and false in fact — worse
        than no line. This test fails the moment somebody adds one.
        """
        plugins = tmp_path / ".functualize" / "plugins"
        plugins.mkdir(parents=True)
        (plugins / "bad_plugin.py").write_text('raise RuntimeError("boom-from-plugin")')

        names = _names(build_report(cwd=tmp_path))
        assert not any("plugin" in n for n in names), (
            f"doctor grew a plugin check ({names}) while the loader still keeps "
            "no failure record — it can only report health it did not observe"
        )

    def test_boot_is_observed_not_assumed(self, tmp_path: Path) -> None:
        """The check exists, and says the app started — having watched it."""
        boot = _by_name(build_report(cwd=tmp_path), "boot")
        assert boot.status is CheckStatus.OK  # type: ignore[attr-defined]

    def test_a_project_that_cannot_boot_is_reported_not_raised(
        self, tmp_path: Path
    ) -> None:
        """AC11 — the whole reason the probe runs in a child process.

        A job module that explodes at import takes down anything that boots
        in-process. Doctor must come back with a finding instead.
        """
        (tmp_path / "exploding.py").write_text(
            "raise SystemError('this module detonates at import')\n"
        )
        (tmp_path / "pyproject.toml").write_text(
            '[project]\nname = "broken"\nversion = "0"\n'
            "[tool.functualize]\nrequire_file_import = false\n"
        )
        report = build_report(cwd=tmp_path)
        # Whatever the verdict, a report came back rather than an exception.
        assert report.checks
        assert _by_name(report, "boot") is not None


class TestRendering:
    def test_text_and_json_render_from_one_structure(self, tmp_path: Path) -> None:
        """So the two cannot drift into disagreeing about one installation."""
        report = build_report(cwd=tmp_path)
        payload = report.to_dict()
        assert payload["status"] == report.worst.value
        assert [c["name"] for c in payload["checks"]] == _names(report)  # type: ignore[index,union-attr]

    def test_the_json_payload_is_json(self, tmp_path: Path) -> None:
        json.dumps(build_report(cwd=tmp_path).to_dict())

    def test_text_lines_mention_every_check(self, tmp_path: Path) -> None:
        report = build_report(cwd=tmp_path)
        blob = "\n".join(render_report_text(report))
        for name in _names(report):
            assert name in blob

    def test_a_remedy_is_rendered_when_present(self) -> None:
        from functualize._cli.self_cmd import Check, DoctorReport

        report = DoctorReport(
            (Check("x", CheckStatus.WARNING, "went wrong", remedy="do this instead"),)
        )
        assert "do this instead" in "\n".join(render_report_text(report))


class TestStatusVocabulary:
    def test_there_is_no_skipped_status(self) -> None:
        """A skipped check reads as health that was not observed.

        The design rule is that an unperformable check is *absent*. A `SKIPPED`
        member is the affordance that would quietly undo it.
        """
        assert [s.value for s in CheckStatus] == ["ok", "info", "warning", "critical"]

    def test_worst_prefers_critical_over_warning(self) -> None:
        from functualize._cli.self_cmd import Check, DoctorReport

        report = DoctorReport(
            (
                Check("a", CheckStatus.WARNING, "w"),
                Check("b", CheckStatus.CRITICAL, "c"),
                Check("c", CheckStatus.OK, "o"),
            )
        )
        assert report.worst is CheckStatus.CRITICAL

    def test_info_alone_is_not_a_problem(self) -> None:
        from functualize._cli.self_cmd import Check, DoctorReport

        report = DoctorReport((Check("a", CheckStatus.INFO, "fyi"),))
        assert report.worst is CheckStatus.OK


class TestItIsReachableThroughTheCli:
    def test_doctor_runs_pre_boot_through_the_real_entry_point(
        self, cli_run, tmp_path: Path
    ) -> None:
        """The wire: `_run_cli` intercepts before `cli_app` boots anything."""
        result = cli_run(["builtin", "self", "doctor"], cwd=tmp_path)
        assert result.exit_code == 0
        assert "install-mode" in result.stdout

    def test_the_json_flag_reaches_it(self, cli_run, tmp_path: Path) -> None:
        result = cli_run(
            ["builtin", "self", "doctor", "--format", "json"], cwd=tmp_path
        )
        assert result.exit_code == 0
        assert json.loads(result.stdout)["checks"]

    def test_a_job_named_doctor_is_not_intercepted(
        self, cli_run, tmp_path: Path
    ) -> None:
        """The intercept matches a three-token prefix, never a bare word."""
        (tmp_path / "doctor.py").write_text("def doctor():\n    print('the job ran')\n")
        result = cli_run(["doctor"], cwd=tmp_path)
        assert "the job ran" in result.stdout

    @pytest.mark.surfaces("func")
    def test_doctor_answers_where_every_other_builtin_cannot(
        self, cli_run, tmp_path: Path
    ) -> None:
        """The one test that distinguishes the two doors — and the point of both.

        **`func`-only, and that is a real limitation rather than a test
        convenience.** `contributor/architecture/surface-boundary.md` records
        that a consumer application's own `main.py` has *no pre-boot layer at
        all*: it reaches `self doctor` through the mounted group, which boots
        first. So on that surface a boot failure makes doctor unreachable in
        exactly the way it does for every other builtin. Answering under a
        broken boot is a property of *how you reach the program*, which the
        boundary doc allows to be `func`-only.

        Sabotaging the pre-boot intercept left all the other tests here green,
        because they reach doctor through the mounted group instead and get the
        same output. Only a project whose boot *fails* can tell them apart.

        A group claiming the reserved `builtin` name is rejected during boot, so
        `builtin version` dies. Doctor is intercepted before that happens and
        must still report. Without the intercept it dies identically, which is
        exactly the case doctor exists for.
        """
        (tmp_path / "reserved.py").write_text(
            'JOB_GROUP = "builtin"\n\n\ndef hello():\n    """Doc."""\n    pass\n'
        )

        blocked = cli_run(["builtin", "version"], cwd=tmp_path)
        assert blocked.exit_code != 0, (
            "premise broken: this project is supposed to fail at boot, so if "
            "`builtin version` now succeeds this test proves nothing"
        )

        report = cli_run(["builtin", "self", "doctor"], cwd=tmp_path)
        assert report.exit_code == 0
        assert "install-mode" in report.stdout

    @pytest.mark.surfaces("func")
    def test_the_boot_check_reports_a_cli_that_cannot_start(
        self, cli_run, tmp_path: Path
    ) -> None:
        """The probe drives the real entry point, not a bare app.

        `func`-only for the same reason as the test above: on the app surface
        doctor is not reached at all here.

        Constructing `FunctualizeApp` directly answers a different question: it
        boots with none of the CLI's discovery config, and reported "the app
        starts" in this very project while `func builtin version` was failing.
        """
        (tmp_path / "reserved.py").write_text(
            'JOB_GROUP = "builtin"\n\n\ndef hello():\n    """Doc."""\n    pass\n'
        )
        result = cli_run(
            ["builtin", "self", "doctor", "--format", "json"], cwd=tmp_path
        )
        payload = json.loads(result.stdout)
        boot = next(c for c in payload["checks"] if c["name"] == "boot")
        assert boot["status"] == "critical", (
            f"doctor reported boot as {boot['status']!r} in a project where the "
            "CLI cannot start"
        )


class TestItReportsTheRegistry:
    """Doctor reads the install registry — and says when an entry has gone.

    Added because sabotage found these undefended: cutting `_check_registry`
    out of `build_report` left every other doctor test green.
    """

    def _write_registry(self, xdg_dirs, *records) -> None:
        from functualize._cli import manifest as m

        config = xdg_dirs.functualize_config
        config.mkdir(parents=True, exist_ok=True)
        m.save(m.Manifest(installations=tuple(records)), m.manifest_path(config))

    def _record(self, path: str, **over):
        from functualize._cli.manifest import InstallRecord

        return InstallRecord(
            binary_path=path,
            runtime_mode=over.get("runtime_mode", "tool_uv"),
            owning_distribution="functualize",
            python_version="3.12.0",
            functualize_version=over.get("version", "1.0"),
        )

    def test_an_empty_registry_says_so(self, tmp_path: Path, xdg_dirs) -> None:
        report = build_report(cwd=tmp_path)
        assert _by_name(report, "installations") is not None

    def test_registered_installations_are_counted(
        self, tmp_path: Path, xdg_dirs
    ) -> None:
        live = tmp_path / "live-func"
        live.touch()
        self._write_registry(xdg_dirs, self._record(str(live)))

        detail = _by_name(build_report(cwd=tmp_path), "installations").detail  # type: ignore[attr-defined]
        assert "1 registered" in detail
        assert "0 stale" in detail

    def test_a_vanished_binary_is_reported_stale_and_kept(
        self, tmp_path: Path, xdg_dirs
    ) -> None:
        """AC7 — reported, never deleted. The registry is append-only."""
        live = tmp_path / "live-func"
        live.touch()
        self._write_registry(
            xdg_dirs,
            self._record(str(live)),
            self._record(str(tmp_path / "gone-func")),
        )

        report = build_report(cwd=tmp_path)
        assert "1 stale" in _by_name(report, "installations").detail  # type: ignore[attr-defined]

        stale_lines = [
            c for c in report.checks if "gone-func" in c.name and "[stale]" in c.detail
        ]
        assert stale_lines, "the vanished entry was not reported"
        assert stale_lines[0].status is CheckStatus.WARNING

        from functualize._cli import manifest as m

        still_there = m.load(m.manifest_path(xdg_dirs.functualize_config))
        assert len(still_there.installations) == 2, "doctor must not delete records"

    def test_the_running_installation_is_distinguishable(
        self, tmp_path: Path, xdg_dirs
    ) -> None:
        """AC9c — you can tell which of them is the one you just typed."""
        import sys as _sys

        running = _sys.argv[0] if _sys.argv else ""
        other = tmp_path / "other-func"
        other.touch()
        self._write_registry(xdg_dirs, self._record(running), self._record(str(other)))

        marked = [
            c for c in build_report(cwd=tmp_path).checks if "(running)" in c.detail
        ]
        assert len(marked) == 1
        assert running in marked[0].name
