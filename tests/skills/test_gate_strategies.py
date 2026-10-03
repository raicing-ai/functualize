"""The gate strategies a skill documents must be the ones the framework accepts.

`skills/functualize/references/workflows.md` states in prose how many
`Gate(strategy=...)` names are valid, and which plugin registers which one.
Nothing derives that paragraph from code, so a sixth strategy would be accepted
by `Gate`, registered by its plugin, and still missing from the document an
agent reads — a capability the reference teaches as absent, or a name it
teaches that the framework rejects.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

# Deliberate private read: the accepted set lives beside `Gate` rather than on
# the public surface, and a guard that re-listed the names here would drift in
# exactly the way the prose it checks does.
from functualize._types.workflow import _VALID_GATE_STRATEGIES

from .conftest import REPO_ROOT, SKILLS_ROOT

WORKFLOWS_DOC = SKILLS_ROOT / "functualize" / "references" / "workflows.md"

#: The heading whose prose this module checks. Scoped to it because the file
#: also backticks plugin slugs, preset names and `Gate(...)` examples, all of
#: which a file-wide scan would read as strategy names.
STRATEGIES_SECTION = "### Strategies"

#: Number words the sentence may use. An unknown word is a failure rather than
#: a skipped assertion, so the check cannot pass by not understanding the prose.
_NUMERALS = {
    "one": 1,
    "two": 2,
    "three": 3,
    "four": 4,
    "five": 5,
    "six": 6,
    "seven": 7,
    "eight": 8,
    "nine": 9,
    "ten": 10,
}


def _strategies_section() -> str:
    """The `### Strategies` paragraph of the workflows reference."""
    text = WORKFLOWS_DOC.read_text(encoding="utf-8")
    match = re.search(
        rf"^{re.escape(STRATEGIES_SECTION)}\s*$(.*?)(?=^## )",
        text,
        re.MULTILINE | re.DOTALL,
    )
    if match is None:
        pytest.fail(
            f"{WORKFLOWS_DOC} has no `{STRATEGIES_SECTION}` section — "
            f"did the heading or the file move?"
        )
    return match.group(1)


def _documented_strategies() -> set[str]:
    """The quoted bare names the paragraph lists, such as ``"resolve"``.

    Quoted spans only. The same paragraph backticks `Gate(strategy=...)` and
    the plugin slugs, none of which is a strategy name.
    """
    return set(re.findall(r'`"([a-z_]+)"`', _strategies_section()))


def _documented_count() -> int:
    """The numeral the paragraph states, as in "Only five bare names are valid"."""
    match = re.search(r"Only\s+(\w+)\s+bare names", _strategies_section())
    if match is None:
        pytest.fail(
            f"{WORKFLOWS_DOC} no longer states how many bare strategy names "
            f"are valid in `{STRATEGIES_SECTION}`"
        )
    word = match.group(1)
    if word not in _NUMERALS:
        pytest.fail(
            f"{WORKFLOWS_DOC} states the strategy count as {word!r}, "
            f"which this test cannot read — add it to _NUMERALS"
        )
    return _NUMERALS[word]


def _documented_plugin_registrations() -> dict[str, str]:
    """The `strategy -> plugin` pairs the paragraph attributes to plugins."""
    sentence = re.search(
        r"registered when a plugin is installed:(.*?)\n\n",
        _strategies_section(),
        re.DOTALL,
    )
    if sentence is None:
        pytest.fail(
            f"{WORKFLOWS_DOC} no longer names the plugins that register the "
            f"non-core strategies in `{STRATEGIES_SECTION}`"
        )
    pairs = re.findall(r"`([a-z_]+)`\s+by\s+`([a-z0-9-]+)`", sentence.group(1))
    if not pairs:
        pytest.fail(
            f"{WORKFLOWS_DOC} `{STRATEGIES_SECTION}` has no readable "
            f"`<strategy> by <plugin>` pairs — did the sentence change shape?"
        )
    return dict(pairs)


def _plugin_root(slug: str) -> Path:
    """The checkout directory of the plugin distributed as ``slug``."""
    for manifest in (REPO_ROOT / "plugins").rglob("pyproject.toml"):
        text = manifest.read_text(encoding="utf-8")
        if re.search(rf'^name = "{re.escape(slug)}"$', text, re.MULTILINE):
            return manifest.parent
    pytest.fail(
        f"{WORKFLOWS_DOC} documents `{slug}` as a plugin, but no plugin with "
        f"that distribution name exists under plugins/"
    )


def _registered_strategies(plugin_root: Path) -> set[str]:
    """Strategy names ``plugin_root``'s source hands to its gate registry.

    Read from source rather than by booting the plugin: registration happens in
    an install hook, and the claim under test is which name that hook passes. A
    bare identifier argument is resolved through the module-level constant it
    names, which is how two of the three plugins spell it.
    """
    constants: dict[str, str] = {}
    arguments: list[str] = []
    for module in plugin_root.rglob("*.py"):
        if "tests" in module.parts:
            continue
        source = module.read_text(encoding="utf-8")
        constants.update(
            re.findall(r'^([A-Z][A-Z0-9_]*)\s*=\s*"([a-z_]+)"', source, re.MULTILINE)
        )
        arguments.extend(
            re.findall(
                r'register_gate_strategy\(\s*("[a-z_]+"|[A-Za-z_][A-Za-z0-9_]*)',
                source,
            )
        )
    resolved: set[str] = set()
    for argument in arguments:
        if argument.startswith('"'):
            resolved.add(argument.strip('"'))
        else:
            resolved.add(constants.get(argument, f"<unresolved:{argument}>"))
    return resolved


def test_documented_strategies_match_the_engine():
    """The paragraph names exactly the strategies ``Gate`` accepts.

    A missing name is a strategy an agent will not reach for; an extra name is
    a strategy it will write and `Gate` will reject when the workflow is built.
    """
    documented = _documented_strategies()
    assert documented, (
        f"{WORKFLOWS_DOC} `{STRATEGIES_SECTION}` lists no quoted strategy names — "
        f"did the paragraph change shape?"
    )
    accepted = set(_VALID_GATE_STRATEGIES)
    assert documented == accepted, (
        f"{WORKFLOWS_DOC} (the `{STRATEGIES_SECTION}` paragraph) disagrees with "
        f"functualize._types.workflow._VALID_GATE_STRATEGIES.\n"
        f"  documented but not accepted: {sorted(documented - accepted)}\n"
        f"  accepted but not documented: {sorted(accepted - documented)}\n"
        f"  documented: {sorted(documented)}\n"
        f"  accepted:   {sorted(accepted)}"
    )


def test_documented_count_matches_the_strategy_count():
    """The stated numeral is the size of the accepted set.

    The sentence is what a reader trusts without counting the names beside it,
    so it is checked against the engine's set rather than against that list.
    """
    count = _documented_count()
    accepted = set(_VALID_GATE_STRATEGIES)
    assert count == len(accepted), (
        f"{WORKFLOWS_DOC} `{STRATEGIES_SECTION}` states {count} bare names, but "
        f"_VALID_GATE_STRATEGIES holds {len(accepted)}: {sorted(accepted)}"
    )


def test_documented_plugin_registrations_are_real():
    """Every strategy the paragraph attributes to a plugin is registered by it.

    This is the half that catches a sixth plugin strategy: the document naming
    one that no plugin registers, or a plugin registering one the document does
    not name, fails here.
    """
    for strategy, slug in _documented_plugin_registrations().items():
        registered = _registered_strategies(_plugin_root(slug))
        assert strategy in registered, (
            f"{WORKFLOWS_DOC} says `{strategy}` is registered by `{slug}`, but "
            f"{slug} registers {sorted(registered) or 'no gate strategy'} via "
            f"app.gates.register_gate_strategy"
        )
