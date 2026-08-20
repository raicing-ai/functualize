"""Property-based tests for preset factory functions (Property 1).

# Feature: codebase-restructure, Property 1: Preset factory functions produce correctly-structured ConfigSources

**Validates: Requirements 6.1, 6.2, 6.4, 6.7**
"""

from __future__ import annotations

from hypothesis import given
from hypothesis import strategies as st

from functualize._config.chain import ResolutionChain
from functualize._config.sources import CliSource, DefaultSource, EnvSource
from functualize.app.config import (
    ConfigSources,
    ExecutionConfig,
    JobSources,
    PluginSources,
)
from functualize.app.core import FunctualizeApp
from functualize.app.presets import classic, env_only, remote_first, twelve_factor

# =============================================================================
# Strategies
# =============================================================================

# Strategy: valid file_pattern strings (non-empty regex-like patterns)
_file_pattern_strategy = st.text(
    alphabet=st.characters(
        whitelist_categories=("L", "Nd", "P", "S"),
        blacklist_characters="\x00",
    ),
    min_size=1,
    max_size=60,
)

# Strategy: dotenv boolean
_dotenv_strategy = st.booleans()

# Strategy: optional dotenv_path (None or a non-empty path string)
_dotenv_path_strategy = st.one_of(
    st.none(),
    st.text(min_size=1, max_size=80).filter(lambda s: s.strip() != ""),
)


# =============================================================================
# Property 1: Preset factory functions produce correctly-structured ConfigSources
# =============================================================================


class TestPresetFactoryProperty:
    """Property 1: Preset factory functions produce correctly-structured ConfigSources.

    For any preset factory function called with any valid combination of its
    keyword arguments, the return value is a ConfigSources instance with the
    correct structure as specified in Requirements 6.1, 6.2, 6.7.

    **Validates: Requirements 6.1, 6.2, 6.4, 6.7**
    """

    @given(file_pattern=_file_pattern_strategy, dotenv=_dotenv_strategy)
    def test_classic_returns_config_sources_with_none_chain(
        self, file_pattern: str, dotenv: bool
    ) -> None:
        """classic() always returns ConfigSources with config_resolution_chain=None.

        **Validates: Requirements 6.1, 6.2, 6.7**
        """
        result = classic(file_pattern=file_pattern, dotenv=dotenv)

        assert isinstance(result, ConfigSources)
        assert result.config_resolution_chain is None
        assert result.dotenv == dotenv
        assert result.file_pattern == file_pattern

    @given(dotenv=_dotenv_strategy)
    def test_twelve_factor_returns_config_sources_with_correct_chain(
        self, dotenv: bool
    ) -> None:
        """twelve_factor() always returns ConfigSources with ResolutionChain [CliSource, EnvSource, DefaultSource].

        **Validates: Requirements 6.1, 6.2, 6.7**
        """
        result = twelve_factor(dotenv=dotenv)

        assert isinstance(result, ConfigSources)
        assert result.dotenv == dotenv

        # Verify chain structure
        chain = result.config_resolution_chain
        assert isinstance(chain, ResolutionChain)
        sources = chain.sources
        assert len(sources) == 3
        assert isinstance(sources[0], CliSource)
        assert isinstance(sources[1], EnvSource)
        assert isinstance(sources[2], DefaultSource)

    @given(dotenv=_dotenv_strategy, dotenv_path=_dotenv_path_strategy)
    def test_env_only_returns_config_sources_with_correct_chain(
        self, dotenv: bool, dotenv_path: str | None
    ) -> None:
        """env_only() always returns ConfigSources with ResolutionChain [CliSource, EnvSource, DefaultSource].

        **Validates: Requirements 6.1, 6.2, 6.7**
        """
        result = env_only(dotenv=dotenv, dotenv_path=dotenv_path)

        assert isinstance(result, ConfigSources)
        assert result.dotenv == dotenv
        assert result.dotenv_path == dotenv_path

        # Verify chain structure
        chain = result.config_resolution_chain
        assert isinstance(chain, ResolutionChain)
        sources = chain.sources
        assert len(sources) == 3
        assert isinstance(sources[0], CliSource)
        assert isinstance(sources[1], EnvSource)
        assert isinstance(sources[2], DefaultSource)

    @given(file_pattern=_file_pattern_strategy, dotenv=_dotenv_strategy)
    def test_remote_first_returns_config_sources_with_none_chain(
        self, file_pattern: str, dotenv: bool
    ) -> None:
        """remote_first() always returns ConfigSources with config_resolution_chain=None.

        **Validates: Requirements 6.1, 6.2, 6.7**
        """
        result = remote_first(file_pattern=file_pattern, dotenv=dotenv)

        assert isinstance(result, ConfigSources)
        assert result.config_resolution_chain is None
        assert result.dotenv == dotenv
        assert result.file_pattern == file_pattern

    @given(dotenv=_dotenv_strategy)
    def test_custom_preset_callable_accepted_by_functualize_app(
        self, dotenv: bool
    ) -> None:
        """Any (**kwargs) -> ConfigSources callable is accepted by FunctualizeApp.

        A user-defined factory function with the same signature as the built-in
        presets can produce a ConfigSources that FunctualizeApp accepts without error.

        **Validates: Requirements 6.4**
        """

        def custom_preset(**kwargs) -> ConfigSources:
            return ConfigSources(dotenv=kwargs.get("dotenv", True))

        config_sources = custom_preset(dotenv=dotenv)

        # FunctualizeApp should accept any ConfigSources instance
        app = FunctualizeApp(
            "test-custom-preset",
            job_sources=JobSources(functions=[]),
            config_sources=config_sources,
            plugin_sources=PluginSources(entry_point_group="", explicit_plugins=[]),
            execution=ExecutionConfig(),
        )

        assert app._config_sources is config_sources
        assert app._config_sources.dotenv == dotenv

    @given(
        dotenv=_dotenv_strategy,
        preset_choice=st.sampled_from(
            ["classic", "twelve_factor", "env_only", "remote_first"]
        ),
    )
    def test_dotenv_field_always_reflects_passed_argument(
        self, dotenv: bool, preset_choice: str
    ) -> None:
        """For all presets, the dotenv field on the returned ConfigSources
        always matches the argument passed to the factory function.

        **Validates: Requirements 6.1, 6.2, 6.7**
        """
        factories = {
            "classic": lambda d: classic(dotenv=d),
            "twelve_factor": lambda d: twelve_factor(dotenv=d),
            "env_only": lambda d: env_only(dotenv=d),
            "remote_first": lambda d: remote_first(dotenv=d),
        }

        result = factories[preset_choice](dotenv)
        assert result.dotenv == dotenv

    @given(
        preset_choice=st.sampled_from(
            ["classic", "twelve_factor", "env_only", "remote_first"]
        ),
        dotenv=_dotenv_strategy,
    )
    def test_all_presets_return_config_sources_instance(
        self, preset_choice: str, dotenv: bool
    ) -> None:
        """Every preset factory always returns a ConfigSources instance (not a subclass or wrapper).

        **Validates: Requirements 6.1, 6.2**
        """
        factories = {
            "classic": lambda d: classic(dotenv=d),
            "twelve_factor": lambda d: twelve_factor(dotenv=d),
            "env_only": lambda d: env_only(dotenv=d),
            "remote_first": lambda d: remote_first(dotenv=d),
        }

        result = factories[preset_choice](dotenv)
        assert type(result) is ConfigSources
