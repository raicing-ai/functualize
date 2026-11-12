"""Keys a settings document carries that the declaration does not know.

One check, one answer per file: for each layer of the settings walk, which
non-table entries the declaration does not accept there, and which declared
key the author most likely meant. Two surfaces consume it -- the annotation on
``func builtin config path`` and ``config.unknown_keys`` on
``func builtin info --json`` -- and neither decides for itself what "unknown"
means.

**No word list of its own.** "Known" is ``schema.keys_in(section)``, so the
declaration added by this feature stays the only statement of the vocabulary.
The one name that is not a setting is ``root``: the walk stops at a file that
sets it, so it is legal at the top level while being document structure rather
than a value. It arrives as the declared constant ``ROOT_KEY`` re-exported by
``functualize.plugin`` -- reading it from there keeps this module from
spelling it a second time.

**What is not checked.** Tables are skipped, not inspected: a ``[my-job]``
table names a job section, an unknown table could be one, and a table nested
in a declared section is not a key at all. Freeform sections (``aliases``)
accept any key by definition, so they are skipped whole -- without that
exemption every alias would read as unknown.

**Warn and continue.** This module only answers; it never raises, never drops
a key, and never changes an exit code. Findings are advisory text, and a
document with findings is still read exactly as before.

Imported by the surfaces that print findings, not at import time of ``_cli``:
a warm job run never touches it.
"""

from __future__ import annotations

import difflib
from collections.abc import Mapping
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from functualize.plugin import ROOT_KEY

if TYPE_CHECKING:
    from collections.abc import Sequence
    from pathlib import Path

    from functualize.plugin import AppSettingsSchema, SettingsLayer

__all__ = [
    "UnknownKey",
    "describe",
    "find_unknown_keys",
    "unknown_keys_in_layers",
]

#: How close a declared key has to be, as ``difflib``'s ratio, to be offered.
#: Below this the "did you mean" line guesses at nothing: a wrong suggestion
#: costs more than no suggestion, because it sends the author to a key they
#: did not write.
_SIMILARITY_FLOOR = 0.6


@dataclass(frozen=True)
class UnknownKey:
    """One key a settings file carries and the declaration does not accept.

    Attributes:
        file: The file the key was found in.
        key: The key as the author wrote it, dotted and relative to the
            functualize table: ``roots`` at the top level, ``cli.outptu``
            inside ``[cli]``.
        suggestion: A declared key in the same scope, or None when nothing is
            close enough to be worth naming.
    """

    file: Path
    key: str
    suggestion: str | None


def find_unknown_keys(
    table: Mapping[str, Any],
    *,
    file: Path,
    schema: AppSettingsSchema,
) -> tuple[UnknownKey, ...]:
    """Return the entries of one document the declaration does not accept.

    Findings are in document order -- the order TOML yields, top-level
    entries first, then each section's keys in the order it declares them --
    which is what ``config path``'s annotation and ``info --json`` both
    publish.

    Args:
        table: The document, already unwrapped to the functualize table: for
            ``pyproject.toml`` the caller passes ``[tool.functualize]``, so a
            sibling ``[tool.ruff]`` is not in scope to be reported.
        file: The file the table came from, carried into every finding.
        schema: The active declaration.

    Returns:
        One finding per unknown key, in document order; empty when the
        document only carries declared keys.
    """
    top_level = _top_level_keys(schema)
    findings: list[UnknownKey] = []
    for key, value in table.items():
        if _is_table(value):
            if key in schema.freeform_sections or key not in schema.sections():
                continue
            findings.extend(_section_findings(key, value, file=file, schema=schema))
            continue
        if _is_table_array(value):
            continue
        if key not in top_level:
            findings.append(UnknownKey(file, key, _suggest(key, top_level)))
    return tuple(findings)


def unknown_keys_in_layers(
    layers: Sequence[SettingsLayer],
    schema: AppSettingsSchema,
) -> tuple[UnknownKey, ...]:
    """Run :func:`find_unknown_keys` over every layer of the settings walk.

    Layers arrive in ascending precedence and findings keep that order, so the
    annotation of each line is produced next to the line it annotates. A layer
    with no values contributes nothing: a missing global file, a
    ``pyproject.toml`` without ``[tool.functualize]``, and an empty file all
    look the same here, and none of them has a key to report.
    """
    findings: list[UnknownKey] = []
    for layer in layers:
        if not layer.values:
            continue
        findings.extend(find_unknown_keys(layer.values, file=layer.path, schema=schema))
    return tuple(findings)


def describe(findings: Sequence[UnknownKey]) -> str:
    """The annotation suffix for a file's line, or ``""`` when it has none.

    The returned string starts with the separator, so a caller appends it and
    does not branch: ``print(line + describe(findings))``.
    """
    if not findings:
        return ""
    parts: list[str] = []
    for finding in findings:
        text = f'unknown key "{finding.key}"'
        if finding.suggestion:
            text += f' (did you mean "{finding.suggestion}"?)'
        parts.append(text)
    return " — " + "; ".join(parts)


def _top_level_keys(schema: AppSettingsSchema) -> frozenset[str]:
    """Top-level names a document may carry: declared keys plus ``root``."""
    return schema.keys_in("") | {ROOT_KEY}


def _section_findings(
    section: str,
    table: Mapping[str, Any],
    *,
    file: Path,
    schema: AppSettingsSchema,
) -> list[UnknownKey]:
    """Unknown scalar entries of one declared, non-freeform section."""
    known = schema.keys_in(section)
    findings: list[UnknownKey] = []
    for key, value in table.items():
        if _is_table(value) or _is_table_array(value):
            continue
        if key in known:
            continue
        suggestion = _suggest(key, known)
        findings.append(
            UnknownKey(
                file,
                f"{section}.{key}",
                f"{section}.{suggestion}" if suggestion is not None else None,
            )
        )
    return findings


def _suggest(key: str, candidates: frozenset[str]) -> str | None:
    """The closest candidate above the similarity floor, or None.

    Ties break alphabetically so the same document always produces the same
    suggestion -- an advisory line that changes between runs is worse than one
    that is slightly arbitrary.
    """
    best: tuple[float, str] | None = None
    for candidate in candidates:
        score = difflib.SequenceMatcher(None, key, candidate).ratio()
        if score < _SIMILARITY_FLOOR:
            continue
        if (
            best is None
            or score > best[0]
            or (score == best[0] and candidate < best[1])
        ):
            best = (score, candidate)
    return best[1] if best is not None else None


def _is_table(value: Any) -> bool:
    return isinstance(value, Mapping)


def _is_table_array(value: Any) -> bool:
    """A list of tables (``[[vault_secret]]``) is a table, not an entry."""
    return isinstance(value, (list, tuple)) and any(
        isinstance(item, Mapping) for item in value
    )
