"""Every API name a skill mentions must exist in the running framework.

This is the test the whole suite is for. Prose that names a type, a flag or a
command is a claim about the code, and claims rot in exactly one direction:
the code moves, the document does not, and an agent writes something confident
and wrong against a surface that no longer exists.

Three of the four checks below already caught live drift when first written —
a capability table calling per-invocation `State` "persistence across runs", a
`--emit-format` vocabulary missing its default, and testing doubles documented with
attributes they do not have.
"""

from __future__ import annotations

import re

import pytest

from functualize._cli.builtins import BUILTIN_COMMANDS, BUILTIN_ROOT
from functualize._cli.scaffold.registry import TEMPLATES
from functualize.types import OPTIONAL_VALUE_VALID_SET

from .conftest import SKILLS_ROOT, backticked, markdown_files

CAPABILITIES_TABLE = SKILLS_ROOT / "functualize" / "references" / "capabilities.md"

#: The public modules a skill may name a type from. Imported by string because
#: ``functualize.workflow`` resolves to the decorator function on the package,
#: not to the module — ``import functualize.workflow as w`` binds the callable.
PUBLIC_MODULES = (
    "functualize.job",
    "functualize.workflow",
    "functualize.testing",
    "functualize.app",
    "functualize.app.utils",
    "functualize.types",
    # Plugin-author surface. The skills document writing an agent step
    # executor, which names `AgentCapability`, `AgentStepContext` and
    # `AgentStepResult` — all exported here and nowhere else, so without this
    # entry a correct reference reads as an invented name.
    "functualize.plugin",
)

#: Backticked CamelCase spans that are legitimately not functualize API.
#: Explicit rather than pattern-skipped, so a genuinely unknown name is a
#: failure instead of a silent pass.
NOT_PUBLIC_API = frozenset(
    {
        # Third-party and stdlib names the skills legitimately mention.
        "BaseModel",
        "PydanticSchemaGenerationError",
        "ImportError",
        "True",
        # Placeholders in illustrative snippets.
        "MyJob",
        "JobConfig",
        "DeployConfig",
        "CollectConfig",
        "FIELD",
        "SECTION",
        # Fragments of environment-variable names in prose.
        "DEV",
        "ENV",
        "ENVIRONMENT",
        "PROD",
        "STAGING",
    }
)


def _public_names() -> set[str]:
    """Everything exported from every public authoring module."""
    import importlib

    names: set[str] = set()
    for dotted in PUBLIC_MODULES:
        module = importlib.import_module(dotted)
        names |= {n for n in getattr(module, "__all__", ()) if not n.startswith("_")}
    return names


def _resolve_public_names() -> dict[str, object]:
    """Every public export, as ``name -> the object itself``.

    `_public_names` returns the spellings; the attribute check needs the
    objects behind them.
    """
    import importlib

    resolved: dict[str, object] = {}
    for dotted in PUBLIC_MODULES:
        module = importlib.import_module(dotted)
        for name in getattr(module, "__all__", ()):
            if not name.startswith("_"):
                resolved.setdefault(name, getattr(module, name, None))
    return resolved


def _capability_types_from_engine() -> set[str]:
    """The types the engine injects.

    Read from `_primitives/capability_names.py`, which is not a hand-kept list
    in the drifting sense: `_engine/capabilities/registry.py` refuses to import
    when the declared `CapabilitySpec` names disagree with it (ADR-014). So
    adding a capability moves this set whether or not anyone remembers the
    documentation — which is what makes the comparison below worth making.
    """
    from functualize._primitives.capability_names import INJECTED_PARAM_TYPE_NAMES

    return set(INJECTED_PARAM_TYPE_NAMES)


#: Heading whose table is *the* capability table. Scoped deliberately: the
#: reference also documents the near-miss types (`Exec`, `Retry`, `Fingerprint`,
#: `Deps`) which are `@job` options rather than injected parameters, in their own
#: table. A file-wide scan reads those rows as capabilities and fails this test
#: for documenting them — the opposite of what it is for.
CAPABILITY_SECTION = "## The set"


def _documented_capability_types() -> set[str]:
    """Backticked type names in the first column of the capability table."""
    documented: set[str] = set()
    in_section = False
    for line in CAPABILITIES_TABLE.read_text(encoding="utf-8").splitlines():
        if line.startswith("## "):
            in_section = line.strip() == CAPABILITY_SECTION
            continue
        if not in_section:
            continue
        match = re.match(r"^\|\s*`(\w+)`\s*\|", line)
        if match:
            documented.add(match.group(1))
    return documented


def test_capability_table_matches_the_engine():
    """The documented capabilities are exactly the injectable ones.

    Missing rows teach an agent to reach for a module global instead of a
    capability. Extra rows teach it to declare a parameter that will never be
    filled.
    """
    documented = _documented_capability_types()
    injected = _capability_types_from_engine()
    assert documented, "capability table parsed as empty — did its format change?"
    assert documented == injected, (
        f"capability table drift.\n"
        f"  documented but not injected: {sorted(documented - injected)}\n"
        f"  injected but undocumented:   {sorted(injected - documented)}"
    )


