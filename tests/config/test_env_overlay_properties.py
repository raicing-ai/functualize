"""Property-based tests for the environment overlay.

Tests Property 15 from the design document: Environment overlay discovery.

**Validates: Requirements 7.2, 7.6**

Every test here drives a **single real** ``FileSource(..., environment=...)``
over files on disk — the same construction ``build_resolution_chain`` uses.
That matters: the previous version of this file built *two* FileSource
instances with env-specific globs it constructed itself and asserted they
merged correctly. It passed the whole time the kernel had no environment
overlay at all, because it reimplemented the feature inside the test instead
of exercising it.

Verifies that:
1. A matching overlay is discovered and loaded alongside base.
2. The overlay overrides base on conflict.
3. A missing overlay is not an error — base still loads.
4. A file naming a different environment is reported but never merged.
"""

from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Any

from hypothesis import given, settings
from hypothesis import strategies as st

from functualize._config.providers.toml import TomlFormatProvider
from functualize._config.registry import ProviderRegistry
from functualize._config.sources import FileSource
from functualize._primitives.locator import ResourceLocator
from functualize._types.enums import ConfigFileRole

# --- Strategies ---

# Environment identifiers (e.g. "production", "staging", "dev"). Lowercase
# ASCII only, so they are always valid filename segments. "base" is excluded:
# it is the reserved always-loaded slot, not an overlay.
env_identifiers = st.from_regex(r"[a-z][a-z0-9_]{0,10}", fullmatch=True).filter(
    lambda s: s != "base"
)

# Strategy for valid TOML bare key names (ASCII lowercase + digits + underscore)
toml_keys = st.from_regex(r"[a-z][a-z0-9_]{0,10}", fullmatch=True)

# Strategy for TOML-safe scalar values (primitives that serialize cleanly)
toml_values: st.SearchStrategy[Any] = st.one_of(
    st.from_regex(r"[a-zA-Z0-9_ ]{0,15}", fullmatch=True),
    st.integers(min_value=-10000, max_value=10000),
    st.booleans(),
)

# Strategy for flat TOML config dicts (no nesting, for simplicity)
flat_config_dicts = st.dictionaries(
    keys=toml_keys,
    values=toml_values,
    min_size=1,
    max_size=5,
)


# --- Helpers ---


def _make_registry() -> ProviderRegistry:
    """Create a registry with only the TOML provider registered."""
    registry = ProviderRegistry()
    registry.register_format_provider(TomlFormatProvider())
    return registry


def _write_toml(path: Path, data: dict[str, Any]) -> None:
    """Serialize a dict to a TOML file at the given path."""
    path.write_text(TomlFormatProvider().serialize(data))


def _source_over(directory: Path, environment: str | None) -> FileSource:
    """Build a FileSource exactly the way build_resolution_chain does."""
    return FileSource(
        ResourceLocator().search_explicit(str(directory)),
        registry=_make_registry(),
        pattern="config.*",
        environment=environment,
    )


# --- Property 15: Environment overlay discovery ---


class TestProperty15EnvironmentOverlayDiscovery:
    """For any environment identifier, the Configuration_System SHALL discover
    and load the matching environment-named overlay file when it exists, and
    SHALL load only the base file without error when no overlay exists.

    **Validates: Requirements 7.2, 7.6**
    """

    @given(env_id=env_identifiers, base_config=flat_config_dicts)
    @settings(max_examples=50)
    def test_overlay_is_loaded_alongside_base(
        self, env_id: str, base_config: dict[str, Any]
    ) -> None:
        """A matching overlay is discovered and loaded with the base file."""
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            _write_toml(tmp_path / "config.base.toml", base_config)
            _write_toml(tmp_path / f"config.{env_id}.toml", {"overlay_marker": 1})

            source = _source_over(tmp_path, env_id)

            assert source.get("overlay_marker") == 1
            # Base keys the overlay didn't touch survive.
            for key, value in base_config.items():
                if key != "overlay_marker":
                    assert source.get(key) == value

    @given(env_id=env_identifiers, base_config=flat_config_dicts)
    @settings(max_examples=50)
    def test_overlay_overrides_base_on_conflict(
        self, env_id: str, base_config: dict[str, Any]
    ) -> None:
        """The overlay wins every key it defines.

        This is the property the kernel had backwards: files merged in
        lexicographic discovery order, so ``config.base.*`` beat every
        overlay, always.
        """
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            overlay_config = {key: "OVERLAY" for key in base_config}
            _write_toml(tmp_path / "config.base.toml", base_config)
            _write_toml(tmp_path / f"config.{env_id}.toml", overlay_config)

            source = _source_over(tmp_path, env_id)

            for key in base_config:
                assert source.get(key) == "OVERLAY"

    @given(env_id=env_identifiers, base_config=flat_config_dicts)
    @settings(max_examples=50)
    def test_missing_overlay_is_not_an_error(
        self, env_id: str, base_config: dict[str, Any]
    ) -> None:
        """An environment with no overlay file is legitimate (Requirement 7.6)."""
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            _write_toml(tmp_path / "config.base.toml", base_config)

            source = _source_over(tmp_path, env_id)

            for key, value in base_config.items():
                assert source.get(key) == value

    @given(active=env_identifiers, other=env_identifiers)
    @settings(max_examples=50)
    def test_other_environments_never_merge(self, active: str, other: str) -> None:
        """A file naming a different environment is reported but never merged."""
        if active == other:
            return
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            _write_toml(tmp_path / "config.base.toml", {"who": "base"})
            _write_toml(tmp_path / f"config.{other}.toml", {"who": other})

            source = _source_over(tmp_path, active)

            assert source.get("who") == "base"
            inert = [i for i in source.file_infos if i.role is ConfigFileRole.INERT]
            assert [Path(i.path).name for i in inert] == [f"config.{other}.toml"]
            # Reported, not silently dropped — with its would-be value intact,
            # so a delivery layer can explain why the file does nothing.
            assert inert[0].values == {"who": other}
            assert inert[0].precedence is None

    @given(env_id=env_identifiers)
    @settings(max_examples=25)
    def test_environment_matching_is_case_insensitive(self, env_id: str) -> None:
        """ENVIRONMENT=PROD selects config.prod.toml."""
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            _write_toml(tmp_path / "config.base.toml", {"who": "base"})
            _write_toml(tmp_path / f"config.{env_id}.toml", {"who": "overlay"})

            source = _source_over(tmp_path, env_id.upper())

            assert source.get("who") == "overlay"

    @given(base_config=flat_config_dicts)
    @settings(max_examples=25)
    def test_no_environment_disables_banding(self, base_config: dict[str, Any]) -> None:
        """environment=None merges every file in discovery order.

        A generic file-merging source has no notion of a "base", so this is
        the correct degenerate behavior — and it is what keeps the existing
        FileSource contract intact.
        """
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            _write_toml(tmp_path / "config.base.toml", base_config)

            source = _source_over(tmp_path, None)

            for key, value in base_config.items():
                assert source.get(key) == value
            assert all(info.role is ConfigFileRole.BASE for info in source.file_infos)
