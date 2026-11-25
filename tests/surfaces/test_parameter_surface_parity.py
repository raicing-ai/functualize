"""One verdict per parameter, on every surface (spec AC-10).

Every row of ``tests/_support/parameter_matrix.py`` is a job module. The rows
are booted in groups by the real ``func``, in a subprocess, cold and then warm
(``pitfalls.md`` §23), with and without ``from __future__ import annotations``
(B-6). Inside each boot the probe plugin (``_parity_probe``) records what ten
surfaces publish and deliver for each row: ``func <job> --help``, the bash and
zsh completion scripts, the SmartBar, the inline TUI's door, ``info``'s input
schema, the MCP tool's schema and call, the HTTP route and the Lambda handler.
:func:`expectations_for` states what the row's verdict requires of each, and
the test reports every disagreement for a group at once.

A refusal's rendering is asserted where only a real process can show it
(§25): ``func <job>`` for each refusal class exits 2 with one ``Error:`` line
and no traceback, cold and warm.

The second half of this module holds the assertions folded in from the three
cross-builder tests this one replaces (``tests/adapters/test_cold_warm_parity.py``,
``tests/config/test_click_builder_agreement.py``,
``tests/cli/test_schema_surface_parity.py``), each under its original name.
"""

from __future__ import annotations

from enum import Enum, StrEnum
from pathlib import Path
from typing import Annotated, Any

import pytest
from pydantic import BaseModel, Field

from functualize._discovery.group_options_extractor import extract_group_options_spec
from functualize._discovery.schema_extractor import extract_field_descriptors
from functualize._primitives.parameter_contract import build_contracts
from functualize._types.descriptors import FieldDescriptor, JobDescriptor
from functualize.app.adapters.click_params import (
    build_click_params,
    build_click_params_from_fields,
)
from functualize.app.utils import field_property, input_schema, job_input_schema
from functualize.job import GroupOptions, Log, Option
from tests._support.declared_fields import declared
from tests.surfaces._parity_project import (
    GROUPS,
    dump,
    func,
    is_group_row,
    write_project,
)

MODES = pytest.mark.parametrize("future", [False, True], ids=["eager", "pep563"])
_CALLER = {"ACCEPTED_FLAG", "ACCEPTED_POSITIONAL", "CONFIG_FIELD"}
_WIRE_SURFACES = ("mcp", "http", "lambda")
#: The class name a delivered value has, where it is not the annotation's own.
_DELIVERED_AS = {"Path": {"PosixPath", "WindowsPath", "Path"}}


# ─── reading a cell ──────────────────────────────────────────────────────────


def _accepted(cell: Any) -> bool:
    if not isinstance(cell, dict) or "raised" in cell:
        return False
    if cell.get("is_error"):
        return False
    return cell.get("status") == "success" and cell.get("code", 200) == 200


def _refused(cell: Any) -> bool:
    """A refusal before the job ran: a usage error, or ``Invalid`` with a 4xx."""
    if not isinstance(cell, dict):
        return False
    if "raised" in cell:
        return cell["raised"].split(":", 1)[0] in {
            "UsageError",
            "NoSuchOption",
            "MissingParameter",
            "BadParameter",
            "BadOptionUsage",
            "BadArgumentUsage",
        }
    code = cell.get("code", 400)
    return cell.get("status") == "invalid" and 400 <= code < 500


def _delivered(expected: str | None, cell: dict[str, Any]) -> bool:
    if not expected:
        return True
    base = expected.split("[", 1)[0]
    return cell.get("type") in _DELIVERED_AS.get(base, {base})


# ─── what a verdict requires ─────────────────────────────────────────────────


