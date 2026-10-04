"""The example is the end-to-end test for `GateNotFoundError`.

`contributor/reference/public-api-example-coverage.md`: a symbol in a public
package's `__all__` must have at least one caller under `examples/`, and
`examples/` is collected by pytest — so the example *is* the integration
test for the API, entered through the user's own door. These tests run the
example's own functions against a real app and a real scope store, rather
than re-implementing the scenario with different code.
"""

from __future__ import annotations

from collections.abc import Generator
from pathlib import Path
from typing import TYPE_CHECKING

import pytest
from gate_refusal import (
    answer_by_declared_name,
    build_app,
    park_at_the_gate,
    the_miss_a_caller_cannot_ignore,
)

from functualize.app.utils import GateNotFoundError, ScopeStore, answer_gate

if TYPE_CHECKING:
    from functualize.app.core import FunctualizeApp


@pytest.fixture(autouse=True)
def _own_project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Generator[None]:
    """Each test parks its walk in its own project, beside its own cwd."""
    (tmp_path / ".functualize").mkdir()
    monkeypatch.chdir(tmp_path)
    yield


@pytest.fixture
def blocked() -> tuple[FunctualizeApp, ScopeStore, str]:
    app = build_app()
    park_at_the_gate(app, "rel-1")
    return app, ScopeStore(app.substrate), "rel-1"


class TestTheDeclaredSpellingAnswers:
    def test_it_records_under_the_canonical_name(
        self, blocked: tuple[FunctualizeApp, ScopeStore, str]
    ) -> None:
        app, store, scope_id = blocked

        result = answer_by_declared_name(app, store, scope_id)

        assert result["status"] == "answered"
        assert result["gate"] == "approve-refund"


class TestTheMissACallerCannotIgnore:
    def test_it_raises_with_the_roster_of_real_gates(
        self, blocked: tuple[FunctualizeApp, ScopeStore, str]
    ) -> None:
        app, store, scope_id = blocked

        with pytest.raises(GateNotFoundError) as raised:
            answer_gate(app, store, scope_id, "nope", {"approved": True})

        assert raised.value.gate == "nope"
        assert raised.value.scope_id == "rel-1"
        assert raised.value.known == ("approve-refund",)

    def test_the_user_shaped_helper_names_the_real_gates(
        self, blocked: tuple[FunctualizeApp, ScopeStore, str]
    ) -> None:
        app, store, scope_id = blocked

        report = the_miss_a_caller_cannot_ignore(app, store, scope_id)

        assert "'nope' in 'rel-1'" in report
        assert "approve-refund" in report
