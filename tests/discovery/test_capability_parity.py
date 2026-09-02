"""Capability parameters must not survive extraction onto any surface.

`test_di_exclusion_properties.py` builds its stub types *from*
`_EXCLUDED_PARAM_TYPE_NAMES`, so it verifies "everything in the list is
excluded" and can never notice a capability the list forgot. That is precisely
how `Stdout` and `Shell` came to be published as required string arguments on
every descriptor-driven surface while the CLI filtered them correctly: the CLI
tests the live annotation on a separate path, so the only surface that leaked
was the one with no test comparing it to another.

`_engine/capabilities/registry.py` now asserts at import that the declared
`CapabilitySpec` names equal `INJECTED_PARAM_TYPE_NAMES`, which owns the
"list agrees with the engine" half of this. What it cannot cover is *behaviour*:
that extraction actually drops those parameters, on the live public types and
under deferred annotations. That is what remains here.
"""

from __future__ import annotations

import importlib
import sys

import pytest

from functualize._discovery.providers import extract_parameters_from_signature
from functualize._primitives.capability_names import INJECTED_PARAM_TYPE_NAMES


def test_no_capability_survives_parameter_extraction():
    """A job declaring every capability publishes only its real arguments.

    Written against the *live* public types rather than stubs named after the
    list, so a capability missing from the list shows up here as a leaked
    parameter.
    """
    # Runtime imports on purpose: annotation *resolution* is the subject under
    # test, so a TYPE_CHECKING block would remove the very thing being checked.
    from functualize.job import (  # noqa: F401, TC001
        TTY,
        Invoke,
        JobConfigView,
        JobContext,
        Live,
        Log,
        Perf,
        Prompt,
        RunContext,
        Shell,
        Sources,
        State,
        Stdout,
    )

    def job_with_everything(
        rc: RunContext,
        log: Log,
        out: Stdout,
        sh: Shell,
        inv: Invoke,
        ask: Prompt,
        perf: Perf,
        st: State,
        srcs: Sources,
        tty: TTY,
        live: Live,
        ctx: JobContext,
        view: JobConfigView,
        real_arg: int = 1,
        another: str = "x",
    ) -> None:
        """Every capability, plus two real arguments."""

    names = [f.name for f in extract_parameters_from_signature(job_with_everything)]
    assert names == ["real_arg", "another"], (
        f"capabilities leaked into published parameters: "
        f"{[n for n in names if n not in ('real_arg', 'another')]}"
    )


@pytest.mark.parametrize("capability", sorted(INJECTED_PARAM_TYPE_NAMES))
def test_each_capability_is_excluded_under_pep_563(capability, tmp_path):
    """PEP 563 turns every annotation into a string — exclusion must survive it.

    Written as a real importable module rather than an ``exec``: ``exec``
    inherits ``from __future__ import annotations`` from *this* file, which
    double-quotes the annotation into something no user file produces. The
    faithful reproduction is a module that imports the capability and defers
    its annotations, which is what half the ecosystem does.
    """
    module_name = f"pep563_probe_{capability.lower()}"
    (tmp_path / f"{module_name}.py").write_text(
        "from __future__ import annotations\n"
        f"from functualize.job import {capability}\n"
        "\n"
        f"def probe(cap: {capability}, real: int = 1) -> None:\n"
        '    """Deferred annotations."""\n',
        encoding="utf-8",
    )

    sys.path.insert(0, str(tmp_path))
    try:
        module = importlib.import_module(module_name)
        names = [f.name for f in extract_parameters_from_signature(module.probe)]
    finally:
        sys.path.remove(str(tmp_path))
        sys.modules.pop(module_name, None)

    assert names == ["real"], f"{capability} leaked under deferred annotations"


def test_stdin_is_not_treated_as_a_capability():
    """`Stdin` is a marker on a real parameter — excluding it deletes a flag."""
    assert "Stdin" not in INJECTED_PARAM_TYPE_NAMES

    from typing import Annotated

    from functualize.job import Stdin

    def transform(data: Annotated[str, Stdin(flag="--data")]) -> None:
        """Reads stdin when no flag is given."""

    names = [f.name for f in extract_parameters_from_signature(transform)]
    assert names == ["data"]
