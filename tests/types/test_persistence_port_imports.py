"""`_types/persistence.py` names no layer above it — AC-5.

`uv run lint-imports` reporting **7 kept, 0 broken** is necessary and not
sufficient. `exclude_type_checking_imports = true` keeps an import inside an
`if TYPE_CHECKING:` block out of import-linter's graph, so a deferred
`_types → _app` import leaves all seven contracts green — measured by adding
one, and recorded at `contributor/architecture/codemaps/dependencies.md:37`.
Section 5 of `contributor/architecture/layer-contract-blind-spot.md` says a
reviewer has to refuse that import by hand, because no contract will. So the
check is on the text, the way `tests/types/test_plugin_host_port.py` already
checks it for `PluginHost`. The criterion is the pair: `lint-imports` *and*
this file.

Why this module. `_types` is the vocabulary every layer may hold — a recorder,
a store, an event sink and a plugin all name the persistence port — and it is
stdlib-only for that reason: naming the port must not drag in the application
that ships it. The module claims as much in its own docstring ("imports nothing
internal, the standard library only"); this file is what checks the sentence.

The sweep is deliberately stricter than the contracts read on their own. It
allows every `functualize` spelling but `functualize._types`, which refuses the
eight internal layers of "Types import nothing internal" and the seven public
folders of "Internal never imports public" (that contract lists `_types` among
its sources), and it also refuses `functualize._gate` — named by neither list,
stdlib-only by the rule, so an import of it is a violation the config would
pass rather than a false positive here.
"""

from __future__ import annotations

import re
from pathlib import Path

#: The module under guard. Imported nowhere in this file, on purpose: the guard
#: is over the source text, because the import it catches never runs.
MODULE = "functualize._types.persistence"

#: `src/`, from `tests/types/`.
_SRC = Path(__file__).resolve().parents[2] / "src"

#: Indentation-blind on purpose. The import this file exists to catch sits
#: inside an `if TYPE_CHECKING:` block, so a sweep anchored at column 0 would
#: be blind to exactly the line it is here to find.
_IMPORT_LINE = re.compile(r"\s*(from|import)\s+\w")


def _source() -> str:
    """The module's text, read where the package ships it."""
    path = (_SRC / Path(*MODULE.split("."))).with_suffix(".py")
    return path.read_text(encoding="utf-8")


def _import_lines(text: str) -> list[str]:
    """Every import line in ``text``, the deferred ones included."""
    return [line.strip() for line in text.splitlines() if _IMPORT_LINE.match(line)]


def _offenders(lines: list[str]) -> list[str]:
    """The lines naming a `functualize` layer other than `_types` itself."""
    return [
        ln for ln in lines if "functualize" in ln and "functualize._types" not in ln
    ]


class TestThePersistencePortNamesNoLayerAboveIt:
    def test_it_imports_nothing_from_the_app(self) -> None:
        """The case the criterion names, `TYPE_CHECKING` or otherwise."""
        offenders = [ln for ln in _import_lines(_source()) if "functualize._app" in ln]
        assert not offenders, offenders

    def test_it_names_no_layer_but_its_own(self) -> None:
        """The general form: `_app` is one of eight refused layers, not the only one."""
        offenders = _offenders(_import_lines(_source()))
        assert not offenders, offenders

    def test_the_sweep_sees_a_deferred_import(self) -> None:
        """The guard that keeps the two above from proving nothing.

        Both pass on a module that imports nothing at all, so they are only
        worth having while the sweep reaches inside `if TYPE_CHECKING:` — which
        is where the blind spot lives. Swept here over the deferred import that
        must not come back to `_types/persistence.py`.
        """
        deferred = (
            "if TYPE_CHECKING:\n    from functualize._app.core import FunctualizeApp\n"
        )
        assert _offenders(_import_lines(deferred)) == [
            "from functualize._app.core import FunctualizeApp"
        ]
