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

from functualize.app.packaging import detect_from_process

if TYPE_CHECKING:
    from collections.abc import Iterable

__all__ = [
    "CatalogEntry",
    "ExtensionEntry",
    "available_rows",
    "discover_extensions",
    "extensions_from",
    "load_catalog",
    "plugin_app",
    "recommended_distributions",
]

#: Every group functualize itself extends through carries this prefix.
_PREFIX = "functualize."

#: The core distribution. It publishes under several ``functualize.*`` groups of
#: its own -- the TOML format provider, the env and keychain vault providers --
#: and `plugin list` is right to show those, because "what extends this
#: installation" includes what core brings. `plugin available` is a different
#: question: what could you *install*. Core is already there by definition, and
#: offering it as an available plugin invites a `plugin uninstall functualize`.
_CORE_DISTRIBUTION = "functualize"

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


#: The curated manifest, beside this module's siblings in ``_cli/data``.
CATALOG_FILENAME = "plugin_catalog.toml"


@dataclass(frozen=True)
class CatalogEntry:
    """One plugin the shipped manifest knows about, installed or not.

    Carries ``group`` rather than a kind, so the classification of a plugin in
    this file is computed by the same function that classifies an installed
    one. A hand-written ``kind`` could disagree with the live answer for a
    plugin present on the machine; a group cannot.
    """

    name: str
    distribution: str
    group: str
    description: str
    recommended: bool

    @property
    def kind(self) -> str:
        from functualize.app.utils import classify_group

        return str(classify_group(self.group))


def load_catalog() -> tuple[CatalogEntry, ...]:
    """The curated manifest. No network, no filesystem outside the package.

    A malformed or missing manifest yields an empty catalog rather than an
    error: ``plugin available`` still has the installed half to report, and a
    packaging accident should degrade discovery rather than break the command.
    """
    import tomllib

    path = Path(__file__).parent / "data" / CATALOG_FILENAME
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError, UnicodeDecodeError):
        return ()

    entries: list[CatalogEntry] = []
    for row in data.get("plugin", []):
        try:
            entries.append(
                CatalogEntry(
                    name=str(row["name"]),
                    distribution=str(row["distribution"]),
                    group=str(row["group"]),
                    description=str(row.get("description", "")),
                    recommended=bool(row.get("recommended", False)),
                )
            )
        except (KeyError, TypeError):
            continue
    return tuple(entries)


def recommended_distributions() -> tuple[str, ...]:
    """What ``install --recommended`` installs, in manifest order.

    The single source both the CLI and the drift test read, so they cannot
    disagree about what "recommended" means.
    """
    return tuple(e.distribution for e in load_catalog() if e.recommended)


@dataclass(frozen=True)
class AvailableRow:
    """One row of ``plugin available``."""

    name: str
    distribution: str | None
    kind: str
    description: str
    installed: bool
    recommended: bool
    #: ``catalog`` (curated, may or may not be installed), ``installed`` (present
    #: on the machine but not in the manifest -- a third-party plugin), or
    #: ``remote`` (found on PyPI, not curated by this project).
    source: str

    def to_json(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "distribution": self.distribution,
            "kind": self.kind,
            "description": self.description,
            "installed": self.installed,
            "recommended": self.recommended,
            "source": self.source,
        }