#: Attributes the capability table lists that do **not** belong to the type in
#: its first column, with what they do belong to. Each is a real member of a
#: real object; the table's third column is prose about how the capability is
#: used, and a handle returned by one of its methods legitimately appears there.
_ATTRIBUTES_OF_SOMETHING_ELSE = {
    ("Live", "update"): "the handle `Live.add`/`Live.panel` returns",
    ("Live", "push"): "the handle `Live.add`/`Live.panel` returns",
    ("Live", "remove"): "the handle `Live.add`/`Live.panel` returns",
}


def _documented_capability_attributes() -> list[tuple[str, str]]:
    """``(type name, attribute)`` for every ``.member`` the table advertises."""
    claims: list[tuple[str, str]] = []
    in_section = False
    for line in CAPABILITIES_TABLE.read_text(encoding="utf-8").splitlines():
        if line.startswith("## "):
            in_section = line.strip() == CAPABILITY_SECTION
            continue
        if not in_section:
            continue
        row = re.match(r"^\|\s*`(\w+)`\s*\|(.*)\|(.*)\|\s*$", line)
        if row is None:
            continue
        type_name, _, described = row.groups()
        for attribute in sorted(set(re.findall(r"`\.(\w+)", described))):
            claims.append((type_name, attribute))
    return claims


def _members_of(obj: object) -> set[str]:
    """Every name the type offers, including dataclass fields.

    A frozen dataclass's fields are not class attributes unless they carry a
    default, so `hasattr(JobContext, "name")` is False for a field that is
    plainly part of the API. Read the field list as well as the class.
    """
    import dataclasses

    members = {name for name in dir(obj) if not name.startswith("_")}
    if dataclasses.is_dataclass(obj):
        members |= {field.name for field in dataclasses.fields(obj)}
    protocol_members = getattr(obj, "__protocol_attrs__", None)
    if protocol_members:
        members |= set(protocol_members)
    return members


def test_documented_capability_attributes_exist():
    """Every `.member` the capability table advertises is on its type.

    `test_capability_table_matches_the_engine` checks the table's **first**
    column — which capabilities exist. Nothing checked the third, so
    `JobContext` was advertised with a `.deadline` that `adjacent-defects` T3
    had deleted, in a file that ships inside the wheel and that `AGENTS.md`
    says is a checkable claim (adj §4).

    Writing this found a second one, pointing the other way: `Shell` documented
    `.cd`, `.prefix`, `.defer`, `.run_deferred` and `.sudo` that existed on the
    implementation and **not on the protocol a job annotates**, so a job
    written exactly as documented failed `mypy --strict`. The doc was right and
    the type was wrong.
    """
    resolved = _resolve_public_names()
    missing: list[str] = []
    for type_name, attribute in _documented_capability_attributes():
        if (type_name, attribute) in _ATTRIBUTES_OF_SOMETHING_ELSE:
            continue
        target = resolved.get(type_name)
        if target is None:
            continue  # `test_no_invented_public_names` owns this failure
        if attribute not in _members_of(target):
            missing.append(f"{type_name}.{attribute}")

    assert not missing, (
        f"the capability table advertises members that do not exist: {missing}. "
        f"Remove them, or add them to the public type — this file ships inside "
        f"the wheel, so a wrong name here is a wrong name an agent will use."
    )


def test_the_exemptions_are_still_documented_somewhere():
    """An exemption for an attribute the table no longer mentions is an excuse
    left behind for a claim nobody makes."""
    claimed = set(_documented_capability_attributes())

    stale = sorted(
        f"{t}.{a}" for t, a in _ATTRIBUTES_OF_SOMETHING_ELSE if (t, a) not in claimed
    )

    assert not stale, (
        f"_ATTRIBUTES_OF_SOMETHING_ELSE exempts members the capability table "
        f"no longer advertises: {stale}"
    )


def test_the_attribute_scan_actually_finds_claims():
    """The falsifier. An empty scan passes both tests above vacuously."""
    claims = _documented_capability_attributes()

    assert len(claims) > 20, len(claims)
    assert ("Log", "info") in claims
    assert ("JobContext", "trace_id") in claims


@pytest.mark.parametrize(
    "path", markdown_files(), ids=lambda p: str(p.relative_to(SKILLS_ROOT))
)
def test_no_invented_public_names(path):
    """Every CamelCase backticked name resolves to a real export.

    Catches a renamed capability, a removed marker, and the invented-name
    failure that reads perfectly and does not run.
    """
    public = _public_names()
    text = path.read_text(encoding="utf-8")

    candidates = {
        span
        for span in backticked(text)
        # Bare CamelCase identifiers only: skips code snippets, flags, paths.
        if re.fullmatch(r"[A-Z][A-Za-z0-9]+", span)
    }
    unknown = candidates - public - NOT_PUBLIC_API
    assert not unknown, (
        f"{path.relative_to(SKILLS_ROOT)} names {sorted(unknown)}, which are not "
        f"exported from functualize.job / .workflow / .testing. Either the name "
        f"changed, or it belongs in NOT_PUBLIC_API with a reason."
    )


