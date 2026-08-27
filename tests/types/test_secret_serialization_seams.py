"""A ``Secret`` must survive the framework's own serialization seams.

``Secret`` masks on the way out to JSON. The framework *also* passes config
models around internally by dumping and rebuilding them, and those dumps are
not output — they are how one job hands its configuration to another:

- ``Invoke`` builds a child job's kwargs from ``config.model_dump()``
- ``Invoke`` merges a gate-resolved model back the same way
- ``RunContext.with_plugin_config`` rebuilds a plugin model from its own dump
- the argument validator merges ``Field()``-validated params back

An unconditional serializer masks all four, so a live credential is replaced by
``•••`` *between two of our own jobs*, with no error and no warning — the child
then authenticates with the mask string. That shipped once. These tests exist so
it cannot ship again: each one asserts the real value survives one seam, and the
last two assert the JSON path is still closed.

The gap this closes: a new type was given a serializer without anyone auditing
the type's existing consumers (``grep -rn model_dump src/`` had four waiting).
When a serializer changes, this module is the audit.
"""

from __future__ import annotations

import pytest
from pydantic import BaseModel

from functualize._types.redaction import MASK, Secret

REAL = "hunter2-real-credential-value"


class Carrier(BaseModel):
    """The shape every seam below round-trips."""

    token: Secret[str]
    plain: str = "visible"


# ===========================================================================
# The dump/rebuild contract the seams rely on
# ===========================================================================


class TestPythonModeRoundTrip:
    def test_python_dump_keeps_the_secret_object(self):
        """``model_dump()`` must not flatten a Secret into its mask."""
        dumped = Carrier(token=REAL).model_dump()
        assert isinstance(dumped["token"], Secret), (
            f"model_dump() replaced the Secret with {dumped['token']!r} — "
            "every internal config-passing seam now moves the mask, not the value"
        )
        assert dumped["token"].get_secret_value() == REAL

    def test_rebuilding_from_a_python_dump_preserves_the_value(self):
        """The exact shape ``with_plugin_config`` uses."""
        original = Carrier(token=REAL)
        rebuilt = Carrier(**{**original.model_dump(), "plain": "changed"})
        assert rebuilt.token.get_secret_value() == REAL
        assert rebuilt.plain == "changed"

    def test_a_python_dump_still_renders_masked(self):
        """Keeping the object is safe *because* the object masks itself."""
        dumped = Carrier(token=REAL).model_dump()
        assert MASK in f"{dumped['token']}"
        assert REAL not in f"{dumped}"


# ===========================================================================
# The JSON path stays closed — this is what the serializer is for
# ===========================================================================


class TestJsonModeStillMasks:
    def test_model_dump_json_masks(self):
        assert REAL not in Carrier(token=REAL).model_dump_json()
        assert MASK in Carrier(token=REAL).model_dump_json()

    def test_model_dump_json_mode_masks(self):
        dumped = Carrier(token=REAL).model_dump(mode="json")
        assert dumped["token"] == MASK

    def test_the_plain_field_is_untouched_in_both_modes(self):
        """Without this the fix above could just be 'stop serializing'."""
        model = Carrier(token=REAL, plain="visible")
        assert model.model_dump()["plain"] == "visible"
        assert "visible" in model.model_dump_json()


# ===========================================================================
# End to end: one job hands a credential to another
# ===========================================================================

INVOKE_JOBS = '''
from pydantic import BaseModel, Field

from functualize.job import RunContext
from functualize.job.decorators import job
from functualize.types import Secret


class TokenConfig(BaseModel):
    token: Secret[str] = Field(default=Secret(""))


@job(extra_description="Receives a credential from its caller")
def child(config: TokenConfig, rc: RunContext) -> str:
    rc.log("child-sees:" + config.token.get_secret_value())
    return "ok"


@job(extra_description="Hands its own config to the child")
def parent(config: TokenConfig, rc: RunContext) -> str:
    rc.log("parent-has:" + config.token.get_secret_value())
    rc.invoke("child", config=config)
    return "ok"
'''

PYPROJECT = """\
[project]
name = "secret-seams-project"
version = "0.1.0"
"""


@pytest.fixture()
def invoke_project(project_tree):
    return project_tree(pyproject=PYPROJECT, jobs={"job_chain.py": INVOKE_JOBS})


def test_invoke_passes_the_real_credential_to_the_child(cli_run, invoke_project):
    """The seam that broke: ``rc.invoke(child, config=cfg)``.

    Asserted on the *logged* value rather than on absence, because a leak and a
    corruption look identical if you only check that ``REAL`` is missing — the
    corrupted child logs the mask and passes such a test.
    """
    result = cli_run(["parent"], cwd=invoke_project, env={"PARENT_TOKEN": REAL})

    assert result.exit_code == 0, result.stderr
    combined = result.stdout + result.stderr
    assert f"child-sees:{REAL}" in combined, (
        "the child job did not receive the caller's credential — "
        f"model_dump() corrupted it in transit:\n{combined}"
    )
    assert f"child-sees:{MASK}" not in combined
