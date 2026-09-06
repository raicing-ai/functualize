"""A job registered at runtime takes the same arguments as one from a file.

The defect this closes: `register_dynamic_job` built its `JobDescriptor` with
`parameters=[]`. Everything else on that descriptor was extracted properly --
`declaration`, `metadata`, the capability markers, `from_job_deps`, the
workflow shape -- so the signature was the one thing the dynamic path dropped.

The consequence reached further than the descriptor. `job_detail` computes
`fields = descriptor.config_fields or descriptor.parameters` and feeds that to
`job_input_schema`, so a dynamically registered job published an **empty
`inputSchema`** -- to `func builtin info --json`, and to every MCP client
reading the tool list. An agent was told a job takes no arguments, called it
with none, and got a `TypeError` from a job that was in fact declared
correctly.
"""

from __future__ import annotations

import textwrap
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from functualize.app import FunctualizeApp, JobSources


def dynamic_target(x: int, flag: bool = False, label: str = "hi") -> str:
    """A job registered from code."""
    return f"{x}-{flag}-{label}"


class NeedsCity(BaseModel):
    city: str = Field(description="required, no default")
    tries: int = 3


def needs_config(config: NeedsCity) -> str:
    """Needs config."""
    return config.city


def _discovered_twin(tmp_path: Path) -> FunctualizeApp:
    """The same function, reached the other way: written to a file and scanned.

    Parity with directory discovery is the whole assertion, so the twin has to
    be genuinely discovered rather than constructed by calling the extractor
    directly -- that would only prove the extractor is deterministic.
    """
    jobs_dir = tmp_path / "jobs"
    jobs_dir.mkdir()
    (jobs_dir / "twin.py").write_text(
        textwrap.dedent(
            '''
            from functualize.job import job


            @job
            def dynamic_target(x: int, flag: bool = False, label: str = "hi") -> str:
                """A job registered from code."""
                return f"{x}-{flag}-{label}"
            '''
        )
    )
    return FunctualizeApp(
        "twin", job_sources=JobSources(directories=[str(jobs_dir)], lazy=False)
    )


def _dynamic_app() -> FunctualizeApp:
    app = FunctualizeApp("dyn", job_sources=JobSources())
    app.register_dynamic_job("dynamic-target", dynamic_target)
    return app


def _descriptor(app: FunctualizeApp, name: str) -> Any:
    found = next((d for d in app.job_registry._job_descriptors if d.name == name), None)
    assert found is not None, f"no descriptor named {name!r}"
    return found


class TestTheDescriptor:
    def test_parameters_are_extracted_at_all(self) -> None:
        descriptor = _descriptor(_dynamic_app(), "dynamic-target")
        assert [f.name for f in descriptor.parameters] == ["x", "flag", "label"]

    def test_parameters_equal_the_discovered_twins(self, tmp_path: Path) -> None:
        """The acceptance criterion: equal, not merely non-empty."""
        dynamic = _descriptor(_dynamic_app(), "dynamic-target")
        discovered = _descriptor(_discovered_twin(tmp_path), "dynamic-target")

        def shape(fields: Any) -> list[tuple[Any, ...]]:
            return [(f.name, f.type_annotation, f.required, f.default) for f in fields]

        assert shape(dynamic.parameters) == shape(discovered.parameters)

    def test_required_and_optional_are_distinguished(self) -> None:
        by_name = {
            f.name: f for f in _descriptor(_dynamic_app(), "dynamic-target").parameters
        }
        assert by_name["x"].required is True
        assert by_name["flag"].required is False
        assert by_name["label"].default == "hi"

    def test_a_zero_argument_job_still_gets_an_empty_list(self) -> None:
        """`[]` was the bug's value, so it must still be reachable honestly --
        otherwise the fix would be indistinguishable from the defect for the
        one function where `[]` is correct."""

        def no_args() -> None:
            """Takes nothing."""

        app = FunctualizeApp("dyn", job_sources=JobSources())
        app.register_dynamic_job("no-args", no_args)
        assert _descriptor(app, "no-args").parameters == []


class TestThePublishedSchema:
    """`contracts.md` §5 says "no caller changes", which is true of call
    *sites* and false of *payloads*: populating `parameters` changes
    `job_detail["parameters"]` and the MCP `inputSchema` for every
    dynamically registered job. That is the desired outcome, and no gate in
    the task list would have caught it -- so it is asserted here."""

    def test_the_input_schema_is_no_longer_empty(self) -> None:
        from functualize._cli.info import job_detail

        detail = job_detail(_dynamic_app(), "dynamic-target")
        assert detail is not None
        schema = detail["inputSchema"]
        assert set(schema.get("properties", {})) == {"x", "flag", "label"}
        assert schema.get("required") == ["x"]

    def test_the_input_schema_equals_the_discovered_twins(self, tmp_path: Path) -> None:
        from functualize._cli.info import job_detail

        dynamic = job_detail(_dynamic_app(), "dynamic-target")
        discovered = job_detail(_discovered_twin(tmp_path), "dynamic-target")
        assert dynamic is not None and discovered is not None
        assert dynamic["inputSchema"] == discovered["inputSchema"]

    def test_the_published_parameter_list_matches_too(self, tmp_path: Path) -> None:
        from functualize._cli.info import job_detail

        dynamic = job_detail(_dynamic_app(), "dynamic-target")
        discovered = job_detail(_discovered_twin(tmp_path), "dynamic-target")
        assert dynamic is not None and discovered is not None
        assert dynamic["parameters"] == discovered["parameters"]


