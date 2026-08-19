"""Property-based test for multi-function module extraction (Property 18).

Tests that for any Python module containing N public functions
(non-underscore-prefixed, locally-defined, passing inspect.isfunction()),
the extraction logic produces exactly N distinct JobDescriptor instances,
each with a name equal to the corresponding function's __name__.

**Validates: Requirements 14.1, 14.2, 14.4**
"""

from __future__ import annotations

import keyword as _kw
import tempfile
from pathlib import Path

from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from functualize._discovery.sync import full_import_and_extract

# --- Strategies ---

# Valid Python function names (public, no underscore prefix)
public_func_names = st.from_regex(r"[a-z][a-z0-9_]{0,15}", fullmatch=True).filter(
    lambda s: s.isidentifier() and not s.startswith("_") and not _kw.iskeyword(s)
)

# Private function names (underscore prefix)
private_func_names = st.from_regex(r"_[a-z][a-z0-9_]{0,15}", fullmatch=True).filter(
    lambda s: s.isidentifier()
)


@st.composite
def module_spec(draw: st.DrawFn) -> tuple[list[str], list[str]]:
    """Generate a module spec: (public_names, private_names).

    Public names are guaranteed unique. Private names are guaranteed unique
    and non-overlapping with public names.
    """
    public_names = draw(
        st.lists(public_func_names, min_size=1, max_size=8, unique=True)
    )
    private_names = draw(
        st.lists(private_func_names, min_size=0, max_size=4, unique=True)
    )
    return public_names, private_names


def _build_module_source(public_names: list[str], private_names: list[str]) -> str:
    """Build a Python module source with public and private functions."""
    lines = ['"""Generated test module."""', ""]

    for name in public_names:
        lines.append(f"def {name}():")
        lines.append(f'    """Docstring for {name}."""')
        lines.append("    pass")
        lines.append("")

    for name in private_names:
        lines.append(f"def {name}():")
        lines.append(f'    """Private helper {name}."""')
        lines.append("    pass")
        lines.append("")

    # Add a constant to verify non-callables are skipped
    lines.append("SOME_CONSTANT = 42")
    lines.append("")

    return "\n".join(lines)


# --- Property 18: Multi-function module extraction completeness ---


@settings(suppress_health_check=[HealthCheck.too_slow], deadline=10000)
@given(spec=module_spec())
def test_property_18_extraction_produces_n_descriptors_for_n_public_functions(
    spec: tuple[list[str], list[str]],
) -> None:
    """For any Python module containing N public functions (non-underscore-prefixed,
    locally-defined, passing inspect.isfunction()), the extraction logic SHALL
    produce exactly N distinct JobDescriptor instances, each with a name equal to
    the corresponding function's __name__.

    **Validates: Requirements 14.1, 14.2, 14.4**
    """
    public_names, private_names = spec

    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_path = Path(tmp_dir)
        module_source = _build_module_source(public_names, private_names)
        module_file = tmp_path / "test_module.py"
        module_file.write_text(module_source)

        # Extract descriptors
        descriptors = full_import_and_extract(str(module_file.resolve()), tmp_path)

        # Property: exactly N descriptors for N public functions
        assert len(descriptors) == len(public_names), (
            f"Expected {len(public_names)} descriptors for public functions "
            f"{public_names}, but got {len(descriptors)}. "
            f"Extracted names: {[d.name for d in descriptors]}. "
            f"Private functions (should be excluded): {private_names}"
        )

        # Property: each descriptor name matches a public function's __name__
        extracted_names = {d.name for d in descriptors}
        expected_names = set(public_names)
        assert extracted_names == expected_names, (
            f"Extracted names {extracted_names} do not match expected public names "
            f"{expected_names}. Missing: {expected_names - extracted_names}. "
            f"Extra: {extracted_names - expected_names}"
        )

        # Property: all descriptor names are distinct
        assert len(extracted_names) == len(descriptors), (
            f"Descriptors contain duplicate names. "
            f"All names: {[d.name for d in descriptors]}"
        )


@settings(suppress_health_check=[HealthCheck.too_slow], deadline=10000)
@given(private_names=st.lists(private_func_names, min_size=1, max_size=5, unique=True))
def test_property_18_only_private_functions_yields_empty(
    private_names: list[str],
) -> None:
    """For any module containing only private functions (underscore-prefixed),
    the extraction logic SHALL produce zero JobDescriptor instances.

    **Validates: Requirements 14.1, 14.2, 14.4**
    """
    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_path = Path(tmp_dir)
        module_source = _build_module_source([], private_names)
        module_file = tmp_path / "test_private_only.py"
        module_file.write_text(module_source)

        descriptors = full_import_and_extract(str(module_file.resolve()), tmp_path)

        assert descriptors == [], (
            f"Expected zero descriptors for module with only private functions "
            f"{private_names}, but got {len(descriptors)}: "
            f"{[d.name for d in descriptors]}"
        )
