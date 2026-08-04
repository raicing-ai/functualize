"""Unit tests for JobToolTranslator."""

from __future__ import annotations

from dataclasses import dataclass, field
from types import SimpleNamespace
from typing import Any

from functualize_mcp._config import MCPConfig
from functualize_mcp._translator import JobToolTranslator

# ---------------------------------------------------------------------------
# Test helpers — minimal descriptor fakes
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class FakeField:
    name: str
    type_annotation: str
    default: Any | None = None
    description: str = ""
    required: bool = True
    choices: list[str] | None = None


@dataclass
class FakeDescriptor:
    name: str
    group: str | None = None
    docstring: str | None = None
    config_fields: list[FakeField] = field(default_factory=list)
    parameters: list[FakeField] = field(default_factory=list)
    declaration: Any = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Tests for translate()
# ---------------------------------------------------------------------------


class TestTranslateSingle:
    """Tests for translating a single JobDescriptor."""

    def test_name_passthrough(self):
        """Tool name matches job name."""
        translator = JobToolTranslator()
        desc = FakeDescriptor(name="deploy_app")
        result = translator.translate(desc)
        assert result.name == "deploy_app"

    def test_description_from_docstring_first_paragraph(self):
        """Description uses only the first paragraph of docstring."""
        translator = JobToolTranslator()
        desc = FakeDescriptor(
            name="my_job",
            docstring="First line of description.\nSecond line.\n\nSecond paragraph.",
        )
        result = translator.translate(desc)
        assert result.description == "First line of description. Second line."

    def test_description_empty_docstring(self):
        """Empty description when docstring is None."""
        translator = JobToolTranslator()
        desc = FakeDescriptor(name="my_job", docstring=None)
        result = translator.translate(desc)
        assert result.description == ""

    def test_description_extra_description_takes_precedence(self):
        """extra_description from metadata overrides docstring."""
        translator = JobToolTranslator()
        desc = FakeDescriptor(
            name="my_job",
            docstring="Original docstring.",
            declaration=SimpleNamespace(
                extra_description="AI-optimized description",
                category=None,
                examples=None,
                tags=None,
                visibility=None,
            ),
        )
        result = translator.translate(desc)
        assert result.description == "AI-optimized description"

    def test_description_includes_examples(self):
        """Examples from metadata are appended to description."""
        translator = JobToolTranslator()
        desc = FakeDescriptor(
            name="my_job",
            docstring="Deploy the app.",
            declaration=SimpleNamespace(
                extra_description=None,
                category=None,
                examples=["deploy --env prod", "deploy --env staging"],
                tags=None,
                visibility=None,
            ),
        )
        result = translator.translate(desc)
        assert "Deploy the app." in result.description
        assert "Examples:" in result.description
        assert "deploy --env prod" in result.description
        assert "deploy --env staging" in result.description

    def test_input_schema_from_config_fields(self):
        """inputSchema is generated from config_fields."""
        translator = JobToolTranslator()
        desc = FakeDescriptor(
            name="my_job",
            config_fields=[
                FakeField(
                    name="target",
                    type_annotation="str",
                    required=True,
                    description="Deployment target",
                ),
                FakeField(
                    name="port",
                    type_annotation="int",
                    required=False,
                    default=8080,
                    description="Port number",
                ),
            ],
        )
        result = translator.translate(desc)
        schema = result.input_schema

        assert schema["type"] == "object"
        assert "target" in schema["properties"]
        assert schema["properties"]["target"]["type"] == "string"
        assert schema["properties"]["target"]["description"] == "Deployment target"
        assert "port" in schema["properties"]
        assert schema["properties"]["port"]["type"] == "integer"
        assert schema["properties"]["port"]["default"] == 8080
        assert "target" in schema["required"]
        assert "port" not in schema.get("required", [])

    def test_input_schema_falls_back_to_parameters(self):
        """Uses parameters when config_fields is empty."""
        translator = JobToolTranslator()
        desc = FakeDescriptor(
            name="my_job",
            config_fields=[],
            parameters=[
                FakeField(name="name", type_annotation="str", required=True),
            ],
        )
        result = translator.translate(desc)
        assert "name" in result.input_schema["properties"]

    def test_input_schema_empty_when_no_fields(self):
        """Empty properties when no fields defined."""
        translator = JobToolTranslator()
        desc = FakeDescriptor(name="my_job")
        result = translator.translate(desc)
        assert result.input_schema["properties"] == {}

    def test_input_schema_enum_choices(self):
        """Enum choices are included in JSON Schema."""
        translator = JobToolTranslator()
        desc = FakeDescriptor(
            name="my_job",
            config_fields=[
                FakeField(
                    name="env",
                    type_annotation="str",
                    required=True,
                    choices=["dev", "staging", "prod"],
                ),
            ],
        )
        result = translator.translate(desc)
        assert result.input_schema["properties"]["env"]["enum"] == [
            "dev",
            "staging",
            "prod",
        ]

    def test_input_schema_type_mappings(self):
        """Various type annotations map to correct JSON Schema types."""
        translator = JobToolTranslator()
        desc = FakeDescriptor(
            name="my_job",
            config_fields=[
                FakeField(name="flag", type_annotation="bool", required=True),
                FakeField(name="ratio", type_annotation="float", required=True),
                FakeField(name="items", type_annotation="list[str]", required=True),
            ],
        )
        result = translator.translate(desc)
        props = result.input_schema["properties"]
        assert props["flag"]["type"] == "boolean"
        assert props["ratio"]["type"] == "number"
        assert props["items"]["type"] == "array"
        assert props["items"]["items"] == {"type": "string"}

    def test_annotations_from_tags(self):
        """Tags from metadata appear in annotations."""
        translator = JobToolTranslator()
        desc = FakeDescriptor(
            name="my_job",
            declaration=SimpleNamespace(
                extra_description=None,
                category="deployment",
                examples=None,
                tags=["deploy", "production"],
                visibility="external",
            ),
        )
        result = translator.translate(desc)
        assert result.annotations["tags"] == ["deploy", "production"]
        assert result.annotations["category"] == "deployment"
        assert result.annotations["visibility"] == "external"

    def test_annotations_include_group(self):
        """Group from descriptor is exported as its structured trie shape (D2-a).

        Was a bare dotted string; now the namespace as an array plus a kind, so
        an agent reads the hierarchy as data rather than re-splitting a string.
        """
        translator = JobToolTranslator()
        desc = FakeDescriptor(name="infra.aws.my_job", group="infra.aws")
        result = translator.translate(desc)
        assert result.annotations["group"] == {
            "namespace": ["infra", "aws"],
            "kind": "job",
        }

    def test_annotations_empty_when_no_metadata(self):
        """Annotations is empty dict when no metadata."""
        translator = JobToolTranslator()
        desc = FakeDescriptor(name="my_job")
        result = translator.translate(desc)
        assert result.annotations == {}

    def test_metadata_as_dict(self):
        """Works when metadata is a plain dict (cached form)."""
        translator = JobToolTranslator()
        desc = FakeDescriptor(
            name="my_job",
            declaration={
                "extra_description": "Dict-based description",
                "category": "utils",
                "examples": ["example1"],
                "tags": ["util"],
                "visibility": "external",
            },
        )
        result = translator.translate(desc)
        assert result.description.startswith("Dict-based description")
        assert "example1" in result.description
        assert result.annotations["tags"] == ["util"]
        assert result.annotations["category"] == "utils"


