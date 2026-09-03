"""The nine defects the mid-path resolver left behind, as executable claims.

`GroupOptions` shipped a resolver — ``resolve_tui_command`` — and wired it into
the TUI's **read** paths. Every **write-back** path kept parsing ``tokens[0]``
and ``tokens[1:]`` as though the SmartBar still held a flat dotted command. For
the canonical bar text::

    deploy --env prod web run v1.2

``tokens[0]`` is the *group*. One cause, nine defects.

The shape that ties them together is a **fixed point**: bar text that resolves
to a job must, when the TUI writes the bar back, come out reading the same
thing. ``emit(resolve(text)) == text``. Four of the nine are direct violations
of it; the rest are the same confusion surfacing somewhere other than the bar.

Every test here drives the shipped example (`group_options_lab`) through a real
booted app. Nothing is stubbed: a stub would prove that a function does what it
is told, when the defect is that nothing tells it.
"""

from __future__ import annotations

import pytest


def _main(item: object) -> str:
    """The visible text of a dropdown candidate, however it was built."""
    return str(getattr(item, "main", item))


# The canonical invocation table, from the example's README. Each entry is a
# line a user can type, and each must survive a write-back unchanged.
CANONICAL = [
    "deploy web run v1.2",
    "deploy --env prod web run v1.2",
    "deploy --env prod web --region eu-west-1 run v1.2",
    "deploy --dry-run web run v1",
]


class TestTheFixedPoint:
    """Text in, text out, unchanged — the property all nine defects violate."""

    @pytest.mark.parametrize("text", CANONICAL)
    async def test_the_bar_survives_a_write_back(self, glab_tui, text) -> None:
        """D2/D3. The TUI rewrites the bar whenever a value changes. What it
        writes must be text its own resolver accepts, and must not silently
        drop the group flags the user typed."""
        async with glab_tui.run_test(size=(120, 40)) as pilot:
            glab_tui._smart_bar.value = text
            await pilot.pause()

            glab_tui._sync_smartbar_from_pending()
            await pilot.pause()

            assert glab_tui._smart_bar.value == text

    async def test_the_same_name_at_two_levels_round_trips(self, collision_tui) -> None:
        """C-20, reproduced rather than believed.

        `tier` is declared at both `deploy` and `deploy.web`. The engine's
        merge is a *flat* dict keyed by field name, by design — so a job
        injecting both classes sees one value. If the emitter is going to
        write that one value back to exactly one level, the round-trip is
        what says which level, and that it is stable.
        """
        text = "deploy --tier outer web run nginx"
        async with collision_tui.run_test(size=(120, 40)) as pilot:
            collision_tui._smart_bar.value = text
            await pilot.pause()

            collision_tui._sync_smartbar_from_pending()
            await pilot.pause()

            assert collision_tui._smart_bar.value == text


