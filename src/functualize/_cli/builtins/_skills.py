"""Moved builtin command registration for skills."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from . import (
    ExitCode,
    _mount,
    shutil,
    subprocess,
)

if TYPE_CHECKING:
    import click


def register_skills(builtin_app: click.Group) -> None:
    import click

    # --- Skills sub-group (agent skills shipped with this version) ---
    # A sibling of `cache` and `state`, not a `scaffold` template: scaffold
    # output is user-owned and edited afterwards, while these are framework-
    # owned and replaced wholesale on upgrade (ADR-006 §3).
    skills_app = click.Group(
        name="skills",
        help="Locate and install the AI agent skills shipped with this version.",
    )

    def _require_skills_locations() -> list[Any]:
        """Core's location first, then every registered third-party host.

        Plural since `third-party-host-seams`/4.1: a distribution can host its
        own skills through the `functualize.skills` entry point, and every
        command below reports all of them rather than only core's.
        """
        from functualize._cli.skills import resolve_skills_locations

        locations = resolve_skills_locations()
        if not locations:
            click.echo(
                "No skills directory found for this installation.",
                err=True,
            )
            raise SystemExit(ExitCode.USAGE)
        return locations

    @skills_app.command("path")
    def skills_path() -> None:
        """Print each directory holding agent skills, one per line.

        Machine-readable on purpose — bare paths, no decoration — but **one
        line per location**, not one path. A third-party distribution can host
        its own skills, so a single path could only ever be core's, and
        answering with core's alone silently hides the rest.

        That makes `"$(func builtin skills path)"` wrong: it substitutes a
        multi-line string as one argument. Loop instead:

            func builtin skills path | while read -r dir; do
                npx skills add "$dir"
            done
        """
        for location in _require_skills_locations():
            click.echo(str(location.path))

    @skills_app.command("list")
    def skills_list() -> None:
        """List the available skills with their descriptions."""
        from functualize._cli.skills import list_skills

        locations = _require_skills_locations()
        total = 0
        for location in locations:
            skills = list_skills(location.path)
            if location.is_packaged:
                origin = f"{location.distribution} {location.version} (packaged)"
            elif location.origin == "entry-point":
                origin = (
                    f"{location.distribution} {location.version} (entry point)"
                    if location.version
                    else f"{location.distribution} (entry point)"
                )
            else:
                origin = f"source checkout at {location.path} (not version-pinned)"

            click.echo(f"Agent skills from {origin}")
            click.echo("")
            if not skills:
                click.echo(f"  (none found in {location.path})")
                click.echo("")
                continue
            for skill in skills:
                total += 1
                click.echo(f"  {skill.name}")
                click.echo(f"    {skill.summary}")
                click.echo(f"    {skill.path}")
                click.echo("")

        if total == 0:
            click.echo("No skills found.")
            return
        click.echo("Install into a project:  func builtin skills install")

    @skills_app.command("materialize")
    @click.option(
        "--prune",
        is_flag=True,
        default=False,
        help="Also delete materialized skills for other functualize versions.",
    )
    def skills_materialize(prune: bool) -> None:
        """Copy this version's skills into the XDG data directory.

        Useful when the environment holding the wheel is disposable (uvx, a
        PEP 723 script env) or when a project that does not depend on
        functualize needs a stable path to point an agent at.
        """
        from functualize import __version__
        from functualize._cli.skills import materialize_skills

        for location in _require_skills_locations():
            # The *owning* distribution's version, never functualize's. The
            # whole promise of a version-stamped copy is that it describes the
            # release it came from, and a shared stamp would make a third-party
            # skill claim functualize's (`_cli/skills.py` docstring).
            version = location.version or __version__
            destination, names = materialize_skills(
                location.path,
                version,
                prune=prune,
                distribution=location.distribution,
            )
            for name in names:
                click.echo(f"  {name}")
            click.echo(f"{len(names)} skill(s) → {destination}")

    @skills_app.command("install")
    @click.option(
        "--dry-run",
        is_flag=True,
        default=False,
        help="Print the command that would run instead of running it.",
    )
    def skills_install(dry_run: bool) -> None:
        """Install the shipped skills into the current project.

        Shells out to the skills CLI rather than reimplementing its
        agent-path matrix (ADR-006 §2). The source is the local directory, so
        what lands is pinned to the installed functualize — not whatever
        master happens to say today.
        """
        locations = _require_skills_locations()
        commands = [["npx", "skills", "add", str(loc.path)] for loc in locations]
        rendered = [" ".join(command) for command in commands]

        if dry_run:
            for line in rendered:
                click.echo(line)
            return

        if shutil.which("npx") is None:
            manual = "\n".join(
                f"  cp -R {loc.path}/* .claude/skills/" for loc in locations
            )
            click.echo(
                "npx was not found on PATH. The skills CLI needs Node.\n"
                "\n"
                "Run these once Node is available:\n"
                + "\n".join(f"  {line}" for line in rendered)
                + "\n"
                "\n"
                "Or copy the directories into your agent's skills folder:\n" + manual,
                err=True,
            )
            raise SystemExit(ExitCode.USAGE)

        # Stop at the first failure rather than pressing on: a half-installed
        # skill set is harder to reason about than one that stopped and said so.
        for command, line in zip(commands, rendered, strict=True):
            click.echo(f"$ {line}")
            code = subprocess.call(command)
            if code != 0:
                raise SystemExit(code)
        raise SystemExit(0)

    _mount(builtin_app, skills_app, "skills")
