"""`func builtin info schema` and an MCP tool must describe a job identically.

Two renderings of one contract is how they drift. The MCP plugin owned the
only JSON Schema builder, and it published `Stdout` and `Shell` as required
string arguments for as long as nobody compared it to the CLI — which filtered
them correctly on an entirely separate code path.

Core now owns the renderer (`functualize.app.utils.job_input_schema`) and the
plugin calls it. These tests hold that: if someone reintroduces a second
builder, the two surfaces diverge here rather than in a user's agent.
"""

from __future__ import annotations

from enum import Enum

import pytest
from pydantic import BaseModel

from functualize._discovery.group_options_extractor import extract_group_options_spec
from functualize._discovery.schema_extractor import extract_field_descriptors
from functualize._primitives.parameter_contract import build_contracts
from functualize._types.descriptors import FieldDescriptor, JobDescriptor
from functualize.app.utils import field_property, input_schema, job_input_schema
from functualize.job import GroupOptions
from tests._support.declared_fields import declared


def _field(
    name,
    annotation="str",
    default=None,
    description=None,
    required=False,
    choices=None,
):
    """A field whose schema comes from its declaration contract."""
    return declared(
        name,
        annotation or "str",
        default=default,
        description=description or "",
        required=required,
        choices=choices,
    )


class _Descriptor:
    def __init__(self, parameters, config_fields=None):
        self.parameters = parameters
        self.config_fields = config_fields


def test_known_types_map_to_json_schema_types():
    assert field_property(_field("a", "int"))["type"] == "integer"
    assert field_property(_field("a", "float"))["type"] == "number"
    assert field_property(_field("a", "bool"))["type"] == "boolean"
    assert field_property(_field("a", "list[str]")) == {
        "type": "array",
        "items": {"type": "string"},
    }


def test_unknown_type_is_refused_by_the_contract():
    """An unresolved declaration publishes no input schema."""
    assert field_property(_field("a", "SomeCustomClass")) == {}
    assert field_property(_field("a", None))["type"] == "string"


def test_default_is_omitted_on_a_required_field():
    """A default on a required field advertises a value the caller must supply."""
    prop = field_property(_field("a", "int", default=5, required=True))
    assert "default" not in prop
    assert field_property(_field("a", "int", default=5))["default"] == 5


def test_choices_become_an_enum():
    assert field_property(_field("a", "str", choices=["x", "y"]))["enum"] == ["x", "y"]


def test_required_is_omitted_rather_than_emitted_empty():
    """An empty `required` is noise, and some consumers read its presence."""
    schema = input_schema([_field("a")])
    assert "required" not in schema

    schema = input_schema([_field("a", required=True)])
    assert schema["required"] == ["a"]


def test_config_fields_win_over_parameters():
    """A job taking a config model publishes the model's fields, not the model."""
    descriptor = _Descriptor(
        parameters=[_field("config", "DeployConfig")],
        config_fields=[_field("region", "str", required=True)],
    )
    assert set(job_input_schema(descriptor)["properties"]) == {"region"}


def test_group_options_injection_point_is_not_published():
    """`opts: DeployOptions` is where resolved options land, not an argument.

    Its flags are published individually; exposing the parameter too would
    offer a bare string an agent might try to fill in.
    """
    descriptor = _Descriptor(
        parameters=[
            _field("image", "str", required=True),
            _field("opts", "DeployOptions"),
        ]
    )
    schema = job_input_schema(descriptor, group_options_class_names={"DeployOptions"})
    assert set(schema["properties"]) == {"image"}


def test_refused_group_option_is_absent_from_core_and_mcp():
    from functualize_mcp._translator import JobToolTranslator

    class BadOptions(GroupOptions, group="deploy"):
        bad: dict[str, str] = {}

    specs = {"deploy": extract_group_options_spec(BadOptions)}
    descriptor = JobDescriptor(name="run", group="deploy")
    core = job_input_schema(descriptor, group_options=specs)
    mcp = JobToolTranslator(specs).translate(descriptor).input_schema
    assert "bad" not in core["properties"]
    assert "bad" not in mcp["properties"]


