"""Unit tests for the composition lab.

The lab's *behaviour* is verified by `examples/docs/scenarios/n-composition.toml`,
which runs the CLI — that is the right place for claims about freshness, exit
codes and the guard pipeline, because none of them are observable from an
import.

What is worth pinning here is narrower and complementary: that each job still
**declares** the combination the guide says it does. A scenario that runs
`func lab publish` and sees `PUBLISHED` passes whether or not `publish` still
declares a status guard — it would simply have run for a different reason. So
the declarations are asserted directly, and the runtime behaviour is asserted by
the scenario. Neither alone is enough.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

_ROOT = Path(__file__).parent.parent


def _load(name: str, relpath: str):
    spec = importlib.util.spec_from_file_location(name, _ROOT / relpath)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


pipeline = _load("composition_lab_pipeline", "jobs/pipeline.py")


def _decl(name: str):
    return getattr(pipeline, name).__functualize_job__


class TestTheCombinationsAreStillDeclared:
    """Each row of the guide's job table, asserted against the declaration."""

    def test_parse_declares_sources_and_generates(self) -> None:
        cache = _decl("parse").cache
        assert cache is not None
        assert cache.sources == ("inputs/*.yaml",)
        assert cache.generates == ("build/parsed.json",)

    def test_report_declares_a_fingerprint_over_the_upstreams_output(self) -> None:
        cache = _decl("report").cache
        assert cache is not None
        assert cache.sources == ("build/parsed.json",)

    def test_publish_declares_deps_status_and_a_fingerprint_together(self) -> None:
        """The R10a intersection. All three must be present for the guide's
        claim ("status cannot mask changed sources") to be about anything."""
        decl = _decl("publish")
        assert decl.deps is not None and decl.deps.refs == ("lab.report",)
        assert decl.guards is not None and decl.guards.status
        assert decl.cache is not None and decl.cache.sources == ("build/report.md",)

    def test_gated_declares_a_precondition(self) -> None:
        guards = _decl("gated").guards
        assert guards is not None and len(guards.preconditions) == 1

    def test_verify_declares_sources_that_cannot_resolve(self) -> None:
        """The §5.3 distinction: declared, and matching nothing."""
        cache = _decl("verify").cache
        assert cache is not None and cache.sources == ("absent/*.json",)
        assert not (_ROOT / "absent").exists()

    def test_counter_declares_nothing(self) -> None:
        """The other half of §5.3: declaring no sources is not a refusal."""
        assert _decl("counter").cache is None

    def test_probe_declares_a_retry(self) -> None:
        exec_decl = _decl("probe").exec
        assert exec_decl is not None and exec_decl.retry is not None
        assert exec_decl.retry.attempts == 2


class TestTheSignatureShapesTheGuideExplains:
    """§2 rule 4 — a config class, a FromJob param and a return type, told
    apart by position."""

    def test_report_has_all_three_annotation_kinds(self) -> None:
        from functualize.app.utils import detect_config_class

        # A *parameter* annotated with a BaseModel subclass is the config class.
        assert detect_config_class(pipeline.report) is pipeline.ReportConfig

    def test_a_pydantic_return_type_is_not_the_config_class(self) -> None:
        from functualize.app.utils import detect_config_class

        # `parse` returns Parsed and takes no config parameter.
        assert detect_config_class(pipeline.parse) is None

    def test_a_from_job_parameter_is_not_the_config_class(self) -> None:
        from functualize.app.utils import detect_config_class

        # `emit` takes Annotated[Parsed, FromJob(...)] and no config.
        assert detect_config_class(pipeline.emit) is None

    def test_from_job_declares_the_edge(self) -> None:
        from functualize._types.from_job import from_job_names

        assert from_job_names(pipeline.report) == ("lab.parse",)
        assert from_job_names(pipeline.emit) == ("lab.parse",)


class TestTheInputsTheGuideQuotes:
    """The guide prints `PARSED n=2 total=8`. That is arithmetic over these."""

    def test_two_inputs_totalling_eight(self) -> None:
        sizes = []
        for path in sorted((_ROOT / "inputs").glob("*.yaml")):
            for line in path.read_text().splitlines():
                if line.startswith("size:"):
                    sizes.append(int(line.split(":", 1)[1]))
        assert len(sizes) == 2
        assert sum(sizes) == 8


# ── The release module ───────────────────────────────────────────────────
#
# `jobs/release.py` imports its sibling as a FLAT module (`from pipeline
# import ...`), because that is the only form that works on both surfaces: the
# discovery loader puts the module's own directory on `sys.path`, not the
# project root. `from jobs.pipeline import ...` resolves under `main.py` — the
# script's directory is `sys.path[0]` — and fails under `func`. Registering the
# already-loaded module under its flat name is what lets this file load it.

sys.modules["pipeline"] = pipeline
release_mod = _load("composition_lab_release", "jobs/release.py")


class TestTheReleaseModuleDeclaresItsShape:
    """The three declarations single jobs could not show."""

    def test_bundle_declares_a_glob_as_its_generates(self) -> None:
        """`generates` entries are patterns, exactly as `sources` entries are.
        Tested as literal paths a glob never exists, so the job reports
        "output missing" forever and rebuilds on every run."""
        cache = release_mod.bundle.__functualize_job__.cache
        assert cache is not None
        assert cache.sources == ("build/report.md",)
        assert cache.generates == ("dist/*.tar.gz",)
        assert any(ch in cache.generates[0] for ch in "*?[")

    def test_the_group_option_is_declared_once_on_the_group(self) -> None:
        assert release_mod.LabOptions.__group_path__ == "lab"
        assert "strict" in release_mod.LabOptions.model_fields

    def test_signoff_crosses_a_group_boundary_and_guards_nothing(self) -> None:
        """Its dependency already produces the archive, so a guard checking for
        one could never fire. The absence is the claim."""
        decl = release_mod.signoff.__functualize_job__
        assert decl.group == "check"
        assert decl.deps is not None and decl.deps.refs == ("lab.bundle",)
        assert decl.guards is None

    def test_the_workflow_pauses_at_a_gate_before_sign_off(self) -> None:
        declaration = release_mod.release.__functualize_workflow__
        names = [node.name for node in declaration.nodes]
        assert names == [
            "lab.parse",
            "lab.report",
            "lab.publish",
            "lab.bundle",
            "approval-gate",
            "check.signoff",
        ]

        gate = declaration.nodes[names.index("approval-gate")]
        assert gate.awaits is release_mod.Approval
        # The edge the gate exists for: nothing is signed off before the pause.
        assert ("approval-gate", "check.signoff") in [
            (e.source, e.target) for e in declaration.edges
        ]
