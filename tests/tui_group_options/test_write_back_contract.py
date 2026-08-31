"""The write-back contract, and the blind spots that hid nine more defects.

`test_smartbar_roundtrip.py` proved `emit(resolve(text)) == text` for text the
user *types*. That is one of the two ways bar text is produced. The other is
the panel writing it back, and every defect below lived on that side.

Each class here is named for the **shape of the gap** that let one through, not
just for the behaviour it pins, because the shapes recur:

* `TestThePanelTheBuilderActuallyProduces` — the old D1 test hand-built its
  `FieldDef` list. Once `build_command_panels` started emitting a second *kind*
  of row, the stub stopped resembling its output and the test went on passing.
* `TestReadinessAgreesWithClick` — "which flags does this job accept?" was
  audited once, by hand, against `--help` for the jobs that happened to exist.
  Here it is derived from the same param builder the CLI runs, per field shape.
* `TestBothSidesOfTheTrieGate` — behaviour gated on `trie is not None` was only
  ever exercised with the trie armed. The X.3 control proves an ungrouped *job*
  is unaffected and says nothing about a *builtin*.
* `TestTheFixedPointOverValuesNotJustLines` — a hand-written table of four
  whitespace-free lines tests the table, not the property.
"""

from __future__ import annotations

import pytest

from functualize._cli.tui.cli_arg_parser import tokenize_bar_text


def _evaluate(app, text: str):
    """Readiness for `text`, wired exactly as `on_input_changed` wires it."""
    tokens = tokenize_bar_text(text)
    resolution = app.resolve_command(tokens)
    readiness = app._smart_bar.evaluate(
        tokens,
        app._get_command_names(),
        app._get_required_fields,
        get_fields=app._get_job_fields,
        resolution=resolution,
        is_non_job_command=app._is_non_job_command,
    )
    return readiness, app._smart_bar._validity_reason


async def _place_real_panel(app, pilot, bar_text: str):
    """Build the command panels the way the app does and mount the config table.

    Deliberately **not** a hand-built field list. The whole reason the group
    write-back defect survived a green suite is that the test that would have
    caught it constructed its own two-row stub, which could not grow a
    `group_path` when the builder learned to emit one.
    """
    from functualize._cli.tui.chain_resolution import build_command_panels
    from functualize._cli.tui.panels.config_table import ConfigTablePanel

    app._smart_bar.value = bar_text
    await pilot.pause()
    panels = build_command_panels(app)
    table = next(p for _title, p in panels if isinstance(p, ConfigTablePanel))
    app._panel_host.set_panels(panels)
    app._active_ring = "command"
    return table


def _row(table, name: str, group_path: str | None):
    return next(
        f for f in table.fields if f.name == name and f.group_path == group_path
    )


