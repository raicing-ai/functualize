"""Flag filtering logic for SmartBar completions.

Excludes single-value flags that have already been used in the current command
text, while keeping list-typed flags always available for repeated use.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class FlagDescriptor:
    """Describes a flag for filtering purposes."""

    long_name: str  # e.g., "region" (without --)
    short_name: str | None = None  # e.g., "r" (without -)
    is_list_type: bool = False  # True for list[T] typed flags


def filter_used_flags(
    all_flags: list[FlagDescriptor],
    used_tokens: list[str],
) -> list[FlagDescriptor]:
    """Filter out single-value flags that are already used.

    Args:
        all_flags: All available flag descriptors for the job.
        used_tokens: Tokens from the current command text (already parsed).

    Returns:
        Flags that should still be shown as completion candidates.
        List-typed flags are always included.
        Single-value flags are excluded if their long or short form appears in used_tokens.
    """
    # Build short-to-long mapping
    short_to_long: dict[str, str] = {}
    for flag in all_flags:
        if flag.short_name:
            short_to_long[flag.short_name] = flag.long_name

    # Build set of used flag names (normalized to long form)
    used_long_names: set[str] = set()

    for token in used_tokens:
        if token.startswith("--"):
            # Long form: --region or --region=value
            name = token[2:].split("=", 1)[0]
            used_long_names.add(name)
        elif (
            token.startswith("-") and len(token) >= 2 and not token[1:].startswith("-")
        ):
            # Short form: -r (single char after -)
            short = token[1:].split("=", 1)[0]
            if short in short_to_long:
                used_long_names.add(short_to_long[short])

    # Filter: keep list-typed flags always, exclude used single-value flags
    result: list[FlagDescriptor] = []
    for flag in all_flags:
        if flag.is_list_type or flag.long_name not in used_long_names:
            result.append(flag)

    return result
