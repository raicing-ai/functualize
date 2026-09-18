"""A declared entry-point group that nothing reads is a plugin that does nothing.

`plugin-taxonomy`/T6. AC-1.

This is the gate the feature exists to install. Three shipped manifests declared
`functualize.*` groups with **no reader anywhere in `src/`**, and the only
symptom was silence:

- `functualize.state_providers` — `functualize-state-sqlite`, and the substrate
  tutorial in `docs/examples/plugins/custom-state-backend.md`. Installing the
  plugin chose no storage and reported nothing.
- `functualize.interactivity_providers` — `functualize-inline`. Installing it
  registered no prompt surface.
- `functualize.vault_key_providers` — declared by core's own `pyproject.toml`,
  and advertised to plugin authors by `_config/vault_keys.py`.

Nothing compared the set of groups that are *declared* against the set that is
*read*, because neither set was written down. `_primitives/entry_point_groups.py`
is now the second half; this is the comparison.

**Why the three could not simply be given readers, which is the finding that
shaped the fix.** A `functualize.<x>_providers` group is not a naming
convention — it is a mechanism. `_plugins/domain_registry.scan_domain_providers`
reads it out of the `entry_point_group` field of a live `DomainMetadata`
published under `functualize.domains`. Exactly two domain SDKs exist, `ai` and
`tasks`, so `ai_providers` and `tasks_providers` are read and a `_providers`
group with no domain behind it **has no reader by construction**. ADR-022
removed the `state` domain; there has never been an `interactivity` or
`vault_key` one.

So a group is readable if and only if it is one of:

1. :data:`READ_GROUPS` — the seven core reads from a fixed ``entry_points(group=)``
   call site in ``src/``; closed by definition.
2. the ``entry_point_group`` of a shipped domain SDK — open, because a
   third-party domain may declare one at any time.

**Manifests are found by glob, never listed.** A hard-coded list would pass
forever the first time somebody adds a plugin, which is the failure mode of the
thing it is checking.

**Domain groups are read from source, not from installed metadata.** A plain
`uv sync` does not install the workspace plugins, so `discover_domains()` would
return nothing and this test would report `ai_providers` as an orphan on a
perfectly good checkout — a false alarm that teaches people to ignore it. The
AST walk answers the same question and does not depend on what is installed.
"""

from __future__ import annotations

import ast
import tomllib
from pathlib import Path

import pytest

from functualize._primitives.entry_point_groups import READ_GROUPS

_ROOT = Path(__file__).resolve().parents[2]
_PREFIX = "functualize."


def _manifests() -> list[Path]:
    """Every shipped `pyproject.toml` that can declare an entry point.

    Core, the workspace plugins at their grouped depth, and the examples —
    which are not an afterthought here: the substrate tutorial was one of the
    three declarants of a dead group, and a reader who follows it end to end
    builds a plugin that never loads.
    """
    found = [_ROOT / "pyproject.toml"]
    found += sorted((_ROOT / "plugins").glob("*/*/pyproject.toml"))
    found += sorted((_ROOT / "examples").glob("**/pyproject.toml"))
    return [p for p in found if p.is_file()]


def _declared_groups(manifest: Path) -> list[str]:
    data = tomllib.loads(manifest.read_text(encoding="utf-8"))
    entry_points = data.get("project", {}).get("entry-points", {}) or {}
    return [g for g in entry_points if g.startswith(_PREFIX)]


def _domain_provider_groups() -> set[str]:
    """Every `entry_point_group` a shipped domain SDK names.

    An AST walk rather than a regex: the value is a syntax question, and a
    regex over source counts the same string in a docstring or a comment. The
    scaffold template is excluded — it is a Jinja file, not a domain.
    """
    groups: set[str] = set()
    for path in sorted((_ROOT / "plugins").glob("*/*/src/**/*.py")):
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except (OSError, SyntaxError):  # pragma: no cover - unreadable source
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            for keyword in node.keywords:
                if keyword.arg == "entry_point_group" and isinstance(
                    keyword.value, ast.Constant
                ):
                    value = keyword.value.value
                    if isinstance(value, str) and value.startswith(_PREFIX):
                        groups.add(value)
    return groups