class TestThePanelTheBuilderActuallyProduces:
    """D1's gap: the write-back was tested against a stub, not against the rows.

    `sync_overrides_to_bar` was handed the panel's whole field list and emitted
    every edited row as one of the *job's* flags. For a group row that produces
    `deploy web run v1.2 -e prod`, which the walk reads as a job flag named
    `env` — there is no such flag, the value comes back as `{}`, and the job
    runs on the group's unedited value. Nothing errors anywhere.

    Routing every writer through one emitter (ADR-009 §1) does not prevent
    this on its own: the emitter places a flag correctly only if it is told
    which kind the flag is. The partition is the invariant, not the funnel.
    """

    async def test_editing_a_group_row_writes_the_flag_mid_path(self, glab_tui) -> None:
        async with glab_tui.run_test(size=(140, 40)) as pilot:
            table = await _place_real_panel(glab_tui, pilot, "deploy web run v1.2")
            await pilot.pause()

            table.apply_value_edit(_row(table, "env", "deploy"), "prod")
            glab_tui._sync_smartbar_from_fields()
            await pilot.pause()

            text = glab_tui._smart_bar.value
            resolution = glab_tui.resolve_command(tokenize_bar_text(text))

        assert text == "deploy --env prod web run v1.2"
        # The half a position-only assertion would miss: the value has to come
        # back as the *group's*, not merely appear somewhere on the line.
        assert resolution.job_name == "deploy.web.run"
        assert resolution.group_values == {"env": "prod"}
        assert resolution.args == ["v1.2"]

    async def test_editing_the_deeper_groups_row_lands_at_its_own_segment(
        self, glab_tui
    ) -> None:
        """Two levels: `--region` belongs beside `web`, not beside `deploy`."""
        async with glab_tui.run_test(size=(140, 40)) as pilot:
            table = await _place_real_panel(glab_tui, pilot, "deploy web run v1.2")
            await pilot.pause()

            table.apply_value_edit(_row(table, "region", "deploy.web"), "eu-west-1")
            glab_tui._sync_smartbar_from_fields()
            await pilot.pause()
            text = glab_tui._smart_bar.value

        assert text == "deploy web --region eu-west-1 run v1.2"

    async def test_editing_a_job_row_keeps_the_groups_flags(self, glab_tui) -> None:
        """The symmetric half: a job edit must not drop what the group holds."""
        async with glab_tui.run_test(size=(140, 40)) as pilot:
            table = await _place_real_panel(
                glab_tui, pilot, "deploy --env prod web run v1.2"
            )
            await pilot.pause()

            table.apply_value_edit(_row(table, "replicas", None), "3")
            glab_tui._sync_smartbar_from_fields()
            await pilot.pause()
            text = glab_tui._smart_bar.value

        assert text == "deploy --env prod web run v1.2 --replicas 3"

    async def test_resetting_a_group_row_removes_its_flag(self, glab_tui) -> None:
        """CTE.3, which had no test at all.

        Two things had to be true and neither was: the row must *carry* an edit
        origin (a bar-typed value arrived marked `NONE`, so `r` hit the panel's
        own no-op guard and never fired), and the reset must reach the group's
        values rather than `clear_override`, which looks only at the job's.
        """
        async with glab_tui.run_test(size=(140, 40)) as pilot:
            table = await _place_real_panel(
                glab_tui, pilot, "deploy --env prod web run v1.2"
            )
            await pilot.pause()

            env = _row(table, "env", "deploy")
            assert env.value == "prod"
            table._cursor_row = table.fields.index(env)
            table.action_reset_override()
            glab_tui._sync_smartbar_from_fields()
            await pilot.pause()
            text = glab_tui._smart_bar.value

        assert text == "deploy web run v1.2"
        # The reset restores the group's own resolved layer rather than
        # blanking the row — `[deploy] env = "staging"` in the example.
        assert env.value == "staging"

    @pytest.mark.parametrize(
        "text",
        [
            "deploy web run v1.2",
            "deploy --env prod web run v1.2",
            "deploy --env prod web --region eu-west-1 run v1.2",
            "deploy --dry-run web run v1",
        ],
    )
    async def test_every_editable_row_survives_a_write_back(
        self, glab_tui, text
    ) -> None:
        """The generalisation, over the rows the builder really emits.

        For each row in turn: edit it, write the bar back, and require that the
        result still resolves to the same job with the same partition. A single
        hand-picked row cannot cover a list whose *kinds* differ.
        """
        async with glab_tui.run_test(size=(140, 40)) as pilot:
            for index in range(
                len((await _place_real_panel(glab_tui, pilot, text)).fields)
            ):
                table = await _place_real_panel(glab_tui, pilot, text)
                await pilot.pause()
                field = table.fields[index]
                if field.secret:
                    continue  # a credential's value is not typed into the bar
                # A bool is a presence flag on the way out and `True` on the
                # way back — probing it with a string would assert the wrong
                # contract, not find a defect.
                is_bool = (field.type_annotation or "") == "bool"
                probe = "true" if is_bool else "probe-value"
                expected: object = True if is_bool else "probe-value"
                table.apply_value_edit(field, probe)
                glab_tui._sync_smartbar_from_fields()
                await pilot.pause()

                written = glab_tui._smart_bar.value
                resolution = glab_tui.resolve_command(tokenize_bar_text(written))

                assert resolution.job_name == "deploy.web.run", (
                    f"editing {field.name!r} (group={field.group_path!r}) wrote "
                    f"{written!r}, which no longer names the job"
                )
                where = (
                    resolution.group_values
                    if field.group_path
                    else glab_tui.job_kwargs_for("deploy.web.run", resolution.args)
                )
                assert where.get(field.name) == expected, (
                    f"editing {field.name!r} (group={field.group_path!r}) wrote "
                    f"{written!r}; the value did not come back as its own kind"
                )


