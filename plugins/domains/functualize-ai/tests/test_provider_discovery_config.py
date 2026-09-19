"""The `[ai]` section is read. `plugin-taxonomy`/T9, AC-18.

`resolve_ai_provider(app=...)` guarded on `hasattr(app, "resolve_model")`, and
`resolve_model` lives on `app.configuration` — never on the app. The branch was
always False, so the section had **never** been read and every caller passing an
app silently got `AIConfig()` defaults.

This is the reachability proof for the fix, and it is deliberately written
against the *shape* of a host rather than against a booted `FunctualizeApp`: the
defect was a wrong attribute path, and a test that builds the object with the
right path is the one that would have caught it.
"""

from __future__ import annotations

from typing import Any

import pytest
from functualize_ai._provider_discovery import _ai_config_from


class _Configuration:
    def __init__(self, answer: Any) -> None:
        self.answer = answer
        self.asked: list[str] = []

    def resolve_model(self, section: str, model_class: type[object]) -> object:
        self.asked.append(section)
        if isinstance(self.answer, Exception):
            raise self.answer
        return self.answer


class _Host:
    def __init__(self, configuration: Any) -> None:
        self.configuration = configuration


def test_the_ai_section_is_actually_asked_for() -> None:
    """The assertion the old guard could never have satisfied."""
    from functualize_ai import AIConfig

    configured = AIConfig()
    configuration = _Configuration(configured)

    resolved = _ai_config_from(_Host(configuration))

    assert configuration.asked == ["ai"], (
        "the config facade was never consulted; the probe is unreachable again"
    )
    assert resolved is configured


def test_no_app_means_defaults() -> None:
    from functualize_ai import AIConfig

    assert isinstance(_ai_config_from(None), AIConfig)


def test_a_host_without_a_configuration_facade_means_defaults() -> None:
    """Not an error: the AI SDK is called from job code as well as from a host,
    and a caller with no config facade simply has no configuration."""
    from functualize_ai import AIConfig

    assert isinstance(_ai_config_from(_Host(None)), AIConfig)
    assert isinstance(_ai_config_from(object()), AIConfig)


def test_a_missing_section_falls_back_rather_than_raising() -> None:
    """A project with no `[ai]` block is the common case, not a failure."""
    from functualize_ai import AIConfig

    resolved = _ai_config_from(_Host(_Configuration(KeyError("no [ai] section"))))
    assert isinstance(resolved, AIConfig)


def test_the_old_probe_would_fail_this_file() -> None:
    """Names the defect so the test cannot be mistaken for a style check.

    `hasattr(app, "resolve_model")` is False for `_Host`, exactly as it was for
    a real app — so under the old guard `test_the_ai_section_is_actually_asked_for`
    would report an empty `asked` list.
    """
    assert not hasattr(_Host(_Configuration(None)), "resolve_model")


if __name__ == "__main__":  # pragma: no cover
    pytest.main([__file__])
