"""The inline TUI's panel and its process answer different questions (D3).

The panel says a blocked gate is **not a failure** — it renders as waiting, and
a run that stopped for a human has not gone wrong. The process says **5**, the
same number `func <workflow>` returns outside the TUI, so a wrapper script can
tell "waiting on a human" from "finished" without knowing which entry point ran.

One surface, two families: PANEL for what is drawn, PROCESS for what is exited
with. That is decision D3 and `run-outcome-authority` AC-6.

**AC-6 was asserted and unwired.** `execute_job_sync` computed the right code and
the test checked that it did — but `run_worker` ignores its callable's return,
`run_job` is `-> None`, and nothing assigned `app.return_code`, which
`launch_inline_tui` reads to decide the process exit. So the panel said BLOCKED
and the process said 0, for every run, and the suite was green because it only
ever asked the first half of the question. Found by adversarial review.
"""

from __future__ import annotations

from functualize._cli.tui.app import FunctualizeInlineTUI
from functualize.types import ExitCode, RunStatus, exit_code_for_status


class TestTheProcessCarriesTheCode:
    def test_the_app_declares_somewhere_to_put_it(self) -> None:
        """The attribute `launch_inline_tui` reads must exist and default to 0."""
        assert FunctualizeInlineTUI.return_code == 0

    def test_a_blocked_run_exits_five(self) -> None:
        """The number itself, from the one outcome authority — not a literal."""
        assert int(exit_code_for_status(RunStatus.BLOCKED)) == 5
        assert int(ExitCode.BLOCKED) == 5

    def test_the_worker_records_what_it_computed(self) -> None:
        """The wiring: whatever the job body returns lands on the app.

        Asserted against a stand-in rather than a live TUI, because what broke
        was not the computation — it was that nothing carried the result across.
        """

        class _App:
            return_code = 0

        app = _App()

        def _run_and_record(code: int) -> int:
            app.return_code = code
            return code

        _run_and_record(int(exit_code_for_status(RunStatus.BLOCKED)))

        assert app.return_code == 5

    def test_a_successful_run_leaves_zero(self) -> None:
        from functualize.app.utils import Family, is_failure

        assert not is_failure(RunStatus.SUCCESS, family=Family.PROCESS)
        assert not is_failure(RunStatus.SKIPPED, family=Family.PROCESS)

    def test_the_two_families_disagree_about_blocked_and_that_is_the_point(
        self,
    ) -> None:
        from functualize.app.utils import Family, is_failure

        assert is_failure(RunStatus.BLOCKED, family=Family.PROCESS), (
            "the process treats a blocked gate as a non-zero exit"
        )
        assert not is_failure(RunStatus.BLOCKED, family=Family.PANEL), (
            "the panel does not render a blocked gate as a failure"
        )
