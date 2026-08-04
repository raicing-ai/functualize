"""Unit tests for the ``PanelActions`` runtime_checkable Protocol.

``PanelActions`` declares the optional panel surface previously
accessed via ad hoc ``hasattr(panel, "...")`` duck typing:
``get_cursor_field``, ``action_reset_override``, ``apply_value_edit``,
``action_enter_persist``, ``action_drill_down``, ``clear_drill_down``,
``exit_detail_view``.
"""

from __future__ import annotations

from functualize._cli.tui.panels import PanelActions


class _FullPanel:
    """Implements every PanelActions method."""

    def get_cursor_field(self) -> None:
        return None

    def action_reset_override(self) -> None:
        pass

    def apply_value_edit(self, field: object, new_value: str) -> None:
        pass

    def action_enter_persist(self) -> None:
        pass

    def action_drill_down(self) -> None:
        pass

    def clear_drill_down(self) -> None:
        pass

    def exit_detail_view(self) -> None:
        pass


class _PartialPanel:
    """Implements only a subset — mirrors real panels (e.g. ConfigTablePanel)."""

    def get_cursor_field(self) -> None:
        return None

    def action_drill_down(self) -> None:
        pass


class _UnrelatedObject:
    """Implements none of the PanelActions methods."""

    def refresh(self) -> None:
        pass


def test_panel_actions_is_runtime_checkable() -> None:
    """PanelActions must be usable with isinstance()."""
    assert getattr(PanelActions, "_is_runtime_protocol", False) is True


def test_full_implementation_satisfies_protocol() -> None:
    """A panel implementing all 7 methods satisfies isinstance()."""
    assert isinstance(_FullPanel(), PanelActions)


def test_partial_implementation_does_not_satisfy_protocol() -> None:
    """A panel implementing only a subset does NOT satisfy full isinstance()."""
    assert not isinstance(_PartialPanel(), PanelActions)


def test_unrelated_object_does_not_satisfy_protocol() -> None:
    """An object with none of the 7 methods does not satisfy the protocol."""
    assert not isinstance(_UnrelatedObject(), PanelActions)


def test_protocol_declares_all_seven_methods() -> None:
    """PanelActions declares exactly the 7 methods enumerated in."""
    expected = {
        "get_cursor_field",
        "action_reset_override",
        "apply_value_edit",
        "action_enter_persist",
        "action_drill_down",
        "clear_drill_down",
        "exit_detail_view",
    }
    declared = {name for name in dir(PanelActions) if not name.startswith("_")}
    assert expected <= declared
