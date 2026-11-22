"""Discovery puts a contract on every parameter; boot applies availability (B-2).

The declaration table is written out as one project, one module per row, and
the real ``func`` boots it in a subprocess: once cold (no cache), once warm
(from the cache the cold boot wrote). A probe plugin registers the matrix's
providers and dumps, per job, the contracts discovery put on the descriptors
and the contracts boot admitted. Both annotation modes are covered.

What must hold on every path (B-7, B-9, DC-1 = B):

- each parameter's declared contract is its row's ``declared_verdict``, and
  the admitted one its ``expected_verdict``;
- cold and warm agree, and the warm boot really was warm;
- every refused parameter is reported as ``UnsupportedParameter`` naming the
  file and the job, and its job stays registered.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import textwrap
from pathlib import Path
from typing import Any

import pytest

from tests._support.parameter_matrix import ROWS, module_source

#: A type registered only under a qualifier. ``DIRegistry.has(QOnly)`` answers
#: true for it; resolving an unqualified ``QOnly`` is ambiguous, so the exact
#: predicate must refuse the unqualified parameter (F-21).
PROVLIB = """
class ProvWidget:
    def __init__(self, v: str = "") -> None:
        self.v = v


class QOnly:
    pass
"""

PLUGIN = """
import json

from functualize._types.descriptors import _contract_to_dict


class ContractProbe:
    name = "contract-probe"
    version = "1.0.0"
    description = "Dump discovery and boot contracts (test only)."

    def __call__(self, app):
        from provlib import ProvWidget, QOnly

        self._app = app
        app.di.provide(ProvWidget, ProvWidget("by-type"))
        app.di.provide(ProvWidget, ProvWidget("by-w"), qualifier="w")
        app.di.provide(QOnly, QOnly(), qualifier="x")
        app.extensions.register_plugin_command("dump", self._dump, namespace="contracts")

    def _dump(self, out: str = "") -> None:
        app = self._app
        admitted = getattr(app, "_admitted_contracts", {})
        jobs = {}
        for descriptor in app.job_registry.get_descriptors():
            entry = app.job_registry._registered_jobs.get(descriptor.name)
            function = getattr(entry, "function", None)
            jobs[descriptor.name] = {
                "file": descriptor.source_file,
                "registered": entry is not None,
                "lazy": bool(getattr(function, "__functualize_lazy__", False)),
                "declared": {
                    f.name: _contract_to_dict(f.contract)
                    for f in descriptor.parameters
                    if f.contract is not None
                },
                "admitted": {
                    name: contract.verdict.name
                    for name, contract in admitted.get(descriptor.name, {}).items()
                },
            }
        failures = [f.as_dict() for f in getattr(app, "_unsatisfiable_jobs", [])]
        with open(out, "w", encoding="utf-8") as handle:
            json.dump({"jobs": jobs, "failures": failures}, handle, default=repr)


plugin = ContractProbe()
"""

QONLY_JOB = """
from functualize.job import job
from provlib import QOnly


@job
def qonly(p: QOnly) -> str:
    return "ran"
