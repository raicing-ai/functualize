"""Unit tests and Property 14 for apply_overrides_to_targets.

Tests override dispatch to file and env targets, including warning
behaviour on IOError and missing config_file_path.

Under the SmartBar-as-CLI model there is no "session"
target and no SessionOverlaySource: the whole call writes every override to a
single caller-supplied target (``"file"`` or ``"env"``). The function retains
zero production call sites (documented-but-unwired).

# Feature: tui-config-inspector, Task 5.2
"""

from __future__ import annotations

import configparser
import os
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest
from hypothesis import given
from hypothesis import strategies as st

from functualize._cli.data.override_applicator import apply_overrides_to_targets
from functualize._cli.data.pending_execution import PendingExecution
from functualize._config.chain import ResolvedValue

# =============================================================================
# Helpers
# =============================================================================


def _make_resolved_value(value: Any, field: str) -> ResolvedValue:
    """Create a minimal ResolvedValue for testing."""
    return ResolvedValue(
        value=value,
        source_type="default",
        source_id="test",
        key=field,
        alternatives=[],
    )


def _make_pending(
    job_name: str,
    overrides: dict[str, Any],
) -> PendingExecution:
    """Build a PendingExecution with given overrides written directly."""
    resolved_values = {
        field: _make_resolved_value("original", field) for field in overrides
    }
    pe = PendingExecution(job_name=job_name, resolved_values=resolved_values)
    for field, value in overrides.items():
        pe.overrides[field] = value
    return pe


# =============================================================================
# Unit Tests: env target
# =============================================================================


