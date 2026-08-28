"""How the panels render a field that belongs to the path, not to the job.

Three claims, in descending order of how much it matters that they hold:

1. **A group's credential is masked.** A group option is a config field like
   any other, so it is a credential like any other; the flag rides in on the
   cached descriptor for free, and the only way to leak one is to drop it on
   the way to the panel. Every masking test here starts from the **declared**
   ``Secret[str]`` in the shipped example, per
   `contributor/guides/wiring-discipline.md` §8 — a stub carrying
   ``secret=True`` would prove the formatter masks when told to, which is not
   the thing in doubt.
2. **A group's field is visibly a group's field**, prefixed with the group
   that declared it, and orderable and filterable by it.
3. **Nothing changes for a job with no groups above it.** The `status` control
   must render exactly as it did.
"""

from __future__ import annotations

CREDENTIAL = "hunter2-real-credential"


def _group_fields(tui, job_name: str, group_values: dict | None = None):
    from functualize._cli.tui.chain_resolution import _build_group_field_defs

    return _build_group_field_defs(tui, job_name, group_values or {})


class TestAGroupsCredentialIsMasked:
    """The security claim. Sabotage-checked: removing ``secret=`` from the
    group `FieldDef` construction in ``_build_group_field_defs`` turns both of
    these red."""

    def test_the_declared_secret_reaches_the_panel_marked(
        self, glab_tui_secret
    ) -> None:
        """Declared once, in `_options.py`. No panel code was told about it."""
        fields = {f.name: f for f in _group_fields(glab_tui_secret, "deploy.web.run")}

        assert fields["token"].secret is True
        assert fields["env"].secret is False

    def test_the_config_table_does_not_render_it(self, glab_tui_secret) -> None:
        """What a viewer actually sees in the Config Table's Value column."""
        from functualize._cli.tui.panels.config_table import ConfigTablePanel

        token = next(
            f
            for f in _group_fields(glab_tui_secret, "deploy.web.run")
            if f.name == "token"
        )
        assert token.value == CREDENTIAL, "the fixture must actually set it"

        cells = ConfigTablePanel._format_field_cells(token)
        assert CREDENTIAL not in " ".join(cells)
        assert "•" in cells[2]

    def test_the_preflight_does_not_render_it(self, glab_tui_secret) -> None:
        """And in the pre-flight summary, which is a separate formatter."""
        from functualize._cli.tui.preflight_summary import (
            format_preflight_field_line,
        )

        token = next(
            f
            for f in _group_fields(glab_tui_secret, "deploy.web.run")
            if f.name == "token"
        )
        line = format_preflight_field_line(token, {}, avail_width=120)

        assert CREDENTIAL not in line
        assert "•" in line

    def test_a_non_secret_group_field_still_renders(self, glab_tui_secret) -> None:
        """The inverse. Masking everything would also pass the tests above."""
        from functualize._cli.tui.panels.config_table import ConfigTablePanel

        env = next(
            f
            for f in _group_fields(glab_tui_secret, "deploy.web.run")
            if f.name == "env"
        )
        assert "staging" in " ".join(ConfigTablePanel._format_field_cells(env))


class TestAttributionAndOrder:
    def test_group_fields_carry_their_declaring_group(self, glab_tui) -> None:
        fields = _group_fields(glab_tui, "deploy.web.run")
        by_name = {f.name: f for f in fields}

        assert by_name["env"].group_path == "deploy"
        assert by_name["region"].group_path == "deploy.web"

    def test_outermost_group_first(self, glab_tui) -> None:
        """D-1's second half. `[deploy]` before `[deploy.web]`, matching the
        order the path itself is read in."""
        paths = [f.group_path for f in _group_fields(glab_tui, "deploy.web.run")]
        assert paths == ["deploy", "deploy", "deploy", "deploy.web"]

    async def test_group_rows_come_after_the_jobs_own(self, glab_tui) -> None:
        """D-1's first half, at the assembled panel: a reader meets the job's
        arguments before the path's."""
        from functualize._cli.tui.chain_resolution import build_command_panels

        async with glab_tui.run_test(size=(120, 40)) as pilot:
            glab_tui._smart_bar.value = "deploy --env prod web run v1.2"
            await pilot.pause()
            panels = build_command_panels(glab_tui)

        table = panels[0][1]
        group_paths = [f.group_path for f in table.fields]
        first_group = group_paths.index("deploy")

        assert all(p is None for p in group_paths[:first_group])
        assert all(p is not None for p in group_paths[first_group:])

    def test_the_row_shows_the_group_prefix(self, glab_tui) -> None:
        from functualize._cli.tui.panels.config_table import ConfigTablePanel

        env = next(
            f for f in _group_fields(glab_tui, "deploy.web.run") if f.name == "env"
        )
        name_cell = ConfigTablePanel._format_field_cells(env)[0]

        assert "[deploy]" in name_cell
        assert "env" in name_cell

    def test_a_job_field_gets_no_prefix(self, glab_tui) -> None:
        from functualize._cli.tui.panels.config_table import (
            ConfigTablePanel,
            FieldDef,
        )

        cell = ConfigTablePanel._format_field_cells(
            FieldDef(name="image", value="v1.2", source="cli")
        )[0]
        assert "[" not in cell


