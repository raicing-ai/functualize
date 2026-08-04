"""T-GO-2 acceptance: discovery, cache (v13), and the trie side map.

Covers the plan's [A] criteria for T-GO-2:
- a ``GroupOptions`` declaration in a job-free, ``_``-prefixed module is
  discovered (the conventional ``jobs/deploy/_group.py`` home);
- a warm boot reads the specs with **no job-module imports**;
- a duplicate binding for one group path is a discovery error;
- the trie side map answers direct and inherited lookups.
"""

from __future__ import annotations

import json
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

from functualize._discovery.cached_provider import CachedDirectoryScanProvider
from functualize._primitives.cache_format import CACHE_FILENAME, CACHE_VERSION
from functualize._primitives.locator import ResourceLocator
from functualize._types.errors import GroupOptionsConflictError
from functualize.app.utils import build_group_trie, read_group_options_from_cache

_GROUP_MODULE = '''
from typing import Annotated
from functualize.job import GroupOptions, Option

class DeployOptions(GroupOptions, group="deploy"):
    """Deploy-level flags."""
    env: Annotated[str, Option("-e", help="Target environment")] = "staging"
    dry_run: Annotated[bool, Option("--dry-run", help="Preview only")] = False
'''

_WEB_JOB = '''
JOB_GROUP = "deploy.web"

def run(image: str = "nginx") -> str:
    """Deploy the web tier."""
    return image
'''


@pytest.fixture(autouse=True)
def _no_module_bleed(clean_sys_modules: None) -> None:
    """Evict this suite's imported job modules after each test.

    The provider imports the fixture files as top-level modules named
    ``_group``/``web`` — generic names another suite (e.g. the surface-parity
    detector) also uses. Left in ``sys.modules``, a stale entry shadows the
    later suite's identically-named file and its jobs silently fail to
    discover. Cleaning up here keeps the pollution from leaving this module.
    """


def _make_project(root: Path, files: dict[str, str]) -> Path:
    """Write a minimal project with a jobs/ dir containing `files`."""
    (root / "pyproject.toml").write_text(
        '[project]\nname = "probe"\nversion = "0.1.0"\ndependencies = []\n'
    )
    jobs = root / "jobs"
    jobs.mkdir(parents=True, exist_ok=True)
    for name, content in files.items():
        (jobs / name).write_text(textwrap.dedent(content).lstrip(), encoding="utf-8")
    return jobs


def _make_provider(root: Path, jobs: Path) -> CachedDirectoryScanProvider:
    cache_dir = root / ".functualize"
    locator = (
        ResourceLocator()
        .search_explicit(str(cache_dir))
        .write_to_explicit(str(cache_dir))
    )
    return CachedDirectoryScanProvider(
        directories=[str(jobs)], locator=locator, project_root=root
    )


def _cache_file(root: Path) -> Path:
    return root / ".functualize" / CACHE_FILENAME


def test_declaration_in_underscore_job_free_module_is_discovered(
    tmp_path: Path,
) -> None:
    """The conventional home is `jobs/deploy/_group.py`: `_`-prefixed and
    containing no jobs at all. Both traits must survive the scan."""
    jobs = _make_project(tmp_path, {"_group.py": _GROUP_MODULE, "web.py": _WEB_JOB})
    provider = _make_provider(tmp_path, jobs)

    names = [d.name for d in provider.list_jobs()]
    assert names == ["deploy.web.run"], "the _-prefixed module defines no jobs"

    data = json.loads(_cache_file(tmp_path).read_text(encoding="utf-8"))
    # Pinned to the constant, not a literal: the cache version is bumped by any
    # feature that changes the format (S6a took it to 13, S5's pipeline work to
    # 14), and this test is about the group_options section, not the number.
    assert data["version"] == CACHE_VERSION
    assert "deploy" in data["group_options"]
    assert data["group_options"]["deploy"]["class_name"] == "DeployOptions"


def test_cached_spec_carries_flags_types_and_marker_help(tmp_path: Path) -> None:
    jobs = _make_project(tmp_path, {"_group.py": _GROUP_MODULE})
    _make_provider(tmp_path, jobs).list_jobs()

    specs = read_group_options_from_cache(_cache_file(tmp_path))
    assert specs is not None
    fields = {f.name: f for f in specs["deploy"].fields}

    assert fields["env"].type_annotation == "str"
    assert fields["env"].default == "staging"
    assert fields["env"].short_flag == "-e"
    assert fields["env"].description == "Target environment"
    assert fields["dry_run"].type_annotation == "bool"
    assert fields["dry_run"].default is False


def test_base_class_is_not_discovered_as_a_declaration(tmp_path: Path) -> None:
    """The module imports `GroupOptions` itself; the base must not register."""
    jobs = _make_project(tmp_path, {"_group.py": _GROUP_MODULE})
    _make_provider(tmp_path, jobs).list_jobs()

    specs = read_group_options_from_cache(_cache_file(tmp_path))
    assert specs is not None
    assert list(specs) == ["deploy"], "only the bound subclass may be cached"


