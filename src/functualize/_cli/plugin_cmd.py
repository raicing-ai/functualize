"""``func builtin plugin`` — what extends this installation, and changing it.

An *extension* is anything registered under a ``functualize.*`` entry-point
group. Listing them is not the same question as "which plugins loaded": a
plugin can register in a group this process never consults, and
``functualize-inline`` is exactly that case — it appears only under
``functualize.interactivity_providers``, so a listing built from
``loaded_plugins`` would omit the document's own canonical example.

**Two names per entry, because they differ and both are needed.** The
registered name is what the framework calls it (``inline``); the distribution is
what a package manager calls it (``functualize-inline``). ``uninstall`` needs
the second, and a user reading a report needs the first.

**Groups are discovered, never listed.** A hard-coded set of group names goes
stale the moment a domain declares a new provider group — and domains do
exactly that (``_plugins/domain_registry.py:246`` reads the group from domain
metadata). So this scans every ``functualize.*`` group that any installed
distribution actually declares.

**The snapshot is taken once, at the moment the command runs, and is never
re-read after an install.** ``importlib.metadata`` caches its view of the
filesystem, and a distribution installed by a subprocess a moment ago is not in
it. Printing a freshly-installed plugin back from that snapshot would report an
absence as a failure.

This module is in the ``_cli/`` layer — stdlib + ``_cli`` siblings + public API.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

import click

from functualize._cli.runtime import detect_from_process

if TYPE_CHECKING:
    from collections.abc import Iterable

__all__ = [
    "ExtensionEntry",
    "discover_extensions",
    "extensions_from",
    "plugin_app",
]

#: Every group functualize itself extends through carries this prefix.
_PREFIX = "functualize."

#: Job *sources*, not extensions. A distribution publishing jobs under this
#: group is supplying work for functualize to run, not changing what
#: functualize can do — and listing it under `plugin list` would invite a
#: `plugin uninstall` that removes somebody's jobs.
_NOT_EXTENSIONS = frozenset({"functualize.jobs"})


@dataclass(frozen=True)
class ExtensionEntry:
    """One ``functualize.*`` entry point, and who provides it."""

    registered_name: str
    #: ``None`` when the metadata carries no readable name. Kept nullable
    #: rather than defaulted: ``uninstall`` needs a real distribution, and a
    #: guessed one would uninstall the wrong package.
    distribution: str | None
    group: str

    @property
    def short_group(self) -> str:
        """``interactivity_providers`` — the prefix is on every row."""
        return (
            self.group[len(_PREFIX) :] if self.group.startswith(_PREFIX) else self.group
        )

    def to_json(self) -> dict[str, str | None]:
        return {
            "name": self.registered_name,
            "distribution": self.distribution,
            "group": self.group,
        }


def discover_extensions() -> tuple[ExtensionEntry, ...]:
    """Every ``functualize.*`` entry point installed alongside this one.

    Reads ``importlib.metadata`` directly rather than through
    ``_primitives.entry_points``: ``_cli`` may not import internal packages,
    and this needs the *distribution* behind each entry point, which the
    internal helper does not carry.
    """
    from importlib.metadata import distributions

    return extensions_from(distributions())


def extensions_from(dists: Iterable[Any]) -> tuple[ExtensionEntry, ...]:
    """:func:`discover_extensions` over a supplied set of distributions.

    **Takes its input as an argument, for the same reason ``detect`` does.**
    A filtering rule that can only be exercised against whatever happens to be
    installed is untestable in the cases that matter: nothing in this checkout
    publishes under ``functualize.jobs``, so a test of that exclusion written
    against the live environment passed with the exclusion deleted.

    Deduplicated, because a path appearing twice in ``sys.path`` yields the same
    distribution twice and would double every row.
    """
    found: set[ExtensionEntry] = set()
    for dist in dists:
        try:
            entries = list(dist.entry_points)
        except Exception:  # noqa: BLE001 - unreadable metadata is not an error
            continue
        if not entries:
            continue
        try:
            raw_name = dist.metadata["Name"]
        except Exception:  # noqa: BLE001 - a broken METADATA file
            raw_name = None
        name = str(raw_name) if raw_name else None
        for entry in entries:
            if entry.group.startswith(_PREFIX) and entry.group not in _NOT_EXTENSIONS:
                found.add(ExtensionEntry(entry.name, name, entry.group))
    return tuple(sorted(found, key=lambda e: (e.group, e.registered_name)))


def render_extensions(entries: Iterable[ExtensionEntry]) -> list[str]:
    """Group by entry-point group, and show both names on every row."""
    rows = list(entries)
    if not rows:
        return ["  no extensions registered"]

    width = max(len(e.registered_name) for e in rows)
    lines: list[str] = []
    current = ""
    for entry in rows:
        if entry.group != current:
            current = entry.group
            lines.append(f"{entry.short_group}:")
        provider = entry.distribution or "(unknown distribution)"
        lines.append(f"  {entry.registered_name:<{width}}  {provider}")
    return lines


@click.group(name="plugin", help="Inspect and manage installed extensions.")
def plugin_app() -> None:
    """Commands about what extends functualize, as opposed to what it runs."""


@plugin_app.command("list")
@click.option(
    "--format",
    "output_format",
    type=click.Choice(["text", "json"]),
    default="text",
    show_default=True,
    help="Render the listing as text or JSON.",
)
def list_(output_format: str) -> None:
    """List every installed extension, with the distribution providing it."""
    entries = discover_extensions()
    if output_format == "json":
        click.echo(json.dumps([e.to_json() for e in entries], indent=2))
        return
    for line in render_extensions(entries):
        click.echo(line)


def _binary_and_config() -> tuple[str, Path]:
    import sys

    from functualize._cli import manifest
    from functualize.app.utils import resolve_user_config_dir

    binary = manifest.resolve_binary_path(
        sys.argv[0] if sys.argv else "", sys.executable
    )
    return binary, resolve_user_config_dir()


@plugin_app.command("install")
@click.argument("package")
@click.option(
    "--yes",
    "-y",
    "assume_yes",
    is_flag=True,
    help="Skip the confirmation prompt. The command is still printed.",
)
def install(package: str, assume_yes: bool) -> None:
    """Install an extension into this installation's environment.

    The same mechanism as `self install`, recorded under a different key: an
    extension appears in `plugin list`, a plain dependency does not.
    """
    from functualize._cli import manifest, package_ops

    detection = detect_from_process()
    if detection.degraded:
        package_ops.refuse(detection, f"install {package}")

    commands = package_ops.plan_or_exit(
        lambda: package_ops.install_commands(detection, package)
    )
    package_ops.announce(commands, assume_yes)

    code = package_ops.run_commands(commands)
    if code != 0:
        raise SystemExit(code)

    # Deliberately not re-listing to confirm. `importlib.metadata` cached its
    # view before the subprocess ran, so the new distribution is not visible in
    # this process and a check here would report a success as a failure.
    binary, config_dir = _binary_and_config()
    if manifest.record_addition(
        config_dir, binary_path=binary, key="plugins", name=package
    ):
        click.echo(f"Recorded {package}; `self update` will restore it.")


@plugin_app.command("uninstall")
@click.argument("package")
@click.option(
    "--yes",
    "-y",
    "assume_yes",
    is_flag=True,
    help="Skip the confirmation prompt. The command is still printed.",
)
def uninstall(package: str, assume_yes: bool) -> None:
    """Remove an extension from this installation's environment."""
    from functualize._cli import manifest, package_ops

    detection = detect_from_process()
    if detection.degraded:
        package_ops.refuse(detection, f"uninstall {package}")

    commands = package_ops.plan_or_exit(
        lambda: package_ops.uninstall_commands(detection, package)
    )
    package_ops.announce(commands, assume_yes)

    code = package_ops.run_commands(commands)
    if code != 0:
        raise SystemExit(code)

    # Forgetting is not optional bookkeeping here. A name left recorded is
    # reinstalled by the next `self update`, which would undo this command
    # silently and at a distance.
    binary, config_dir = _binary_and_config()
    if manifest.forget_addition(config_dir, binary_path=binary, name=package):
        click.echo(f"No longer recorded; `self update` will not restore {package}.")