def check_row(row: dict[str, Any], seen: dict[str, Any]) -> list[str]:
    """Every way ``seen`` disagrees with ``row``'s verdict; empty when none."""
    verdict, required = row["expected_verdict"], row["required"]
    spelling, wire = row["cli_spelling"], row["wire_spelling"]
    probe, group = row["probe"], is_group_row(row)
    problems: list[str] = []

    def bad(surface: str, what: str) -> None:
        problems.append(f"{surface}: {what}")

    # info and MCP publish exactly the wire inputs, with their requiredness.
    for surface in ("info", "mcp_schema"):
        schema = seen.get(surface)
        if not isinstance(schema, dict) or "raised" in schema:
            bad(surface, f"no schema ({schema})")
            continue
        props, needed = schema.get("properties", {}), schema.get("required", [])
        if wire:
            key = wire[0]
            if key not in props:
                bad(surface, f"{key!r} not published")
            elif (key in needed) != (required and not group):
                bad(
                    surface,
                    f"{key!r} required={key in needed}, verdict says {required}",
                )
        elif probe in props:
            bad(surface, f"{probe!r} published for a {verdict} parameter")

    # `func <job> --help` renders exactly the command-line inputs.
    helped = seen.get("help", {})
    if not group:
        if "raised" in helped:
            bad("help", helped["raised"])
        else:
            params = {p["name"]: p for p in helped["params"] if p["name"] != "help"}
            name = row["probe"]
            param = params.get(name)
            if spelling and param is None:
                bad("help", f"{name!r} not rendered")
            elif not spelling and param is not None:
                bad("help", f"{name!r} rendered for a {verdict} parameter")
            elif param is not None:
                positional = not spelling[0].startswith("-")
                if positional != (param["kind"] == "Argument"):
                    bad(
                        "help",
                        f"{name!r} is a {param['kind']}, verdict says {spelling}",
                    )
                elif not positional and spelling[0] not in param["opts"]:
                    bad("help", f"{spelling[0]} not among {param['opts']}")
                if verdict == "CONFIG_FIELD":
                    shown = (
                        "[required]" in helped["text"]
                        or "\\[required]" in helped["text"]
                    )
                    if required and not shown:
                        bad("help", "required config field not marked [required]")
                elif "Stdin(" in row["declaration"]:
                    pass  # stdin may supply it: never click-required (B-14)
                elif param["required"] != required and not (
                    param["kind"] == "Option" and not required
                ):
                    bad(
                        "help",
                        f"{name!r} required={param['required']}, verdict says {required}",
                    )
                if param["hidden"] != row["hidden"]:
                    bad("help", f"{name!r} hidden={param['hidden']}")

    # Completion and the SmartBar offer exactly the visible flags.
    flag = spelling[0] if spelling and spelling[0].startswith("-") else None
    for surface in ("bash", "zsh", "smartbar"):
        if group:
            break
        words = seen.get(surface)
        if not isinstance(words, list):
            bad(surface, f"no candidates ({words})")
            continue
        if flag and not row["hidden"] and flag not in words:
            bad(surface, f"{flag} not offered (offers {words})")
        if flag and row["hidden"] and flag in words:
            bad(surface, f"hidden {flag} offered")
        if not flag and f"--{probe}" in words:
            bad(surface, f"--{probe} offered for a {verdict} parameter")

    # Calls: what each door does with a supplied value, and with none.
    for surface in ("tui", *_WIRE_SURFACES):
        given, absent = seen.get(f"{surface}_given"), seen.get(f"{surface}_absent")
        on_wire = surface in _WIRE_SURFACES
        if verdict in _CALLER or (verdict == "INVOCATION_ONLY" and on_wire):
            if not _accepted(given):
                bad(surface, f"a supplied value was not accepted: {given}")
            elif not _delivered(row["delivered_type"], given):
                bad(
                    surface,
                    f"delivered {given.get('type')}, declared {row['delivered_type']}",
                )
            if (
                required
                and not group
                and verdict != "CONFIG_FIELD"
                and not _refused(absent)
            ):
                bad(surface, f"a required input absent was not refused: {absent}")
            if not required and not _accepted(absent):
                bad(surface, f"an optional input absent was not accepted: {absent}")
        elif verdict == "INVOCATION_ONLY":  # the TUI has no spelling for it (B-15)
            if not _refused(given):
                bad(surface, f"a command-line spelling was accepted: {given}")
        elif verdict == "INJECTED":
            if not _refused(given):
                bad(
                    surface,
                    f"a value for an injected parameter was not refused: {given}",
                )
        else:  # REJECTED_DISCOVERY: listed, and every call refused (DC-1 = B)
            for case, cell in (("given", given), ("absent", absent)):
                if not _refused(cell):
                    bad(
                        surface,
                        f"a call ({case}) to a refused job was not refused: {cell}",
                    )
    return problems


def _report(
    group: tuple[dict[str, Any], ...], seen: dict[str, Any], future: bool
) -> list[str]:
    lines: list[str] = []
    for row in group:
        cell = seen.get(row["id"], {})
        if row["id"] == "E142" and not future:
            # `FromJob[...]` is not a type: the module fails to import without
            # PEP 563, so the job is reported and never registered (B-6).
            if cell.get("registered"):
                lines.append("E142: registered although its module cannot import")
            continue
        if not cell.get("registered"):
            lines.append(f"{row['id']}: not registered")
            continue
        lines += [f"{row['id']} {problem}" for problem in check_row(row, cell)]
    return lines