class TestAJobWithAConfigClass:
    """The other half of parity, and the case where fixing only `parameters`
    would have made things *worse*.

    `job_detail` reads `config_fields or parameters`. A job declared as
    `def needs(config: NeedsCity)` has one signature parameter -- `config`,
    of a Pydantic model type that no CLI caller and no agent can supply. With
    `parameters` populated and `config_fields` still empty, that useless
    parameter is what gets published, in place of the model's real fields.
    Before the fix both were empty, so nothing was published at all.

    Discovery's rule is: fields from the config class if there is one, else
    the signature. The dynamic path now applies the same rule.
    """

    @staticmethod
    def _config_twin(tmp_path: Path) -> FunctualizeApp:
        jobs_dir = tmp_path / "jobs"
        jobs_dir.mkdir()
        (jobs_dir / "twin.py").write_text(
            textwrap.dedent(
                '''
                from pydantic import BaseModel, Field
                from functualize.job import job


                class NeedsCity(BaseModel):
                    city: str = Field(description="required, no default")
                    tries: int = 3


                @job
                def needsconfig(config: NeedsCity) -> str:
                    """Needs config."""
                    return config.city
                '''
            )
        )
        return FunctualizeApp(
            "twin", job_sources=JobSources(directories=[str(jobs_dir)], lazy=False)
        )

    @staticmethod
    def _config_dynamic() -> FunctualizeApp:
        app = FunctualizeApp("dyn", job_sources=JobSources())
        app.register_dynamic_job("needsconfig", needs_config, config_class=NeedsCity)
        return app

    def test_config_fields_are_the_models_fields_not_the_parameter(self) -> None:
        descriptor = _descriptor(self._config_dynamic(), "needsconfig")
        assert [f.name for f in descriptor.parameters] == ["config"]
        assert [f.name for f in descriptor.config_fields] == ["city", "tries"]

    def test_it_matches_the_discovered_twin(self, tmp_path: Path) -> None:
        dynamic = _descriptor(self._config_dynamic(), "needsconfig")
        discovered = _descriptor(self._config_twin(tmp_path), "needsconfig")
        assert [f.name for f in dynamic.config_fields] == [
            f.name for f in discovered.config_fields
        ]
        assert [f.required for f in dynamic.config_fields] == [
            f.required for f in discovered.config_fields
        ]

    def test_the_published_schema_matches_the_discovered_twin(
        self, tmp_path: Path
    ) -> None:
        """The payload an agent actually reads. Publishing `config: NeedsCity`
        here would tell an MCP client to send an object it has no schema for."""
        from functualize._cli.info import job_detail

        dynamic = job_detail(self._config_dynamic(), "needsconfig")
        discovered = job_detail(self._config_twin(tmp_path), "needsconfig")
        assert dynamic is not None and discovered is not None
        assert dynamic["inputSchema"] == discovered["inputSchema"]
        assert set(dynamic["inputSchema"]["properties"]) == {"city", "tries"}
        assert "config" not in dynamic["inputSchema"]["properties"]

    def test_an_explicit_config_class_is_honoured_without_an_annotation(self) -> None:
        """`register_dynamic_job(config_class=...)` is the caller stating the
        answer -- and the one `RegisteredJob` already trusts. It must win even
        when the signature carries nothing to detect."""

        def unannotated(config) -> str:  # type: ignore[no-untyped-def]
            """No annotation to detect."""
            return str(config)

        app = FunctualizeApp("dyn", job_sources=JobSources())
        app.register_dynamic_job("bare", unannotated, config_class=NeedsCity)
        assert [f.name for f in _descriptor(app, "bare").config_fields] == [
            "city",
            "tries",
        ]

    def test_a_job_without_a_config_class_falls_back_to_its_parameters(self) -> None:
        """The `else` branch of discovery's rule, which the fallback in
        `job_detail` depends on."""
        descriptor = _descriptor(_dynamic_app(), "dynamic-target")
        assert [f.name for f in descriptor.config_fields] == [
            f.name for f in descriptor.parameters
        ]


class TestWhatTheDynamicPathAlreadyGotRight:
    """Regression guard. The fix inserts one extraction into a descriptor
    built from six others; the rest must keep working."""

    def test_the_declaration_and_module_path_survive(self) -> None:
        descriptor = _descriptor(_dynamic_app(), "dynamic-target")
        assert descriptor.source == "<dynamic>"
        assert descriptor.module_path == dynamic_target.__module__
        assert descriptor.docstring == "A job registered from code."
