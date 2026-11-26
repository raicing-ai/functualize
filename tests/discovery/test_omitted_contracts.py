"""The parameters a descriptor omits still carry their contracts (spec B-1, B-9).

``parameters`` leaves out capability types, ``FromJob`` and a ``GroupOptions``
injection point: no surface spells them. Their contracts now ride on the
descriptor as ``omitted_contracts``, decided by the same walk, so:

- ``parameters``' contracts and ``omitted_contracts`` are disjoint, and
  together name exactly the signature ``build_contracts`` classifies;
- cold and warm boots carry the same omitted contracts;
- no published surface changes: the click parameters and ``job_input_schema``
  built from each descriptor equal those built with ``omitted_contracts=()``;
- an omitted parameter that is refused is reported once, as
  ``UnsupportedParameter``, never also as ``UnsatisfiableParameter``.

Every table row is written as one project and booted by the real ``func`` in a
subprocess, cold then warm, in both annotation modes.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import types
from pathlib import Path
from typing import Any

import pytest

from functualize._primitives.parameter_contract import build_contracts
from tests._support.parameter_matrix import ROWS, module_source

PROVLIB = """
class ProvWidget:
    def __init__(self, v: str = "") -> None:
        self.v = v
"""

PLUGIN = """
import dataclasses
import json

from functualize._primitives.job_schema import job_input_schema
from functualize._types.descriptors import _contract_to_dict
from functualize.app.adapters.click_params import build_click_params_from_descriptor


def _surfaces(descriptor):
    params = [p.to_info_dict() for p in build_click_params_from_descriptor(descriptor)]
    return json.dumps([params, job_input_schema(descriptor)], sort_keys=True, default=repr)


class OmittedProbe:
    name = "omitted-probe"
    version = "1.0.0"
    description = "Dump both halves of each signature (test only)."

    def __call__(self, app):
        from provlib import ProvWidget

        self._app = app
        app.di.provide(ProvWidget, ProvWidget("by-type"))
        app.di.provide(ProvWidget, ProvWidget("by-w"), qualifier="w")
        app.extensions.register_plugin_command("dump", self._dump, namespace="omitted")

    def _dump(self, out: str = "") -> None:
        app = self._app
        jobs = {}
        for descriptor in app.job_registry.get_descriptors():
            entry = app.job_registry._registered_jobs.get(descriptor.name)
            bare = dataclasses.replace(descriptor, omitted_contracts=())
            jobs[descriptor.name] = {
                "file": descriptor.source_file,
                "lazy": bool(getattr(getattr(entry, "function", None), "__functualize_lazy__", False)),
                "parameters": [f.name for f in descriptor.parameters],
                "parameter_contracts": [
                    f.contract.name for f in descriptor.parameters if f.contract is not None
                ],
                "omitted": [_contract_to_dict(c) for c in descriptor.omitted_contracts],
                "surfaces_unchanged": _surfaces(descriptor) == _surfaces(bare),
            }
        failures = [f.as_dict() for f in getattr(app, "_unsatisfiable_jobs", [])]
        with open(out, "w", encoding="utf-8") as handle:
            json.dump({"jobs": jobs, "failures": failures}, handle, default=repr)


plugin = OmittedProbe()
"""

#: A CLI marker on a capability: the walk omits it (``Log``), and the
#: classifier refuses it (a marker on a type nothing converts, B-8).
REFUSED_OMITTED_JOB = """
from typing import Annotated

from functualize.job import Log, Option, job


@job
def capmark(p: Annotated[Log, Option()]) -> str:
    return "ran"
