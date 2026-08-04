"""Property-based tests for DiscoveryConfig TOML round-trip.

# Feature: cli-config-and-discovery-filtering, Property 1: DiscoveryConfig TOML Round-Trip
"""

from __future__ import annotations

import os
import re
import tomllib
from pathlib import Path
from typing import Any

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from functualize._cli.config import _get_value, _validate_aliases
from functualize.app.config import DiscoveryConfig

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
    @settings(max_examples=300)
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
    @settings(max_examples=300)
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
    @settings(max_examples=300)
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
# Feature: cli-config-and-discovery-filtering, Property 3: Environment Variable Name Mapping
# =============================================================================

# Strategy: valid section names (lowercase identifiers, no underscores to avoid ambiguity)
_section_name = st.from_regex(r"[a-z][a-z0-9]{0,10}", fullmatch=True)

# Strategy: valid key names (lowercase identifiers, may contain underscores)
_key_name = st.from_regex(r"[a-z][a-z0-9_]{0,20}", fullmatch=True)

# Strategy: non-empty env var values
_env_value = st.text(
    alphabet=st.characters(whitelist_categories=("L", "N", "P", "S")),
    min_size=1,
    max_size=50,
)


@pytest.mark.slow
class TestEnvVarNameMapping:
    """Property 3: Environment Variable Name Mapping.

    For any valid config key path (section + key name), the corresponding
    environment variable name SHALL equal FUNCTUALIZE_ concatenated with the
    uppercased section name, an underscore, and the uppercased key name.

    For example: discovery.require_file_import → FUNCTUALIZE_DISCOVERY_REQUIRE_FILE_IMPORT

    **Validates: Requirements 3.6, 18.1**
    """

    @given(section=_section_name, key=_key_name, value=_env_value)
    @settings(max_examples=300)
    def test_env_var_maps_to_section_key(self, section: str, key: str, value: str):
        """Setting FUNCTUALIZE_<SECTION>_<KEY> maps to {section: {key: value}}.

        **Validates: Requirements 3.6, 18.1**
        """
        from functualize._cli.config import resolve_env_overrides

        # Construct the env var name from section.key
        env_var_name = f"FUNCTUALIZE_{section.upper()}_{key.upper()}"

        # Save and clear existing FUNCTUALIZE_ env vars
        saved = {k: v for k, v in os.environ.items() if k.startswith("FUNCTUALIZE_")}
        for k in saved:
            del os.environ[k]

        try:
            # Set our target env var
            os.environ[env_var_name] = value

            # Resolve and check mapping
            result = resolve_env_overrides()

            assert section in result, (
                f"Expected section '{section}' in result but got: {result}"
            )
            assert key in result[section], (
                f"Expected key '{key}' in section '{section}' but got: {result[section]}"
            )
            assert result[section][key] == value, (
                f"Expected value '{value}' for {section}.{key} but got: {result[section][key]}"
            )
        finally:
            # Restore original env vars
            if env_var_name in os.environ:
                del os.environ[env_var_name]
            for k, v in saved.items():
                os.environ[k] = v

    @given(section=_section_name, key=_key_name)
    @settings(max_examples=300)
    def test_empty_env_var_is_treated_as_unset(self, section: str, key: str):
        """Empty string FUNCTUALIZE_* env vars are treated as unset (skipped).

        **Validates: Requirements 3.6, 18.1**
        """
        from functualize._cli.config import resolve_env_overrides

        env_var_name = f"FUNCTUALIZE_{section.upper()}_{key.upper()}"

        # Save and clear existing FUNCTUALIZE_ env vars
        saved = {k: v for k, v in os.environ.items() if k.startswith("FUNCTUALIZE_")}
        for k in saved:
            del os.environ[k]

        try:
            # Set empty string value
            os.environ[env_var_name] = ""

            result = resolve_env_overrides()

            # Empty values should not appear in the result
            if section in result:
                assert key not in result[section], (
                    f"Empty env var should not map to {section}.{key}"
                )
        finally:
            # Restore original env vars
            if env_var_name in os.environ:
                del os.environ[env_var_name]
            for k, v in saved.items():
                os.environ[k] = v

    @given(section=_section_name, key=_key_name, value=_env_value)
    @settings(max_examples=300)
    def test_mapping_is_case_insensitive_to_uppercase(
        self, section: str, key: str, value: str
    ):
        """The env var name is FUNCTUALIZE_ + upper(section) + _ + upper(key).

        The resolved section and key are always lowercase in the result dict.

        **Validates: Requirements 3.6, 18.1**
        """
        from functualize._cli.config import resolve_env_overrides

        env_var_name = f"FUNCTUALIZE_{section.upper()}_{key.upper()}"

        # Save and clear existing FUNCTUALIZE_ env vars
        saved = {k: v for k, v in os.environ.items() if k.startswith("FUNCTUALIZE_")}
        for k in saved:
            del os.environ[k]

        try:
            os.environ[env_var_name] = value

            result = resolve_env_overrides()

            # Result keys should be lowercase
            for result_section in result:
                assert result_section == result_section.lower(), (
                    f"Section key '{result_section}' should be lowercase"
                )
                for result_key in result[result_section]:
                    assert result_key == result_key.lower(), (
                        f"Config key '{result_key}' should be lowercase"
                    )
        finally:
            # Restore original env vars
            if env_var_name in os.environ:
                del os.environ[env_var_name]
            for k, v in saved.items():
                os.environ[k] = v