class TestTheWriteBackPaths:
    """D1–D6 — the sites that parse the bar to write it back."""

    async def test_d1_editing_a_field_keeps_the_whole_command_path(
        self, glab_tui
    ) -> None:
        """`_sync_smartbar_from_fields` rebuilds the bar from `tokens[0]`,
        which for a grouped job is the outermost *group*. Editing any field
        truncates `deploy web run` to `deploy`.

        The panel is placed directly rather than through the panel action:
        `build_command_panels` resolves by `tokens[0]` too (D6), so routing
        through it would only reproduce that defect instead of this one.
        """
        from functualize._cli.tui.panels.config_table import (
            ConfigTablePanel,
            EditOrigin,
            FieldDef,
        )

        fields = [
            FieldDef(
                name="image",
                value="v1.2",
                source="cli",
                required=True,
                positional=True,
                edit_origin=EditOrigin.VALUE,
            ),
        ]

        async with glab_tui.run_test(size=(120, 40)) as pilot:
            glab_tui._smart_bar.value = "deploy web run v1.2"
            await pilot.pause()

            panel = ConfigTablePanel()
            panel.set_fields(fields)
            glab_tui._panel_host.set_panels([("Config", panel)])
            glab_tui._active_ring = "command"
            await pilot.pause()

            glab_tui._sync_smartbar_from_fields()
            await pilot.pause()

            value = glab_tui._smart_bar.value

        assert value.startswith("deploy web run"), (
            f"the command path was truncated to {value!r}"
        )

    async def test_d2_the_write_back_produces_text_its_own_reader_accepts(
        self, glab_tui
    ) -> None:
        """The pending sync emits the canonical *dotted* name — the one
        spelling ``resolve_tui_command`` deliberately refuses. The writer
        breaks its own reader."""
        async with glab_tui.run_test(size=(120, 40)) as pilot:
            glab_tui._smart_bar.value = "deploy web run v1.2"
            await pilot.pause()

            glab_tui._sync_smartbar_from_pending()
            await pilot.pause()

            written = glab_tui._smart_bar.value
            resolution = glab_tui.resolve_command(written.split())

            assert resolution.dotted_token is None, (
                f"the write-back emitted {written!r}, which its own resolver "
                f"refuses as a dotted spelling"
            )
            assert resolution.job_name == "deploy.web.run"

    async def test_d3_a_group_override_is_not_dropped(self, glab_tui) -> None:
        """`--env prod` is consumed mid-path by the resolver and then written
        nowhere, so it vanishes the first time anything rewrites the bar."""
        async with glab_tui.run_test(size=(120, 40)) as pilot:
            glab_tui._smart_bar.value = "deploy --env prod web run v1.2"
            await pilot.pause()

            glab_tui._sync_smartbar_from_pending()
            await pilot.pause()

            written = glab_tui._smart_bar.value
            resolution = glab_tui.resolve_command(written.split())

            assert resolution.group_values.get("env") == "prod", (
                f"the group override was dropped: {written!r}"
            )

    async def test_d4_a_path_segment_never_binds_to_a_positional(
        self, glab_tui
    ) -> None:
        """Silent data corruption, and the only defect here that produces a
        *wrong value* rather than a missing one.

        The bar→table sync parses everything after the first token, so for
        `deploy web run v1.2` the first bare token it sees is `web` — a path
        segment — and binds it to `image`, the job's first positional. The
        table then shows `image = web`, sourced "cli", and the command reads
        ready.

        Driven through the app rather than the function: the defect is as much
        in what the caller hands over as in what the parser does with it.
        """
        from functualize._cli.tui.panels.config_table import (
            ConfigTablePanel,
            FieldDef,
        )

        fields = [
            FieldDef(name="image", value="", source="", required=True, positional=True),
            FieldDef(name="replicas", value="1", source="default"),
        ]

        async with glab_tui.run_test(size=(120, 40)) as pilot:
            panel = ConfigTablePanel()
            panel.set_fields(fields)
            glab_tui._panel_host.set_panels([("Config", panel)])
            glab_tui._active_ring = "command"
            glab_tui._smart_bar.value = "deploy web run v1.2"
            await pilot.pause()

            glab_tui._sync_config_table_from_smartbar()
            await pilot.pause()

        assert fields[0].value != "web", (
            "a group path segment was bound to the job's positional argument"
        )
        assert fields[0].value == "v1.2"

    async def test_d5_ctrl_s_saves_the_job_not_the_group(self, glab_tui) -> None:
        """A shortcut is a generated file calling `invoke("<name>", …)`. Saving
        the group name writes one that cannot run, and folds the group's flags
        into the job's kwargs on the way."""
        captured: dict = {}

        async with glab_tui.run_test(size=(120, 40)) as pilot:
            glab_tui._smart_bar.value = "deploy --env prod web run v1.2"
            await pilot.pause()

            def _capture(modal, *args, **kwargs):
                captured["job_name"] = modal._job_name
                captured["kwargs"] = modal._kwargs

            glab_tui.push_screen = _capture  # type: ignore[method-assign]
            glab_tui.action_save_shortcut()
            await pilot.pause()

        assert captured["job_name"] == "deploy.web.run", (
            f"saved a shortcut for {captured['job_name']!r}, which is a group"
        )
        assert "env" not in captured["kwargs"], (
            "the group's flag was folded into the job's kwargs"
        )

    async def test_d6_panels_are_built_for_the_resolved_job(self, glab_tui) -> None:
        """`build_command_panels` resolves by `tokens[0]`, finds no descriptor
        for a group, and returns no panels at all for every grouped job."""
        from functualize._cli.tui.chain_resolution import build_command_panels

        async with glab_tui.run_test(size=(120, 40)) as pilot:
            glab_tui._smart_bar.value = "deploy --env prod web run v1.2"
            await pilot.pause()

            panels = build_command_panels(glab_tui)

        assert panels, "no panels were built for a grouped job"


