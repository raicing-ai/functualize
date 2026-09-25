"""The capability refusal — boot asks the store, and takes no for an answer.

FUN-17/T13, acceptance criterion 3's second half. A store's profile says
what it can do; the configuration says what this project needs; and when
the two disagree, selection refuses — naming the store, the field and the
config key — rather than proceeding with the store anyway. A silent
downgrade is the failure mode ``StoreProfile`` exists to make impossible.

The refusal is exercised against the real shipped profile
(``DOCUMENT_PROFILE``) with ``multi_machine`` — the capability absent from
every measured column of the capability matrix, so no future backend
correction can make this test vacuous.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from functualize._app import boot
from functualize._primitives.document_store import DOCUMENT_PROFILE
from functualize._types.errors import RuntimeStoreCapabilityError

_RESUME_ACROSS_RUNNERS = boot.RequiredCapability(
    field="multi_machine",
    value=True,
    config_key="workflow.resume_across_runners",
    because="workflow resume across runners was configured",
)


class TestTheRefusal:
    def test_an_absent_capability_refuses_naming_store_field_and_key(
        self,
    ) -> None:
        with pytest.raises(RuntimeStoreCapabilityError) as raised:
            boot.check_required_capabilities(
                DOCUMENT_PROFILE, {"multi_machine": _RESUME_ACROSS_RUNNERS}
            )

        error = raised.value
        assert error.store == DOCUMENT_PROFILE.name
        assert error.field == "multi_machine"
        assert error.config_key == "workflow.resume_across_runners"
        assert error.needed is True and error.actual is False
        message = str(error)
        assert DOCUMENT_PROFILE.name in message
        assert "multi_machine" in message
        assert "workflow.resume_across_runners" in message

    def test_a_capability_the_store_has_does_not_refuse(self) -> None:
        """`fencing` is a Literal, not a bool — it must compare just as well."""
        requirements = {
            "offline_capable": boot.RequiredCapability(
                field="offline_capable",
                value=True,
                config_key="general.offline",
                because="the offline binary is why the binary exists",
            ),
            "fencing": boot.RequiredCapability(
                field="fencing",
                value="cross-process",
                config_key="workflow.fencing",
                because="a stale writer must be refused from any process",
            ),
        }
        boot.check_required_capabilities(DOCUMENT_PROFILE, requirements)

    def test_no_requirements_no_refusal(self) -> None:
        boot.check_required_capabilities(DOCUMENT_PROFILE, {})


class TestTheRefusalIsInsideSelection:
    def test_selection_itself_refuses_rather_than_returning_a_store(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The production call path: both boot paths reach the refusal here.

        ``_select_runtime_store`` is what ``boot_static`` and
        ``boot_standard`` both call at step 6.5, so a requirement the shipped
        store lacks must abort *selection* — the ``pytest.raises`` is the
        no-fallback: there is no weaker store handed back and no log line
        that carries on. Today no shipped config key declares a requirement
        (``_required_capabilities`` is empty and says why), so the monkeypatch
        stands in for the first feature that does.
        """
        monkeypatch.setattr(
            boot,
            "_required_capabilities",
            lambda app: {"multi_machine": _RESUME_ACROSS_RUNNERS},
        )
        app = SimpleNamespace(
            _substrate_claims=(), substrate_override=None, fresh_root=tmp_path
        )
        with pytest.raises(RuntimeStoreCapabilityError, match="multi_machine"):
            boot._select_runtime_store(app)
