"""`discovery_hash_for` had no test, and three ways to answer `None`.

The cache's `group_options` section describes the tree a *particular* discovery
configuration scanned. A caller running with different filters is looking at a
different tree, and `discovery_hash_for(app)` is what lets the reader refuse to
serve it someone else's answer.

`None` from this function means "cannot know", and skips that check. It used to
also mean "the attribute was renamed", "the app was a stand-in" and "something
raised" — because the body read `_discovery_config`, fell back to a
`discovery_config` with **no writer anywhere in `src/`**, and swallowed every
exception. With zero test coverage (`rg -c 'discovery_hash_for' tests/` → 0),
the failure mode was not an error: it was the check quietly no longer happening
(adj §4, and `contributor/reference/pitfalls.md` §5 — a fingerprint is only
worth the construction sites that supply it).
"""

from __future__ import annotations

import pytest

from functualize.app import DiscoveryConfig, FunctualizeApp
from functualize.app.utils import discovery_hash_for


def test_no_app_is_the_documented_cannot_know() -> None:
    """The one legitimate `None`: a caller with no app in hand."""
    assert discovery_hash_for(None) is None


def test_an_app_with_no_discovery_config_is_also_none() -> None:
    """That app declared none, so there is nothing to fingerprint."""
    app = FunctualizeApp(name="plain")

    assert discovery_hash_for(app) is None


def test_an_app_with_a_discovery_config_gets_a_hash() -> None:
    app = FunctualizeApp(
        name="filtered",
        discovery_config=DiscoveryConfig(exclude_patterns=("vendor/**",)),
    )

    result = discovery_hash_for(app)

    assert isinstance(result, str)
    assert result


def test_different_filters_hash_differently() -> None:
    """The property the whole corridor exists for.

    A hash that ignored the filters would pass every test above and defeat the
    check it feeds.
    """
    narrow = FunctualizeApp(
        name="a", discovery_config=DiscoveryConfig(exclude_patterns=("vendor/**",))
    )
    wide = FunctualizeApp(
        name="b", discovery_config=DiscoveryConfig(exclude_patterns=("build/**",))
    )

    assert discovery_hash_for(narrow) != discovery_hash_for(wide)


def test_the_same_filters_hash_the_same() -> None:
    """The other half. A hash that differed per instance would refuse every
    warm cache, which is a correctness check that costs a rescan every run."""
    one = FunctualizeApp(
        name="a", discovery_config=DiscoveryConfig(exclude_patterns=("vendor/**",))
    )
    two = FunctualizeApp(
        name="b", discovery_config=DiscoveryConfig(exclude_patterns=("vendor/**",))
    )

    assert discovery_hash_for(one) == discovery_hash_for(two)


class TestSomethingThatIsNotAnAppIsLoud:
    """A stand-in used to answer `None` and disable the check silently."""

    def test_a_bare_object_raises(self) -> None:
        with pytest.raises(AttributeError, match="no `_discovery_config`"):
            discovery_hash_for(object())

    def test_the_old_second_spelling_is_not_a_way_in(self) -> None:
        """`discovery_config` was read as a fallback and written by nothing.

        An object carrying only that name is exactly the stand-in the fallback
        was supposedly for, and it is now refused rather than quietly served.
        """

        class NotAnApp:
            discovery_config = DiscoveryConfig(exclude_patterns=("vendor/**",))

        with pytest.raises(AttributeError, match="no `_discovery_config`"):
            discovery_hash_for(NotAnApp())

    def test_the_message_names_what_arrived(self) -> None:
        class Stub:
            pass

        with pytest.raises(AttributeError) as caught:
            discovery_hash_for(Stub())

        assert "Stub" in str(caught.value)


def test_every_production_caller_passes_a_real_app() -> None:
    """The premise of raising, asserted rather than assumed.

    Raising is only safe because no caller passes a stand-in. If one appears,
    this fails here rather than in that caller's user's terminal.
    """
    import re
    from pathlib import Path

    src = Path(__file__).resolve().parents[2] / "src"
    calls: list[str] = []
    for file in sorted(src.rglob("*.py")):
        for line in file.read_text(encoding="utf-8").splitlines():
            match = re.search(r"discovery_hash_for\(([^)]*)\)", line)
            if match and "def " not in line:
                calls.append(match.group(1).strip())

    assert calls, "no production caller found — did the corridor move?"
    unexpected = [arg for arg in calls if arg not in {"app", "func_app", ""}]
    assert not unexpected, (
        f"discovery_hash_for is called with {unexpected}; this test's premise "
        f"is that every caller holds a real app. Check that one before "
        f"assuming the AttributeError above is unreachable in production."
    )
