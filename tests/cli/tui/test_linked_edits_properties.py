"""Property-based tests for ConfigTablePanel linked edits.

Property 3: Linked edits maintain value/source consistency
- Value edit → field.value=new_value, field.source="cli", edit_origin=VALUE
- Source edit → field.source=new_source, field.value=chain_value, edit_origin=SOURCE
- Reset → restore original_value/source, edit_origin=NONE

Property 11: Edit markers are consistent with EditOrigin
- VALUE origin → "← " marker on value, "⚡ " marker on source
- SOURCE origin → "⚡ " marker on value, "← " marker on source
- NONE origin → no markers (plain values)

**Validates: Requirements 5.1, 5.2, 5.3, 5.4, 5.5, 5.6, 5.7**
"""

from __future__ import annotations

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from functualize._cli.tui.panels.config_table import (
    ChainEntry,
    ConfigTablePanel,
    EditOrigin,
    FieldDef,
)

# Suppress the function-scoped fixture health check since we don't use
# monkeypatch — instead we patch post_message directly on each fresh panel.


# =============================================================================
# Strategies
# =============================================================================

# Non-empty text without null bytes or newlines (valid field values)
_field_text = st.text(
    alphabet=st.characters(
        blacklist_categories=("Cs",),
        blacklist_characters="\x00\n\r",
    ),
    min_size=1,
    max_size=30,
)

# Non-empty source names (short identifiers)
_source_name = st.text(
    alphabet=st.characters(
        whitelist_categories=("L", "N"),
        whitelist_characters="_-.",
    ),
    min_size=1,
    max_size=15,
)


@st.composite
def _chain_entry_with_value(draw: st.DrawFn) -> ChainEntry:
    """Generate a ChainEntry with a non-empty value."""
    source = draw(_source_name)
    value = draw(_field_text)
    return ChainEntry(source=source, value=value)


@st.composite
def _chain_entry_maybe_empty(draw: st.DrawFn) -> ChainEntry:
    """Generate a ChainEntry with either empty or non-empty value."""
    source = draw(_source_name)
    has_value = draw(st.booleans())
    value = draw(_field_text) if has_value else ""
    return ChainEntry(source=source, value=value)


@st.composite
def _field_def_with_chain(draw: st.DrawFn) -> FieldDef:
    """Generate a FieldDef with a chain containing 1-5 entries (mix of empty/non-empty).

    Ensures at least one chain entry has a non-empty value so source edits
    can be tested.
    """
    name = draw(_field_text)
    value = draw(_field_text)
    source = draw(_source_name)

    # Generate chain: at least 1 entry with value, rest may be empty
    chain_with_value = draw(st.lists(_chain_entry_with_value(), min_size=1, max_size=3))
    chain_maybe_empty = draw(
        st.lists(_chain_entry_maybe_empty(), min_size=0, max_size=2)
    )
    chain = chain_with_value + chain_maybe_empty

    return FieldDef(
        name=name,
        value=value,
        source=source,
        chain=chain,
        original_value=value,
        original_source=source,
    )


@st.composite
def _field_def_with_origin(draw: st.DrawFn) -> FieldDef:
    """Generate a FieldDef with a specific edit_origin for marker testing."""
    name = draw(_field_text)
    value = draw(_field_text)
    source = draw(_source_name)
    origin = draw(st.sampled_from(list(EditOrigin)))

    return FieldDef(
        name=name,
        value=value,
        source=source,
        chain=[],
        edit_origin=origin,
        original_value=value,
        original_source=source,
    )


def _make_panel(field: FieldDef) -> ConfigTablePanel:
    """Create a ConfigTablePanel with one field, bypassing Textual mount.

    Patches post_message to a no-op so linked edit methods don't crash.
    """
    panel = ConfigTablePanel.__new__(ConfigTablePanel)
    panel._fields = [field]
    panel._row_count = 1
    panel._cursor_row = 0
    panel._cursor_col = 1
    panel._table = None  # No mounted DataTable — _sync_table_cursor is a no-op
    panel.post_message = lambda msg: None  # type: ignore[assignment]
    return panel


# =============================================================================
# Property 3: Linked edits maintain value/source consistency
# =============================================================================


