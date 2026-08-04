"""Unit tests for GroupByModuleAttributeTransform.

Tests that GroupByModuleAttributeTransform correctly reads a module-level
variable and sets the group field on job descriptors.

**Validates: Requirements 25.1, 25.2, 25.3, 25.4, 25.5**
"""

from __future__ import annotations

import sys
import types
from pathlib import Path

from functualize._discovery.transforms import GroupByModuleAttributeTransform
from functualize._types.descriptors import JobDescriptor

# --- Helpers ---


def _make_descriptor(
    name: str,
    module_path: str = "test.module",
    source_file: str = "/fake/test.py",
    group: str | None = None,
) -> JobDescriptor:
    """Create a minimal JobDescriptor for testing."""
    return JobDescriptor(
        name=name,
        group=group,
        module_path=module_path,
        source_file=source_file,
        source_mtime=0.0,
        content_hash="a" * 64,
        docstring=None,
        config_fields=[],
        dependencies={},
        metadata=None,
    )


def _register_module(module_path: str, **attrs: str) -> types.ModuleType:
    """Create and register a fake module in sys.modules with given attributes."""
    mod = types.ModuleType(module_path)
    for key, value in attrs.items():
        setattr(mod, key, value)
    sys.modules[module_path] = mod
    return mod


# =============================================================================
# GroupByModuleAttributeTransform Tests
# =============================================================================