def available_rows(
    catalog: Iterable[CatalogEntry],
    installed: Iterable[ExtensionEntry],
    remote: Iterable[str] = (),
) -> list[AvailableRow]:
    """Merge the three sources into one listing.

    **Installed metadata wins over the manifest.** For a plugin present on the
    machine the entry-point group is a fact; the manifest is a record of what
    was true when this version shipped. So an installed plugin classifies from
    its live group, and one the manifest has never heard of still appears --
    which is what makes a third-party plugin visible here at all.

    Takes its three inputs as arguments for the reason ``extensions_from``
    does: a merge rule exercised only against whatever happens to be installed
    is untestable in precisely the cases that matter.
    """
    from functualize.app.utils import classify_group

    by_distribution: dict[str, ExtensionEntry] = {}
    for extension in installed:
        if extension.distribution in (None, _CORE_DISTRIBUTION):
            continue
        if extension.distribution not in by_distribution:
            by_distribution[str(extension.distribution)] = extension

    rows: list[AvailableRow] = []
    seen: set[str] = set()

    for curated in catalog:
        live = by_distribution.get(curated.distribution)
        seen.add(curated.distribution)
        rows.append(
            AvailableRow(
                name=curated.name,
                distribution=curated.distribution,
                # Live group when installed, manifest group otherwise.
                kind=str(classify_group(live.group)) if live else curated.kind,
                description=curated.description,
                installed=live is not None,
                recommended=curated.recommended,
                source="catalog",
            )
        )

    for distribution, extension in sorted(by_distribution.items()):
        if distribution in seen:
            continue
        rows.append(
            AvailableRow(
                name=extension.registered_name,
                distribution=distribution,
                kind=str(classify_group(extension.group)),
                description="",
                installed=True,
                recommended=False,
                source="installed",
            )
        )

    for distribution in sorted(set(remote) - seen):
        rows.append(
            AvailableRow(
                name=distribution.removeprefix("functualize-"),
                distribution=distribution,
                # Unknowable without installing it: the entry-point group is
                # in the distribution's metadata, not in the package index.
                kind="unknown",
                description="",
                installed=False,
                recommended=False,
                source="remote",
            )
        )

    return rows


#: Display order and heading for each kind.
_KIND_ORDER: tuple[tuple[str, str], ...] = (
    ("adapter", "ADAPTERS — add commands or a delivery surface"),
    ("domain", "DOMAINS — capability protocols jobs are written against"),
    ("implementation", "IMPLEMENTATIONS — pick the one matching your infrastructure"),
    ("unknown", "UNCURATED — found on PyPI, not vetted by this project"),
)


def render_available(rows: Iterable[AvailableRow]) -> list[str]:
    """Group by kind, mark what is installed, and pad to columns."""
    all_rows = list(rows)
    if not all_rows:
        return ["  no plugins known"]

    width = max(len(r.name) for r in all_rows)
    dist_width = max(len(r.distribution or "") for r in all_rows)
    lines: list[str] = []
    for kind, heading in _KIND_ORDER:
        group_rows = sorted(
            (r for r in all_rows if r.kind == kind), key=lambda r: r.name
        )
        if not group_rows:
            continue
        lines.append(heading)
        for row in group_rows:
            marker = "installed" if row.installed else ("" if row.recommended else "-")
            if not row.installed and row.recommended:
                marker = "recommended"
            lines.append(
                f"  {row.name:<{width}}  {(row.distribution or ''):<{dist_width}}  "
                f"{marker:<11}  {row.description}".rstrip()
            )
        lines.append("")
    return lines[:-1] if lines and lines[-1] == "" else lines


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


