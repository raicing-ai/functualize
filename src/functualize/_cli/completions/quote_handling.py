"""Quote handling utilities for the SmartBar tokenizer.

Provides shlex-based tokenization with graceful handling of unclosed quotes,
and completion value quoting for insertion.
"""

from __future__ import annotations

import shlex


def tokenize_smart_bar(text: str) -> list[str]:
    """Tokenize SmartBar text using shlex semantics.

    Uses shlex.split() for proper quote handling. When quotes are unclosed
    (user still typing), treats everything from opening quote to end as a
    single in-progress token.

    Args:
        text: The SmartBar input text.

    Returns:
        List of token strings.
    """
    try:
        return shlex.split(text, posix=True)
    except ValueError:
        # Unclosed quote: find the opening quote and treat the rest as one token
        # Strategy: split by whitespace up to the unclosed quote, then
        # everything after is one token
        return _split_with_unclosed_quote(text)


def _split_with_unclosed_quote(text: str) -> list[str]:
    """Handle tokenization when there's an unclosed quote.

    Finds the last unmatched quote and treats everything from it to end
    as a single in-progress token.
    """
    # Find the position of the unclosed quote by scanning for unmatched quotes
    in_single = False
    in_double = False
    last_quote_pos = 0

    for i, ch in enumerate(text):
        if ch == "'" and not in_double:
            in_single = not in_single
            if in_single:
                last_quote_pos = i
        elif ch == '"' and not in_single:
            in_double = not in_double
            if in_double:
                last_quote_pos = i

    # Split text before the unclosed quote normally, then append the rest
    prefix = text[:last_quote_pos].rstrip()
    suffix = text[last_quote_pos:]

    tokens: list[str] = []
    if prefix:
        try:
            tokens = shlex.split(prefix, posix=True)
        except ValueError:
            tokens = prefix.split()

    # Remove the opening quote from the suffix for the token value
    if suffix and suffix[0] in ('"', "'"):
        tokens.append(suffix[1:])
    else:
        tokens.append(suffix)

    return tokens


def quote_for_insertion(value: str) -> str:
    """Quote a completion value for insertion into the SmartBar.

    - No spaces: return as-is
    - Has spaces but no double quotes: wrap in double quotes
    - Has spaces and double quotes: wrap in single quotes

    Args:
        value: The completion value to potentially quote.

    Returns:
        The value, quoted if necessary for safe insertion.
    """
    if " " not in value:
        return value

    if '"' not in value:
        return f'"{value}"'

    # Has both spaces and double quotes — use single quotes
    return f"'{value}'"