# ---------------------------------------------------------------------------
# Tests for translate_all() with filtering
# ---------------------------------------------------------------------------


class TestTranslateAll:
    """Tests for batch translation with MCPConfig visibility filters."""

    def test_excludes_internal_jobs(self):
        """Jobs with visibility=internal are excluded."""
        translator = JobToolTranslator()
        descriptors = [
            FakeDescriptor(
                name="public_job",
                declaration=SimpleNamespace(
                    extra_description=None,
                    category=None,
                    examples=None,
                    tags=None,
                    visibility="external",
                ),
            ),
            FakeDescriptor(
                name="internal_job",
                declaration=SimpleNamespace(
                    extra_description=None,
                    category=None,
                    examples=None,
                    tags=None,
                    visibility="internal",
                ),
            ),
        ]
        config = MCPConfig()
        results = translator.translate_all(descriptors, config)
        names = [r.name for r in results]
        assert "public_job" in names
        assert "internal_job" not in names

    def test_exclude_jobs_by_name(self):
        """Jobs listed in exclude_jobs are excluded."""
        translator = JobToolTranslator()
        descriptors = [
            FakeDescriptor(name="keep_me"),
            FakeDescriptor(name="drop_me"),
        ]
        config = MCPConfig(exclude_jobs=["drop_me"])
        results = translator.translate_all(descriptors, config)
        names = [r.name for r in results]
        assert "keep_me" in names
        assert "drop_me" not in names

    def test_exclude_tags(self):
        """Jobs tagged with excluded tags are excluded."""
        translator = JobToolTranslator()
        descriptors = [
            FakeDescriptor(
                name="safe_job",
                declaration=SimpleNamespace(
                    extra_description=None,
                    category=None,
                    examples=None,
                    tags=["safe"],
                    visibility=None,
                ),
            ),
            FakeDescriptor(
                name="dangerous_job",
                declaration=SimpleNamespace(
                    extra_description=None,
                    category=None,
                    examples=None,
                    tags=["dangerous"],
                    visibility=None,
                ),
            ),
        ]
        config = MCPConfig(exclude_tags=["dangerous"])
        results = translator.translate_all(descriptors, config)
        names = [r.name for r in results]
        assert "safe_job" in names
        assert "dangerous_job" not in names

    def test_include_tags_filter(self):
        """When include_tags is set, only matching jobs are included."""
        translator = JobToolTranslator()
        descriptors = [
            FakeDescriptor(
                name="tagged_job",
                declaration=SimpleNamespace(
                    extra_description=None,
                    category=None,
                    examples=None,
                    tags=["allowed"],
                    visibility=None,
                ),
            ),
            FakeDescriptor(
                name="untagged_job",
                declaration=SimpleNamespace(
                    extra_description=None,
                    category=None,
                    examples=None,
                    tags=["other"],
                    visibility=None,
                ),
            ),
            FakeDescriptor(
                name="no_tags_job",
                declaration={},
            ),
        ]
        config = MCPConfig(include_tags=["allowed"])
        results = translator.translate_all(descriptors, config)
        names = [r.name for r in results]
        assert "tagged_job" in names
        assert "untagged_job" not in names
        assert "no_tags_job" not in names

    def test_include_tags_empty_means_all(self):
        """Empty include_tags means no tag filtering (all visible)."""
        translator = JobToolTranslator()
        descriptors = [
            FakeDescriptor(name="job_a"),
            FakeDescriptor(name="job_b"),
        ]
        config = MCPConfig(include_tags=[])
        results = translator.translate_all(descriptors, config)
        assert len(results) == 2

    def test_combined_filters(self):
        """Multiple filters are applied together."""
        translator = JobToolTranslator()
        descriptors = [
            FakeDescriptor(
                name="visible_tagged",
                declaration=SimpleNamespace(
                    extra_description=None,
                    category=None,
                    examples=None,
                    tags=["api"],
                    visibility="external",
                ),
            ),
            FakeDescriptor(
                name="internal_tagged",
                declaration=SimpleNamespace(
                    extra_description=None,
                    category=None,
                    examples=None,
                    tags=["api"],
                    visibility="internal",
                ),
            ),
            FakeDescriptor(
                name="excluded_by_name",
                declaration=SimpleNamespace(
                    extra_description=None,
                    category=None,
                    examples=None,
                    tags=["api"],
                    visibility=None,
                ),
            ),
        ]
        config = MCPConfig(
            include_tags=["api"],
            exclude_jobs=["excluded_by_name"],
        )
        results = translator.translate_all(descriptors, config)
        names = [r.name for r in results]
        assert names == ["visible_tagged"]