class TestFiltering:
    def test_the_config_table_filters_by_group(self, glab_tui) -> None:
        """`deploy` is what the prefix shows, so it is what someone types."""
        from functualize._cli.tui.panels.config_table import ConfigTablePanel

        panel = ConfigTablePanel()
        panel.set_fields([*_group_fields(glab_tui, "deploy.web.run")])
        panel.apply_filter("deploy.web")

        assert [f.name for f in panel._filtered_fields] == ["region"]

    def test_the_config_table_still_filters_by_field_name(self, glab_tui) -> None:
        from functualize._cli.tui.panels.config_table import ConfigTablePanel

        panel = ConfigTablePanel()
        panel.set_fields(_group_fields(glab_tui, "deploy.web.run"))
        panel.apply_filter("env")

        assert [f.name for f in panel._filtered_fields] == ["env"]

    def test_the_job_browser_shows_the_spaced_command(self) -> None:
        from functualize._cli.tui.panels.job_browser import _display_command

        assert _display_command("deploy.web.run") == "deploy web run"
        assert _display_command("status") == "status"

    def test_the_job_browser_filter_takes_all_three_separators(self) -> None:
        """Dots, spaces and hyphens all mean the same job."""
        from functualize._cli.tui.panels.job_browser import _normalize_for_filter

        target = _normalize_for_filter("deploy.web.run")
        for query in ("deploy web", "deploy.web", "deploy-web", "DEPLOY WEB"):
            assert _normalize_for_filter(query) in target


class TestTheControl:
    """X.3 — an ungrouped job must be untouched by all of the above."""

    def test_an_ungrouped_job_inherits_no_group_rows(self, glab_tui) -> None:
        assert _group_fields(glab_tui, "status") == []

    async def test_its_panel_holds_only_its_own_fields(self, glab_tui) -> None:
        from functualize._cli.tui.chain_resolution import build_command_panels

        async with glab_tui.run_test(size=(120, 40)) as pilot:
            glab_tui._smart_bar.value = "status --verbose"
            await pilot.pause()
            panels = build_command_panels(glab_tui)

        table = panels[0][1]
        assert [f.name for f in table.fields] == ["verbose"]
        assert all(f.group_path is None for f in table.fields)


class TestTheSettingsPanelCannotInheritThePrefix:
    """A guard, not a behaviour.

    ``SettingsPanel`` builds its own ``FieldDef``s and has its own
    ``_populate_table``; it never calls ``ConfigTablePanel._format_field_cells``.
    That is parallel evolution, not design — a later refactor unifying the two
    renderers would start printing `[group]` prefixes on rows that have no
    group, and nothing else would catch it.
    """

    def test_it_does_not_share_the_config_tables_formatter(self) -> None:
        from functualize._cli.tui.panels.config_table import ConfigTablePanel
        from functualize._cli.tui.settings_panel import SettingsPanel

        assert not issubclass(SettingsPanel, ConfigTablePanel)
        assert "_populate_table" in vars(SettingsPanel)
        assert "_format_field_cells" not in vars(SettingsPanel)

    def test_its_fields_carry_no_group(self) -> None:
        """Whatever it builds, nothing in it is a group's field."""
        import inspect

        from functualize._cli.tui import settings_panel

        source = inspect.getsource(settings_panel)
        assert "group_path" not in source