def _readable_groups() -> set[str]:
    return set(READ_GROUPS) | _domain_provider_groups()


def test_the_manifest_scan_finds_the_shipped_plugins() -> None:
    """Guards the guard.

    A glob that stops matching returns an empty list, and every assertion below
    would then pass while checking nothing — the vacuous-success shape this
    feature keeps running into. `plugin-taxonomy`/T3 moved the plugin
    directories one level deeper and two globs elsewhere failed exactly this
    way, silently.
    """
    manifests = _manifests()
    assert len(manifests) >= 13, (
        f"expected core plus twelve workspace plugins, found {len(manifests)}: "
        f"{[str(m.relative_to(_ROOT)) for m in manifests]}"
    )
    assert any("state-sqlite" in str(m) for m in manifests)
    assert any("examples" in str(m) for m in manifests)


def test_two_domain_sdks_are_shipped_and_they_name_their_groups() -> None:
    """The open half of the readable set, pinned so its absence is not silent."""
    assert _domain_provider_groups() == {
        "functualize.ai_providers",
        "functualize.tasks_providers",
    }


@pytest.mark.parametrize(
    "manifest", _manifests(), ids=lambda p: str(p.relative_to(_ROOT))
)
def test_every_group_this_manifest_declares_has_a_reader(manifest: Path) -> None:
    """AC-1. Parametrised per manifest so a failure names the file to fix."""
    readable = _readable_groups()
    orphans = [g for g in _declared_groups(manifest) if g not in readable]
    assert not orphans, (
        f"{manifest.relative_to(_ROOT)} declares {orphans}, which nothing reads.\n"
        f"A group is read only if it is in READ_GROUPS "
        f"(_primitives/entry_point_groups.py) or is the entry_point_group of a "
        f"shipped domain SDK. A `<x>_providers` group with no domain behind it "
        f"cannot be given a reader — the reader is the domain registry, and it "
        f"only scans groups a live DomainMetadata names."
    )


def test_the_cli_group_constants_agree_with_the_read_set() -> None:
    """`_cli` cannot import `_primitives`, so the link is asserted here.

    `functualize.skills` and `functualize.displays` are read from `_cli`, and
    the `_cli uses public API only` import contract forbids that layer from
    importing `_primitives`. Routing the constants through
    `functualize.app.utils` would widen the **public** API — and every public
    symbol owes a caller in `examples/` — to buy nothing at runtime. So the two
    constants stay where they are and this test is what keeps them honest.
    """
    from functualize._cli.skills import SKILLS_ENTRY_POINT_GROUP
    from functualize._cli.tui.display_provider_discovery import (
        _DISPLAY_ENTRY_POINT_GROUP,
    )

    assert SKILLS_ENTRY_POINT_GROUP in READ_GROUPS
    assert _DISPLAY_ENTRY_POINT_GROUP in READ_GROUPS


def test_every_read_group_is_actually_read_somewhere_in_src() -> None:
    """The other direction: a constant nobody reads is the same defect mirrored.

    `READ_GROUPS` is closed *by definition* — it is the set of
    `entry_points(group=)` call sites in `src/` — so a member that no module
    mentions means the reader was deleted and the constant was not, and the
    next manifest to declare that group would be silently dead again.
    """
    sources = "\n".join(
        path.read_text(encoding="utf-8")
        for path in (_ROOT / "src" / "functualize").rglob("*.py")
        if path.name != "entry_point_groups.py"
    )
    unread = sorted(g for g in READ_GROUPS if g not in sources)
    assert not unread, (
        f"READ_GROUPS names {unread}, which no module in src/ mentions. Either "
        f"the reader was removed and the constant should go with it, or the "
        f"reader stopped using the constant."
    )