# ---------------------------------------------------------------------------
# Group options in the tool schema (S6a T-GO-5)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class FakeSpec:
    """Stands in for a cached ``GroupOptionsSpec``."""

    group: str
    class_name: str
    fields: list[FakeField] = field(default_factory=list)


_DEPLOY_SPEC = FakeSpec(
    group="deploy",
    class_name="DeployOptions",
    fields=[
        FakeField(
            name="env",
            type_annotation="str",
            default="staging",
            description="Target environment",
            required=False,
        ),
        FakeField(
            name="dry_run",
            type_annotation="bool",
            default=False,
            required=False,
        ),
    ],
)

_WEB_SPEC = FakeSpec(
    group="deploy.web",
    class_name="WebOptions",
    fields=[
        FakeField(name="replicas", type_annotation="int", default=1, required=False),
    ],
)


class TestGroupOptionsInSchema:
    """A group's flags are typeable on the command line, so an agent must be
    able to set them too — otherwise the MCP surface is strictly weaker than
    the shell for no reason a tool description could explain."""

    def _translator(self) -> JobToolTranslator:
        return JobToolTranslator({"deploy": _DEPLOY_SPEC, "deploy.web": _WEB_SPEC})

    def test_inherited_options_appear_in_the_schema(self):
        desc = FakeDescriptor(
            name="run",
            group="deploy.web",
            parameters=[
                FakeField(name="image", type_annotation="str", default="nginx")
            ],
        )

        result = self._translator().translate(desc)

        properties = result.input_schema["properties"]
        assert set(properties) == {"image", "env", "dry_run", "replicas"}
        assert properties["env"]["description"] == "Target environment"
        assert properties["env"]["default"] == "staging"
        assert properties["dry_run"]["type"] == "boolean"

    def test_the_group_names_are_reported_separately(self):
        """The wrapper needs the split: a group field is not a parameter of
        the job function and must reach the engine as a group layer."""
        desc = FakeDescriptor(
            name="run",
            group="deploy.web",
            parameters=[FakeField(name="image", type_annotation="str")],
        )

        result = self._translator().translate(desc)

        assert result.group_option_names == {"env", "dry_run", "replicas"}

    def test_a_job_outside_the_group_gets_nothing(self):
        desc = FakeDescriptor(
            name="other",
            group="unrelated",
            parameters=[FakeField(name="image", type_annotation="str")],
        )

        result = self._translator().translate(desc)

        assert set(result.input_schema["properties"]) == {"image"}
        assert result.group_option_names == frozenset()

    def test_an_ungrouped_job_gets_nothing(self):
        desc = FakeDescriptor(
            name="loose", parameters=[FakeField(name="image", type_annotation="str")]
        )

        result = self._translator().translate(desc)

        assert result.group_option_names == frozenset()

    def test_only_ancestors_on_the_path_are_inherited(self):
        """`deploy` sees its own options, not its child's."""
        desc = FakeDescriptor(
            name="top",
            group="deploy",
            parameters=[FakeField(name="image", type_annotation="str")],
        )

        result = self._translator().translate(desc)

        assert "replicas" not in result.input_schema["properties"]
        assert result.group_option_names == {"env", "dry_run"}

    def test_the_jobs_own_field_wins_a_name_clash(self):
        """One flat namespace over MCP, and the job's parameter is the nearer
        declaration — the rule position encodes on the command line (D-d)."""
        desc = FakeDescriptor(
            name="run",
            group="deploy",
            parameters=[
                FakeField(
                    name="env",
                    type_annotation="str",
                    default="job-default",
                    description="the job's own",
                    required=False,
                )
            ],
        )

        result = self._translator().translate(desc)

        assert (
            result.input_schema["properties"]["env"]["description"] == "the job's own"
        )
        assert "env" not in result.group_option_names

    def test_group_options_are_never_required(self):
        """They always resolve to something (default < file < env), so
        demanding one would make every call carry it."""
        required_field = FakeField(name="token", type_annotation="str", required=True)
        spec = FakeSpec(group="deploy", class_name="D", fields=[required_field])
        desc = FakeDescriptor(name="run", group="deploy")

        result = JobToolTranslator({"deploy": spec}).translate(desc)

        assert "token" not in result.input_schema.get("required", [])

    def test_the_injection_parameter_itself_is_not_an_argument(self):
        """`opts: DeployOptions` is where the resolved instance lands. Exposed,
        it would show as a bare string an agent might try to fill in — while
        the flags it stands for are already published individually."""
        desc = FakeDescriptor(
            name="run",
            group="deploy",
            parameters=[
                FakeField(name="image", type_annotation="str"),
                FakeField(name="opts", type_annotation="DeployOptions"),
            ],
        )

        result = self._translator().translate(desc)

        assert "opts" not in result.input_schema["properties"]
        assert "image" in result.input_schema["properties"]

    def test_a_translator_without_specs_is_unchanged(self):
        """Every existing caller passes nothing; nothing about them moves."""
        desc = FakeDescriptor(
            name="run",
            group="deploy.web",
            parameters=[FakeField(name="image", type_annotation="str")],
        )

        result = JobToolTranslator().translate(desc)

        assert set(result.input_schema["properties"]) == {"image"}
        assert result.group_option_names == frozenset()
