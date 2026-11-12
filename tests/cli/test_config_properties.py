"""Property-based tests for DiscoveryConfig TOML round-trip.

# Feature: cli-config-and-discovery-filtering, Property 1: DiscoveryConfig TOML Round-Trip
"""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

import pytest
from hypothesis import given
from hypothesis import strategies as st

from functualize.app.config import DiscoveryConfig, _validate_aliases

# =============================================================================
# Strategies: Generate valid DiscoveryConfig instances
# =============================================================================

# Strategy: non-empty strings suitable for identifiers/patterns
_identifier_str = st.from_regex(r"[a-zA-Z][a-zA-Z0-9_]{0,20}", fullmatch=True)

# Strategy: glob pattern strings (non-empty)
_glob_pattern_str = st.from_regex(r"[a-zA-Z0-9_*?/]{1,30}", fullmatch=True)

# Strategy: directory path strings (non-empty)
_directory_str = st.from_regex(r"[a-zA-Z0-9_./-]{1,40}", fullmatch=True)

# Strategy: optional string (str | None)
_optional_str = st.one_of(st.none(), _identifier_str)

# Strategy: tuple of strings for patterns/directories
_str_tuple = st.tuples().map(lambda _: ()).filter(lambda _: True) | st.lists(
    _glob_pattern_str, min_size=0, max_size=5
).map(tuple)

_dir_tuple = st.lists(_directory_str, min_size=0, max_size=5).map(tuple)

# Strategy: optional tuple of decorator names (None or non-empty tuple)
_optional_decorator_tuple = st.one_of(
    st.none(),
    st.lists(_identifier_str, min_size=1, max_size=5, unique=True).map(tuple),
)

# Strategy: generate a valid DiscoveryConfig instance
discovery_config_strategy = st.builds(
    DiscoveryConfig,
    exclude_patterns=st.lists(_glob_pattern_str, min_size=0, max_size=5).map(tuple),
    extra_directories=st.lists(_directory_str, min_size=0, max_size=5).map(tuple),
    require_file_prefix=_optional_str,
    require_file_postfix=_optional_str,
    require_file_import=_optional_str,
    require_file_marker=_optional_str,
    require_job_decorators=_optional_decorator_tuple,
    require_job_prefix=_optional_str,
    require_job_postfix=_optional_str,
)


# =============================================================================
# Helpers: TOML serialization and deserialization for DiscoveryConfig
# =============================================================================


def _escape_toml_string(s: str) -> str:
    """Escape a string for TOML basic string representation."""
    return s.replace("\\", "\\\\").replace('"', '\\"')


def _serialize_toml_value(value: object) -> str:
    """Serialize a Python value to a TOML-compatible string representation."""
    if value is None:
        # TOML has no null — we skip None fields during serialization
        raise ValueError("Cannot serialize None to TOML")
    if isinstance(value, str):
        return f'"{_escape_toml_string(value)}"'
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, tuple):
        items = ", ".join(_serialize_toml_value(item) for item in value)
        return f"[{items}]"
    if isinstance(value, list):
        items = ", ".join(_serialize_toml_value(item) for item in value)
        return f"[{items}]"
    msg = f"Unsupported type: {type(value)}"
    raise TypeError(msg)


def discovery_config_to_toml(config: DiscoveryConfig) -> str:
    """Serialize a DiscoveryConfig to a TOML string under [discovery] section."""
    lines: list[str] = ["[discovery]"]

    fields = [
        ("exclude_patterns", config.exclude_patterns),
        ("extra_directories", config.extra_directories),
        ("require_file_prefix", config.require_file_prefix),
        ("require_file_postfix", config.require_file_postfix),
        ("require_file_import", config.require_file_import),
        ("require_file_marker", config.require_file_marker),
        ("require_job_decorators", config.require_job_decorators),
        ("require_job_prefix", config.require_job_prefix),
        ("require_job_postfix", config.require_job_postfix),
    ]

    for name, value in fields:
        if value is None:
            continue
        lines.append(f"{name} = {_serialize_toml_value(value)}")

    return "\n".join(lines) + "\n"


def discovery_config_from_toml_dict(data: dict[str, object]) -> DiscoveryConfig:
    """Reconstruct a DiscoveryConfig from a parsed TOML [discovery] dict."""
    discovery = data.get("discovery", {})
    assert isinstance(discovery, dict)

    def _get_tuple(key: str) -> tuple[str, ...]:
        val = discovery.get(key)
        if val is None:
            return ()
        assert isinstance(val, list)
        return tuple(val)

    def _get_optional_str(key: str) -> str | None:
        val = discovery.get(key)
        if val is None:
            return None
        assert isinstance(val, str)
        return val

    def _get_optional_tuple(key: str) -> tuple[str, ...] | None:
        val = discovery.get(key)
        if val is None:
            return None
        assert isinstance(val, list)
        return tuple(val)

    return DiscoveryConfig(
        exclude_patterns=_get_tuple("exclude_patterns"),
        extra_directories=_get_tuple("extra_directories"),
        require_file_prefix=_get_optional_str("require_file_prefix"),
        require_file_postfix=_get_optional_str("require_file_postfix"),
        require_file_import=_get_optional_str("require_file_import"),
        require_file_marker=_get_optional_str("require_file_marker"),
        require_job_decorators=_get_optional_tuple("require_job_decorators"),
        require_job_prefix=_get_optional_str("require_job_prefix"),
        require_job_postfix=_get_optional_str("require_job_postfix"),
    )