#: Slow tier: sixteen cold-and-warm boot pairs, about seven minutes serial (418 s
#: measured), so it runs where `--run-slow` runs — `test-full`, on every CI
#: Python version (AC-10) — and in a wave barrier, not on every fast run.
@pytest.mark.slow
@MODES
@pytest.mark.parametrize("index", range(len(GROUPS)), ids=lambda i: f"rows{i}")
def test_every_surface_follows_the_rows_verdict(
    index: int, future: bool, tmp_path: Path
) -> None:
    group = GROUPS[index]
    project = write_project(tmp_path / "project", future=future, rows=group)
    for phase in ("cold", "warm"):
        seen = dump(project, phase)
        problems = _report(group, seen, future)
        assert not problems, f"{phase} boot:\n" + "\n".join(problems)


# ─── a refusal renders as one line, in a real process (§25) ──────────────────

#: One row per refusal class: missing required, non-converting, wire-only on
#: a command line, an injected key's flag, and a job refused at discovery.
_REFUSALS = {
    "A001": [],
    "A005": ["seven"],
    "C082": [],
    "H163": ["--p", "x"],
    "H166": [],
}


@MODES
def test_a_refused_call_is_one_error_line_and_exit_2(
    future: bool, tmp_path: Path
) -> None:
    by_id = {row["id"]: row for group in GROUPS for row in group}
    rows = tuple(by_id[rid] for rid in _REFUSALS)
    project = write_project(tmp_path / "project", future=future, rows=rows)
    for phase in ("cold", "warm"):
        for rid, argv in _REFUSALS.items():
            done = func(project, *by_id[rid]["path"], *argv, timeout=120)
            errors = [
                line for line in done.stderr.splitlines() if line.startswith("Error:")
            ]
            assert done.returncode == 2, (phase, rid, done.stderr[-800:])
            assert len(errors) == 1, (phase, rid, done.stderr[-800:])
            assert "Traceback" not in done.stderr, (phase, rid, done.stderr[-800:])


# ─── Folded from tests/adapters/test_cold_warm_parity.py — a config field's short flag, cold and warm ───


class ShortFlagConfig(BaseModel):
    """A config model whose field declares a short flag."""

    region: Annotated[str, Option("-s")] = Field(
        default="us-east-1", description="Target region"
    )


def target(log: Log, config: ShortFlagConfig) -> None:
    """A job whose only config field carries a short flag."""


def _by_name(params: object) -> dict[str, object]:
    """Flatten whatever the builder returns into {param name: param}."""
    flat: list = []
    stack = [params]
    while stack:
        item = stack.pop()
        if isinstance(item, (list, tuple)):
            stack.extend(item)
        elif hasattr(item, "name"):
            flat.append(item)
    return {p.name: p for p in flat}


def _warm_descriptors() -> list:
    """The cached shape the warm builder consumes, with the marker resolved."""
    import dataclasses

    from functualize._discovery.group_options_extractor import (
        extract_field_descriptors,
    )

    resolved = []
    for descriptor in extract_field_descriptors(ShortFlagConfig):
        info = ShortFlagConfig.model_fields.get(descriptor.name)
        short = descriptor.short_flag
        for meta in getattr(info, "metadata", ()) or ():
            if type(meta).__name__ == "Option" and getattr(meta, "short", None):
                short = meta.short
        resolved.append(
            dataclasses.replace(descriptor, short_flag=short, from_config_model=True)
        )
    return resolved


def test_both_builders_render_the_same_opts_for_a_short_flagged_config_field() -> None:
    """A1's precondition: one declaration, one spelling, on both boot paths."""
    cold = _by_name(build_click_params(target, job_config_class=ShortFlagConfig))
    warm = _by_name(build_click_params_from_fields(_warm_descriptors()))

    assert "region" in cold, f"cold builder produced {sorted(cold)}"
    assert "region" in warm, f"warm builder produced {sorted(warm)}"

    assert tuple(cold["region"].opts) == tuple(warm["region"].opts), (  # type: ignore[attr-defined]
        f"cold={tuple(cold['region'].opts)} warm={tuple(warm['region'].opts)}"  # type: ignore[attr-defined]
    )
    assert tuple(cold["region"].secondary_opts) == tuple(  # type: ignore[attr-defined]
        warm["region"].secondary_opts  # type: ignore[attr-defined]
    )


def test_the_short_flag_is_actually_present() -> None:
    """The control.

    Without it, a fix that dropped `-s` from *both* builders would satisfy the
    agreement test perfectly while removing the capability.
    """
    cold = _by_name(build_click_params(target, job_config_class=ShortFlagConfig))

    assert "-s" in cold["region"].opts, (  # type: ignore[attr-defined]
        f"the declared short flag is missing: {tuple(cold['region'].opts)}"  # type: ignore[attr-defined]
    )


