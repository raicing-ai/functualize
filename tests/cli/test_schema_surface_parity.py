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

import pytest

from functualize.app.utils import field_property, input_schema, job_input_schema


class _Field:
    """Minimal FieldDescriptor stand-in — only what the renderer reads."""

    def __init__(
        self,
        name,
        type_annotation="str",
        default=None,
        description=None,
        required=False,
        choices=None,
    ):
        self.name = name
        self.type_annotation = type_annotation
        self.default = default
        self.description = description
        self.required = required
        self.choices = choices
        self.is_stdin = False


class _Descriptor:
    def __init__(self, parameters, config_fields=None):
        self.parameters = parameters
        self.config_fields = config_fields


def test_known_types_map_to_json_schema_types():
    assert field_property(_Field("a", "int"))["type"] == "integer"
    assert field_property(_Field("a", "float"))["type"] == "number"
    assert field_property(_Field("a", "bool"))["type"] == "boolean"
    assert field_property(_Field("a", "list[str]")) == {
        "type": "array",
        "items": {"type": "string"},
    }


def test_unknown_type_degrades_to_string():
    """The honest answer: the CLI would take the flag as text too."""
    assert field_property(_Field("a", "SomeCustomClass"))["type"] == "string"
    assert field_property(_Field("a", None))["type"] == "string"


def test_default_is_omitted_on_a_required_field():
    """A default on a required field advertises a value the caller must supply."""
    prop = field_property(_Field("a", "int", default=5, required=True))
    assert "default" not in prop
    assert field_property(_Field("a", "int", default=5))["default"] == 5


def test_choices_become_an_enum():
    assert field_property(_Field("a", "str", choices=["x", "y"]))["enum"] == ["x", "y"]


def test_required_is_omitted_rather_than_emitted_empty():
    """An empty `required` is noise, and some consumers read its presence."""
    schema = input_schema([_Field("a")])
    assert "required" not in schema

    schema = input_schema([_Field("a", required=True)])
    assert schema["required"] == ["a"]


def test_config_fields_win_over_parameters():
    """A job taking a config model publishes the model's fields, not the model."""
    descriptor = _Descriptor(
        parameters=[_Field("config", "DeployConfig")],
        config_fields=[_Field("region", "str", required=True)],
    )
    assert set(job_input_schema(descriptor)["properties"]) == {"region"}


def test_group_options_injection_point_is_not_published():
    """`opts: DeployOptions` is where resolved options land, not an argument.

    Its flags are published individually; exposing the parameter too would
    offer a bare string an agent might try to fill in.
    """
    descriptor = _Descriptor(
        parameters=[
            _Field("image", "str", required=True),
            _Field("opts", "DeployOptions"),
        ]
    )
    schema = job_input_schema(descriptor, group_options_class_names={"DeployOptions"})
    assert set(schema["properties"]) == {"image"}


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
