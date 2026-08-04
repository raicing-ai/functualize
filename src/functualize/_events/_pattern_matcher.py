"""Internal pattern matching for perf phase filtering."""

from __future__ import annotations

import re


def parse_patterns(pattern: str) -> list[str]:
    """Split a comma-separated pattern string into individual patterns.

    Args:
        pattern: A pattern string, possibly comma-separated.

    Returns:
        List of individual trimmed pattern strings.
    """
    return [p.strip() for p in pattern.split(",") if p.strip()]


def matches_pattern(name: str, pattern: str) -> bool:
    """Check if a phase name matches a single pattern.

    Rules:
    - No '*' in pattern: prefix match (name.startswith(pattern))
    - Contains '*': glob match where '*' matches any char except '.',
      '**' matches any char including '.'

    Args:
        name: The phase name to test.
        pattern: A single pattern (no commas).

    Returns:
        True if name matches pattern.
    """
    if "*" not in pattern:
        return name.startswith(pattern)
    regex = _glob_to_regex(pattern)
    return regex.fullmatch(name) is not None


def matches_any(name: str, patterns: list[str]) -> bool:
    """Check if name matches any of the given patterns (OR semantics)."""
    return any(matches_pattern(name, p) for p in patterns)


def filter_phases(
    phase_names: list[str],
    include: str | None = None,
    exclude: str | None = None,
) -> list[str]:
    """Apply include/exclude filters to a list of phase names.

    Order: include narrows first, then exclude removes from that set.

    Args:
        phase_names: List of phase names to filter.
        include: Optional include pattern (prefix/glob/comma-separated).
        exclude: Optional exclude pattern (prefix/glob/comma-separated).

    Returns:
        Filtered list of phase names preserving original order.
    """
    result = phase_names

    if include is not None:
        include_patterns = parse_patterns(include)
        result = [n for n in result if matches_any(n, include_patterns)]

    if exclude is not None:
        exclude_patterns = parse_patterns(exclude)
        result = [n for n in result if not matches_any(n, exclude_patterns)]

    return result


def _glob_to_regex(pattern: str) -> re.Pattern[str]:
    """Convert glob pattern to regex.

    ** → .* (any chars including '.')
    *  → [^.]* (any chars except '.')
    Other chars are escaped.
    """
    parts: list[str] = []
    i = 0
    while i < len(pattern):
        if i + 1 < len(pattern) and pattern[i : i + 2] == "**":
            parts.append(".*")
            i += 2
        elif pattern[i] == "*":
            parts.append("[^.]*")
            i += 1
        else:
            parts.append(re.escape(pattern[i]))
            i += 1
    return re.compile("".join(parts))