# =============================================================================
# Property 1: DiscoveryConfig TOML Round-Trip
# =============================================================================


@pytest.mark.slow
class TestDiscoveryConfigTomlRoundTrip:
    """Property 1: DiscoveryConfig TOML Round-Trip.

    For any valid DiscoveryConfig instance, serializing it to a TOML string
    and reparsing that string back into a DiscoveryConfig SHALL produce a
    DiscoveryConfig with field values equal to the original.

    **Validates: Requirements 12.5, 21.3**
    """

    @given(config=discovery_config_strategy)
    def test_round_trip_preserves_all_fields(self, config: DiscoveryConfig):
        """Serialize DiscoveryConfig to TOML, parse back, assert equality.

        **Validates: Requirements 12.5, 21.3**
        """
        # Serialize to TOML string
        toml_str = discovery_config_to_toml(config)

        # Parse back from TOML
        parsed = tomllib.loads(toml_str)

        # Reconstruct DiscoveryConfig from parsed dict
        reconstructed = discovery_config_from_toml_dict(parsed)

        assert reconstructed == config, (
            f"Round-trip failed:\n"
            f"  original:      {config}\n"
            f"  TOML:          {toml_str!r}\n"
            f"  reconstructed: {reconstructed}"
        )

    @given(config=discovery_config_strategy)
    def test_serialized_toml_is_valid(self, config: DiscoveryConfig):
        """Serialized TOML string is always parseable by tomllib.

        **Validates: Requirements 12.5, 21.3**
        """
        toml_str = discovery_config_to_toml(config)

        # Should not raise — valid TOML
        parsed = tomllib.loads(toml_str)

        # Should always have a [discovery] section
        assert "discovery" in parsed

    @given(config=discovery_config_strategy)
    def test_none_fields_are_absent_from_toml(self, config: DiscoveryConfig):
        """Fields set to None are not serialized to the TOML output.

        **Validates: Requirements 12.5, 21.3**
        """
        toml_str = discovery_config_to_toml(config)
        parsed = tomllib.loads(toml_str)
        discovery_section = parsed.get("discovery", {})

        # Check that None fields are absent from the serialized TOML
        optional_fields = [
            ("require_file_prefix", config.require_file_prefix),
            ("require_file_postfix", config.require_file_postfix),
            ("require_file_import", config.require_file_import),
            ("require_file_marker", config.require_file_marker),
            ("require_job_decorators", config.require_job_decorators),
            ("require_job_prefix", config.require_job_prefix),
            ("require_job_postfix", config.require_job_postfix),
        ]

        for field_name, field_value in optional_fields:
            if field_value is None:
                assert field_name not in discovery_section, (
                    f"Field '{field_name}' is None but present in TOML output"
                )
            else:
                assert field_name in discovery_section, (
                    f"Field '{field_name}' is set but missing from TOML output"
                )


# =============================================================================
# Property 12: XDG Config Path Resolution
# Feature: cli-config-and-discovery-filtering, Property 12: XDG Config Path Resolution
# =============================================================================


@pytest.mark.slow
class TestXDGConfigPathResolution:
    """Property 12: XDG Config Path Resolution.

    For any value of $XDG_CONFIG_HOME (set to non-empty string, set to empty
    string, or unset), the resolved global config directory SHALL equal
    {XDG_CONFIG_HOME}/functualize when XDG_CONFIG_HOME is a non-empty string,
    and ~/.config/functualize otherwise.

    **Validates: Requirements 1.1, 1.6**
    """

    @given(
        xdg_value=st.one_of(
            # Non-empty path strings (absolute-style)
            st.from_regex(r"/[a-zA-Z0-9_/.]{1,60}", fullmatch=True),
            # Non-empty relative paths
            st.from_regex(r"[a-zA-Z0-9_/.]{1,60}", fullmatch=True),
        )
    )
    def test_nonempty_xdg_config_home_uses_xdg_path(self, xdg_value: str):
        """When XDG_CONFIG_HOME is a non-empty string, resolve_user_config_dir()
        returns Path(xdg_value) / "functualize".

        **Validates: Requirements 1.1, 1.6**
        """
        import os

        from functualize.app.utils import resolve_user_config_dir

        old = os.environ.get("XDG_CONFIG_HOME")
        try:
            os.environ["XDG_CONFIG_HOME"] = xdg_value
            result = resolve_user_config_dir()
            expected = Path(xdg_value) / "functualize"
            assert result == expected, (
                f"XDG_CONFIG_HOME={xdg_value!r} → expected {expected}, got {result}"
            )
        finally:
            if old is None:
                os.environ.pop("XDG_CONFIG_HOME", None)
            else:
                os.environ["XDG_CONFIG_HOME"] = old

    # Two inputs, so enumerate them: Hypothesis would draw the same two
    # values over and over, and parametrize reports which case failed.
    @pytest.mark.parametrize(
        ("is_empty", "xdg_desc"), [(True, '""'), (False, "<unset>")]
    )
    def test_empty_or_unset_xdg_config_home_uses_default(
        self, is_empty: bool, xdg_desc: str, monkeypatch: pytest.MonkeyPatch
    ):
        """When XDG_CONFIG_HOME is empty or unset, resolve_user_config_dir()
        returns Path.home() / ".config" / "functualize".

        **Validates: Requirements 1.1, 1.6**
        """
        from functualize.app.utils import resolve_user_config_dir

        if is_empty:
            monkeypatch.setenv("XDG_CONFIG_HOME", "")
        else:
            monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)

        result = resolve_user_config_dir()
        expected = Path.home() / ".config" / "functualize"
        assert result == expected, (
            f"XDG_CONFIG_HOME={xdg_desc} → expected {expected}, got {result}"
        )


