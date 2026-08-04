"""Unit tests for the @job decorator and JobDeclaration aggregate (S1/T3).

Covers identity preservation, bare vs full-kwarg forms, stacking with existing
job decorators, and JobDeclaration serialization round-trip.
"""

from __future__ import annotations

import json

import pytest

from functualize.job import (
    Deps,
    Exec,
    Fingerprint,
    Guards,
    JobDeclaration,
    Precondition,
    Retry,
    call,
    job,
    suppress_live,
    surface_hint,
)


class TestBareAndParameterizedForms:
    def test_bare_job_attaches_default_declaration(self) -> None:
        @job
        def build() -> None: ...

        decl = build.__functualize_job__
        assert isinstance(decl, JobDeclaration)
        assert decl.group is None

    def test_empty_parens_form(self) -> None:
        @job()
        def build() -> None: ...

        assert isinstance(build.__functualize_job__, JobDeclaration)

    def test_full_kwargs_form(self) -> None:
        @job(
            group="infra",
            extra_description="Ships it",
            category="deployment",
            examples=["deploy --env prod"],
            tags=["deploy"],
            visibility="external",
            config_section="deploy",
            deps=Deps("lint", "test", policy="fail-fast"),
            cache=Fingerprint(sources=["src/**/*.py"], generates=["dist/*.whl"]),
            guards=Guards(preconditions=["docker --version"]),
            exec=Exec(retry=Retry(attempts=2)),
            matrix={"env": ["dev", "prod"]},
        )
        def deploy() -> None: ...

        decl = deploy.__functualize_job__
        assert decl.group == "infra"
        assert decl.deps is not None and decl.deps.refs == ("lint", "test")
        assert decl.cache is not None and decl.cache.generates == ("dist/*.whl",)
        assert decl.exec is not None
        assert decl.matrix == {"env": ["dev", "prod"]}


class TestIdentity:
    def test_bare_is_identity_preserving(self) -> None:
        def build() -> None: ...

        assert job(build) is build

    def test_parameterized_is_identity_preserving(self) -> None:
        def deploy() -> None: ...

        decorated = job(group="infra")(deploy)
        assert decorated is deploy

    def test_call_metadata_preserved(self) -> None:
        @job(group="infra")
        def deploy() -> None:
            """Deploy docstring."""

        assert deploy.__name__ == "deploy"
        assert deploy.__doc__ == "Deploy docstring."


class TestStacking:
    def test_stacks_with_surface_hint_and_suppress_live(self) -> None:
        @job(group="infra", deps=Deps("lint"))
        @surface_hint("stdout")
        @suppress_live("flow-viz")
        def deploy() -> None: ...

        assert deploy.__functualize_job__.group == "infra"
        assert deploy.__functualize_surface_hint__ == "stdout"
        assert deploy.__functualize_suppress_live__ == ("flow-viz",)
        # identity preserved through the whole stack
        assert deploy.__name__ == "deploy"

    def test_order_independent(self) -> None:
        @surface_hint("stdout")
        @job(group="infra")
        def deploy() -> None: ...

        assert deploy.__functualize_job__.group == "infra"
        assert deploy.__functualize_surface_hint__ == "stdout"


class TestValidationAtDecorationTime:
    def test_invalid_visibility_raises(self) -> None:
        with pytest.raises(ValueError, match="visibility"):

            @job(visibility="secret")  # type: ignore[arg-type]
            def deploy() -> None: ...

    def test_invalid_value_object_type_raises(self) -> None:
        with pytest.raises(ValueError, match="deps must be a Deps"):

            @job(deps="lint")  # type: ignore[arg-type]
            def deploy() -> None: ...

    def test_invalid_matrix_raises(self) -> None:
        with pytest.raises(ValueError, match="matrix"):

            @job(matrix={"env": "dev"})  # type: ignore[dict-item]
            def deploy() -> None: ...

    def test_name_and_aliases_are_not_accepted(self) -> None:
        """Both were removed: each gave one job a second spelling.

        A job's addressable name derives from `__name__` alone, so the cold
        and warm paths cannot disagree about it. Asserting the rejection keeps
        a re-add from passing silently.
        """
        for kwargs in ({"name": "deploy-app"}, {"aliases": ["d"]}):
            with pytest.raises(TypeError, match="unexpected keyword argument"):

                @job(**kwargs)  # type: ignore[call-overload]
                def deploy() -> None: ...


class TestSerializationRoundTrip:
    def test_full_string_declaration_dict_stable(self) -> None:
        decl = JobDeclaration(
            group="infra",
            extra_description="x",
            category="deployment",
            examples=("e",),
            tags=("t",),
            visibility="external",
            config_section="deploy",
            deps=Deps("lint", call("build", target="wheel"), policy="keep-going"),
            cache=Fingerprint(sources=["a"], generates=["b"], method="checksum"),
            guards=Guards(
                preconditions=[Precondition("docker --version", msg="install")],
                status=["test -f x"],
            ),
            exec=Exec(retry=Retry(attempts=2, on_exit_codes=(1,))),
            matrix={"env": ["dev", "prod"]},
        )
        as_dict = decl.to_dict()
        # JSON-serializable
        json.dumps(as_dict)
        # from_dict reconstructs a declaration whose dict form is identical
        rebuilt = JobDeclaration.from_dict(as_dict)
        assert rebuilt.to_dict() == as_dict

    def test_bare_declaration_round_trip(self) -> None:
        decl = JobDeclaration()
        assert JobDeclaration.from_dict(decl.to_dict()) == decl

    def test_to_dict_is_json_serializable_for_bare(self) -> None:
        json.dumps(JobDeclaration().to_dict())