"""

#: Capability and ``FromJob`` parameters: `extract_parameters_from_signature`
#: emits no field for them, so they carry no descriptor contract.
NOT_EMITTED = frozenset(
    row["id"]
    for row in ROWS
    if row["axis"] == "injected" and row["expected_verdict"] == "INJECTED"
)

SIGNATURE_ROWS = [
    row
    for row in ROWS
    if row["axis"] != "config" and not row["declaration"].startswith("GROUP:")
]


def _write_project(root: Path, *, future: bool) -> Path:
    jobs = root / "jobs"
    jobs.mkdir(parents=True)
    (root / "pyproject.toml").write_text(
        '[project]\nname = "pc"\nversion = "0"\n\n'
        '[tool.functualize]\njobs_directories = ["jobs"]\n',
        encoding="utf-8",
    )
    for row in ROWS:
        source = module_source(row, future_annotations=future)
        (jobs / f"{row['id'].lower()}.py").write_text(source, encoding="utf-8")
    (jobs / "qonly.py").write_text(QONLY_JOB, encoding="utf-8")
    plugins = root / ".functualize" / "plugins"
    plugins.mkdir(parents=True)
    (plugins / "contract_probe.py").write_text(PLUGIN, encoding="utf-8")
    (root / "pylib").mkdir()
    (root / "pylib" / "provlib.py").write_text(PROVLIB, encoding="utf-8")
    return root


def _dump(project: Path, label: str) -> dict[str, Any]:
    home = project / ".home"
    env = {
        **os.environ,
        "HOME": str(home),
        "XDG_CONFIG_HOME": str(home / "config"),
        "XDG_CACHE_HOME": str(home / "cache"),
        "XDG_STATE_HOME": str(home / "state"),
        "XDG_DATA_HOME": str(home / "data"),
        "PYTHONPATH": str(project / "pylib"),
    }
    out = project / f"{label}.json"
    done = subprocess.run(  # noqa: S603
        [sys.executable, "-m", "functualize", "contracts", "dump", "--out", str(out)],
        cwd=project,
        env=env,
        capture_output=True,
        text=True,
        timeout=300,
        check=False,
    )
    assert done.returncode == 0, done.stdout + done.stderr
    data: dict[str, Any] = json.loads(out.read_text(encoding="utf-8"))
    data["stderr"] = done.stderr
    return data


@pytest.fixture(scope="module", params=[False, True], ids=["eager", "pep563"])
def boots(
    request: pytest.FixtureRequest, tmp_path_factory: pytest.TempPathFactory
) -> dict[str, Any]:
    future: bool = request.param
    project = _write_project(tmp_path_factory.mktemp("contracts"), future=future)
    cold = _dump(project, "cold")
    warm = _dump(project, "warm")
    return {"future": future, "cold": cold, "warm": warm, "project": project}


def _job(dump: dict[str, Any], row: dict[str, Any]) -> dict[str, Any] | None:
    """The row's job: defined in its own file, named by the row's path tail."""
    tail = row["path"][-1].replace("_", "-")
    for name, job in dump["jobs"].items():
        stem = Path(job["file"]).stem
        if stem == row["id"].lower() and name.split(".")[-1] == tail:
            return job
    return None


def _row_job(boots: dict[str, Any], row: dict[str, Any], phase: str) -> dict[str, Any]:
    job = _job(boots[phase], row)
    if row["id"] == "E142" and not boots["future"]:
        assert job is None  # FromJob[...] raises at import: no job, no contract
        pytest.skip("E142 is refused at import without PEP 563")
    assert job is not None, f"{row['id']} not discovered on the {phase} boot"
    return job


@pytest.mark.parametrize("phase", ["cold", "warm"])
@pytest.mark.parametrize("row", SIGNATURE_ROWS, ids=lambda row: row["id"])
def test_every_row_gets_its_verdicts_on_both_boots(
    boots: dict[str, Any], row: dict[str, Any], phase: str
) -> None:
    job = _row_job(boots, row, phase)
    if row["id"] in NOT_EMITTED:
        # Engine-filled, and kept off `parameters` as before: no surface
        # spells it, so no descriptor field (and no contract) exists for it.
        assert row["probe"] not in job["declared"]
        assert row["expected_verdict"] == "INJECTED"
        return
    declared = job["declared"][row["probe"]]
    assert declared["verdict"] == row["declared_verdict"].lower(), declared
    assert job["admitted"][row["probe"]] == row["expected_verdict"]
    assert job["registered"]  # DC-1 = B: a refused parameter keeps its job


def test_cold_and_warm_carry_the_same_contracts(boots: dict[str, Any]) -> None:
    cold, warm = boots["cold"]["jobs"], boots["warm"]["jobs"]
    assert cold.keys() == warm.keys()
    for name in cold:
        assert cold[name]["declared"] == warm[name]["declared"], name
        assert cold[name]["admitted"] == warm[name]["admitted"], name


def test_the_warm_boot_was_warm(boots: dict[str, Any]) -> None:
    assert not any(job["lazy"] for job in boots["cold"]["jobs"].values())
    assert all(job["lazy"] for job in boots["warm"]["jobs"].values())


@pytest.mark.parametrize("phase", ["cold", "warm"])
def test_every_refusal_is_reported_naming_file_and_job(
    boots: dict[str, Any], phase: str
) -> None:
    dump = boots[phase]
    reported = [
        failure
        for failure in dump["failures"]
        if failure["error_type"] == "UnsupportedParameter"
    ]
    refused = {
        name: job
        for name, job in dump["jobs"].items()
        if "REJECTED_DISCOVERY" in job["admitted"].values()
    }
    assert refused
    for name, job in refused.items():
        hits = [
            f
            for f in reported
            if f"job {name!r}" in f["message"] and f["path"] == job["file"]
        ]
        assert hits, f"{name} refused but not reported"
        assert job["file"] in hits[0]["message"]
        assert hits[0]["message"] in dump["stderr"]  # the boot warning (B-9)


def test_a_qualified_only_provider_does_not_satisfy_a_bare_parameter(
    boots: dict[str, Any],
) -> None:
    for phase in ("cold", "warm"):
        job = boots[phase]["jobs"]["qonly"]
        assert job["declared"]["p"]["verdict"] == "injected"
        assert job["admitted"]["p"] == "REJECTED_DISCOVERY"
    message = next(
        f["message"]
        for f in boots["cold"]["failures"]
        if f["error_type"] == "UnsupportedParameter" and "'qonly'" in f["message"]
    )
    assert "provlib.QOnly without a qualifier" in message


def test_the_cache_keeps_the_contract_before_admit(boots: dict[str, Any]) -> None:
    """B-7: availability is never cached; the declared contract is."""
    cache = next((boots["project"] / ".functualize").rglob("*.json"), None)
    text = cache.read_text(encoding="utf-8") if cache else ""
    assert '"verdict": "injected"' in text
    assert "No provider is registered" not in text


def test_library_mode_admits_like_func(tmp_path: Path) -> None:
    """An app a project builds itself reaches the same boot step (plan R-5)."""
    from functualize.app.config import JobSources, PluginSources
    from functualize.app.core import FunctualizeApp

    by_id = {row["id"]: row for row in ROWS}
    jobs = tmp_path / "jobs"
    jobs.mkdir()
    for rid in ("A001", "C085", "C082", "H163"):
        source = module_source(by_id[rid])
        (jobs / f"{rid.lower()}.py").write_text(source, encoding="utf-8")
    provlib = tmp_path / "pylib"
    provlib.mkdir()
    (provlib / "provlib.py").write_text(textwrap.dedent(PROVLIB), encoding="utf-8")
    sys.path.insert(0, str(provlib))
    try:
        import provlib as provlib_module

        def providers(app: Any) -> None:
            app.di.provide(provlib_module.ProvWidget, provlib_module.ProvWidget())

        providers.name = "providers"  # type: ignore[attr-defined]
        providers.version = "1.0.0"  # type: ignore[attr-defined]
        providers.description = "test providers"  # type: ignore[attr-defined]
        app = FunctualizeApp(
            name="lib",
            job_sources=JobSources(directories=[str(jobs)]),
            plugin_sources=PluginSources(
                explicit_plugins=[providers], ambient_directory=False
            ),
        )
    finally:
        sys.path.remove(str(provlib))
        sys.modules.pop("provlib", None)
    verdicts = {
        job: {name: c.verdict.name for name, c in params.items()}
        for job, params in app._admitted_contracts.items()
    }
    assert verdicts["a001"] == {"p": "ACCEPTED_POSITIONAL"}
    assert verdicts["c082"] == {"p": "INVOCATION_ONLY"}
    assert verdicts["c085"] == {"p": "REJECTED_DISCOVERY"}
    assert verdicts["h163"] == {"p": "INJECTED"}
    refused = [
        f for f in app._unsatisfiable_jobs if f.error_type == "UnsupportedParameter"
    ]
    assert [f.path for f in refused] == [str(jobs / "c085.py")]