def _fetch_remote_distributions(timeout: float = 10.0) -> tuple[str, ...]:
    """Distribution names on PyPI beginning ``functualize-``.

    PyPI retired its search API, and the Simple index is the only endpoint that
    can *enumerate*. It is large, which is the honest reason ``--remote`` is
    opt-in rather than the default: discovery of packages nobody told us about
    cannot be done cheaply, and paying for it should be a choice.

    Raises on any failure. The caller degrades; this function does not decide
    that a listing is worth less than an error.
    """
    import json
    import urllib.request

    request = urllib.request.Request(
        "https://pypi.org/simple/",
        headers={
            "Accept": "application/vnd.pypi.simple.v1+json",
            "User-Agent": "functualize-plugin-available",
        },
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310
        payload = json.loads(response.read().decode("utf-8"))

    return tuple(
        sorted(
            name
            for project in payload.get("projects", [])
            if isinstance(name := project.get("name"), str)
            and name.startswith("functualize-")
        )
    )


@plugin_app.command("available")
@click.option(
    "--format",
    "output_format",
    type=click.Choice(["text", "json"]),
    default="text",
    show_default=True,
    help="Render the listing as text or JSON.",
)
@click.option(
    "--remote",
    is_flag=True,
    help=(
        "Also query PyPI for functualize-* distributions this version does not "
        "know about. Off by default, and off means no network request is made."
    ),
)
def available(output_format: str, remote: bool) -> None:
    """List plugins that exist, grouped by what they contribute.

    Three kinds, and the distinction is the point of the grouping. An *adapter*
    adds commands or a delivery surface and is broadly useful. A *domain*
    publishes the protocol a capability is written against. An
    *implementation* is a concrete backend chosen for the infrastructure you
    already run — two of them serving one domain is a decision, not a richer
    setup.

    Works offline. Installed plugins classify from their live entry-point group,
    which is authoritative; the shipped manifest supplies the kind only for
    plugins that are not installed, where there is no metadata to read.
    """
    remote_names: tuple[str, ...] = ()
    if remote:
        try:
            remote_names = _fetch_remote_distributions()
        except Exception as exc:  # noqa: BLE001 - any network failure degrades
            click.echo(
                f"Warning: could not reach PyPI ({exc}); showing the shipped "
                f"catalog only.",
                err=True,
            )

    rows = available_rows(load_catalog(), discover_extensions(), remote_names)

    if output_format == "json":
        click.echo(json.dumps([r.to_json() for r in rows], indent=2))
        return
    for line in render_available(rows):
        click.echo(line)


def _binary_and_config() -> tuple[str, Path]:
    import sys

    from functualize._cli import manifest
    from functualize.app.packaging import detect_from_process
    from functualize.app.utils import resolve_user_config_dir

    binary = manifest.resolve_binary_path(
        sys.argv[0] if sys.argv else "",
        sys.executable,
        detect_from_process().standalone_binary,
    )
    return binary, resolve_user_config_dir()


@plugin_app.command("install")
@click.argument("package", required=False)
@click.option(
    "--recommended",
    is_flag=True,
    help="Install the recommended set instead of one named package.",
)
@click.option(
    "--yes",
    "-y",
    "assume_yes",
    is_flag=True,
    help="Skip the confirmation prompt. The command is still printed.",
)
def install(package: str | None, recommended: bool, assume_yes: bool) -> None:
    """Install an extension into this installation's environment.

    The same mechanism as `self install`, recorded under a different key: an
    extension appears in `plugin list`, a plain dependency does not.

    `--recommended` installs the whole recommended set, which is a different
    *input* to that mechanism and not a second installer: the same planning,
    the same confirmation, and every name recorded so `self update` restores it.
    """
    from functualize._cli import manifest, package_ops
    from functualize.app import packaging

    if recommended and package is not None:
        raise click.UsageError(
            "--recommended installs the whole set; it cannot be combined with "
            "a package name. Drop one."
        )
    if not recommended and package is None:
        raise click.UsageError(
            "Name a package to install, or pass --recommended for the whole "
            "set. `plugin available` lists what there is."
        )

    packages = list(recommended_distributions()) if recommended else [str(package)]
    if not packages:
        click.echo("Nothing to install: the catalog recommends no packages.")
        return

    detection = detect_from_process()
    if detection.degraded:
        package_ops.refuse(detection, f"install {' '.join(packages)}")

    commands = package_ops.plan_or_exit(
        lambda: tuple(
            command
            for name in packages
            for command in packaging.install_commands(detection, name)
        )
    )
    package_ops.announce(commands, assume_yes)

    code = package_ops.run_commands(commands)
    if code != 0:
        raise SystemExit(code)

    # Deliberately not re-listing to confirm. `importlib.metadata` cached its
    # view before the subprocess ran, so the new distribution is not visible in
    # this process and a check here would report a success as a failure.
    binary, config_dir = _binary_and_config()
    for name in packages:
        if manifest.record_addition(
            config_dir, binary_path=binary, key="plugins", name=name
        ):
            click.echo(f"Recorded {name}; `self update` will restore it.")


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
    from functualize.app import packaging

    detection = detect_from_process()
    if detection.degraded:
        package_ops.refuse(detection, f"uninstall {package}")

    commands = package_ops.plan_or_exit(
        lambda: packaging.uninstall_commands(detection, package)
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
