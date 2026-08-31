"""The excluded-capability list must equal what the engine actually injects.

`test_di_exclusion_properties.py` builds its stub types *from*
`_EXCLUDED_PARAM_TYPE_NAMES`, so it verifies "everything in the list is
excluded" and can never notice a capability the list forgot. That is precisely
how `Stdout` and `Shell` came to be published as required string arguments on
every descriptor-driven surface while the CLI filtered them correctly: the CLI
tests the live annotation on a separate path, so the only surface that leaked
was the one with no test comparing it to another.

These tests bind the list to two independent sources — the engine's injection
dispatch, and the CLI's own parameter rendering — so a new capability cannot be
added without either updating the list or failing here.
"""

from __future__ import annotations

import importlib
import re
import sys
from pathlib import Path

import pytest

from functualize._discovery.providers import extract_parameters_from_signature
from functualize._types.capabilities import INJECTED_CAPABILITY_TYPE_NAMES

EXECUTOR = (
    Path(__file__).resolve().parents[2]
    / "src"
    / "functualize"
    / "_engine"
    / "executor.py"
)


def _engine_injected_names() -> set[str]:
    """Type names the executor's capability factory dispatches on.

    Read from source rather than kept by hand: a second hand-kept list would
    reproduce the bug this file exists to prevent. If the dispatch is
    restructured this test fails, which is when a human should look at the
    exclusion list anyway.
    """
    found = set(re.findall(r"(?:if|elif) type_ is (\w+):", EXECUTOR.read_text()))
    # Injected on separate paths: RunContext *is* the context rather than
    # something built from it, and the config view arrives through the app's
    # configured view type rather than a literal identity branch.
    return found | {"RunContext", "JobConfigView"}


def test_exclusion_list_matches_engine_injection():
    """Every injected capability is excluded, and nothing else is."""
    injected = _engine_injected_names()
    assert injected == INJECTED_CAPABILITY_TYPE_NAMES, (
        "capability exclusion drift — a parameter the engine fills would be "
        "published as a caller-supplied argument (or a real argument would be "
        "deleted).\n"
        f"  injected but not excluded: {sorted(injected - INJECTED_CAPABILITY_TYPE_NAMES)}\n"
        f"  excluded but not injected: {sorted(INJECTED_CAPABILITY_TYPE_NAMES - injected)}"
    )


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


@pytest.mark.parametrize("capability", sorted(INJECTED_CAPABILITY_TYPE_NAMES))
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
    assert "Stdin" not in INJECTED_CAPABILITY_TYPE_NAMES

    from typing import Annotated

    from functualize.job import Stdin

    def transform(data: Annotated[str, Stdin(flag="--data")]) -> None:
        """Reads stdin when no flag is given."""

    names = [f.name for f in extract_parameters_from_signature(transform)]
    assert names == ["data"]