# ─── Folded from tests/config/test_click_builder_agreement.py — the live and cached builders agree ───


class Mode(StrEnum):
    FAST = "fast"
    THOROUGH = "thorough"


class WideConfig(BaseModel):
    """One field per shape the two builders route differently."""

    required_str: str
    defaulted_str: str = Field(default="DEFAULT")
    defaulted_int: int = 3
    flag_false: bool = False
    flag_true: bool = True
    optional_none: str | None = None
    factory_list: list[str] = Field(default_factory=list)
    enum_field: Mode = Mode.FAST


def _wide_cold() -> dict[str, object]:
    def job() -> None: ...

    params, _, _ = build_click_params(job, WideConfig)
    return _by_name(params)


def _wide_warm() -> dict[str, object]:
    return _by_name(
        build_click_params_from_fields(extract_field_descriptors(WideConfig))
    )


WIDE_FIELDS = sorted(WideConfig.model_fields)


@pytest.mark.parametrize("field", WIDE_FIELDS)
def test_the_two_builders_agree_on_the_default(field: str) -> None:
    """A default supplied by the CLI layer outranks the config file.

    The cold builder passes `default=None` precisely so the resolution ladder
    stays reachable; the warm builder must not smuggle the model's default in
    as though the user had typed it.
    """
    cold, warm = _wide_cold().get(field), _wide_warm().get(field)
    assert cold is not None and warm is not None, f"{field} missing from a builder"
    assert getattr(warm, "default", None) == getattr(cold, "default", None), (
        f"{field}: cold default={getattr(cold, 'default', None)!r} "
        f"warm default={getattr(warm, 'default', None)!r} — the warm value "
        f"reaches call_kwargs and outranks every config source"
    )


@pytest.mark.parametrize("field", WIDE_FIELDS)
def test_the_two_builders_agree_on_the_parameter_shape(field: str) -> None:
    """A field must not be an Option on one boot and a positional on the next."""
    cold, warm = _wide_cold().get(field), _wide_warm().get(field)
    assert cold is not None and warm is not None, f"{field} missing from a builder"
    assert type(warm).__name__ == type(cold).__name__, (
        f"{field}: cold is {type(cold).__name__}, warm is {type(warm).__name__}"
    )
    assert warm.required == cold.required, (
        f"{field}: cold required={cold.required}, warm required={warm.required}"
    )


# ─── Folded from tests/cli/test_schema_surface_parity.py — info and MCP publish one schema ───


def _schema_field(
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
    assert field_property(_schema_field("a", "int"))["type"] == "integer"
    assert field_property(_schema_field("a", "float"))["type"] == "number"
    assert field_property(_schema_field("a", "bool"))["type"] == "boolean"
    assert field_property(_schema_field("a", "list[str]")) == {
        "type": "array",
        "items": {"type": "string"},
    }


def test_unknown_type_is_refused_by_the_contract():
    """An unresolved declaration publishes no input schema."""
    assert field_property(_schema_field("a", "SomeCustomClass")) == {}
    assert field_property(_schema_field("a", None))["type"] == "string"


def test_default_is_omitted_on_a_required_field():
    """A default on a required field advertises a value the caller must supply."""
    prop = field_property(_schema_field("a", "int", default=5, required=True))
    assert "default" not in prop
    assert field_property(_schema_field("a", "int", default=5))["default"] == 5


def test_choices_become_an_enum():
    assert field_property(_schema_field("a", "str", choices=["x", "y"]))["enum"] == [
        "x",
        "y",
    ]


def test_required_is_omitted_rather_than_emitted_empty():
    """An empty `required` is noise, and some consumers read its presence."""
    schema = input_schema([_schema_field("a")])
    assert "required" not in schema

    schema = input_schema([_schema_field("a", required=True)])
    assert schema["required"] == ["a"]


def test_config_fields_win_over_parameters():
    """A job taking a config model publishes the model's fields, not the model."""
    descriptor = _Descriptor(
        parameters=[_schema_field("config", "DeployConfig")],
        config_fields=[_schema_field("region", "str", required=True)],
    )
    assert set(job_input_schema(descriptor)["properties"]) == {"region"}


def test_group_options_injection_point_is_not_published():
    """`opts: DeployOptions` is where resolved options land, not an argument.

    Its flags are published individually; exposing the parameter too would
    offer a bare string an agent might try to fill in.
    """
    descriptor = _Descriptor(
        parameters=[
            _schema_field("image", "str", required=True),
            _schema_field("opts", "DeployOptions"),
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
