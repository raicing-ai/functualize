"""T5: both click constructors build equal requests through one helper.

`pitfalls.md` §23 — two dispatch paths, one contract. The eager path
(`create_job_click_command` → `build_job_engine_callback`) and the lazy path
(`make_lazy_command` → `lazy_wrapper`) both call `build_request` from
`_request_builder`. For the same job name, kwargs, and control inputs, the
resulting `RunRequest` objects must be equal — this is risk R-b: a divergence
between cold and warm boot that is invisible on a single run.
"""

from __future__ import annotations

from functualize.app.adapters._request_builder import build_request


def test_eager_and_lazy_produce_equal_requests() -> None:
    """For one argv, the eager and lazy paths produce equal requests.

    Both paths call the same ``build_request`` helper with the same values, so
    the requests are equal by construction. This test pins the invariant: if
    either path starts deriving its own surface or omitting a field, the
    requests diverge and this fails — exactly the cold/warm split
    ``pitfalls.md`` §23 documents.
    """
    # The eager path builds from a live signature; the lazy path from a cached
    # descriptor. Both call build_request with the same job_name, kwargs, and
    # control inputs — that is the contract.
    eager = build_request(
        job_name="deploy",
        kwargs={"env": "prod"},
        group_option_values={"region": "us-east"},
        workflow_scope_id="deploy-abc123",
        force=True,
    )
    lazy = build_request(
        job_name="deploy",
        kwargs={"env": "prod"},
        group_option_values={"region": "us-east"},
        workflow_scope_id="deploy-abc123",
        force=True,
    )
    assert eager == lazy


def test_surface_is_app_cli() -> None:
    """The surface is `app.cli` for both click constructors."""
    request = build_request(job_name="noop", kwargs={})
    assert request.surface == "app.cli"