class TestReadinessAgreesWithClick:
    """The bar's "would this run?" against the params the CLI actually builds.

    ADR-009 §7 records that the `--no-` trap was found "by comparing the
    shell's notion of a valid flag against real `--help` output for every job
    in every example project". That comparison was a **one-off, by hand**, over
    the field shapes those projects happen to contain — so it caught the plain
    bool and missed two: a bool carrying a short flag has no `--no-` pair at
    all, and a positional is a `click.Argument` with no flag spelling.

    Derived here from `build_click_params_from_fields`, so the day the param
    builder changes a rule, this says so.
    """

    @staticmethod
    def _click_flags(app, job_name: str) -> set[str]:
        """Every `--spelling` and `-s` click really accepts for this job."""
        from functualize.app.adapters.click_params import (
            build_click_params_from_fields,
        )

        flags: set[str] = set()
        for param in build_click_params_from_fields(app._get_job_fields(job_name)):
            for opt in getattr(param, "opts", []) or []:
                flags.add(opt)
            for opt in getattr(param, "secondary_opts", []) or []:
                flags.add(opt)
        return {f for f in flags if f.startswith("-")}

    @pytest.mark.parametrize(
        "fixture_name,job_name,command",
        [
            ("glab_tui", "deploy.web.run", "deploy web run v1.2"),
            ("flag_shapes_tui", "shapes", "shapes v1.2"),
        ],
    )
    async def test_the_bar_accepts_exactly_what_click_accepts(
        self, request, fixture_name, job_name, command
    ) -> None:
        app = request.getfixturevalue(fixture_name)
        async with app.run_test(size=(140, 40)):
            accepted = self._click_flags(app, job_name)

            # Every spelling click builds must leave the bar runnable.
            for flag in sorted(accepted):
                readiness, reason = _evaluate(app, f"{command} {flag} x")
                assert readiness.name != "GREY", (
                    f"{flag} is a real click option for {job_name} but the bar "
                    f"refused it: {reason}"
                )

            # And the shapes click does *not* build must be refused. Derived,
            # not listed: a positional's `--name`, and a bool's `--no-name`
            # where click built no negative half.
            for field in app._get_job_fields(job_name):
                hyphen = field.name.replace("_", "-")
                for spelled in (f"--{hyphen}", f"--no-{hyphen}"):
                    if spelled in accepted:
                        continue
                    readiness, _ = _evaluate(app, f"{command} {spelled} x")
                    assert readiness.name == "GREY", (
                        f"{spelled} is not a click option for {job_name} "
                        f"(field {field.name!r}, positional="
                        f"{getattr(field, 'positional', False)}, short_flag="
                        f"{getattr(field, 'short_flag', None)!r}) but the bar "
                        f"reported it runnable"
                    )

    async def test_a_negative_number_is_a_value_not_a_flag(
        self, flag_shapes_tui
    ) -> None:
        """The guard the stricter check needs, or `--count -1` greys out."""
        async with flag_shapes_tui.run_test(size=(140, 40)):
            readiness, reason = _evaluate(flag_shapes_tui, "shapes v1 --count -1")
        assert readiness.name != "GREY", reason


