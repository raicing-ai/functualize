"""Property-based tests for ShortcutGenerator (Properties 5, 6).

Tests generate_shortcut_content from functualize._cli.shortcut_generator:
- Property 5: Shortcut generation produces valid syntax
- Property 6: Shortcut content preserves all kwargs

# Feature: tui-smart-bar-and-modals, Task 3.2
"""

from __future__ import annotations

import keyword
from pathlib import Path

import pytest
from hypothesis import given
from hypothesis import strategies as st

from functualize._cli.data.shortcut_generator import (
    ShortcutSpec,
    generate_shortcut_content,
)

# =============================================================================
# Strategies
# =============================================================================

# Strategy: valid Python identifiers (not keywords) for shortcut_name
_python_identifier_strategy = st.from_regex(
    r"[a-z][a-z0-9_]{0,15}", fullmatch=True
).filter(lambda name: not keyword.iskeyword(name))

# Strategy: job names
_job_name_strategy = st.text(
    alphabet="abcdefghijklmnopqrstuvwxyz_", min_size=1, max_size=15
)

# Strategy: kwargs keys — must be valid Python identifiers (not keywords)
_kwargs_key_strategy = st.from_regex(r"[a-z][a-z0-9_]{0,10}", fullmatch=True).filter(
    lambda name: not keyword.iskeyword(name)
)

# Strategy: kwargs values — alphanumeric only to avoid escape complexity
_kwargs_value_strategy = st.text(
    alphabet="abcdefghijklmnopqrstuvwxyz0123456789", min_size=0, max_size=30
)

# Strategy: kwargs dict
_kwargs_strategy = st.dictionaries(
    keys=_kwargs_key_strategy,
    values=_kwargs_value_strategy,
    min_size=0,
    max_size=5,
)


@st.composite
def _python_shortcut_spec(draw: st.DrawFn) -> ShortcutSpec:
    """Generate a valid ShortcutSpec."""
    shortcut_name = draw(_python_identifier_strategy)
    job_name = draw(_job_name_strategy)
    kwargs = draw(_kwargs_strategy)
    return ShortcutSpec(
        shortcut_name=shortcut_name,
        job_name=job_name,
        kwargs=kwargs,
        output_file=Path("/tmp/shortcuts.py"),
    )


# =============================================================================
# Property 5: Shortcut generation produces valid syntax
# =============================================================================


@pytest.mark.slow
class TestShortcutGenerationValidSyntax:
    """Property 5: Shortcut generation produces valid syntax.

    For any valid ShortcutSpec: compile(generate_shortcut_content(spec),
    "<test>", "exec") does NOT raise SyntaxError.

    **Validates: Requirements 9.1, 9.4**
    """

    @given(spec=_python_shortcut_spec())
    def test_python_format_compiles_without_error(self, spec: ShortcutSpec) -> None:
        """Python output compiles without SyntaxError.

        **Validates: Requirements 9.1, 9.4**
        """
        content = generate_shortcut_content(spec)
        # Must not raise SyntaxError
        compile(content, "<test>", "exec")


# =============================================================================
# Property 6: Shortcut content preserves all kwargs
# =============================================================================


@pytest.mark.slow
class TestShortcutContentPreservesKwargs:
    """Property 6: Shortcut content preserves all kwargs.

    For any valid ShortcutSpec, every key and every value from spec.kwargs
    appears in the generated content.

    **Validates: Requirements 9.3**
    """

    @given(spec=_python_shortcut_spec())
    def test_all_kwargs_keys_appear_in_content(self, spec: ShortcutSpec) -> None:
        """Every key from spec.kwargs appears in the generated content.

        **Validates: Requirements 9.3**
        """
        content = generate_shortcut_content(spec)
        for key in spec.kwargs:
            assert key in content, (
                f"Key {key!r} not found in generated content for spec={spec}"
            )

    @given(spec=_python_shortcut_spec())
    def test_all_kwargs_values_appear_in_content(self, spec: ShortcutSpec) -> None:
        """Every value from spec.kwargs appears in the generated content.

        **Validates: Requirements 9.3**
        """
        content = generate_shortcut_content(spec)
        for key, value in spec.kwargs.items():
            assert value in content, (
                f"Value {value!r} for key {key!r} not found in generated "
                f"content for spec={spec}"
            )