class TestGroupByModuleAttributeTransform:
    """Tests for GroupByModuleAttributeTransform.

    **Validates: Requirements 25.1, 25.2, 25.3, 25.4, 25.5**
    """

    def setup_method(self) -> None:
        """Track registered modules for cleanup."""
        self._registered_modules: list[str] = []

    def teardown_method(self) -> None:
        """Remove fake modules from sys.modules."""
        for mod_path in self._registered_modules:
            sys.modules.pop(mod_path, None)

    def _register(self, module_path: str, **attrs: str) -> types.ModuleType:
        """Register a module and track for cleanup."""
        self._registered_modules.append(module_path)
        return _register_module(module_path, **attrs)

    def test_default_attribute_is_job_name(self) -> None:
        """Default attribute_name is 'JOB_GROUP'.

        **Validates: Requirements 25.1**
        """
        transform = GroupByModuleAttributeTransform()
        assert transform._attribute_name == "JOB_GROUP"

    def test_custom_attribute_name(self) -> None:
        """Custom attribute_name is accepted.

        **Validates: Requirements 25.1**
        """
        transform = GroupByModuleAttributeTransform(attribute_name="MY_GROUP")
        assert transform._attribute_name == "MY_GROUP"

    def test_transform_list_sets_group_from_module_variable(self) -> None:
        """transform_list sets group from module-level JOB_GROUP.

        **Validates: Requirements 25.2**
        """
        self._register("test.deploy_module", JOB_GROUP="deploy")
        desc = _make_descriptor("my_job", module_path="test.deploy_module")

        transform = GroupByModuleAttributeTransform()
        result = transform.transform_list([desc])

        assert len(result) == 1
        assert result[0].group == "deploy"
        assert result[0].name == "deploy.my-job"  # Name rewritten to qualified form

    def test_transform_list_leaves_group_unchanged_when_no_variable(self) -> None:
        """transform_list leaves group unchanged when module has no JOB_GROUP.

        **Validates: Requirements 25.3**
        """
        self._register("test.no_group_module")
        desc = _make_descriptor("my_job", module_path="test.no_group_module")

        transform = GroupByModuleAttributeTransform()
        result = transform.transform_list([desc])

        assert len(result) == 1
        assert result[0].group is None

    def test_transform_list_preserves_existing_group_when_no_variable(self) -> None:
        """When module has no JOB_GROUP, existing group is preserved.

        **Validates: Requirements 25.3**
        """
        self._register("test.existing_group_module")
        desc = _make_descriptor(
            "my_job", module_path="test.existing_group_module", group="existing"
        )

        transform = GroupByModuleAttributeTransform()
        result = transform.transform_list([desc])

        assert len(result) == 1
        assert result[0].group == "existing"

    def test_transform_list_multiple_jobs_from_same_module(self) -> None:
        """Multiple jobs from same module all get same group.

        **Validates: Requirements 25.2**
        """
        self._register("test.shared_module", JOB_GROUP="shared_group")
        desc1 = _make_descriptor("job_a", module_path="test.shared_module")
        desc2 = _make_descriptor("job_b", module_path="test.shared_module")

        transform = GroupByModuleAttributeTransform()
        result = transform.transform_list([desc1, desc2])

        assert len(result) == 2
        assert result[0].group == "shared-group"
        assert result[1].group == "shared-group"
        assert result[0].name == "shared-group.job-a"
        assert result[1].name == "shared-group.job-b"

    def test_transform_list_mixed_modules(self) -> None:
        """Jobs from different modules get their respective groups.

        **Validates: Requirements 25.2, 25.3**
        """
        self._register("test.mod_a", JOB_GROUP="group_a")
        self._register("test.mod_b")  # No JOB_GROUP

        desc_a = _make_descriptor("job_a", module_path="test.mod_a")
        desc_b = _make_descriptor("job_b", module_path="test.mod_b")

        transform = GroupByModuleAttributeTransform()
        result = transform.transform_list([desc_a, desc_b])

        assert result[0].group == "group-a"
        assert result[0].name == "group-a.job-a"
        assert result[1].group is None
        # No JOB_GROUP: the transform returns the descriptor untouched, so the
        # name is whatever discovery produced — normalization happens in
        # `qualified_name`, which this path never reaches.
        assert result[1].name == "job_b"

    def test_transform_get_sets_group(self) -> None:
        """transform_get sets group from module variable.

        **Validates: Requirements 25.2**
        """
        self._register("test.get_module", JOB_GROUP="my_group")
        desc = _make_descriptor("my_job", module_path="test.get_module")

        transform = GroupByModuleAttributeTransform()
        result = transform.transform_get("my_job", desc)

        assert result is not None
        assert result.group == "my-group"
        assert result.name == "my-group.my-job"

    def test_transform_get_returns_none_for_none_descriptor(self) -> None:
        """transform_get returns None when descriptor is None.

        **Validates: Requirements 25.4**
        """
        transform = GroupByModuleAttributeTransform()
        result = transform.transform_get("missing", None)
        assert result is None

    def test_transform_get_leaves_group_unchanged_when_no_variable(self) -> None:
        """transform_get leaves group unchanged when module has no JOB_GROUP.

        **Validates: Requirements 25.3**
        """
        self._register("test.no_var_module")
        desc = _make_descriptor("my_job", module_path="test.no_var_module")

        transform = GroupByModuleAttributeTransform()
        result = transform.transform_get("my_job", desc)

        assert result is not None
        assert result.group is None

    def test_custom_attribute_name_works(self) -> None:
        """Custom attribute_name reads the correct variable.

        **Validates: Requirements 25.1**
        """
        self._register("test.custom_attr_module", MY_CUSTOM_GROUP="custom_value")
        desc = _make_descriptor("job", module_path="test.custom_attr_module")

        transform = GroupByModuleAttributeTransform(attribute_name="MY_CUSTOM_GROUP")
        result = transform.transform_get("job", desc)

        assert result is not None
        assert result.group == "custom-value"

    def test_non_string_attribute_ignored(self) -> None:
        """Non-string attribute values are ignored (group left unchanged).

        **Validates: Requirements 25.3**
        """
        mod = self._register("test.non_string_module")
        mod.JOB_GROUP = 42  # type: ignore[assignment]  # Not a string

        desc = _make_descriptor("job", module_path="test.non_string_module")

        transform = GroupByModuleAttributeTransform()
        result = transform.transform_get("job", desc)

        assert result is not None
        assert result.group is None

    def test_module_not_in_sys_modules_with_nonexistent_file(self) -> None:
        """When module not loaded and source file doesn't exist, group unchanged.

        **Validates: Requirements 25.3**
        """
        desc = _make_descriptor(
            "job",
            module_path="test.nonexistent_module_xyz",
            source_file="/nonexistent/path.py",
        )

        transform = GroupByModuleAttributeTransform()
        result = transform.transform_get("job", desc)

        assert result is not None
        assert result.group is None

    def test_does_not_filter_jobs(self) -> None:
        """Transform does not affect job eligibility — never filters out jobs.

        **Validates: Requirements 25.4**
        """
        self._register("test.eligible_module")  # No JOB_GROUP
        desc = _make_descriptor("eligible_job", module_path="test.eligible_module")

        transform = GroupByModuleAttributeTransform()
        result = transform.transform_list([desc])

        # Job is still present, not filtered
        assert len(result) == 1
        assert result[0].name == "eligible_job"

    def test_satisfies_job_transform_protocol(self) -> None:
        """GroupByModuleAttributeTransform satisfies JobTransform Protocol.

        **Validates: Requirements 25.1**
        """
        from functualize._types.protocols import JobTransform

        transform = GroupByModuleAttributeTransform()
        assert isinstance(transform, JobTransform)

    def test_transform_list_with_real_module_file(self, tmp_path: Path) -> None:
        """Transform reads JOB_GROUP from a real .py file on disk.

        **Validates: Requirements 25.2**
        """
        # Create a module file with JOB_GROUP
        module_file = tmp_path / "real_module.py"
        module_file.write_text('JOB_GROUP = "from_file"\n\ndef my_job():\n    pass\n')

        desc = _make_descriptor(
            "my_job",
            module_path="test.real_file_module_xyz",
            source_file=str(module_file),
        )

        # Ensure module is NOT in sys.modules
        sys.modules.pop("test.real_file_module_xyz", None)

        transform = GroupByModuleAttributeTransform()
        result = transform.transform_get("my_job", desc)

        assert result is not None
        assert result.group == "from-file"
        assert result.name == "from-file.my-job"