# =============================================================================
# Feature: cli-config-and-discovery-filtering, Property 4: Boolean Environment Variable Parsing
# =============================================================================

# Strategy: generate random case variations of recognized boolean strings
_bool_true_literals = ("true", "1")
_bool_false_literals = ("false", "0")


def _random_case(s: str) -> st.SearchStrategy[str]:
    """Generate all possible case variations of a string."""
    # For each character, independently choose upper or lower
    return st.tuples(*(st.sampled_from([c.lower(), c.upper()]) for c in s)).map("".join)


# Strategy: a truthy boolean env value with random casing
_truthy_env_value = st.one_of(
    _random_case("true"),
    # "1" has no case variation, but include it directly
    st.just("1"),
)

# Strategy: a falsy boolean env value with random casing
_falsy_env_value = st.one_of(
    _random_case("false"),
    # "0" has no case variation, but include it directly
    st.just("0"),
)


@pytest.mark.slow
class TestBooleanEnvVarParsing:
    """Property 4: Boolean Environment Variable Parsing.

    For any case variation of the strings "true", "1", "false", and "0",
    parsing as a boolean environment variable SHALL produce the correct
    boolean value (True for true/1, False for false/0).

    **Validates: Requirements 3.9, 18.4**
    """

    @given(value=_truthy_env_value)
    @settings(max_examples=300)
    def test_truthy_values_parse_to_true(self, value: str):
        """Any case variation of 'true' or '1' parses to True.

        **Validates: Requirements 3.9, 18.4**
        """
        from functualize._cli.config import _parse_bool_env

        result = _parse_bool_env(value)
        assert result is True, f"Expected True for input {value!r}, got {result!r}"

    @given(value=_falsy_env_value)
    @settings(max_examples=300)
    def test_falsy_values_parse_to_false(self, value: str):
        """Any case variation of 'false' or '0' parses to False.

        **Validates: Requirements 3.9, 18.4**
        """
        from functualize._cli.config import _parse_bool_env

        result = _parse_bool_env(value)
        assert result is False, f"Expected False for input {value!r}, got {result!r}"

    @given(value=st.one_of(_truthy_env_value, _falsy_env_value))
    @settings(max_examples=300)
    def test_result_is_never_none_for_valid_inputs(self, value: str):
        """Valid boolean inputs never return None.

        **Validates: Requirements 3.9, 18.4**
        """
        from functualize._cli.config import _parse_bool_env

        result = _parse_bool_env(value)
        assert result is not None, f"Expected a boolean for input {value!r}, got None"


# =============================================================================
# Feature: cli-config-and-discovery-filtering, Property 2: Config Precedence — Highest Non-None Wins
# =============================================================================

# Strategy: non-None config values (strings, ints, bools)
_config_value = st.one_of(
    st.text(
        min_size=1, max_size=20, alphabet=st.characters(whitelist_categories=("L", "N"))
    ),
    st.integers(min_value=0, max_value=100),
    st.booleans(),
)

# Strategy: optional config value (value or None)
_optional_config_value = st.one_of(st.none(), _config_value)