"""

CAPABILITY_ROWS = {f"E{n}" for n in range(108, 138)}
FROM_JOB_ROWS = {"E140", "E141"}


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
    (jobs / "capmark.py").write_text(REFUSED_OMITTED_JOB, encoding="utf-8")
    plugins = root / ".functualize" / "plugins"
    plugins.mkdir(parents=True)
    (plugins / "omitted_probe.py").write_text(PLUGIN, encoding="utf-8")
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
        [sys.executable, "-m", "functualize", "omitted", "dump", "--out", str(out)],
        cwd=project,
        env=env,
        capture_output=True,
        text=True,
        timeout=300,
        check=False,
    )
    assert done.returncode == 0, done.stdout + done.stderr
    data: dict[str, Any] = json.loads(out.read_text(encoding="utf-8"))
    return data


@pytest.fixture(scope="module", params=[False, True], ids=["eager", "pep563"])
def boots(
    request: pytest.FixtureRequest, tmp_path_factory: pytest.TempPathFactory
) -> dict[str, Any]:
    future: bool = request.param
    project = _write_project(tmp_path_factory.mktemp("omitted"), future=future)
    cold = _dump(project, "cold")
    warm = _dump(project, "warm")
    return {"future": future, "cold": cold, "warm": warm}


@pytest.fixture(autouse=True, scope="module")
def _provlib() -> Any:
    module = types.ModuleType("provlib")
    module.ProvWidget = type("ProvWidget", (), {"__module__": "provlib"})  # type: ignore[attr-defined]
    previous = sys.modules.get("provlib")
    sys.modules["provlib"] = module
    yield
    if previous is None:
        sys.modules.pop("provlib", None)
    else:
        sys.modules["provlib"] = previous


def _signature_names(row: dict[str, Any], future: bool) -> list[str]:
    """What the classifier sees: ``build_contracts`` over the live function."""
    name = f"_omit_{row['id'].lower()}_{int(future)}"
    module = types.ModuleType(name)
    sys.modules[name] = module
    source = module_source(row, future_annotations=future)
    exec(compile(source, f"<{name}>", "exec", dont_inherit=True), module.__dict__)
    rid = row["id"].lower()
    if row["declaration"].startswith("CLASS:"):
        function = getattr(module.__dict__[f"K_{rid}"], row["path"][-1])
    else:
        function = module.__dict__[row["path"][-1]]
    return [contract.name for contract in build_contracts(function)]


def _job(dump: dict[str, Any], row: dict[str, Any]) -> dict[str, Any] | None:
    tail = row["path"][-1].replace("_", "-")
    for name, job in dump["jobs"].items():
        if Path(job["file"]).stem == row["id"].lower() and name.split(".")[-1] == tail:
            return job
    return None


@pytest.mark.parametrize("phase", ["cold", "warm"])
@pytest.mark.parametrize("row", ROWS, ids=lambda row: row["id"])
def test_both_halves_cover_the_signature_disjointly(
    boots: dict[str, Any], row: dict[str, Any], phase: str
) -> None:
    job = _job(boots[phase], row)
    if row["id"] == "E142" and not boots["future"]:
        assert job is None  # FromJob[...] raises at import: nothing to cover
        return
    assert job is not None, row["id"]
    declared = set(job["parameter_contracts"])
    omitted = [contract["name"] for contract in job["omitted"]]
    assert not declared & set(omitted)
    assert declared | set(omitted) == set(_signature_names(row, boots["future"]))
    assert job["surfaces_unchanged"]


@pytest.mark.parametrize("phase", ["cold", "warm"])
def test_capability_and_from_job_contracts_are_omitted_not_emitted(
    boots: dict[str, Any], phase: str
) -> None:
    by_id = {row["id"]: row for row in ROWS}
    for rid in sorted(CAPABILITY_ROWS | FROM_JOB_ROWS):
        job = _job(boots[phase], by_id[rid])
        assert job is not None, rid
        assert "p" not in job["parameters"], rid
        (contract,) = [c for c in job["omitted"] if c["name"] == "p"]
        assert contract["verdict"] == "injected", rid
        key = "capability" if rid in CAPABILITY_ROWS else "from_job"
        assert contract["injection"][key], rid


def test_cold_and_warm_carry_the_same_omitted_contracts(boots: dict[str, Any]) -> None:
    cold, warm = boots["cold"]["jobs"], boots["warm"]["jobs"]
    assert cold.keys() == warm.keys()
    assert not any(job["lazy"] for job in cold.values())
    assert all(job["lazy"] for job in warm.values())
    for name in cold:
        assert cold[name]["omitted"] == warm[name]["omitted"], name


def test_every_descriptor_publishes_the_same_surfaces(boots: dict[str, Any]) -> None:
    for phase in ("cold", "warm"):
        changed = [
            name
            for name, job in boots[phase]["jobs"].items()
            if not job["surfaces_unchanged"]
        ]
        assert changed == [], phase


@pytest.mark.parametrize("phase", ["cold", "warm"])
def test_an_omitted_refusal_is_reported_once(boots: dict[str, Any], phase: str) -> None:
    dump = boots[phase]
    (contract,) = dump["jobs"]["capmark"]["omitted"]
    assert contract["verdict"] == "rejected_discovery"
    about = [f for f in dump["failures"] if "'capmark'" in f["message"]]
    assert [f["error_type"] for f in about] == ["UnsupportedParameter"], about
    assert about[0]["path"].endswith("capmark.py")