class TestTheThreeFoundBySweep:
    """D7–D9 — the same confusion, outside the write-back paths."""

    async def test_d7_readiness_is_evaluated_against_the_resolved_job(
        self, glab_tui
    ) -> None:
        """`_get_command_names()` includes top-level *group* nodes, so `deploy`
        passes the recognition check; `get_required_fields("deploy")` then
        returns `[]` and the bar reports READY with `image` unfilled."""
        from functualize._cli.tui.bar import BarReadiness

        async with glab_tui.run_test(size=(120, 40)) as pilot:
            glab_tui._smart_bar.value = "deploy --env prod web run"
            await pilot.pause()

            readiness = glab_tui._smart_bar.readiness

        assert readiness is BarReadiness.PENDING, (
            f"bar reports {readiness} with the required `image` unfilled"
        )

    async def test_d8_missing_args_detection_runs_for_a_grouped_job(
        self, glab_tui
    ) -> None:
        """Returns `None` — "not a job" — whenever `tokens[0]` is a group,
        which silently disables the whole feature for every grouped job."""
        from functualize._cli.introspect import InProcessIntrospector
        from functualize._cli.tui.missing_args import get_missing_required_args

        introspector = InProcessIntrospector(glab_tui._func_app)
        result = await get_missing_required_args(
            introspector, ["deploy", "--env", "prod", "web", "run"]
        )

        assert result is not None, "missing-args detection was skipped entirely"
        assert result.job_name == "deploy.web.run"
        assert [f.name for f in result.missing_fields] == ["image"]

    async def test_d8_a_provided_positional_is_not_reported_missing(
        self, glab_tui
    ) -> None:
        """The other half: once `image` is typed, nothing is missing."""
        from functualize._cli.introspect import InProcessIntrospector
        from functualize._cli.tui.missing_args import get_missing_required_args

        introspector = InProcessIntrospector(glab_tui._func_app)
        result = await get_missing_required_args(
            introspector, ["deploy", "--env", "prod", "web", "run", "v1.2"]
        )

        assert result is not None
        assert result.is_executable, (
            f"still reports {[f.name for f in result.missing_fields]} missing"
        )

    def test_d9_used_flag_filtering_counts_only_the_jobs_own_tokens(
        self, collision_tui
    ) -> None:
        """`used_tokens = tokens[1:]` treats path segments and *group* flags as
        used **job** flags.

        The completion chain rewrites a walked line into ``<dotted job> <args…>``
        before handing it on, and slices the arguments off at ``len(segments)``
        — a count of *path* tokens applied to a list that also holds the flag
        tokens. Every mid-path flag shifts the cut, so path segments and the
        deeper group's own flags spill into what the job is told are its
        arguments.

        The collision project makes the consequence visible: `deploy.web`
        declares `--region` and so does the job. Typing the group's must not
        retire the job's own — they are two flags that happen to share a name,
        and the CLI already resolves the clash in the job's favour.
        """
        from functualize._cli.completions.provenance import (
            CompletionProvenanceClassifier,
        )
        from functualize._cli.tui.smart_bar_autocomplete import SmartBarAutoComplete

        app = collision_tui._func_app
        autocomplete = SmartBarAutoComplete(app, CompletionProvenanceClassifier(app))

        text = "deploy --env prod web --region eu-west-1 run --"
        offered = " ".join(
            _main(item)
            for item in autocomplete._command_mode_candidates(text, len(text))
        )

        assert "region" in offered, (
            f"the job's own `--region` was retired by the group's; offered: {offered!r}"
        )