class TestEnvTarget:
    """Test target='env' sets os.environ with uppercase SECTION_FIELD pattern.

    **Validates: Requirements 10.4, 12.5**
    """

    @pytest.mark.asyncio
    async def test_env_target_sets_environ(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Env target sets os.environ[SECTION_FIELD] in uppercase."""
        monkeypatch.delenv("DEPLOY_ENVIRONMENT", raising=False)

        pending = _make_pending("deploy", {"environment": "staging"})

        await apply_overrides_to_targets(pending, config_file_path=None, target="env")

        assert os.environ["DEPLOY_ENVIRONMENT"] == "staging"
        monkeypatch.delenv("DEPLOY_ENVIRONMENT", raising=False)

    @pytest.mark.asyncio
    async def test_env_target_converts_value_to_str(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Env target converts non-string values to str."""
        monkeypatch.delenv("MYJOB_PORT", raising=False)

        pending = _make_pending("myjob", {"port": 8080})

        await apply_overrides_to_targets(pending, config_file_path=None, target="env")

        assert os.environ["MYJOB_PORT"] == "8080"
        monkeypatch.delenv("MYJOB_PORT", raising=False)

    @pytest.mark.asyncio
    async def test_env_changes_are_process_local(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Env changes are visible in os.environ (process-local).

        **Validates: Requirements 12.5**
        """
        monkeypatch.delenv("TESTJOB_FLAG", raising=False)

        pending = _make_pending("testjob", {"flag": "on"})

        await apply_overrides_to_targets(pending, config_file_path=None, target="env")

        assert os.environ.get("TESTJOB_FLAG") == "on"
        monkeypatch.delenv("TESTJOB_FLAG", raising=False)


# =============================================================================
# Unit Tests: file target
# =============================================================================


class TestFileTarget:
    """Test target='file' writes value to config file.

    **Validates: Requirements 10.2, 12.3**
    """

    @pytest.mark.asyncio
    async def test_file_target_writes_ini(self, tmp_path: Path) -> None:
        """File target writes the value to a config INI file."""
        config_file = tmp_path / "config.ini"

        pending = _make_pending("deploy", {"template": "./new.yaml"})

        warnings = await apply_overrides_to_targets(
            pending, config_file_path=config_file, target="file"
        )

        assert warnings == []
        assert config_file.exists()
        parser = configparser.ConfigParser(interpolation=None)
        parser.read(str(config_file))
        assert parser.get("deploy", "template") == "./new.yaml"

    @pytest.mark.asyncio
    async def test_file_target_preserves_existing(self, tmp_path: Path) -> None:
        """File target preserves existing config values in the file."""
        config_file = tmp_path / "config.ini"
        parser = configparser.ConfigParser(interpolation=None)
        parser.add_section("deploy")
        parser.set("deploy", "existing_key", "existing_value")
        with open(config_file, "w") as f:
            parser.write(f)

        pending = _make_pending("deploy", {"new_field": "new_value"})

        await apply_overrides_to_targets(
            pending, config_file_path=config_file, target="file"
        )

        result_parser = configparser.ConfigParser(interpolation=None)
        result_parser.read(str(config_file))
        assert result_parser.get("deploy", "existing_key") == "existing_value"
        assert result_parser.get("deploy", "new_field") == "new_value"


class TestFileTargetWarnings:
    """Test target='file' warning behaviour when the write cannot happen.

    **Validates: Requirements 10.3, 10.5**
    """

    @pytest.mark.asyncio
    async def test_file_target_warns_when_config_path_is_none(self) -> None:
        """File target returns a warning when config_file_path is None.

        **Validates: Requirements 10.3**
        """
        pending = _make_pending("deploy", {"template": "./t.yaml"})

        warnings = await apply_overrides_to_targets(
            pending, config_file_path=None, target="file"
        )

        assert len(warnings) == 1
        assert "template" in warnings[0]

    @pytest.mark.asyncio
    async def test_file_target_warns_on_permission_error(self, tmp_path: Path) -> None:
        """File target returns a warning on PermissionError.

        **Validates: Requirements 10.5**
        """
        pending = _make_pending("deploy", {"key": "value"})

        with patch(
            "functualize._cli.data.override_applicator._write_to_config_file",
            side_effect=PermissionError("Permission denied"),
        ):
            warnings = await apply_overrides_to_targets(
                pending, config_file_path=tmp_path / "config.ini", target="file"
            )

        assert len(warnings) == 1
        assert "key" in warnings[0]


# =============================================================================
# Property 14: Override target dispatch correctness
# =============================================================================

_field_name_st = st.text(
    alphabet=st.characters(categories=("L", "N")),
    min_size=1,
    max_size=10,
).filter(lambda s: s.isalnum())

_ini_safe_text = st.text(
    alphabet=st.characters(
        categories=("L", "N", "P", "S"),
        exclude_characters="\x00\r\n",
    ),
    min_size=1,
    max_size=20,
)

_value_st = st.one_of(
    st.integers(min_value=-1000, max_value=1000),
    _ini_safe_text,
    st.booleans(),
)

_target_st = st.sampled_from(["file", "env"])


@st.composite
def _overrides_set(draw: st.DrawFn) -> tuple[str, dict[str, Any], str]:
    """Generate a job_name, overrides dict, and a single call-wide target."""
    job_name = draw(
        st.text(
            alphabet=st.characters(categories=("L", "N")),
            min_size=1,
            max_size=10,
        ).filter(lambda s: s.isalnum())
    )
    # Case-insensitive uniqueness: both targets fold case, so `F0000` and
    # `f0000` are one setting, not two. Env keys are upper-cased into
    # `SECTION_FIELD` and configparser lower-cases option names, so generating
    # both spellings makes the second write clobber the first and the earlier
    # field's assertion read the later field's value.
    field_names = draw(
        st.lists(_field_name_st, min_size=1, max_size=8, unique_by=str.lower)
    )
    overrides: dict[str, Any] = {field: draw(_value_st) for field in field_names}
    target = draw(_target_st)
    return job_name, overrides, target


@pytest.mark.slow
class TestOverrideTargetDispatch:
    """Property 14: Override target dispatch correctness.

    All N overrides are dispatched to the single call-wide target:
    - file → written to config file
    - env → os.environ set with SECTION_FIELD pattern

    **Validates: Requirements 10.2, 10.4, 12.3, 12.5**
    """

    @given(data=_overrides_set())
    @pytest.mark.asyncio
    async def test_all_overrides_dispatched_correctly(
        self,
        data: tuple[str, dict[str, Any], str],
    ) -> None:
        """Every override dispatched to the call-wide target.

        **Validates: Requirements 10.2, 10.4**
        """
        import tempfile

        job_name, overrides, target = data
        env_keys_to_clean: list[str] = []

        try:
            with tempfile.TemporaryDirectory() as tmpdir:
                config_file = Path(tmpdir) / "config.ini"
                pending = _make_pending(job_name, overrides)

                await apply_overrides_to_targets(
                    pending, config_file_path=config_file, target=target
                )

                for field, value in overrides.items():
                    if target == "file":
                        parser = configparser.ConfigParser(interpolation=None)
                        parser.read(str(config_file))
                        assert parser.has_section(job_name), (
                            f"File target: section {job_name!r} missing"
                        )
                        assert parser.get(job_name, field) == str(value), (
                            f"File target: field {field!r} has wrong value"
                        )
                    elif target == "env":
                        env_key = f"{job_name}_{field}".upper()
                        env_keys_to_clean.append(env_key)
                        assert os.environ.get(env_key) == str(value), (
                            f"Env target: {env_key} not set correctly"
                        )
        finally:
            for key in env_keys_to_clean:
                os.environ.pop(key, None)