def test_importing_a_declaration_elsewhere_is_not_a_duplicate(
    tmp_path: Path,
) -> None:
    """Re-exporting a declaration must not register it a second time.

    A job module that does `from _group import DeployOptions` puts the class
    in its own namespace. Only the module that *defines* it may register it —
    otherwise the same declaration is discovered once per importer and trips
    the one-per-path check with a phantom conflict.
    """
    importer = """
    JOB_GROUP = "deploy"
    from _group import DeployOptions

    def status(opts: DeployOptions = None) -> str:
        return "ok"
    """
    jobs = _make_project(
        tmp_path, {"_group.py": _GROUP_MODULE, "importer.py": importer}
    )
    provider = _make_provider(tmp_path, jobs)

    provider.list_jobs()  # must not raise

    specs = read_group_options_from_cache(_cache_file(tmp_path))
    assert specs is not None
    assert list(specs) == ["deploy"]
    assert specs["deploy"].source_file.endswith("_group.py"), (
        "the defining module must own the binding, not the importer"
    )


def test_duplicate_binding_for_one_group_is_a_discovery_error(
    tmp_path: Path,
) -> None:
    other = _GROUP_MODULE.replace("DeployOptions", "OtherDeployOptions")
    jobs = _make_project(tmp_path, {"_group.py": _GROUP_MODULE, "_dup.py": other})
    provider = _make_provider(tmp_path, jobs)

    with pytest.raises(GroupOptionsConflictError) as exc:
        provider.list_jobs()

    assert exc.value.group == "deploy"
    assert "declared exactly once" in str(exc.value)


def test_rescanning_the_same_file_is_not_a_conflict(tmp_path: Path) -> None:
    """A file re-imported on a later cycle must not conflict with itself."""
    jobs = _make_project(tmp_path, {"_group.py": _GROUP_MODULE})
    provider = _make_provider(tmp_path, jobs)
    provider.list_jobs()
    provider.list_jobs()  # would raise if the self-rebind were treated as a dup

    specs = read_group_options_from_cache(_cache_file(tmp_path))
    assert specs is not None and list(specs) == ["deploy"]


def test_removing_the_declaration_drops_it_from_the_cache(tmp_path: Path) -> None:
    jobs = _make_project(tmp_path, {"_group.py": _GROUP_MODULE})
    provider = _make_provider(tmp_path, jobs)
    provider.list_jobs()
    assert read_group_options_from_cache(_cache_file(tmp_path)) != {}

    (jobs / "_group.py").unlink()
    provider.list_jobs()

    assert read_group_options_from_cache(_cache_file(tmp_path)) == {}


def test_trie_side_map_resolves_direct_and_inherited(tmp_path: Path) -> None:
    jobs = _make_project(tmp_path, {"_group.py": _GROUP_MODULE, "web.py": _WEB_JOB})
    _make_provider(tmp_path, jobs).list_jobs()

    specs = read_group_options_from_cache(_cache_file(tmp_path))
    assert specs is not None
    trie = build_group_trie([], groups=["deploy", "deploy.web"], group_options=specs)

    direct = trie.group_options(["deploy"])
    assert direct is not None and direct.class_name == "DeployOptions"
    # `deploy.web` declares nothing of its own...
    assert trie.group_options(["deploy", "web"]) is None
    # ...but inherits `deploy`'s by containment.
    assert [s.group for s in trie.group_options_on_path(["deploy", "web"])] == [
        "deploy"
    ]
    assert [s.group for s in trie.group_options_on_path(["deploy", "web", "run"])] == [
        "deploy"
    ]
    assert trie.group_options_on_path(["other"]) == []


def test_inheritance_is_outermost_first(tmp_path: Path) -> None:
    """Nested declarations return outermost-first so the nearest wins a merge."""
    nested = """
    from typing import Annotated
    from functualize.job import GroupOptions, Option

    class WebOptions(GroupOptions, group="deploy.web"):
        replicas: Annotated[int, Option("-r")] = 1
    """
    jobs = _make_project(
        tmp_path, {"_group.py": _GROUP_MODULE, "_web_group.py": nested}
    )
    _make_provider(tmp_path, jobs).list_jobs()

    specs = read_group_options_from_cache(_cache_file(tmp_path))
    assert specs is not None
    trie = build_group_trie([], groups=["deploy", "deploy.web"], group_options=specs)

    assert [s.group for s in trie.group_options_on_path(["deploy", "web"])] == [
        "deploy",
        "deploy.web",
    ]


def test_warm_boot_reads_specs_with_no_job_module_imports(tmp_path: Path) -> None:
    """The load-bearing property: a warm read of the group_options section
    must not import the declaring module.

    Asserted in a subprocess so the check is against a real interpreter's
    module table, not this test session's already-polluted one.
    """
    jobs = _make_project(tmp_path, {"_group.py": _GROUP_MODULE, "web.py": _WEB_JOB})
    _make_provider(tmp_path, jobs).list_jobs()  # cold scan populates the cache

    probe = textwrap.dedent(
        f"""
        import sys
        from pathlib import Path
        from functualize.app.utils import read_group_options_from_cache

        specs = read_group_options_from_cache(Path({str(_cache_file(tmp_path))!r}))
        assert specs is not None, "cache unreadable"
        assert "deploy" in specs, "group options not read"
        assert [f.name for f in specs["deploy"].fields] == ["env", "dry_run"]

        # No module from the scanned jobs dir may have been imported.
        leaked = [
            name
            for name, mod in sys.modules.items()
            if getattr(mod, "__file__", None)
            and str(Path(getattr(mod, "__file__")).parent) == {str(jobs)!r}
        ]
        assert not leaked, f"warm read imported job modules: {{leaked}}"
        print("OK")
        """
    )
    result = subprocess.run(
        [sys.executable, "-c", probe], capture_output=True, text=True
    )
    assert result.returncode == 0, result.stderr
    assert "OK" in result.stdout