@pytest.mark.slow
class TestConfigPrecedenceHighestNonNoneWins:
    """Property 2: Config Precedence — Highest Non-None Wins.

    For any configuration key and any combination of values set at different
    precedence levels (CLI flags, env vars, project config, global config),
    the resolved value SHALL equal the value from the highest-priority level
    where that key is set to a non-None value.

    Precedence order: cli_flags → env → project → global

    **Validates: Requirements 3.1, 3.2, 3.3, 18.5**
    """

    @given(
        cli_val=_optional_config_value,
        env_val=_optional_config_value,
        proj_val=_optional_config_value,
        glob_val=_optional_config_value,
    )
    @settings(max_examples=300)
    def test_highest_non_none_wins_flat_key(
        self,
        cli_val: Any,
        env_val: Any,
        proj_val: Any,
        glob_val: Any,
    ):
        """Resolved value equals the highest-priority non-None value (flat key, no section).

        **Validates: Requirements 3.1, 3.2, 3.3, 18.5**
        """
        key = "some_key"
        cli_flags: dict[str, Any] = {} if cli_val is None else {key: cli_val}
        env: dict[str, Any] = {} if env_val is None else {key: env_val}
        project: dict[str, Any] = {} if proj_val is None else {key: proj_val}
        global_: dict[str, Any] = {} if glob_val is None else {key: glob_val}

        result = _get_value(key, cli_flags, env, project, global_)

        # Determine expected: first non-None in precedence order
        expected = None
        for val in [cli_val, env_val, proj_val, glob_val]:
            if val is not None:
                expected = val
                break

        assert result == expected, (
            f"Precedence violation: got {result!r}, expected {expected!r}\n"
            f"  cli={cli_val!r}, env={env_val!r}, proj={proj_val!r}, glob={glob_val!r}"
        )

    @given(
        cli_val=_optional_config_value,
        env_val=_optional_config_value,
        proj_val=_optional_config_value,
        glob_val=_optional_config_value,
        section=st.from_regex(r"[a-z]{3,10}", fullmatch=True),
    )
    @settings(max_examples=300)
    def test_highest_non_none_wins_with_section(
        self,
        cli_val: Any,
        env_val: Any,
        proj_val: Any,
        glob_val: Any,
        section: str,
    ):
        """Resolved value equals the highest-priority non-None value (nested under section).

        **Validates: Requirements 3.1, 3.2, 3.3, 18.5**
        """
        key = "some_key"
        # CLI flags are always flat (no nesting by section)
        cli_flags: dict[str, Any] = {} if cli_val is None else {key: cli_val}
        # env, project, global are nested under section
        env: dict[str, Any] = {} if env_val is None else {section: {key: env_val}}
        project: dict[str, Any] = {} if proj_val is None else {section: {key: proj_val}}
        global_: dict[str, Any] = {} if glob_val is None else {section: {key: glob_val}}

        result = _get_value(key, cli_flags, env, project, global_, section=section)

        # Determine expected: first non-None in precedence order
        expected = None
        for val in [cli_val, env_val, proj_val, glob_val]:
            if val is not None:
                expected = val
                break

        assert result == expected, (
            f"Precedence violation (section={section!r}): got {result!r}, expected {expected!r}\n"
            f"  cli={cli_val!r}, env={env_val!r}, proj={proj_val!r}, glob={glob_val!r}"
        )

    @given(
        cli_val=_config_value,
        env_val=_config_value,
        proj_val=_config_value,
        glob_val=_config_value,
    )
    @settings(max_examples=300)
    def test_cli_always_wins_when_set(
        self,
        cli_val: Any,
        env_val: Any,
        proj_val: Any,
        glob_val: Any,
    ):
        """CLI flag value always wins when provided, regardless of other levels.

        **Validates: Requirements 3.1, 3.2, 18.5**
        """
        key = "some_key"
        cli_flags: dict[str, Any] = {key: cli_val}
        env: dict[str, Any] = {key: env_val}
        project: dict[str, Any] = {key: proj_val}
        global_: dict[str, Any] = {key: glob_val}

        result = _get_value(key, cli_flags, env, project, global_)

        assert result == cli_val, (
            f"CLI should always win: got {result!r}, expected {cli_val!r}\n"
            f"  env={env_val!r}, proj={proj_val!r}, glob={glob_val!r}"
        )

    @given(data=st.data())
    @settings(max_examples=300)
    def test_all_none_returns_none(self, data: st.DataObject):
        """When all levels are None, _get_value returns None.

        **Validates: Requirements 3.1, 3.2, 3.3, 18.5**
        """
        key = "some_key"
        use_section = data.draw(st.booleans())
        section = (
            data.draw(st.from_regex(r"[a-z]{3,10}", fullmatch=True))
            if use_section
            else None
        )

        result = _get_value(key, {}, {}, {}, {}, section=section)

        assert result is None, f"Expected None when all levels unset, got {result!r}"


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
    @settings(max_examples=300)
    def test_nonempty_xdg_config_home_uses_xdg_path(self, xdg_value: str):
        """When XDG_CONFIG_HOME is a non-empty string, _resolve_xdg_config_dir()
        returns Path(xdg_value) / "functualize".

        **Validates: Requirements 1.1, 1.6**
        """
        import os

        from functualize._cli.config import _resolve_xdg_config_dir

        old = os.environ.get("XDG_CONFIG_HOME")
        try:
            os.environ["XDG_CONFIG_HOME"] = xdg_value
            result = _resolve_xdg_config_dir()
            expected = Path(xdg_value) / "functualize"
            assert result == expected, (
                f"XDG_CONFIG_HOME={xdg_value!r} → expected {expected}, got {result}"
            )
        finally:
            if old is None:
                os.environ.pop("XDG_CONFIG_HOME", None)
            else:
                os.environ["XDG_CONFIG_HOME"] = old

    @given(
        # Generate a scenario indicator: True=empty string, False=unset
        is_empty=st.booleans(),
    )
    @settings(max_examples=100)
    def test_empty_or_unset_xdg_config_home_uses_default(self, is_empty: bool):
        """When XDG_CONFIG_HOME is empty or unset, _resolve_xdg_config_dir()
        returns Path.home() / ".config" / "functualize".

        **Validates: Requirements 1.1, 1.6**
        """
        import os

        from functualize._cli.config import _resolve_xdg_config_dir

        old = os.environ.get("XDG_CONFIG_HOME")
        try:
            if is_empty:
                os.environ["XDG_CONFIG_HOME"] = ""
            else:
                os.environ.pop("XDG_CONFIG_HOME", None)

            result = _resolve_xdg_config_dir()
            expected = Path.home() / ".config" / "functualize"
            xdg_desc = '""' if is_empty else "<unset>"
            assert result == expected, (
                f"XDG_CONFIG_HOME={xdg_desc} → expected {expected}, got {result}"
            )
        finally:
            if old is None:
                os.environ.pop("XDG_CONFIG_HOME", None)
            else:
                os.environ["XDG_CONFIG_HOME"] = old


