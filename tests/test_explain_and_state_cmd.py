"""Tests for `func why`/`--explain` rendering and `func state` (S3/T21).

Also pins the §D.3 Fix 2 lifecycle boundary: clearing runtime state must not
touch the discovery cache, and clearing the cache must not drop fingerprints.
"""

from __future__ import annotations

import pytest

from functualize._engine.explain import HEADLINES, render_dep_line, render_verdict
from functualize._engine.guards import GuardState, GuardVerdict
from functualize._primitives.state_store import StateStore


class TestRenderVerdict:
    def test_headline_names_the_job_and_outcome(self) -> None:
        out = render_verdict("deploy", GuardVerdict(GuardState.RUN, "no guard skipped"))
        assert out.splitlines()[0] == "deploy → WOULD RUN"

    def test_every_state_has_a_headline(self) -> None:
        for state in GuardState:
            assert state in HEADLINES

    def test_skip_states_are_distinguishable(self) -> None:
        # CI must be able to tell "not applicable" from "already done" from
        # "up to date" (§D.2).
        headlines = {
            HEADLINES[GuardState.SKIP_NEUTRAL],
            HEADLINES[GuardState.SKIP_SATISFIED],
            HEADLINES[GuardState.SKIP_FRESH],
        }
        assert len(headlines) == 3

    def test_check_trace_is_rendered_in_order(self) -> None:
        verdict = GuardVerdict(
            GuardState.RUN,
            "sources changed",
            checks=("platforms  linux ✓", "preconditions  docker --version ✓"),
        )
        lines = render_verdict("deploy", verdict).splitlines()
        assert lines[1].strip() == "platforms  linux ✓"
        assert lines[2].strip() == "preconditions  docker --version ✓"

    def test_reason_is_shown_when_not_already_in_a_check(self) -> None:
        out = render_verdict("deploy", GuardVerdict(GuardState.RUN, "sources changed"))
        assert "reason  sources changed" in out

    def test_reason_is_not_duplicated(self) -> None:
        verdict = GuardVerdict(
            GuardState.SKIP_FRESH,
            "3 sources unchanged",
            checks=("fingerprint  3 sources unchanged",),
        )
        out = render_verdict("deploy", verdict)
        assert out.count("3 sources unchanged") == 1

    def test_blocked_names_the_awaited_model(self) -> None:
        class Approval:
            pass

        out = render_verdict(
            "deploy", GuardVerdict(GuardState.BLOCKED, "gate", awaiting=Approval)
        )
        assert "awaiting  Approval" in out

    def test_deps_summary_line(self) -> None:
        deps = [
            render_dep_line("lint", GuardVerdict(GuardState.SKIP_FRESH, "fresh")),
            render_dep_line("test", GuardVerdict(GuardState.RUN, "stale")),
        ]
        out = render_verdict("deploy", GuardVerdict(GuardState.RUN, "x"), deps=deps)
        assert "deps  lint ✓ fresh · test → will run first" in out

    def test_error_headline(self) -> None:
        out = render_verdict(
            "deploy", GuardVerdict(GuardState.ERROR, "Docker required")
        )
        assert "ERROR" in out.splitlines()[0]
        assert "Docker required" in out


class TestRenderDepLine:
    @pytest.mark.parametrize(
        ("state", "expected"),
        [
            (GuardState.SKIP_FRESH, "✓ fresh"),
            (GuardState.SKIP_NEUTRAL, "✓ skipped"),
            (GuardState.SKIP_SATISFIED, "✓ skipped"),
            (GuardState.ERROR, "✗ error"),
            (GuardState.BLOCKED, "⏸ blocked"),
            (GuardState.RUN, "→ will run first"),
        ],
    )
    def test_marker_per_state(self, state, expected) -> None:
        assert expected in render_dep_line("lint", GuardVerdict(state, ""))


class TestStateAndCacheAreIndependent:
    """§D.3 Fix 2: the two stores have different lifecycles."""

    def test_clearing_state_does_not_touch_the_cache(self, tmp_path) -> None:
        from functualize._primitives.cache_format import resolve_cache_path

        (tmp_path / ".functualize").mkdir()
        cache_path = resolve_cache_path(tmp_path)
        cache_path.write_text('{"format_version": 9, "jobs": {}}')

        store = StateStore.for_project(tmp_path)
        store.put_fingerprint("build::h::checksum", {"n": 1})
        store.clear()

        assert cache_path.exists()  # the discovery cache is untouched
        assert store.get_fingerprint("build::h::checksum") is None

    def test_deleting_the_cache_does_not_drop_fingerprints(self, tmp_path) -> None:
        from functualize._primitives.cache_format import resolve_cache_path

        (tmp_path / ".functualize").mkdir()
        cache_path = resolve_cache_path(tmp_path)
        cache_path.write_text('{"format_version": 9, "jobs": {}}')

        store = StateStore.for_project(tmp_path)
        store.put_fingerprint("build::h::checksum", {"n": 1})

        cache_path.unlink()  # `func cache clear`

        assert StateStore.for_project(tmp_path).get_fingerprint("build::h::checksum")

    def test_state_and_cache_are_different_files(self, tmp_path) -> None:
        from functualize._primitives.cache_format import resolve_cache_path
        from functualize._primitives.state_format import resolve_state_path

        (tmp_path / ".functualize").mkdir()
        assert resolve_state_path(tmp_path) != resolve_cache_path(tmp_path)


class TestStateCommandRegistration:
    def test_state_is_a_registered_builtin(self) -> None:
        from functualize._cli.builtins import BUILTIN_COMMANDS

        names = {cmd.name for cmd in BUILTIN_COMMANDS}
        assert "state" in names

    def test_state_declares_show_and_clear(self) -> None:
        from functualize._cli.builtins import BUILTIN_COMMANDS

        state = next(c for c in BUILTIN_COMMANDS if c.name == "state")
        assert {sub for sub, _desc in state.subcommands} == {"show", "clear"}

    def test_state_store_is_reachable_from_public_utils(self) -> None:
        # _cli may only import the public API — the re-export must exist.
        from functualize.app.utils import StateStore as PublicStateStore
        from functualize.app.utils import resolve_state_path

        assert PublicStateStore is StateStore
        assert callable(resolve_state_path)
