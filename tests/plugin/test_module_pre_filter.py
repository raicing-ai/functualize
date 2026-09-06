"""`ModulePreFilter` is public, and it carries `fingerprint()`.

`DiscoveryConfig` offers seven `require_*` predicates over filenames, imports,
markers and decorator names. A host whose jobs are *methods on classes* cannot
express itself in any of them, and its only alternatives were to contort its
layout or to import `functualize._primitives.pre_filter` — an underscore
package the constitution forbids even `_cli` from touching.

The Protocol moved to `_types/protocols.py`, where every other extension
Protocol lives, and `functualize.plugin` re-exports it. `_primitives` imports
it downward; nothing imports upward.

**`fingerprint()` is load-bearing, not decorative.** The discovery cache
persists *negative* pre-filter decisions and replays them, trusting them only
while the discovery fingerprint matches. A caller-supplied predicate cannot
join that hash by identity, and both alternatives were verified before this
method existed:

- **Hash the object** — `_normalize_discovery_value` falls through to
  `f"str({value})"`, and `str()` of a function is
  `'<function p at 0x7fd949036160>'`. The digest would differ on every boot,
  invalidating the cache on every run.
- **Omit it** — reproduces the X1–X4 replay defect verbatim: a warm cache
  replaying decisions made under a *different* predicate. That is the bug
  ADR-010/ADR-011 exist to close, and it drove `CACHE_VERSION` 15→16→17.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from functualize._primitives import pre_filter as builtins
from functualize.plugin import ModulePreFilter

REPO_ROOT = Path(__file__).resolve().parents[2]

BUILT_INS = [
    builtins.DefaultModulePreFilter(),
    builtins.ASTModulePreFilter(),
    builtins.DisplayClassPreFilter(),
    builtins.GroupOptionsPreFilter(),
    builtins.FilePrefixPreFilter("job_"),
    builtins.FilePostfixPreFilter("_job"),
    builtins.ImportModulePreFilter("functualize"),
    builtins.MarkerModulePreFilter(),
    builtins.DecoratorModulePreFilter(("job",)),
    builtins.GlobExcludePreFilter(("*.tmp",), Path("/tmp")),
    builtins.AllOf(builtins.ASTModulePreFilter()),
    builtins.AnyOf(builtins.ASTModulePreFilter()),
    builtins.NoneOf(builtins.ASTModulePreFilter()),
]


class TestItIsPublic:
    def test_it_imports_from_the_plugin_package(self) -> None:
        assert ModulePreFilter is not None

    def test_it_is_the_same_object_primitives_uses(self) -> None:
        """One Protocol, not two. A second definition would let a filter
        satisfy the public one and fail the internal check, or vice versa."""
        from functualize._primitives import pre_filter
        from functualize._types import protocols

        assert ModulePreFilter is protocols.ModulePreFilter
        assert ModulePreFilter is pre_filter.ModulePreFilter

    def test_a_host_can_implement_it_without_touching_an_underscore_package(
        self,
    ) -> None:
        """The whole point. Structural satisfaction, nothing to inherit."""

        class MethodsOnClasses:
            def should_import(self, source_file: Path) -> bool:
                return "class " in source_file.read_text(encoding="utf-8")

            def fingerprint(self) -> str:
                return "methods-on-classes/v1"

        assert isinstance(MethodsOnClasses(), ModulePreFilter)


class TestEveryBuiltInSatisfiesIt:
    @pytest.mark.parametrize("instance", BUILT_INS, ids=lambda f: type(f).__name__)
    def test_isinstance(self, instance: object) -> None:
        assert isinstance(instance, ModulePreFilter)

    @pytest.mark.parametrize("instance", BUILT_INS, ids=lambda f: type(f).__name__)
    def test_fingerprint_is_a_non_empty_string(self, instance: object) -> None:
        fingerprint = instance.fingerprint()  # type: ignore[attr-defined]
        assert isinstance(fingerprint, str)
        assert fingerprint

    def test_the_list_covers_every_built_in(self) -> None:
        """A new filter class must not be able to ship without a
        `fingerprint()` — it would join the discovery hash as nothing."""
        import inspect

        declared = {
            name
            for name, obj in vars(builtins).items()
            if inspect.isclass(obj)
            and hasattr(obj, "should_import")
            and obj is not ModulePreFilter
        }
        covered = {type(f).__name__ for f in BUILT_INS}
        assert declared == covered


class TestFingerprintDiscriminates:
    def test_different_configuration_gives_a_different_fingerprint(self) -> None:
        a = builtins.DecoratorModulePreFilter(("job",))
        b = builtins.DecoratorModulePreFilter(("task",))
        assert a.fingerprint() != b.fingerprint()

    def test_different_class_gives_a_different_fingerprint(self) -> None:
        assert (
            builtins.FilePrefixPreFilter("x").fingerprint()
            != builtins.FilePostfixPreFilter("x").fingerprint()
        )

    def test_the_same_configuration_gives_the_same_fingerprint(self) -> None:
        assert (
            builtins.DecoratorModulePreFilter(("job",)).fingerprint()
            == builtins.DecoratorModulePreFilter(("job",)).fingerprint()
        )

    def test_decorator_order_does_not_matter(self) -> None:
        """The filter stores a set, so `("a", "b")` and `("b", "a")` are the
        same predicate and must share a cache entry."""
        assert (
            builtins.DecoratorModulePreFilter(("a", "b")).fingerprint()
            == builtins.DecoratorModulePreFilter(("b", "a")).fingerprint()
        )

    def test_a_composite_folds_its_members(self) -> None:
        inner_a = builtins.FilePrefixPreFilter("a")
        inner_b = builtins.FilePrefixPreFilter("b")
        assert (
            builtins.AllOf(inner_a).fingerprint()
            != builtins.AllOf(inner_b).fingerprint()
        )

    def test_composite_order_matters(self) -> None:
        """`AllOf` short-circuits, so two compositions of the same filters read
        different files and must not share a cache entry."""
        a = builtins.FilePrefixPreFilter("a")
        b = builtins.FilePrefixPreFilter("b")
        assert builtins.AllOf(a, b).fingerprint() != builtins.AllOf(b, a).fingerprint()

    def test_the_combinators_are_distinguishable(self) -> None:
        inner = builtins.ASTModulePreFilter()
        assert (
            len(
                {
                    builtins.AllOf(inner).fingerprint(),
                    builtins.AnyOf(inner).fingerprint(),
                    builtins.NoneOf(inner).fingerprint(),
                }
            )
            == 3
        )


class TestFingerprintIsStableAcrossProcesses:
    """The half that proves the address problem is gone. Everything above runs
    in one interpreter, where even `id()`-based identity would look stable."""

    def test_a_fresh_process_produces_the_same_value(self) -> None:
        program = (
            "from functualize._primitives.pre_filter import DecoratorModulePreFilter;"
            "print(DecoratorModulePreFilter(('job',)).fingerprint())"
        )
        runs = [
            subprocess.run(
                [sys.executable, "-c", program],
                cwd=REPO_ROOT,
                capture_output=True,
                text=True,
                check=True,
            ).stdout.strip()
            for _ in range(2)
        ]
        assert runs[0] == runs[1]
        assert runs[0] == builtins.DecoratorModulePreFilter(("job",)).fingerprint()

    def test_str_of_a_callable_would_not_have_been(self) -> None:
        """The reason `fingerprint()` exists, asserted rather than asserted-in-
        prose: `str()` of a function carries its address, so the digest built
        that way differs between two objects with identical behaviour."""

        def make():  # noqa: ANN202 - two identical functions, different objects
            def predicate(path: Path) -> bool:
                return True

            return predicate

        assert str(make()) != str(make())
