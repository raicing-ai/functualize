"""A control input cannot arrive as a job argument (spec §1.6a, AC-17a).

The channel this closes is an *accidental* one, and it was accidental in the
literal sense: nobody designed it. `FunctualizeApp.execute` used to take

    execute(job_name, *, scope_id=None, group_option_values=None, **kwargs)

and a wire surface handed it a caller's payload with `**body`. So a JSON body
of `{"scope_id": "abc"}` did not become an argument named `scope_id` — it
became the **scope the run joined**, chosen by whoever wrote the request. The
same shape gave `group_option_values` away too.

Wave 3 stopped every door from splatting (`rg -n 'app\\.execute\\([a-z_]*name,
\\*\\*' src/ plugins/` is 0). This task makes it *unrepresentable* rather than
merely unpractised: `execute` takes a `RunRequest` and nothing else, and
`request_for(**kwargs)` puts every keyword in `kwargs`, where a job argument
belongs. A caller who genuinely means a control input constructs the request
and says so in the field's own name.

These tests are about the **shape of the seam**, so they assert on the request
rather than on a live HTTP server: the property is that no spelling of a
keyword can cross from the payload half to the control half.
"""

from __future__ import annotations

import pytest

from functualize.app.core import request_for
from functualize.types import RunRequest

_CONTROL_SPELLINGS = [
    "scope_id",
    "workflow_scope_id",
    "group_option_values",
    "parent_scope",
    "surface",
    "prompt_gates",
    "output_format",
    "force",
    "invoke_depth",
    "run_dependencies",
    "force_fresh",
    "cwd",
    "job_directory",
]


class TestAPayloadKeywordStaysAPayloadKeyword:
    @pytest.mark.parametrize("name", _CONTROL_SPELLINGS)
    def test_it_lands_in_kwargs_and_nowhere_else(self, name: str) -> None:
        """Every field name on the request, tried as a job argument."""
        request = request_for("greet", **{name: "from-the-wire"})

        assert request.kwargs == {name: "from-the-wire"}, (
            f"{name!r} did not reach the job as an argument"
        )

    def test_scope_id_does_not_address_a_scope(self) -> None:
        """The concrete case the audit reproduced: an HTTP body naming a scope."""
        body = {"scope_id": "attacker-chosen", "name": "ada"}

        request = request_for("greet", **body)

        assert request.kwargs == body
        assert request.workflow_scope_id is None, (
            "a payload key addressed a workflow scope"
        )
        assert request.parent_scope is None

    def test_group_option_values_does_not_become_the_group_layer(self) -> None:
        body = {"group_option_values": {"env": "prod"}}

        request = request_for("deploy", **body)

        assert request.kwargs == body
        assert request.group_option_values is None

    def test_surface_in_a_payload_does_not_relabel_the_door(self) -> None:
        """A door's own identity is not something a caller may choose."""
        request = request_for("greet", surface="mcp.tool")

        assert request.surface == "app.execute"
        assert request.kwargs == {"surface": "mcp.tool"}


class TestTheFacadeTakesARequestAndNothingElse:
    def test_execute_has_no_control_keywords_left(self) -> None:
        """The signature is the enforcement; this reads it rather than trusting it.

        A gate spelled as `rg 'def execute\\(self, job_name.*scope_id'` cannot
        see this: ruff wraps the signature across lines, so the pattern matches
        nothing whether or not the parameters exist. Introspection cannot be
        fooled that way.
        """
        import inspect

        from functualize.app.core import FunctualizeApp

        parameters = inspect.signature(FunctualizeApp.execute).parameters

        assert "scope_id" not in parameters
        assert "group_option_values" not in parameters
        assert not any(
            p.kind is inspect.Parameter.VAR_KEYWORD for p in parameters.values()
        ), "**kwargs on the facade is the channel itself"

    def test_a_request_is_the_only_accepted_argument(self) -> None:
        import inspect

        from functualize.app.core import FunctualizeApp

        positional = [
            name
            for name, p in inspect.signature(FunctualizeApp.execute).parameters.items()
            if name != "self"
            and p.kind
            in (
                inspect.Parameter.POSITIONAL_ONLY,
                inspect.Parameter.POSITIONAL_OR_KEYWORD,
            )
        ]

        assert positional == ["request"], positional

    def test_request_for_still_refuses_to_be_a_control_channel(self) -> None:
        """`request_for` is the convenience path, and convenience is where a
        control channel would grow back."""
        import inspect

        parameters = inspect.signature(request_for).parameters

        assert "scope_id" not in parameters
        assert "group_option_values" not in parameters


class TestConstructingTheRequestIsHowYouMeanIt:
    def test_a_caller_who_means_a_scope_names_the_field(self) -> None:
        """Not a loophole — the point. The distinction is now visible in the
        source of whoever wrote it, instead of hiding in a dict's key."""
        request = RunRequest(
            job_name="greet",
            surface="app.execute",
            kwargs={"name": "ada"},
            workflow_scope_id="deliberate",
        )

        assert request.workflow_scope_id == "deliberate"
        assert request.kwargs == {"name": "ada"}