# =============================================================================
# Feature: cli-config-and-discovery-filtering, Property 5: List Merge Deduplication
# =============================================================================


# Strategy: generate lists of strings for merge testing
_merge_list_str = st.text(
    alphabet=st.characters(categories=("L", "N", "P", "S")),
    min_size=0,
    max_size=20,
)

_string_list = st.lists(_merge_list_str, min_size=0, max_size=15)


@pytest.mark.slow
class TestListMergeDeduplication:
    """Property 5: List Merge Deduplication.

    For any two lists of strings (project-level and global-level), merging them
    SHALL produce a list that is the concatenation of both lists with duplicates
    removed (retaining the project-level entry when a string appears in both),
    preserving the relative order of non-duplicate elements.

    **Validates: Requirements 3.7**
    """

    @given(
        project_list=_string_list,
        global_list=_string_list,
    )
    @settings(max_examples=300)
    def test_merged_result_has_no_duplicates(
        self, project_list: list[str], global_list: list[str]
    ):
        """Merged output contains no duplicate entries.

        **Validates: Requirements 3.7**
        """
        from functualize._cli.config import _merge_lists_dedup

        result = _merge_lists_dedup(project_list, global_list)

        assert len(result) == len(set(result)), f"Duplicates found in result: {result}"

    @given(
        project_list=_string_list,
        global_list=_string_list,
    )
    @settings(max_examples=300)
    def test_merged_result_contains_all_unique_elements(
        self, project_list: list[str], global_list: list[str]
    ):
        """Merged output is the union of both input lists (no elements lost).

        **Validates: Requirements 3.7**
        """
        from functualize._cli.config import _merge_lists_dedup

        result = _merge_lists_dedup(project_list, global_list)

        all_unique = set(project_list) | set(global_list)
        assert set(result) == all_unique, (
            f"Expected union {all_unique}, got {set(result)}"
        )

    @given(
        project_list=_string_list,
        global_list=_string_list,
    )
    @settings(max_examples=300)
    def test_project_entries_precede_global_entries(
        self, project_list: list[str], global_list: list[str]
    ):
        """Project-level entries appear before global-only entries in the result.

        Relative order is preserved: project items come first (in their original
        order, deduplicated), then global-only items (in their original order).

        **Validates: Requirements 3.7**
        """
        from functualize._cli.config import _merge_lists_dedup

        result = _merge_lists_dedup(project_list, global_list)

        # Build expected result manually: project deduped, then global-only deduped
        seen: set[str] = set()
        expected: list[str] = []
        for item in project_list:
            if item not in seen:
                seen.add(item)
                expected.append(item)
        for item in global_list:
            if item not in seen:
                seen.add(item)
                expected.append(item)

        assert list(result) == expected, (
            f"Order mismatch:\n"
            f"  project: {project_list}\n"
            f"  global:  {global_list}\n"
            f"  expected: {expected}\n"
            f"  got:      {list(result)}"
        )

    @given(
        project_list=_string_list,
        global_list=_string_list,
    )
    @settings(max_examples=300)
    def test_project_entry_retained_on_conflict(
        self, project_list: list[str], global_list: list[str]
    ):
        """When a string appears in both lists, the project-level occurrence is
        the one retained (i.e., it appears at its project-level position).

        **Validates: Requirements 3.7**
        """
        from functualize._cli.config import _merge_lists_dedup

        result = _merge_lists_dedup(project_list, global_list)
        result_list = list(result)

        # Items in both lists should appear at their first project-level position
        conflicts = set(project_list) & set(global_list)
        for item in conflicts:
            # The item should be in the result
            assert item in result_list
            # Its position should match where it first appears in the project ordering
            # (i.e., it must appear before any global-only items that follow it)
            result_idx = result_list.index(item)
            # Count how many unique project items came before this in project_list
            seen_before: set[str] = set()
            project_position = 0
            for p_item in project_list:
                if p_item == item:
                    break
                if p_item not in seen_before:
                    seen_before.add(p_item)
                    project_position += 1
            assert result_idx == project_position, (
                f"Conflict item '{item}' at wrong position: "
                f"expected {project_position}, got {result_idx}"
            )

    @given(
        project_list=_string_list,
    )
    @settings(max_examples=300)
    def test_none_global_list_returns_project_deduped(self, project_list: list[str]):
        """When global list is None, result is just the deduplicated project list.

        **Validates: Requirements 3.7**
        """
        from functualize._cli.config import _merge_lists_dedup

        result = _merge_lists_dedup(project_list, None)

        # Expected: project list deduplicated preserving order
        seen: set[str] = set()
        expected: list[str] = []
        for item in project_list:
            if item not in seen:
                seen.add(item)
                expected.append(item)

        assert list(result) == expected

    @given(
        global_list=_string_list,
    )
    @settings(max_examples=300)
    def test_none_project_list_returns_global_deduped(self, global_list: list[str]):
        """When project list is None, result is just the deduplicated global list.

        **Validates: Requirements 3.7**
        """
        from functualize._cli.config import _merge_lists_dedup

        result = _merge_lists_dedup(None, global_list)

        # Expected: global list deduplicated preserving order
        seen: set[str] = set()
        expected: list[str] = []
        for item in global_list:
            if item not in seen:
                seen.add(item)
                expected.append(item)

        assert list(result) == expected

    def test_both_none_returns_empty(self):
        """When both lists are None, result is an empty tuple.

        **Validates: Requirements 3.7**
        """
        from functualize._cli.config import _merge_lists_dedup

        result = _merge_lists_dedup(None, None)
        assert result == ()


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
    @settings(max_examples=500)
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
    @settings(max_examples=300)
    def test_valid_aliases_always_accepted(self, name: str):
        """Strings matching the pattern with length ≤ 32 are always accepted.

        **Validates: Requirements 2.3, 2.8**
        """
        aliases_raw: dict[str, str] = {name: "target_job"}
        result = _validate_aliases(aliases_raw)
        assert name in result, f"Valid alias '{name!r}' was rejected"

    @given(name=_invalid_start_alias)
    @settings(max_examples=300)
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
    @settings(max_examples=100)
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