# =============================================================================
# Feature: cli-config-and-discovery-filtering, Property 11: Alias Name Validation
# =============================================================================

# The same pattern and max length used by the implementation
_VALID_ALIAS_RE = re.compile(r"^[a-zA-Z][a-zA-Z0-9_-]*$")
_ALIAS_MAX_LEN = 32

# Strategy: arbitrary text strings (including empty, unicode, special chars)
_arbitrary_alias_name = st.text(min_size=0, max_size=50)

# Strategy: strings that are valid alias names (match pattern + length)
_valid_alias_name = st.from_regex(r"[a-zA-Z][a-zA-Z0-9_-]{0,31}", fullmatch=True)

# Strategy: strings that are definitely invalid (start with digit or special char)
_invalid_start_alias = st.from_regex(r"[^a-zA-Z].{0,30}", fullmatch=True)


@pytest.mark.slow
class TestAliasNameValidation:
    """Property 11: Alias Name Validation.

    For any string, it is a valid alias name if and only if it matches
    the regex pattern ^[a-zA-Z][a-zA-Z0-9_-]*$ and has a length of at most
    32 characters. Valid aliases SHALL be accepted; invalid aliases SHALL be
    rejected with a warning.

    **Validates: Requirements 2.3, 2.8**
    """

    @given(name=_arbitrary_alias_name)
    def test_alias_accepted_iff_matches_pattern_and_length(self, name: str):
        """Any string is accepted as an alias name iff it matches the regex
        pattern ^[a-zA-Z][a-zA-Z0-9_-]*$ AND has length ≤ 32.

        **Validates: Requirements 2.3, 2.8**
        """
        # Determine expected validity
        expected_valid = (
            bool(_VALID_ALIAS_RE.match(name)) and len(name) <= _ALIAS_MAX_LEN
        )

        # Use a valid target value so only the name is tested
        aliases_raw: dict[str, str] = {name: "some_job"}
        result = _validate_aliases(aliases_raw)

        if expected_valid:
            assert name in result, (
                f"Expected alias name '{name!r}' to be accepted "
                f"(matches pattern and len={len(name)} ≤ 32)"
            )
            assert result[name] == "some_job"
        else:
            assert name not in result, (
                f"Expected alias name '{name!r}' to be rejected "
                f"(pattern match={bool(_VALID_ALIAS_RE.match(name))}, "
                f"len={len(name)})"
            )

    @given(name=_valid_alias_name)
    def test_valid_aliases_always_accepted(self, name: str):
        """Strings matching the pattern with length ≤ 32 are always accepted.

        **Validates: Requirements 2.3, 2.8**
        """
        aliases_raw: dict[str, str] = {name: "target_job"}
        result = _validate_aliases(aliases_raw)
        assert name in result, f"Valid alias '{name!r}' was rejected"

    @given(name=_invalid_start_alias)
    def test_invalid_start_char_always_rejected(self, name: str):
        """Strings not starting with a letter are always rejected.

        **Validates: Requirements 2.3, 2.8**
        """
        aliases_raw: dict[str, str] = {name: "target_job"}
        result = _validate_aliases(aliases_raw)
        assert name not in result, f"Invalid alias '{name!r}' was accepted"

    @given(
        first=st.from_regex(r"[a-zA-Z]", fullmatch=True),
        rest=st.text(
            alphabet=st.sampled_from(
                "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-"
            ),
            min_size=32,
            max_size=60,
        ),
    )
    def test_over_length_aliases_rejected(self, first: str, rest: str):
        """Strings matching the pattern but exceeding 32 chars are rejected.

        **Validates: Requirements 2.3, 2.8**
        """
        base = first + rest
        assert len(base) > _ALIAS_MAX_LEN
        aliases_raw: dict[str, str] = {base: "target_job"}
        result = _validate_aliases(aliases_raw)
        assert base not in result, (
            f"Over-length alias '{base!r}' (len={len(base)}) was accepted"
        )