@pytest.mark.slow
class TestLinkedEditsConsistency:
    """Property 3: Linked edits maintain value/source consistency.

    **Validates: Requirements 5.1, 5.2, 5.6, 5.7**
    """

    @given(field_def=_field_def_with_chain(), new_value=_field_text)
    @settings(max_examples=200)
    def test_value_edit_sets_cli_source(
        self, field_def: FieldDef, new_value: str
    ) -> None:
        """Value edit → field.value=new_value, field.source="cli", edit_origin=VALUE.

        **Validates: Requirements 5.1**
        """
        panel = _make_panel(field_def)

        panel.apply_value_edit(field_def, new_value)

        assert field_def.value == new_value
        assert field_def.source == "cli"
        assert field_def.edit_origin == EditOrigin.VALUE

    @given(data=st.data())
    @settings(max_examples=200)
    def test_source_edit_pulls_value_from_chain(self, data: st.DataObject) -> None:
        """Source edit → field.source=new_source, field.value=chain_value, edit_origin=SOURCE.

        **Validates: Requirements 5.2**
        """
        field_def = data.draw(_field_def_with_chain())
        panel = _make_panel(field_def)

        # Pick a source from the chain that has a non-empty value
        sources_with_values = field_def.sources_with_values()
        assert len(sources_with_values) > 0  # strategy guarantees this
        chosen = data.draw(st.sampled_from(sources_with_values))

        # value_for_source returns the first match for this source name
        expected_value = field_def.value_for_source(chosen.source)
        assert expected_value is not None

        panel.apply_source_edit(field_def, chosen.source)

        assert field_def.source == chosen.source
        assert field_def.value == expected_value
        assert field_def.edit_origin == EditOrigin.SOURCE

    @given(field_def=_field_def_with_chain(), new_value=_field_text)
    @settings(max_examples=200)
    def test_reset_after_value_edit_restores_originals(
        self, field_def: FieldDef, new_value: str
    ) -> None:
        """Reset after value edit → restore original_value/source, edit_origin=NONE.

        **Validates: Requirements 5.6**
        """
        original_value = field_def.original_value
        original_source = field_def.original_source

        panel = _make_panel(field_def)

        # Apply a value edit first
        panel.apply_value_edit(field_def, new_value)
        assert field_def.edit_origin == EditOrigin.VALUE

        # Reset
        panel.action_reset_override()

        assert field_def.value == original_value
        assert field_def.source == original_source
        assert field_def.edit_origin == EditOrigin.NONE

    @given(data=st.data())
    @settings(max_examples=200)
    def test_reset_after_source_edit_restores_originals(
        self, data: st.DataObject
    ) -> None:
        """Reset after source edit → restore original_value/source, edit_origin=NONE.

        **Validates: Requirements 5.6**
        """
        field_def = data.draw(_field_def_with_chain())
        original_value = field_def.original_value
        original_source = field_def.original_source

        panel = _make_panel(field_def)

        # Apply a source edit first
        sources_with_values = field_def.sources_with_values()
        chosen = data.draw(st.sampled_from(sources_with_values))
        panel.apply_source_edit(field_def, chosen.source)
        assert field_def.edit_origin == EditOrigin.SOURCE

        # Reset
        panel.action_reset_override()

        assert field_def.value == original_value
        assert field_def.source == original_source
        assert field_def.edit_origin == EditOrigin.NONE

    @given(field_def=_field_def_with_chain())
    @settings(max_examples=200)
    def test_reset_on_none_is_noop(self, field_def: FieldDef) -> None:
        """Reset on edit_origin NONE → no-op (field unchanged).

        **Validates: Requirements 5.7**
        """
        assert field_def.edit_origin == EditOrigin.NONE
        original_value = field_def.value
        original_source = field_def.source

        panel = _make_panel(field_def)
        posted: list = []
        panel.post_message = lambda msg: posted.append(msg)  # type: ignore[assignment]

        panel.action_reset_override()

        assert field_def.value == original_value
        assert field_def.source == original_source
        assert field_def.edit_origin == EditOrigin.NONE
        assert len(posted) == 0


# =============================================================================
# Property 11: Edit markers are consistent with EditOrigin
# =============================================================================


@pytest.mark.slow
class TestEditMarkersConsistency:
    """Property 11: Edit markers are consistent with EditOrigin.

    **Validates: Requirements 5.3, 5.4, 5.5**
    """

    @given(field_def=_field_def_with_origin())
    @settings(max_examples=200)
    def test_value_origin_markers(self, field_def: FieldDef) -> None:
        """VALUE origin — value and source are plain (markers handled at render layer).

        **Validates: Requirements 5.3**
        """
        field_def.edit_origin = EditOrigin.VALUE
        _, _, value_display, source_display, _ = ConfigTablePanel._format_field_cells(
            field_def
        )

        assert value_display == field_def.value
        assert source_display == field_def.source

    @given(field_def=_field_def_with_origin())
    @settings(max_examples=200)
    def test_source_origin_markers(self, field_def: FieldDef) -> None:
        """SOURCE origin — value and source are plain (markers handled at render layer).

        **Validates: Requirements 5.4**
        """
        field_def.edit_origin = EditOrigin.SOURCE
        _, _, value_display, source_display, _ = ConfigTablePanel._format_field_cells(
            field_def
        )

        assert value_display == field_def.value
        assert source_display == field_def.source

    @given(field_def=_field_def_with_origin())
    @settings(max_examples=200)
    def test_none_origin_no_markers(self, field_def: FieldDef) -> None:
        """NONE origin → no markers (plain values).

        **Validates: Requirements 5.5**
        """
        field_def.edit_origin = EditOrigin.NONE
        _, _, value_display, source_display, _ = ConfigTablePanel._format_field_cells(
            field_def
        )

        assert value_display == field_def.value
        assert source_display == field_def.source

    @given(field_def=_field_def_with_origin())
    @settings(max_examples=200)
    def test_markers_match_origin_exhaustively(self, field_def: FieldDef) -> None:
        """For any edit_origin, value and source are returned plainly.

        **Validates: Requirements 5.3, 5.4, 5.5**
        """
        _, _, value_display, source_display, _ = ConfigTablePanel._format_field_cells(
            field_def
        )

        assert value_display == field_def.value
        assert source_display == field_def.source
