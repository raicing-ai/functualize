"""Config and group fields carry contracts; an unsupported config type is refused.

Config fields come from ``extract_field_descriptors`` and are ``CONFIG_FIELD``.
Group fields come from ``extract_group_options_fields`` and are group-level
``ACCEPTED_FLAG`` (B-1). A config field whose type no config source can supply
(``dict``, a nested model; F-29) is ``REJECTED_DISCOVERY``: rows F150 and F151.
Those two are *reported* on the real ``func``'s cold and warm boots, and are
not run.
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

from functualize._discovery.group_options_extractor import (
    extract_group_options_fields,
)
from functualize._discovery.schema_extractor import extract_field_descriptors
from functualize._types.descriptors import _field_from_dict, _field_to_dict
from tests._support.parameter_matrix import ROWS, module_source

CONFIG_ROWS = [row for row in ROWS if row["axis"] == "config"]
GROUP_ROWS = [row for row in ROWS if row["declaration"].startswith("GROUP:")]
REFUSED = {"F150", "F151"}
MODES = pytest.mark.parametrize("future", [False, True], ids=["eager", "pep563"])


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


def _model(row: dict[str, Any], future: bool, prefix: str) -> Any:
    name = f"_cfc_{row['id'].lower()}"
    module = types.ModuleType(name)
    sys.modules[name] = module
    source = module_source(row, future_annotations=future)
    exec(compile(source, f"<{name}>", "exec", dont_inherit=True), module.__dict__)
    return module.__dict__[f"{prefix}_{row['id'].lower()}"]


@MODES
@pytest.mark.parametrize("row", CONFIG_ROWS, ids=lambda row: row["id"])
def test_config_fields_carry_their_verdict(row: dict[str, Any], future: bool) -> None:
    fields = {f.name: f for f in extract_field_descriptors(_model(row, future, "Cfg"))}
    contract = fields[row["probe"]].contract
    assert contract is not None
    assert contract.verdict.name == row["expected_verdict"], contract.reject_reason
    assert (contract.verdict.name == "REJECTED_DISCOVERY") is (row["id"] in REFUSED)


@MODES
@pytest.mark.parametrize("row", GROUP_ROWS, ids=lambda row: row["id"])
def test_group_fields_are_group_level_flags(row: dict[str, Any], future: bool) -> None:
    fields = {f.name: f for f in extract_group_options_fields(_model(row, future, "G"))}
    contract = fields[row["probe"]].contract
    assert contract is not None
    assert contract.verdict.name == "ACCEPTED_FLAG"
    assert contract.cli is not None and contract.cli.long == "--p"


@pytest.mark.parametrize("row", CONFIG_ROWS + GROUP_ROWS, ids=lambda row: row["id"])
def test_field_contracts_survive_the_cache_codec(row: dict[str, Any]) -> None:
    """B-7: the warm descriptor is the cold one, contract included."""
    group = row in GROUP_ROWS
    model = _model(row, True, "G" if group else "Cfg")
    fields = (
        extract_group_options_fields(model)
        if group
        else extract_field_descriptors(model)
    )
    for field in fields:
        encoded = json.loads(json.dumps(_field_to_dict(field)))
        assert _field_from_dict(encoded).contract == field.contract


def test_an_option_marker_on_a_config_field_spells_its_short_flag() -> None:
    row = next(r for r in CONFIG_ROWS if r["id"] == "F152")
    (field,) = extract_field_descriptors(_model(row, True, "Cfg"))
    assert field.contract is not None and field.contract.cli is not None
    assert field.contract.cli.short == "-t"


def _func(project: Path, *argv: str) -> subprocess.CompletedProcess[str]:
    home = project / ".home"
    env = {
        **os.environ,
        "HOME": str(home),
        "XDG_CONFIG_HOME": str(home / "config"),
        "XDG_CACHE_HOME": str(home / "cache"),
        "XDG_STATE_HOME": str(home / "state"),
        "XDG_DATA_HOME": str(home / "data"),
    }
    return subprocess.run(  # noqa: S603
        [sys.executable, "-m", "functualize", *argv],
        cwd=project,
        env=env,
        capture_output=True,
        text=True,
        timeout=180,
        check=False,
    )


@pytest.fixture(scope="module")
def project(tmp_path_factory: pytest.TempPathFactory) -> Path:
    root = tmp_path_factory.mktemp("config-fields")
    jobs = root / "jobs"
    jobs.mkdir()
    (root / "pyproject.toml").write_text(
        '[project]\nname = "pc"\nversion = "0"\n\n'
        '[tool.functualize]\njobs_directories = ["jobs"]\n',
        encoding="utf-8",
    )
    for row in CONFIG_ROWS:
        # The header imports `provlib`; config rows never use it.
        source = module_source(row).replace("from provlib import ProvWidget\n", "")
        (jobs / f"{row['id'].lower()}.py").write_text(source, encoding="utf-8")
    return root


def test_refused_config_fields_are_reported_not_run(project: Path) -> None:
    for phase in ("cold", "warm"):
        if phase == "warm":
            # No `.functualize/` here, so the cache lives under XDG_CACHE_HOME.
            assert any(project.rglob("cache.json")), "no cache to warm from"
        _assert_reported(_func(project, "builtin", "info", "--json"), phase)


def _assert_reported(info: subprocess.CompletedProcess[str], phase: str) -> None:
    assert info.returncode == 0, (phase, info.stderr)
    report = json.loads(info.stdout)
    refused = [
        item
        for item in report["discovery_failures"]
        if item["error_type"] == "UnsupportedParameter"
    ]
    for row in CONFIG_ROWS:
        rid = row["id"]
        items = [item for item in refused if f"job '{rid.lower()}'" in item["message"]]
        assert bool(items) is (rid in REFUSED), (phase, rid, items)
        if rid in REFUSED:
            (item,) = items
            assert item["path"].endswith(f"{rid.lower()}.py")
            assert "no config source or flag can supply" in item["message"]
            assert item["message"] in info.stderr, phase  # the boot warning (B-9)
    names = json.dumps(report)
    assert all(f'"{rid.lower()}"' in names for rid in REFUSED)  # still listed


def test_a_secret_marked_default_never_reaches_the_contract() -> None:
    """The contract is cached too: `json_schema_extra` secrets lose their default."""
    from pydantic import BaseModel, Field

    from functualize.job import GroupOptions

    class Cfg(BaseModel):
        credential: str = Field(default="dev-key", json_schema_extra={"secret": True})

    class Opts(GroupOptions, group="secret-defaults"):
        credential: str = Field(default="dev-key", json_schema_extra={"secret": True})

    for fields in (extract_field_descriptors(Cfg), extract_group_options_fields(Opts)):
        (field,) = fields
        assert field.contract is not None
        assert field.contract.default_json is None
        assert "dev-key" not in json.dumps(_field_to_dict(field))