class TestBothSidesOfTheTrieGate:
    """Behaviour gated on the trie was only ever asserted with it armed.

    Every group-options fixture boots a project that *has* a `GroupOptions`
    subclass; every pre-existing readiness test runs where the trie is `None`.
    Nothing ran a **builtin** through the armed gate, and the trie holds jobs
    only — so the walk returned "no job", readiness greyed out, and
    `action_execute` (which fires only on READY) made Enter a silent no-op for
    every builtin in the project. `_get_command_names`'s own docstring exists
    to prevent exactly that.
    """

    @pytest.mark.parametrize("fixture_name", ["glab_tui", "ungrouped_tui"])
    @pytest.mark.parametrize("text", ["builtin", "builtin env", "status"])
    async def test_a_builtin_is_runnable_either_way(
        self, request, fixture_name, text
    ) -> None:
        app = request.getfixturevalue(fixture_name)
        async with app.run_test(size=(140, 40)):
            readiness, reason = _evaluate(app, text)
        assert readiness.name == "READY", (
            f"{text!r} greyed out under {fixture_name}: {reason}"
        )

    async def test_a_group_is_still_an_invitation_not_a_command(self, glab_tui) -> None:
        """The distinction the builtin fallback must not blur."""
        async with glab_tui.run_test(size=(140, 40)):
            assert _evaluate(glab_tui, "deploy")[0].name == "GREY"
            assert _evaluate(glab_tui, "nonsense")[0].name == "GREY"


class TestTheFixedPointOverValuesNotJustLines:
    """`CANONICAL` is four hand-written, whitespace-free lines.

    The emitters call `_quoted` and wrap any value containing whitespace, so a
    quoted value is a class of output they go out of their way to produce — and
    every reader split the text on bare whitespace, which hands the opening
    quote back as part of the value and the remainder as a stray path token.
    The line then resolved to no job at all.
    """

    @pytest.mark.parametrize(
        "value", ["us east", "a  b", 'say "hi"', "trailing ", "plain"]
    )
    async def test_a_group_value_needing_quotes_round_trips(
        self, glab_tui, value
    ) -> None:
        from functualize._cli.tui.sync import build_command_line

        async with glab_tui.run_test(size=(140, 40)):
            text = build_command_line(
                "deploy.web.run", [], {"env": value}, glab_tui._group_trie
            )
            resolution = glab_tui.resolve_command(tokenize_bar_text(text))

        assert resolution.job_name == "deploy.web.run", (
            f"emitted {text!r}, which resolves to nothing"
        )
        assert resolution.group_values == {"env": value}

    async def test_a_job_value_needing_quotes_round_trips(self, glab_tui) -> None:
        from functualize._cli.tui.sync import build_command_line

        async with glab_tui.run_test(size=(140, 40)):
            text = build_command_line(
                "deploy.web.run",
                [("replicas", "two words", False, None)],
                {},
                glab_tui._group_trie,
            )
            resolution = glab_tui.resolve_command(tokenize_bar_text(text))
            kwargs = glab_tui.job_kwargs_for("deploy.web.run", resolution.args)

        assert kwargs.get("replicas") == "two words"


class TestTheConfigFilesPanelSeesEveryDeclaringGroup:
    """CF.1 was closed "by audit", and the audit had no artifact.

    The panel resolves one section — the job's — so for `deploy.web.run` it
    read `[deploy.web]` and reported `region`. `[deploy]`'s `env`, two lines up
    in the same file, did not appear. The audit was right about the shape it
    reasoned over (one level) and there was nothing left behind to re-run when
    a two-level example arrived.
    """

    async def test_every_group_section_contributes_to_the_fields_column(
        self, glab_tui
    ) -> None:
        from functualize._cli.tui.chain_resolution import build_command_panels
        from functualize._cli.tui.panels.config_files import ConfigFilesPanel

        async with glab_tui.run_test(size=(140, 40)) as pilot:
            glab_tui._smart_bar.value = "deploy web run v1.2"
            await pilot.pause()
            panels = build_command_panels(glab_tui)
            files = next(p for _t, p in panels if isinstance(p, ConfigFilesPanel))
            entries = [e for e in files._files if e.display_name == "config.base.toml"]

        assert entries, "the example's config file was not listed at all"
        fields = entries[0].fields_from_file
        assert "[deploy] env" in fields
        assert "[deploy.web] region" in fields
