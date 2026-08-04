"""Unit tests for StaticProvider and Job dataclass.

Tests cover construction from plain callables, Job dataclass instances,
mixed lists, name derivation, group/config_model overrides, and
list_jobs/get_job behavior.

**Validates: Requirements 23.1, 23.2, 23.3, 23.4, 23.5**
"""

from __future__ import annotations

from functualize._discovery.providers import Job, StaticProvider

# --- Sample callables for testing ---


def deploy():
    """Deploy the application."""
    pass


def build():
    """Build the project."""
    pass


def sample_job():
    """A test job."""
    pass


# =============================================================================
# StaticProvider Tests
# =============================================================================


class TestStaticProviderPlainCallables:
    """Tests for StaticProvider with plain callables.

    **Validates: Requirements 23.1, 23.2, 23.3, 23.5**
    """

    def test_single_callable_produces_one_descriptor(self) -> None:
        """Single callable produces exactly one JobDescriptor.

        **Validates: Requirements 23.3**
        """
        provider = StaticProvider(functions=[deploy])
        jobs = provider.list_jobs()

        assert len(jobs) == 1
        assert jobs[0].name == "deploy"

    def test_name_derived_from_function_name(self) -> None:
        """Plain callable derives job name from function.__name__.

        **Validates: Requirements 23.5**
        """
        provider = StaticProvider(functions=[deploy])
        descriptor = provider.list_jobs()[0]

        assert descriptor.name == "deploy"

    def test_multiple_callables_produce_multiple_descriptors(self) -> None:
        """Multiple callables produce one descriptor each.

        **Validates: Requirements 23.3**
        """
        provider = StaticProvider(functions=[deploy, build, sample_job])
        jobs = provider.list_jobs()

        assert len(jobs) == 3
        names = {j.name for j in jobs}
        assert names == {"deploy", "build", "sample-job"}

    def test_docstring_preserved(self) -> None:
        """Function docstring is preserved in descriptor.

        **Validates: Requirements 23.3**
        """
        provider = StaticProvider(functions=[deploy])
        descriptor = provider.list_jobs()[0]

        assert descriptor.docstring == "Deploy the application."

    def test_group_is_none_for_plain_callable(self) -> None:
        """Plain callable has group=None.

        **Validates: Requirements 23.5**
        """
        provider = StaticProvider(functions=[deploy])
        descriptor = provider.list_jobs()[0]

        assert descriptor.group is None

    def test_source_file_is_static(self) -> None:
        """StaticProvider marks source as '<static>'.

        **Validates: Requirements 23.3**
        """
        provider = StaticProvider(functions=[deploy])
        descriptor = provider.list_jobs()[0]

        assert descriptor.source == "<static>"

    def test_zero_io_no_mtime_or_hash(self) -> None:
        """StaticProvider produces zero-I/O descriptors (mtime=0, hash empty).

        **Validates: Requirements 23.3**
        """
        provider = StaticProvider(functions=[deploy])
        descriptor = provider.list_jobs()[0]

        assert descriptor.source_mtime == 0.0
        assert descriptor.content_hash == ""

    def test_empty_functions_list(self) -> None:
        """Empty functions list produces empty list_jobs.

        **Validates: Requirements 23.2**
        """
        provider = StaticProvider(functions=[])
        jobs = provider.list_jobs()

        assert jobs == []


class TestStaticProviderJobDataclass:
    """Tests for StaticProvider with Job dataclass instances.

    **Validates: Requirements 23.3, 23.4**
    """

    def test_job_with_explicit_name(self) -> None:
        """Job dataclass with explicit name overrides function.__name__.

        **Validates: Requirements 23.4**
        """
        job = Job(function=deploy, name="custom_deploy")
        provider = StaticProvider(functions=[job])
        descriptor = provider.list_jobs()[0]

        assert descriptor.name == "custom-deploy"

    def test_job_without_name_uses_function_name(self) -> None:
        """Job dataclass without name falls back to function.__name__.

        **Validates: Requirements 23.4, 23.5**
        """
        job = Job(function=deploy)
        provider = StaticProvider(functions=[job])
        descriptor = provider.list_jobs()[0]

        assert descriptor.name == "deploy"

    def test_job_with_explicit_group(self) -> None:
        """Job dataclass with explicit group sets group on descriptor.

        **Validates: Requirements 23.4**
        """
        job = Job(function=deploy, group="deployment")
        provider = StaticProvider(functions=[job])
        descriptor = provider.list_jobs()[0]

        assert descriptor.group == "deployment"

    def test_job_with_config_model(self) -> None:
        """Job dataclass uses function directly — config model is extracted from function signature.

        **Validates: Requirements 23.4**
        """
        # Job no longer accepts config_model — config extraction happens
        # via function signature inspection during discovery
        job = Job(function=deploy, name="deploy_job")
        provider = StaticProvider(functions=[job])
        descriptor = provider.list_jobs()[0]

        # The descriptor is created from the function
        assert descriptor.name == "deploy-job"
        assert descriptor.function is deploy

    def test_job_with_all_overrides(self) -> None:
        """Job dataclass with all overrides applied.

        **Validates: Requirements 23.4**
        """
        job = Job(function=deploy, name="my_deploy", group="ops")
        provider = StaticProvider(functions=[job])
        descriptor = provider.list_jobs()[0]

        assert descriptor.name == "my-deploy"
        assert descriptor.group == "ops"


