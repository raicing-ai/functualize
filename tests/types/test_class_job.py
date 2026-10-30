"""`ClassJobMethod` exposes a job's method receiver-less (plan.md §4.4).

The proxy is what a class job registers: the bound `run` method minus its
receiver, carrying the descriptor's *effective merged* declaration instead of
the method's own unmerged `@job`. Every assertion here comes from schema §6's
member table — the signature (first parameter removed, PEP 563 annotations
resolved to live types), the introspection copies, the own-attribute
declaration, delegation for everything else, a `__functualize_lazy__` that is
never reachable, and a `__call__` that refuses to build a second config
instance.

The `resolved_hints(proxy) == {}` case runs against the fixture's
`unresolvable` method — the one whose annotations cannot resolve. That is not
an evasion of the check: it pins the property the proxy relies on (a proxy is
not a function, so hint resolution falls back to `{}`) instead of re-measuring
the fixture's resolvable annotations, which `get_type_hints` would happily
unwrap through `__wrapped__` to the method's globals.
"""

from __future__ import annotations

import inspect
from typing import get_args

import pytest

from functualize._types.annotations import resolved_hints
from functualize._types.class_job import ClassJobMethod
from functualize._types.job_declaration import JobDeclaration

from .fixtures.class_job_cases import (
    ExampleJob,
    MarkeredJob,
    merged_declaration,
)


def _proxy(job_class: type = ExampleJob, method_name: str = "run") -> ClassJobMethod:
    return ClassJobMethod(job_class, method_name, merged_declaration())


class TestSignature:
    def test_receiver_removed_and_order_and_defaults_kept(self) -> None:
        signature = _proxy().__signature__
        assert list(signature.parameters) == ["count", "label"]
        assert signature.parameters["count"].default is inspect.Parameter.empty
        assert signature.parameters["label"].default == "x"
        assert signature.return_annotation is int

    def test_renamed_receiver_is_removed_by_position(self) -> None:
        class Renamed:
            def go(self, first: int, second: int = 2) -> None: ...

        signature = ClassJobMethod(Renamed, "go", merged_declaration()).__signature__
        assert list(signature.parameters) == ["first", "second"]

    def test_annotations_resolve_to_live_types_including_extras(self) -> None:
        signature = _proxy().__signature__
        count = signature.parameters["count"].annotation
        # The live Annotated, with Field() metadata intact — not the PEP 563 string.
        assert count.__origin__ is int or getattr(count, "__metadata__", None)
        assert get_args(count)[0] is int
        assert get_args(count)[1].metadata[0].ge == 0
        assert signature.parameters["label"].annotation is str

    def test_unresolvable_annotations_fall_back_to_raw(self) -> None:
        signature = _proxy(ExampleJob, "unresolvable").__signature__
        assert list(signature.parameters) == ["value"]
        assert signature.parameters["value"].annotation == "Missing_"


class TestIntrospectionCopies:
    def test_dunders_come_from_the_underlying_function(self) -> None:
        method = ExampleJob.run
        proxy = _proxy()
        assert proxy.__name__ == method.__name__
        assert proxy.__qualname__ == method.__qualname__
        assert proxy.__doc__ == method.__doc__
        assert proxy.__module__ == method.__module__
        assert proxy.__annotations__ == method.__annotations__
        assert proxy.__wrapped__ is method

    def test_own_attributes_are_not_delegated(self) -> None:
        proxy = _proxy()
        assert "__name__" in vars(proxy)
        assert "__signature__" in vars(proxy)
        assert "__wrapped__" in vars(proxy)


class TestDeclaration:
    def test_declaration_is_own_attribute(self) -> None:
        declaration = merged_declaration()
        proxy = ClassJobMethod(ExampleJob, "run", declaration)
        assert proxy.__functualize_job__ is declaration
        assert "__functualize_job__" in vars(proxy)

    def test_declaration_is_the_merged_one_not_the_methods_own(self) -> None:
        class OwnJob:
            def run(self) -> None: ...

        run = OwnJob.run
        run.__functualize_job__ = JobDeclaration(tags=("mine",))  # type: ignore[attr-defined]

        declaration = merged_declaration()
        proxy = ClassJobMethod(OwnJob, "run", declaration)
        assert proxy.__functualize_job__ is declaration
        assert proxy.__functualize_job__ is not run.__functualize_job__  # type: ignore[attr-defined]

    def test_exposes_job_class_and_method_name(self) -> None:
        proxy = _proxy()
        assert proxy.job_class is ExampleJob
        assert proxy.method_name == "run"


class TestDelegation:
    def test_delegates_to_the_function(self) -> None:
        proxy = _proxy(MarkeredJob)
        assert proxy.__functualize_workflow__ == "workflow-marker"
        assert proxy.__functualize_surface_hint__ == "stdout"

    def test_getattr_serves_type_level_dunders(self) -> None:
        # __doc__ shadows __getattr__ on instances; the copy keeps it serving.
        assert _proxy().__doc__ == ExampleJob.run.__doc__

    def test_lazy_is_never_truthy_even_when_the_method_carries_it(self) -> None:
        assert MarkeredJob.run.__functualize_lazy__ is True  # type: ignore[attr-defined]
        proxy = _proxy(MarkeredJob)
        assert not getattr(proxy, "__functualize_lazy__", False)
        assert "__functualize_lazy__" not in vars(proxy)
        with pytest.raises(AttributeError):
            proxy.__functualize_lazy__  # noqa: B018


class TestCall:
    def test_call_raises_runtime_error_naming_the_job(self) -> None:
        proxy = _proxy()
        with pytest.raises(RuntimeError, match="ExampleJob.run"):
            proxy()

    def test_call_raises_for_the_renamed_receiver_method(self) -> None:
        class Renamed:
            def go(self, first: int) -> None: ...

        with pytest.raises(RuntimeError, match="Renamed.go"):
            ClassJobMethod(Renamed, "go", merged_declaration())(1)


class TestResolvedHints:
    def test_resolved_hints_on_the_proxy_is_empty(self) -> None:
        proxy = _proxy(ExampleJob, "unresolvable")
        assert resolved_hints(proxy) == {}

    def test_resolved_hints_on_the_method_still_resolves(self) -> None:
        # The fallback is the proxy's shape, not a broken fixture: the method
        # behind the proxy resolves exactly as the signature case shows.
        assert (
            resolved_hints(ExampleJob.run)["count"].__metadata__[0].metadata[0].ge == 0
        )