def test_contract_enum_values_keep_their_integer_type():
    class Number(Enum):
        ONE = 1
        TWO = 2

    class Config(BaseModel):
        number: Number = Number.ONE

    field = extract_field_descriptors(Config)[0]
    assert field_property(field) == {"type": "integer", "enum": [1, 2], "default": 1}


def test_literal_required_sentinel_is_a_valid_default():
    def job(value: str = "__REQUIRED__") -> None:
        pass

    contract = build_contracts(job)[0]
    field = FieldDescriptor(
        name="value",
        default="__REQUIRED__",
        description="",
        required=False,
        contract=contract,
    )
    assert field_property(field)["default"] == "__REQUIRED__"


def test_nested_group_override_and_group_only_shape_match_mcp():
    from functualize_mcp._translator import JobToolTranslator

    from functualize._cli.info import job_detail

    class Parent(GroupOptions, group="a"):
        x: str = "parent"

    class Child(GroupOptions, group="a.b"):
        x: int = 2

    specs = {
        "a": extract_group_options_spec(Parent),
        "a.b": extract_group_options_spec(Child),
    }
    translator = JobToolTranslator(specs)
    for group in ("a", "a.b"):
        descriptor = JobDescriptor(name="run", group=group)
        core = job_input_schema(descriptor, group_options=specs)
        mcp = translator.translate(descriptor).input_schema

        class AppLike:
            _discovery_config = None
            _group_options = specs

            def __init__(self, job_descriptor):
                self.job_descriptor = job_descriptor

            def get_jobs(self):
                return [self.job_descriptor]

        detail = job_detail(AppLike(descriptor), "run")
        assert detail is not None
        assert detail["inputSchema"] == mcp
        assert core == mcp
        assert core["required"] == []
    assert (
        job_input_schema(JobDescriptor(name="run", group="a.b"), group_options=specs)[
            "properties"
        ]["x"]["default"]
        == 2
    )


def test_info_group_options_reader_tracks_app_changes():
    from functualize._cli.info import _group_options

    class AppLike:
        _discovery_config = None

        def __init__(self):
            self._group_options = {"a": object()}

    app = AppLike()
    first = _group_options(app)
    app._group_options = {"b": object()}
    second = _group_options(app)
    assert set(first) == {"a"}
    assert set(second) == {"b"}


def test_mcp_translator_delegates_to_the_core_renderer():
    """The plugin must not carry a second builder.

    Imported lazily so the test skips cleanly where the plugin is absent
    rather than failing for an unrelated reason.
    """
    translator_module = pytest.importorskip("functualize_mcp._translator")

    source = __import__("inspect").getsource(translator_module)
    assert "job_input_schema" in source, (
        "the MCP translator no longer delegates to core's schema renderer — "
        "a second builder is how Stdout and Shell leaked last time"
    )
    assert "_TYPE_MAP: dict" not in source, (
        "the plugin has reintroduced a local type map; core owns TYPE_MAP"
    )


def test_cli_schema_matches_mcp_schema_for_the_same_job(cli_run, project_tree):
    """End to end: the two surfaces agree on a real job, not a stub."""
    pytest.importorskip("functualize_mcp")
    import json

    project = project_tree(
        jobs={
            "jobs.py": (
                '"""Jobs."""\n'
                "from functualize.job import Log, Shell, Stdout\n"
                "\n"
                "\n"
                "def deploy(log: Log, sh: Shell, out: Stdout,\n"
                "           region: str, dry_run: bool = False) -> None:\n"
                '    """Deploy the app."""\n'
            )
        }
    )

    cli = cli_run(["builtin", "info", "schema", "deploy"], cwd=project)
    assert cli.exit_code == 0
    cli_schema = json.loads(cli.stdout)

    mcp = cli_run(["mcp", "schema"], cwd=project)
    assert mcp.exit_code == 0
    mcp_schema = next(
        tool for tool in json.loads(mcp.stdout) if tool["name"] == "deploy"
    )

    assert cli_schema["inputSchema"] == mcp_schema["inputSchema"]
    # And neither publishes a capability.
    assert set(cli_schema["inputSchema"]["properties"]) == {"region", "dry_run"}