class TestStaticProviderGetJob:
    """Tests for StaticProvider.get_job().

    **Validates: Requirements 23.2**
    """

    def test_get_job_returns_matching_descriptor(self) -> None:
        """get_job returns descriptor for known name.

        **Validates: Requirements 23.2**
        """
        provider = StaticProvider(functions=[deploy, build])
        result = provider.get_job("deploy")

        assert result is not None
        assert result.name == "deploy"

    def test_get_job_returns_none_for_unknown_name(self) -> None:
        """get_job returns None for unknown name.

        **Validates: Requirements 23.2**
        """
        provider = StaticProvider(functions=[deploy])
        result = provider.get_job("nonexistent")

        assert result is None

    def test_get_job_with_job_dataclass_override_name(self) -> None:
        """get_job uses the overridden name from Job dataclass.

        **Validates: Requirements 23.2, 23.4**
        """
        job = Job(function=deploy, name="custom_name")
        provider = StaticProvider(functions=[job])

        # Should find by overridden name
        assert provider.get_job("custom_name") is not None
        # Should NOT find by original function name
        assert provider.get_job("deploy") is None


class TestStaticProviderMixedInput:
    """Tests for StaticProvider with mixed callables and Job instances.

    **Validates: Requirements 23.3**
    """

    def test_mixed_callables_and_jobs(self) -> None:
        """Mix of plain callables and Job instances works correctly.

        **Validates: Requirements 23.3, 23.4, 23.5**
        """
        job = Job(function=deploy, name="production_deploy", group="ops")
        provider = StaticProvider(functions=[job, build])
        jobs = provider.list_jobs()

        assert len(jobs) == 2
        names = {j.name for j in jobs}
        assert names == {"production-deploy", "build"}

        # Verify the Job instance got overrides
        prod = provider.get_job("production_deploy")
        assert prod is not None
        assert prod.group == "ops"

        # Verify plain callable derived name
        b = provider.get_job("build")
        assert b is not None
        assert b.group is None


class TestStaticProviderProtocolCompliance:
    """Tests for StaticProvider satisfying JobProvider Protocol.

    **Validates: Requirements 23.1, 23.2**
    """

    def test_has_list_jobs_method(self) -> None:
        """StaticProvider has list_jobs() method.

        **Validates: Requirements 23.2**
        """
        provider = StaticProvider(functions=[deploy])
        assert hasattr(provider, "list_jobs")
        assert callable(provider.list_jobs)

    def test_has_get_job_method(self) -> None:
        """StaticProvider has get_job() method.

        **Validates: Requirements 23.2**
        """
        provider = StaticProvider(functions=[deploy])
        assert hasattr(provider, "get_job")
        assert callable(provider.get_job)

    def test_list_jobs_returns_sequence(self) -> None:
        """list_jobs returns a Sequence[JobDescriptor].

        **Validates: Requirements 23.2**
        """
        from collections.abc import Sequence

        from functualize._types.descriptors import JobDescriptor

        provider = StaticProvider(functions=[deploy])
        result = provider.list_jobs()

        assert isinstance(result, Sequence)
        for item in result:
            assert isinstance(item, JobDescriptor)


class TestJobDataclass:
    """Tests for the Job frozen dataclass.

    **Validates: Requirements 23.4**
    """

    def test_job_is_frozen(self) -> None:
        """Job dataclass is frozen (immutable)."""
        import dataclasses

        job = Job(function=deploy)
        assert dataclasses.is_dataclass(job)
        with __import__("pytest").raises(
            (AttributeError, dataclasses.FrozenInstanceError)
        ):
            job.name = "changed"  # type: ignore

    def test_job_defaults(self) -> None:
        """Job dataclass has correct defaults."""
        job = Job(function=deploy)
        assert job.function is deploy
        assert job.name is None
        assert job.group is None

    def test_job_with_all_fields(self) -> None:
        """Job dataclass accepts all fields."""
        job = Job(function=deploy, name="my_job", group="ops")
        assert job.function is deploy
        assert job.name == "my_job"
        assert job.group == "ops"
