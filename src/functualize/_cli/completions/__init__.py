"""Completions subpackage — all autocomplete logic.

This package consolidates cursor context parsing, flag filtering,
provenance classification, and quote handling for the SmartBar.
"""

from __future__ import annotations

from functualize._cli.completions.cursor_context import (
    CursorContext,
    parse_cursor_context,
)
from functualize._cli.completions.engine import DropdownItem, SwappableCompleter
from functualize._cli.completions.flag_filtering import (
    FlagDescriptor,
    filter_used_flags,
)
from functualize._cli.completions.provenance import (
    CompletionProvenanceClassifier,
    ProvenanceInfo,
)
from functualize._cli.completions.quote_handling import (
    quote_for_insertion,
    tokenize_smart_bar,
)

__all__: list[str] = [
    "CompletionProvenanceClassifier",
    "CursorContext",
    "DropdownItem",
    "FlagDescriptor",
    "ProvenanceInfo",
    "SwappableCompleter",
    "filter_used_flags",
    "parse_cursor_context",
    "quote_for_insertion",
    "tokenize_smart_bar",
]
