"""A group's declared flags are served only from a cache written under the caller's filter set.

`read_group_options_from_cache` took `cache_path` and nothing else, so no caller could tell it
which discovery configuration it was running under — and the section it reads is the one section
of the cache with no fingerprint of its own. Every sibling section is protected by the file's
`discovery_hash` header, checked in `CachedDirectoryScanProvider._is_globally_invalidated`; a raw
reader that does not check it serves flags from a scan the caller never ran.

Reproduced before the fix (`a cache written under one filter set, read under another`): header
`sha256:0f61ce09…` written under `DiscoveryConfig(exclude_patterns=("nothing*.py",))`, read by a
caller whose own fingerprint is `sha256:da5f26ab…`, and the section came back anyway —
`groups: ['deploy']`.

The parameter is deliberately defaulted (`contracts.md` §1): `None` means *"cannot know"* and
skips the check, which is the pre-existing behaviour and the one place this feature accepts a
shim, so an out-of-tree reader does not break. Every in-tree caller supplies one.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from functualize._discovery.filter_factory import discovery_hash_from_config
from functualize.app.config import DiscoveryConfig
from functualize.app.utils import (
    build_discovery_cache_provider,
    read_group_options_from_cache,
    resolve_cache_path,
)

_GROUP_MODULE = '''\
from typing import Annotated

from functualize.job import GroupOptions, Option


class DeployOptions(GroupOptions, group="deploy"):
    """Deploy-level flags."""

    env: Annotated[str, Option("-e", help="Target environment")] = "staging"
'''

_WEB_JOB = '''\
JOB_GROUP = "deploy.web"


def run() -> str:
    """Deploy the web tier."""
    return "ok"
'''

#: A filter set that is *not* the default — the fingerprint therefore differs
#: from `discovery_hash_from_config(None)`, which is what a run without flags
#: resolves to.
_FILTERED = DiscoveryConfig(exclude_patterns=("nothing*.py",))


@pytest.fixture(autouse=True)
def _no_module_bleed(clean_sys_modules: None) -> None:
    """Evict this suite's job modules after each test.

    The provider registers these files as top-level modules named `_group` and
    `web` — names other suites also use. Left in `sys.modules`, a stale entry
    shadows a later suite's identically-named file.
    """


def _write_cache(project_tree, discovery_config: DiscoveryConfig) -> Path:
    """Write a discovery cache the way a filtered CLI run does.

    Always with a config, never the bare writer: a bare provider persists
    ``discovery_hash: null`` (see `build_discovery_cache_provider`), which is a
    different case from the all-defaults digest a real unfiltered run writes.
    """
    root = project_tree(jobs={"_group.py": _GROUP_MODULE, "web.py": _WEB_JOB})
    provider = build_discovery_cache_provider(
        cwd=root, discovery_config=discovery_config
    )
    provider.list_jobs()
    return resolve_cache_path(root)


def test_a_cache_from_another_filter_set_is_refused(project_tree) -> None:
    """The whole point: the caller's fingerprint decides, not the file's shape."""
    cache = _write_cache(project_tree, _FILTERED)

    mine = discovery_hash_from_config(_FILTERED)
    assert read_group_options_from_cache(cache, discovery_hash=mine) is not None

    someone_elses = discovery_hash_from_config(None)
    assert someone_elses != mine, "the fixture filter must move the fingerprint"
    assert read_group_options_from_cache(cache, discovery_hash=someone_elses) is None


def test_changing_a_discovery_filter_invalidates_the_section(project_tree) -> None:
    """AC-2's operative claim, on the artefact rather than on the signature.

    The header is the artefact the boot path already acts on: a config-aware
    provider refills a cache written under another filter set. The reader now
    answers the same question the same way, so a changed
    `exclude_patterns` no longer leaves one section being replayed from the old
    scan while every other section is rebuilt.
    """
    cache = _write_cache(project_tree, DiscoveryConfig())

    header = json.loads(cache.read_text(encoding="utf-8"))["discovery_hash"]
    assert header == discovery_hash_from_config(None)

    changed = discovery_hash_from_config(_FILTERED)
    assert changed != header
    assert read_group_options_from_cache(cache, discovery_hash=changed) is None


def test_no_fingerprint_skips_the_check(project_tree) -> None:
    """The documented default: a caller that cannot know is not refused.

    This is the pre-existing behaviour, kept on purpose (`contracts.md` §1) —
    it is the one shim this change accepts, for readers outside the tree whose
    signature we cannot update.
    """
    cache = _write_cache(project_tree, _FILTERED)

    specs = read_group_options_from_cache(cache)

    assert specs is not None and list(specs) == ["deploy"]


def test_the_section_is_still_refused_for_an_unreadable_cache(tmp_path: Path) -> None:
    """The fingerprint check does not replace the checks that were there.

    Ordered ahead of it deliberately: a missing file is not a fingerprint
    mismatch, and both must answer the same way — `None`, so the caller falls
    back to scanning.
    """
    assert (
        read_group_options_from_cache(
            tmp_path / "absent.json", discovery_hash=discovery_hash_from_config(None)
        )
        is None
    )
