"""Every API name a skill mentions must exist in the running framework.

This is the test the whole suite is for. Prose that names a type, a flag or a
command is a claim about the code, and claims rot in exactly one direction:
the code moves, the document does not, and an agent writes something confident
and wrong against a surface that no longer exists.

Three of the four checks below already caught live drift when first written —
a capability table calling per-invocation `State` "persistence across runs", a
`--output` vocabulary missing its default, and testing doubles documented with
attributes they do not have.
"""

from __future__ import annotations

import re

import pytest

from functualize._cli.builtins import BUILTIN_COMMANDS, BUILTIN_ROOT
from functualize._cli.dispatch import _OPTIONAL_VALUE_VALID_SET
from functualize._cli.scaffold.registry import TEMPLATES

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
    """The `--output` vocabulary in prose is the one dispatch accepts."""
    valid, default = _OPTIONAL_VALUE_VALID_SET["--output"]
    text = "\n".join(p.read_text(encoding="utf-8") for p in markdown_files())

    # Wherever the skills enumerate the vocabulary, the default must be in it —
    # omitting `auto` was the original drift, and it is the value most callers
    # actually get.
    assert default in valid
    mentions = re.findall(r"`--output`[^\n]*", text)
    assert mentions, "no skill documents --output any more — intended?"
    enumerations = [m for m in mentions if "json" in m and "ndjson" in m]
    assert enumerations, "--output is mentioned but never enumerated"
    for line in enumerations:
        assert default in line, (
            f"--output enumeration omits the default {default!r}: {line}"
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
