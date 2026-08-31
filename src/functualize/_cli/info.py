"""Structured views over a booted app — the data behind ``func builtin info``.

Separated from the click wiring in ``builtins.py`` because there are three
renderings of the same facts (``rich``, ``plain``, ``json``) and one of them is
a contract: an agent that parses ``info schema`` should not be reading a
function that also knows about panel borders.

The JSON Schema itself is built by ``functualize.app.utils.job_input_schema``,
which the MCP plugin also calls, so a tool definition and
``func builtin info schema`` describe a job identically by construction rather
than by review.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Iterator, Sequence

    from functualize.app.core import FunctualizeApp

#: The one reserved top-level segment. Mirrors ``_cli.builtins.BUILTIN_ROOT``;
#: kept as a literal here so this module stays importable from ``--help``
#: without pulling the builtin registry in.
BUILTIN_ROOT_SEGMENT = "builtin"

__all__ = [
    "RENDERERS",
    "full_report",
    "job_catalog",
    "job_detail",
    "command_schemas",
    "render_catalog_text",
    "render_report_text",
    "resolve_renderer",
]

#: The three renderings, matching the ``[cli] output`` vocabulary.
RENDERERS = ("rich", "plain", "json")


def resolve_renderer(json_flag: bool, cli_config: Any) -> str:
    """Which rendering to use: the explicit flag, else the configured default.

    ``--json`` is an override rather than a mode, so a project that sets
    ``[cli] output = "plain"`` still gets JSON when a caller asks for it, and
    an agent that exports ``FUNCTUALIZE_CLI_OUTPUT=json`` never has to pass a
    flag at all.
    """
    if json_flag:
        return "json"
    configured = getattr(cli_config, "output", None)
    return str(configured) if configured in RENDERERS else "rich"


def _summary(descriptor: Any) -> str:
    """First line of the docstring — what a listing shows."""
    docstring = getattr(descriptor, "docstring", None)
    if not isinstance(docstring, str) or not docstring.strip():
        return ""
    return docstring.strip().splitlines()[0].strip()


def _parameter(field: Any) -> dict[str, Any]:
    """One published parameter, as data rather than as a flag rendering."""
    entry: dict[str, Any] = {
        "name": field.name,
        "type": getattr(field, "type_annotation", None),
        "required": bool(field.required),
    }
    if field.default is not None:
        entry["default"] = field.default
    if field.description:
        entry["description"] = field.description
    if field.choices:
        entry["choices"] = list(field.choices)
    if getattr(field, "is_stdin", False):
        entry["stdin"] = True
    return entry


def _group_options_class_names(app: FunctualizeApp) -> frozenset[str]:
    """Known ``GroupOptions`` class names, if the app exposes any."""
    specs = getattr(app, "_group_options", None) or {}
    try:
        return frozenset(
            name
            for spec in specs.values()
            if (name := getattr(spec, "class_name", None))
        )
    except AttributeError:
        return frozenset()


def job_catalog(app: FunctualizeApp) -> list[dict[str, Any]]:
    """Every discovered job, in the shape a listing needs.

    Deliberately shallow: names, summaries and the few flags that change how a
    job may be called. ``job_detail`` is the deep view.
    """
    catalog: list[dict[str, Any]] = []
    for descriptor in sorted(app.get_jobs(), key=lambda d: d.name):
        catalog.append(
            {
                "name": descriptor.name,
                "group": descriptor.group,
                "summary": _summary(descriptor),
                "parameters": [f.name for f in descriptor.parameters],
                "requires_tty": bool(getattr(descriptor, "requires_tty", False)),
            }
        )
    return catalog


def job_detail(app: FunctualizeApp, name: str) -> dict[str, Any] | None:
    """One job in full, or None when no job resolves to ``name``."""
    from functualize.app.utils import job_input_schema

    descriptor = next((d for d in app.get_jobs() if d.name == name), None)
    if descriptor is None:
        return None

    fields = descriptor.config_fields or descriptor.parameters
    return {
        "name": descriptor.name,
        "group": descriptor.group,
        "summary": _summary(descriptor),
        "docstring": descriptor.docstring,
        "parameters": [_parameter(f) for f in fields],
        "dependencies": list(getattr(descriptor, "dependencies", ()) or ()),
        "requires_tty": bool(getattr(descriptor, "requires_tty", False)),
        "uses_live": bool(getattr(descriptor, "uses_live", False)),
        "source_file": getattr(descriptor, "source_file", None),
        "module_path": getattr(descriptor, "module_path", None),
        "python_name": getattr(descriptor, "python_name", None),
        "inputSchema": job_input_schema(
            descriptor,
            group_options_class_names=_group_options_class_names(app),
        ),
    }


def _walk_tree(
    nodes: Sequence[Any], path: tuple[str, ...] = ()
) -> Iterator[tuple[tuple[str, ...], Any]]:
    """Every node in the command tree, depth-first, with its full path."""
    for node in nodes:
        here = (*path, node.name)
        yield here, node
        yield from _walk_tree(node.children(), here)


def _is_runnable(node: Any, has_children: bool) -> bool:
    """Can a caller actually run this node, or is it only a namespace?

    A leaf is runnable. A node with children is runnable only if it accepts
    parameters of its own — ``builtin info`` does (``--json``), ``builtin
    cache`` does not and only prints usage. Publishing a pure namespace as a
    command with an empty schema would tell an agent it can run something that
    exits 2.
    """
    if not has_children:
        return True
    try:
        return bool(node.params())
    except Exception:
        return False


def command_schemas(
    app: FunctualizeApp,
    name: str | None = None,
    *,
    kind: str | None = None,
) -> list[dict[str, Any]]:
    """Input contracts for everything runnable — jobs *and* builtins.

    Walks the one command tree rather than ``app.get_jobs()``, because the
    tree is where this project already decided jobs and builtins are the same
    thing. ``CommandNode``'s own docstring: *"Nothing here distinguishes a job
    from a builtin; that is the point"*, and ``params()`` is *"deliberately the
    existing FieldDescriptor … there is one description of a command's
    parameters and every surface reads it."* Reading ``get_jobs()`` here would
    reinstate the split the convergence work removed, and would leave an agent
    walking ``--help`` for the ~30 builtin subcommands.

    Args:
        app: A booted app.
        name: Restrict to one command, addressed by its dotted path
            (``demo.report``, ``builtin.skills.materialize``).
        kind: Restrict to ``"job"`` or ``"builtin"``.

    The entry shape keeps the MCP tool fields (``name`` / ``description`` /
    ``inputSchema``) so agent tooling reads it unchanged, and adds two:

    ``kind``
        ``"job"`` or ``"builtin"`` — the filter an MCP surface applies.
    ``path``
        The segments to type, as an array. Structured over opaque: a dotted
        string would have to be re-split, and the split is not obvious for a
        job whose group contains a dot-free name.
    """
    from functualize.app.commands import build_command_tree
    from functualize.app.utils import input_schema

    entries: list[dict[str, Any]] = []
    for path, node in _walk_tree(build_command_tree(app)):
        if not _is_runnable(node, bool(node.children())):
            continue

        entry_kind = "builtin" if path[0] == BUILTIN_ROOT_SEGMENT else "job"
        if kind is not None and entry_kind != kind:
            continue

        dotted = ".".join(path)
        if name is not None and dotted != name:
            continue

        entries.append(
            {
                "name": dotted,
                "kind": entry_kind,
                "path": list(path),
                "description": node.help_text or "",
                "inputSchema": input_schema(node.params()),
            }
        )

    return sorted(entries, key=lambda e: (e["kind"] != "job", e["name"]))


def full_report(app: FunctualizeApp, cli_config: Any = None) -> dict[str, Any]:
    """Everything ``info`` knows, as one document.

    What an agent should fetch once at the start of a session instead of
    running four commands and parsing three prose formats.
    """
    from functualize import __version__
    from functualize._cli.skills import list_skills, resolve_skills_dir

    report: dict[str, Any] = {
        "functualize": __version__,
        "environment": {
            "name": app.active_environment(),
            "source": getattr(app.environment_source(), "value", None),
        },
        "jobs": [job_detail(app, entry["name"]) for entry in job_catalog(app)],
    }

    if cli_config is not None:
        anchor = getattr(cli_config, "anchor", None)
        report["config"] = {
            "anchor": str(anchor) if anchor is not None else None,
            "import_libs": [
                str(p) for p in getattr(cli_config, "import_libs", ()) or ()
            ],
            "dotenv": bool(getattr(cli_config, "dotenv", False)),
            "output": getattr(cli_config, "output", None),
        }

    location = resolve_skills_dir()
    report["skills"] = (
        {
            "path": str(location.path),
            "origin": location.origin,
            "names": [s.name for s in list_skills(location.path)],
        }
        if location is not None
        else None
    )

    return report


def render_catalog_text(catalog: list[dict[str, Any]]) -> list[str]:
    """The catalog as aligned columns — no box drawing, safe through a pipe."""
    if not catalog:
        return ["No jobs discovered."]

    width = max(len(entry["name"]) for entry in catalog)
    lines = []
    for entry in catalog:
        summary = entry["summary"]
        marker = "  [tty]" if entry["requires_tty"] else ""
        lines.append(f"{entry['name']:<{width}}  {summary}{marker}".rstrip())
    return lines


def render_report_text(report: dict[str, Any]) -> list[str]:
    """The full report as plain key/value lines.

    The ``plain`` rendering of ``func builtin info``: the same facts the rich
    panels carry, minus the 300-odd box-drawing characters that made the
    piped output unparseable.
    """
    lines = [f"functualize {report['functualize']}"]

    environment = report.get("environment") or {}
    source = environment.get("source") or "default"
    lines.append(f"environment: {environment.get('name')} ({source})")

    config = report.get("config") or {}
    if config:
        lines.append(f"anchor: {config.get('anchor')}")
        lines.append(f"dotenv: {config.get('dotenv')}")
        import_libs = config.get("import_libs") or []
        lines.append(
            f"import_libs: {', '.join(import_libs) if import_libs else '(none)'}"
        )

    skills = report.get("skills")
    if skills:
        lines.append(f"skills: {skills['path']} ({skills['origin']})")
    else:
        lines.append("skills: (none found)")

    jobs = report.get("jobs") or []
    lines.append("")
    lines.append(f"jobs ({len(jobs)}):")
    catalog = [
        {
            "name": job["name"],
            "summary": job["summary"],
            "requires_tty": job["requires_tty"],
        }
        for job in jobs
        if job is not None
    ]
    lines.extend(f"  {line}" for line in render_catalog_text(catalog))
    return lines
