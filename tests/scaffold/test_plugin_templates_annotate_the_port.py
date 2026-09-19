"""A scaffolded plugin annotates against `PluginHost` — AC-11.

Two plugin templates carry an `app` parameter, and both used to type it wrongly
in different ways: `plugin.py.j2:18` said `app: FunctualizeApp` (the concrete
class, so a plugin author's first act was to name the application) and
`domain-plugin/_plugin.py.j2:20` said `app: Any` (so nothing they typed next
could be checked at all).

The scaffold is where a plugin author's habits come from, so this is the one
place the annotation has to be right by default rather than by discipline.

**Two claims, and the second is the one that matters.** That the templates do
not say `Any` or `FunctualizeApp` is a grep. That what they *render* actually
type-checks under `mypy --strict`, importing the real `PluginHost`, is the
claim -- a template can name the port and still produce a file that does not
compile, and nothing in `tests/scaffold/` would have noticed.

`tasks.md`'s gate was `rg -n 'app: (Any|FunctualizeApp)'` over the templates
directory, with a note that the alternation matters because a pattern for
`app: FunctualizeApp` alone silently misses the `domain-plugin` one. Both
spellings are checked below, per template, so a failure names which file
regressed and how.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest
from jinja2 import Environment, PackageLoader

#: The two templates with an `app` parameter, and a context that renders each.
#: The other four plugin templates take `rc: RunContext` or no host at all.
PLUGIN_TEMPLATES = {
    "plugin.py.j2": {
        "plugin_name": "myplug",
        "module_name": "myplug",
    },
    "domain-plugin/_plugin.py.j2": {
        "project_name": "functualize-ai-my-provider",
        "class_name": "MyProvider",
        "provider_name": "my_provider",
        "domain_name": "ai",
        "description": "MyProvider provider for the ai domain",
    },
}

TEMPLATE_DIR = (
    Path(__file__).resolve().parents[2] / "src/functualize/_cli/scaffold/templates"
)

_WRONG = re.compile(r"app: (Any|FunctualizeApp)\b")


def _render(name: str, context: dict[str, str]) -> str:
    env = Environment(
        loader=PackageLoader("functualize._cli.scaffold", "templates"),
        keep_trailing_newline=True,
    )
    return env.get_template(name).render(**context)


def test_exactly_two_plugin_templates_take_a_host() -> None:
    """So a third cannot appear annotated `Any` without this file noticing.

    Measured: six `*plugin*.j2` templates exist; the four not listed here take
    `rc: RunContext` (`file_plugin.py.j2`, `job-folder/file_plugin.py.j2`) or
    have no such parameter (`domain-plugin/test_plugin.py.j2`,
    `plugin-project/plugin.py.j2`).
    """
    with_app = {
        str(path.relative_to(TEMPLATE_DIR))
        for path in TEMPLATE_DIR.rglob("*plugin*.j2")
        if re.search(r"\bapp: ", path.read_text(encoding="utf-8"))
    }
    assert with_app == set(PLUGIN_TEMPLATES)


@pytest.mark.parametrize("template", sorted(PLUGIN_TEMPLATES))
def test_the_template_does_not_name_any_or_the_concrete_app(template: str) -> None:
    """The alternation, not just `FunctualizeApp` -- each template was wrong
    in a different way, so a one-spelling check would have passed one of them."""
    offenders = _WRONG.findall((TEMPLATE_DIR / template).read_text(encoding="utf-8"))
    assert not offenders, f"{template} annotates `app` as {offenders}"


@pytest.mark.parametrize("template", sorted(PLUGIN_TEMPLATES))
def test_the_rendered_plugin_annotates_the_port(template: str) -> None:
    """Checked on the AST, so a mention in a docstring does not satisfy it."""
    tree = ast.parse(_render(template, PLUGIN_TEMPLATES[template]))
    found = [
        ast.unparse(arg.annotation)
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef)
        for arg in node.args.args
        if arg.arg == "app" and arg.annotation is not None
    ]
    assert found == ["PluginHost"], f"{template} renders `app: {found}`"


@pytest.mark.parametrize("template", sorted(PLUGIN_TEMPLATES))
def test_the_rendered_plugin_type_checks_out_of_the_box(
    template: str, tmp_path: Path
) -> None:
    """The claim a grep cannot make. `mypy --strict`, importing the real port.

    A template can name `PluginHost` and still render a file that does not
    compile -- a missing import, or a deferred one under no
    `from __future__ import annotations`. Both templates get that right by
    different routes: `plugin.py.j2` imports at runtime because it has no
    `__future__` line, the domain template defers under `TYPE_CHECKING`
    because it has one.
    """
    api = pytest.importorskip("mypy.api", reason="mypy is a dev dependency")
    rendered = tmp_path / "scaffolded_plugin.py"
    rendered.write_text(_render(template, PLUGIN_TEMPLATES[template]))

    out, _err, _code = api.run(["--strict", str(rendered)])
    errors = [line for line in out.splitlines() if re.match(r"^.*?:\d+: error:", line)]
    assert not errors, f"a freshly scaffolded {template} does not type-check:\n{out}"
