"""A dotted section name reaches the nested table it denotes (S6a T-GO-4).

Group option paths are dotted (`deploy.web`), and the section lookup was a
flat `merged.get(section)` — but TOML parses `[deploy.web]` into
`{"deploy": {"web": {...}}}`, so the one spelling anyone would write resolved
to nothing at all. Silent fall-through to the default is the failure mode
`FileSource` already warns about for hyphen/underscore spellings; this is the
same trap one level down.

Job names carry no dots today, so nothing that worked before changes: a flat
key spelled with a literal dot is still preferred, and the walk only runs when
neither literal lookup matched.
"""

from __future__ import annotations

from functualize._config.chain import ResolutionChain
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


def test_a_dotted_section_reads_the_nested_table() -> None:
    source = _Source({"deploy": {"web": {"env": "child"}}})

    assert source.get("env", section="deploy.web") == "child"
    assert source.has("env", section="deploy.web")


def test_the_parent_table_still_reads_its_own_keys() -> None:
    """A nested child must not shadow the parent's own values."""
    source = _Source({"deploy": {"env": "parent", "web": {"env": "child"}}})

    assert source.get("env", section="deploy") == "parent"
    assert source.get("env", section="deploy.web") == "child"


def test_a_literal_dotted_key_still_wins() -> None:
    """Some formats produce a flat key containing a dot. That spelling was
    reachable before and stays preferred — the walk is a fallback, not a
    replacement."""
    source = _Source(
        {"deploy.web": {"env": "flat"}, "deploy": {"web": {"env": "nested"}}}
    )

    assert source.get("env", section="deploy.web") == "flat"


def test_a_partial_path_does_not_resolve() -> None:
    """`deploy.web.extra` must miss rather than fall back to `deploy.web`."""
    source = _Source({"deploy": {"web": {"env": "child"}}})

    assert source.get("env", section="deploy.web.extra") is None


def test_walking_into_a_scalar_is_not_an_error() -> None:
    """`[deploy] web = "x"` makes `deploy.web` a string, not a table. The walk
    has to survive that — a malformed config file is not a crash."""
    source = _Source({"deploy": {"web": "not-a-table"}})

    assert source.get("env", section="deploy.web") is None
    assert not source.has("env", section="deploy.web")


def test_keys_reports_what_get_can_read() -> None:
    """`keys()` used the flat lookup while `get()` did not, so
    `resolve_section` would skip keys `resolve` returns. The two agree now."""
    source = _Source({"deploy": {"web": {"env": "child", "replicas": 3}}})

    assert source.keys("deploy.web") == {"env", "replicas"}


def test_resolve_section_sees_a_nested_table() -> None:
    """The end-to-end reason `keys()` matters: section-wide resolution."""
    chain = ResolutionChain([_Source({"deploy": {"web": {"env": "child"}}})])

    resolved = chain.resolve_section("deploy.web")

    assert {k: v.value for k, v in resolved.items()} == {"env": "child"}
