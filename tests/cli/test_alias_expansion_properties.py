"""Property-based tests for alias expansion correctness.

# Feature: eliminate-fallback-group
# Property 10: Alias Expansion Correctness

Tests that invoking with an alias executes the target job (not a job named
after the alias). Validates the alias expansion logic in _handle_job: the
function extracts aliases via _extract_aliases(merged_config) and expands
args[0] if it's an alias before looking up the job.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from functualize._cli.main import _extract_aliases
from functualize._types.naming import normalize_segment

# =============================================================================
# Strategies
# =============================================================================

# Characters valid for job/alias names (lowercase alphanumeric + underscore/dash)
_name_chars = st.sampled_from("abcdefghijklmnopqrstuvwxyz0123456789_-")

# A valid job or alias name. Generated text is canonicalized and empties are
# dropped, so the strategy produces names a real registry can actually hold —
# which is the premise this property depends on ("where target_job exists in
# the job registry"). Raw text produced two kinds of unreachable state:
#
#   * separator-only names ("_", "-", "__") canonicalize to "", and cannot name
#     a job at all — convention discovery skips leading-underscore functions,
#     and `@job(group="_")` is rejected with "group must be a non-empty string
#     when provided";
#   * non-canonical names ("0_") differing from a canonical one ("0") only by
#     stripped separators. Registered names are always canonical, so a registry
#     holding "0_" is a state only the MagicMock can reach — the alias path
#     normalizes its target and then compares exactly, so the mocked registry
#     missed a job the real one would have stored under the canonical name.
#
# Canonicalizing here also makes the `k != v` filter below mean *canonically*
# distinct, which is the distinctness that matters.
_valid_name = (
    st.text(_name_chars, min_size=1, max_size=20).map(normalize_segment).filter(bool)
)

# An alias mapping: dict of alias -> target job name (both non-empty, distinct)
_alias_mapping = st.dictionaries(
    keys=_valid_name,
    values=_valid_name,
    min_size=1,
    max_size=10,
).filter(lambda d: all(k != v for k, v in d.items()))

# A merged config dict containing an aliases section
_merged_config_with_aliases = _alias_mapping.map(lambda a: {"aliases": a})


# =============================================================================
# Property 10: Alias Expansion Correctness
# =============================================================================


@pytest.mark.slow
class TestAliasExpansionCorrectness:
    """Property 10: Alias Expansion Correctness.

    For any alias mapping {alias: target_job} where target_job exists in the
    job registry, invoking the CLI with the alias SHALL execute the target_job
    (not a job named after the alias).

    **Validates: Requirements 4.7, 12.3**
    """

    @given(aliases=_alias_mapping)
    def test_extract_aliases_returns_alias_mapping(
        self, aliases: dict[str, str]
    ) -> None:
        """_extract_aliases correctly extracts the aliases section from config.

        **Validates: Requirements 4.7, 12.3**
        """
        merged_config: dict[str, Any] = {"aliases": aliases}
        result = _extract_aliases(merged_config)

        assert result == aliases, f"Expected aliases={aliases}, got {result}"

    @given(aliases=_alias_mapping)
    @settings(suppress_health_check=[HealthCheck.function_scoped_fixture])
    def test_handle_job_expands_alias_to_target(
        self, aliases: dict[str, str], tmp_path: Path
    ) -> None:
        """_handle_job expands alias to target job name before lookup.

        When invoked with an alias name, _handle_job SHALL look up the
        target job name in the registry (not the alias name itself).

        **Validates: Requirements 4.7, 12.3**
        """
        # Pick the first alias -> target pair for this test
        alias_name = next(iter(aliases))
        target_job = aliases[alias_name]

        # Build merged_config with the alias mapping
        merged_config: dict[str, Any] = {"aliases": aliases}
        effective: dict[str, list[str]] = {
            "jobs_directories": [],
            "import_libs": [],
        }

        # Create a mock job descriptor for the TARGET job
        mock_job = MagicMock()
        mock_job.name = target_job
        mock_job.function = lambda: None

        # Mock FunctualizeApp to return the target job
        mock_app = MagicMock()
        mock_app.get_jobs.return_value = [mock_job]

        mock_cli_config = MagicMock()
        mock_cli_config.scan_depth = 0
        mock_cli_config.discovery = MagicMock()
        mock_cli_config.dotenv = False
        mock_cli_config.dotenv_path = None

        with (
            patch(
                "functualize._cli.config.resolve_cli_config",
                return_value=mock_cli_config,
            ),
            patch(
                "functualize.app.utils.auto_discover",
                return_value=MagicMock(),
            ),
            patch(
                "functualize.app.FunctualizeApp",
                return_value=mock_app,
            ),
            patch(
                "functualize.app.adapters.click_params.create_job_click_command",
                return_value=MagicMock(),
            ) as mock_create_cmd,
            patch(
                "functualize._cli.main._apply_import_libs",
            ),
        ):
            with patch(
                "functualize.app.adapters.click_params.invoke_command_capturing",
                return_value=0,
            ):
                from functualize._cli.main import _handle_job

                _handle_job(
                    args=[alias_name],
                    anchor=tmp_path,
                    merged_config=merged_config,
                    effective=effective,
                    cli_flags={},
                )

            # Verify create_job_command was called with the TARGET job name
            # (not the alias name)
            mock_create_cmd.assert_called_once()
            call_kwargs = mock_create_cmd.call_args
            # create_job_command is called with name=target_job
            called_name = call_kwargs.kwargs.get("name")
            assert called_name == target_job, (
                f"Expected create_job_command to be called with "
                f"name='{target_job}' (target), but got name='{called_name}'. "
                f"Alias '{alias_name}' should have been expanded."
            )

    @given(aliases=_alias_mapping)
    @settings(suppress_health_check=[HealthCheck.function_scoped_fixture])
    def test_alias_expansion_never_executes_alias_named_job(
        self, aliases: dict[str, str], tmp_path: Path
    ) -> None:
        """When alias is provided, the job registry lookup uses target name.

        Even if a job exists with the alias name, the target job is what
        gets executed (detect_mode handles shadowing; _handle_job always
        expands through the alias mapping).

        **Validates: Requirements 4.7, 12.3**
        """
        alias_name = next(iter(aliases))
        target_job = aliases[alias_name]

        merged_config: dict[str, Any] = {"aliases": aliases}
        effective: dict[str, list[str]] = {
            "jobs_directories": [],
            "import_libs": [],
        }

        # Create job descriptors for BOTH alias-named and target jobs
        mock_alias_job = MagicMock()
        mock_alias_job.name = alias_name
        mock_alias_job.function = lambda: "alias_job_executed"

        mock_target_job = MagicMock()
        mock_target_job.name = target_job
        mock_target_job.function = lambda: "target_job_executed"

        # Return both jobs from the registry
        mock_app = MagicMock()
        mock_app.get_jobs.return_value = [mock_alias_job, mock_target_job]

        mock_cli_config = MagicMock()
        mock_cli_config.scan_depth = 0
        mock_cli_config.discovery = MagicMock()
        mock_cli_config.dotenv = False
        mock_cli_config.dotenv_path = None

        with (
            patch(
                "functualize._cli.config.resolve_cli_config",
                return_value=mock_cli_config,
            ),
            patch(
                "functualize.app.utils.auto_discover",
                return_value=MagicMock(),
            ),
            patch(
                "functualize.app.FunctualizeApp",
                return_value=mock_app,
            ),
            patch(
                "functualize.app.adapters.click_params.create_job_click_command",
                return_value=MagicMock(),
            ) as mock_create_cmd,
            patch(
                "functualize._cli.main._apply_import_libs",
            ),
        ):
            with patch(
                "functualize.app.adapters.click_params.invoke_command_capturing",
                return_value=0,
            ):
                from functualize._cli.main import _handle_job

                _handle_job(
                    args=[alias_name],
                    anchor=tmp_path,
                    merged_config=merged_config,
                    effective=effective,
                    cli_flags={},
                )

            # The key assertion: create_job_command MUST be called with
            # the target job name, NOT the alias name
            mock_create_cmd.assert_called_once()
            call_kwargs = mock_create_cmd.call_args
            called_name = call_kwargs.kwargs.get("name")
            assert called_name == target_job, (
                f"Alias expansion failed: expected target '{target_job}' "
                f"but create_job_command was called with name='{called_name}'. "
                f"Alias '{alias_name}' should expand to '{target_job}'."
            )

    @given(
        config_data=st.dictionaries(
            keys=st.text(st.characters(codec="ascii"), min_size=1, max_size=10),
            values=st.one_of(st.integers(), st.text(min_size=0, max_size=10)),
            max_size=5,
        )
    )
    def test_extract_aliases_returns_empty_for_missing_section(
        self, config_data: dict[str, Any]
    ) -> None:
        """_extract_aliases returns empty dict when aliases section is absent.

        **Validates: Requirements 4.7, 12.3**
        """
        # Ensure no 'aliases' key of dict type exists
        config_data.pop("aliases", None)
        result = _extract_aliases(config_data)

        assert result == {}, (
            f"Expected empty dict for config without aliases, got {result}"
        )

    @given(
        bad_aliases=st.one_of(
            st.integers(),
            st.text(min_size=0, max_size=10),
            st.lists(st.text(min_size=1, max_size=5), max_size=5),
            st.none(),
        )
    )
    def test_extract_aliases_returns_empty_for_non_dict_value(
        self, bad_aliases: Any
    ) -> None:
        """_extract_aliases returns empty dict when aliases value is not a dict.

        **Validates: Requirements 4.7, 12.3**
        """
        merged_config: dict[str, Any] = {"aliases": bad_aliases}
        result = _extract_aliases(merged_config)

        assert result == {}, (
            f"Expected empty dict for non-dict aliases value {bad_aliases!r}, "
            f"got {result}"
        )
