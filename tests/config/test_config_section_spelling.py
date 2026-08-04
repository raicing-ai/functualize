"""A job's config section is read under either spelling (S8/T36).

Job names are canonical (`file-cfg`), but a config file may reasonably spell
the section the way the function is spelled (`[file_cfg]`) — and every config
file written before the identity flip does. Both denote the same job, so both
are read.

Documented in the CHANGELOG as "existing config files keep working", which is
a promise worth having a test behind.
"""

from __future__ import annotations

import pytest

from functualize._config.sources import FileSource


class _Source(FileSource):
    """A FileSource over an in-memory document, bypassing file discovery."""

    def __init__(self, merged: dict) -> None:  # type: ignore[type-arg]
        self._merged_config = merged
        self._format_providers = {}
        self._discovered_paths = []
        self._per_file_configs = []
        self._file_infos = []
        self._event_bus = None


@pytest.mark.parametrize("written", ["file_cfg", "file-cfg"])
@pytest.mark.parametrize("asked", ["file_cfg", "file-cfg"])
def test_either_spelling_reads_either_section(written: str, asked: str) -> None:
    """Four combinations, all of which must find the value."""
    source = _Source({written: {"port": 9090}})

    assert source.get("port", section=asked) == 9090
    assert source.has("port", section=asked)


def test_the_canonical_section_wins_when_a_file_carries_both() -> None:
    """A file with both is ambiguous; the canonical spelling is the tie-break
    so the answer does not depend on dict ordering."""
    source = _Source({"file-cfg": {"port": 1}, "file_cfg": {"port": 2}})

    assert source.get("port", section="file-cfg") == 1


def test_an_unrelated_section_is_not_matched() -> None:
    """Normalization must not make two different jobs share config."""
    source = _Source({"other_job": {"port": 9090}})

    assert source.get("port", section="file-cfg") is None