class TestARefusalIsVisibleBeforeItIsFatal:
    """SBP.4 — position is what makes a flag the group's or the job's."""

    async def test_a_group_flag_after_the_job_is_not_ready(self, glab_tui) -> None:
        """`deploy web run v1 --env prod` is a *job* flag called `env`, and no
        such thing exists. The CLI errors on it; the bar used to call it
        Ready, which sent the user to a click error with no warning.
        """
        from functualize._cli.tui.bar import BarReadiness

        async with glab_tui.run_test(size=(120, 40)) as pilot:
            glab_tui._smart_bar.value = "deploy web run v1 --env prod"
            await pilot.pause()

            readiness = glab_tui._smart_bar.readiness
            reason = str(glab_tui._smart_bar.placeholder)

        assert readiness is not BarReadiness.READY
        assert "env" in reason

    async def test_the_same_flag_before_the_job_is_ready(self, glab_tui) -> None:
        """The control: mid-path, it is the group's and perfectly valid."""
        from functualize._cli.tui.bar import BarReadiness

        async with glab_tui.run_test(size=(120, 40)) as pilot:
            glab_tui._smart_bar.value = "deploy --env prod web run v1"
            await pilot.pause()

            readiness = glab_tui._smart_bar.readiness

        assert readiness is BarReadiness.READY

    async def test_a_jobs_negative_boolean_spelling_is_still_ready(
        self, glab_tui
    ) -> None:
        """The trap in rejecting unknown flags.

        Click renders a **job's** boolean as a pair — `--verbose/--no-verbose`
        — so the negative spelling is a flag the CLI really accepts even though
        no field is named `no_verbose`. A naive "is this a field name?" check
        greys out a valid line, and this caught exactly that against
        `discovery_lab`'s `build --no-optimize` before it shipped.
        """
        from functualize._cli.tui.bar import BarReadiness

        async with glab_tui.run_test(size=(120, 40)) as pilot:
            glab_tui._smart_bar.value = "status --no-verbose"
            await pilot.pause()

            readiness = glab_tui._smart_bar.readiness

        assert readiness is BarReadiness.READY

    async def test_a_groups_negative_boolean_spelling_is_too(self, glab_tui) -> None:
        """The asymmetry is gone, and this test is what said so.

        This cell used to pin the opposite — that a **group** boolean had no
        negative spelling, because `_flag_aliases` (`_cli/dispatch.py`) built
        the long form, the undecorated form and any short flag, and nothing
        else. Greying the line out was the bar agreeing with dispatch.

        Its own closing line was: *"Whether group booleans should gain the pair
        is a dispatch-level question this feature does not answer. If they ever
        do, this test is the one that will say so."*

        They did, in the boolean-flag-negation feature, and it did — this was
        the single failure across the group-options and TUI suites when
        dispatch learned the spelling. **Inverted rather than deleted**, so the
        record of which direction the contract moved survives in the file that
        held the old one.
        """
        from functualize._cli.tui.bar import BarReadiness

        async with glab_tui.run_test(size=(120, 40)) as pilot:
            glab_tui._smart_bar.value = "deploy --no-dry-run web run v1"
            await pilot.pause()

            readiness = glab_tui._smart_bar.readiness

        assert readiness is BarReadiness.READY

    async def test_an_undeclared_mid_path_flag_is_not_ready(self, glab_tui) -> None:
        """And a flag no ancestor declares stops the walk outright."""
        from functualize._cli.tui.bar import BarReadiness

        async with glab_tui.run_test(size=(120, 40)) as pilot:
            glab_tui._smart_bar.value = "deploy --nonsense x web run v1"
            await pilot.pause()

            readiness = glab_tui._smart_bar.readiness

        assert readiness is not BarReadiness.READY