def test_documented_output_values_match_the_flag():
    """The `--emit-format` vocabulary in prose is the one dispatch accepts."""
    valid, default = OPTIONAL_VALUE_VALID_SET["--emit-format"]
    text = "\n".join(p.read_text(encoding="utf-8") for p in markdown_files())

    # Wherever the skills enumerate the vocabulary, the default must be in it —
    # omitting `auto` was the original drift, and it is the value most callers
    # actually get.
    assert default in valid
    mentions = re.findall(r"`--emit-format`[^\n]*", text)
    assert mentions, "no skill documents --emit-format any more — intended?"
    enumerations = [m for m in mentions if "json" in m and "ndjson" in m]
    assert enumerations, "--emit-format is mentioned but never enumerated"
    for line in enumerations:
        assert default in line, (
            f"--emit-format enumeration omits the default {default!r}: {line}"
        )


def test_documented_scaffold_templates_exist():
    """Template names in the app skill resolve against the scaffold registry."""
    text = (SKILLS_ROOT / "functualize-app" / "SKILL.md").read_text(encoding="utf-8")
    documented = {
        span
        for span in backticked(text)
        if re.fullmatch(r"[a-z][a-z-]+", span) and span in TEMPLATES
    }
    missing = set(TEMPLATES) - documented
    assert not missing, (
        f"scaffold templates never mentioned in functualize-app: {sorted(missing)}"
    )


def _bash_blocks() -> list[tuple[str, str]]:
    """(source file, line) for every command line inside a ```bash fence."""
    lines: list[tuple[str, str]] = []
    for path in markdown_files():
        relative = str(path.relative_to(SKILLS_ROOT))
        for block in re.findall(
            r"```bash\n(.*?)```", path.read_text(encoding="utf-8"), re.DOTALL
        ):
            for line in block.splitlines():
                stripped = line.strip()
                if stripped and not stripped.startswith("#"):
                    lines.append((relative, stripped))
    return lines


def test_no_bare_invocation_of_a_command_that_needs_a_subcommand():
    """A copyable line must be runnable.

    `func builtin cache` on its own exits with usage rather than doing
    anything, so showing it inside a bash fence hands an agent a command that
    fails. Prose may still mention the command bare; a code fence may not.
    """
    needs_sub = {c.name for c in BUILTIN_COMMANDS if c.requires_subcommand}
    problems = [
        f"{source}: {line}"
        for source, line in _bash_blocks()
        for command in [re.match(rf"\S*func\s+{BUILTIN_ROOT}\s+(\w[\w-]*)\s*$", line)]
        if command and command.group(1) in needs_sub
    ]
    assert not problems, "bare invocations that exit with usage:\n  " + "\n  ".join(
        problems
    )


def test_documented_builtin_commands_exist():
    """Every `func builtin …` invocation in the skills is a real command.

    A command that was renamed leaves the prose looking authoritative and the
    agent running something that does not exist.
    """
    registry = {c.name: {s for s, _ in c.subcommands} for c in BUILTIN_COMMANDS}
    text = "\n".join(p.read_text(encoding="utf-8") for p in markdown_files())

    pattern = re.compile(
        rf"(?:\S*func|\S+\.py|myapp)\s+{BUILTIN_ROOT}"
        rf"\s+([a-z][a-z-]*)(?:\s+([a-z][a-z-]*))?"
    )
    problems: list[str] = []
    for command, subcommand in pattern.findall(text):
        if command not in registry:
            problems.append(f"unknown builtin command: {command}")
            continue
        known = registry[command]
        # A command with subcommands may still be documented bare (e.g. to
        # show its help); only a *wrong* subcommand is a problem.
        if known and subcommand and subcommand not in known:
            problems.append(f"{command} has no subcommand {subcommand!r}")

    assert not problems, "builtin command drift:\n  " + "\n  ".join(
        sorted(set(problems))
    )


def test_exit_code_table_matches_the_mapping():
    """The exit-code table is the contract agents branch on — pin it."""
    from functualize._types.exit_codes import ExitCode

    text = (SKILLS_ROOT / "functualize" / "references" / "idiomatic.md").read_text(
        encoding="utf-8"
    )
    documented = {int(m) for m in re.findall(r"^\| (\d) \|", text, re.MULTILINE)}
    assert documented == {c.value for c in ExitCode}, (
        f"exit-code table lists {sorted(documented)}, ExitCode defines "
        f"{sorted(c.value for c in ExitCode)}"
    )
