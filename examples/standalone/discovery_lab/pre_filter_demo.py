"""The tenth filter — one you write yourself.

The nine `require_*` settings are switched on per-run with a
`FUNCTUALIZE_DISCOVERY_*` env var or a CLI flag. `pre_filter` is the one that
cannot be: it takes a *predicate*, so it is set programmatically when the app
is constructed. This script is the lab's `main.py` for that one filter.

Run it against the same jobs tree the rest of the lab uses:

    cd examples/standalone/discovery_lab
    uv run python pre_filter_demo.py

The predicate here admits a module only when its **filename contains a
digit-free word ending in `y`** — deliberately something no `require_*`
setting can express, since it is neither a prefix, a postfix, an import, a
marker, nor a decorator. Real ones are usually more sensible; the point is
that the shape is yours.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from functualize.app import FunctualizeApp, JobSources
from functualize.app.config import DiscoveryConfig

if TYPE_CHECKING:
    from functualize.plugin import ModulePreFilter

LAB = Path(__file__).parent


class NameContainsWordEndingInY:
    """Admit a module whose stem has a word ending in 'y'.

    Two methods, both required. `should_import` answers the question;
    `fingerprint` is what lets the discovery cache trust the answer later.
    """

    def should_import(self, source_file: Path) -> bool:
        return any(part.endswith("y") for part in source_file.stem.split("_"))

    def fingerprint(self) -> str:
        # Bump this whenever `should_import` changes. The cache stores which
        # files this filter *rejected* and replays those decisions while the
        # fingerprint matches -- so a stale stamp replays decisions the current
        # logic would not make. Identity cannot be used instead: `str()` of an
        # object carries its memory address, so the digest would differ on
        # every boot and the cache would never be warm.
        return "word-ending-in-y:v1"


def jobs_with(pre_filter: ModulePreFilter | None) -> list[str]:
    app = FunctualizeApp(
        "discovery-lab",
        job_sources=JobSources(directories=[str(LAB / "jobs")]),
        discovery_config=DiscoveryConfig(pre_filter=pre_filter),
    )
    return sorted(job.name for job in app.get_jobs())


def main() -> None:
    baseline = jobs_with(None)
    filtered = jobs_with(NameContainsWordEndingInY())

    print("no pre_filter :", ", ".join(baseline))
    print("with pre_filter:", ", ".join(filtered) or "(none)")
    print()
    print("dropped        :", ", ".join(sorted(set(baseline) - set(filtered))))
    print()
    print("Only jobs/job_deploy.py survives -- 'deploy' ends in 'y' -- so its")
    print("two jobs remain and every other file is skipped before import.")
    print("Composition is AND: set require_file_prefix='job_' as well and you")
    print("get the intersection, not a replacement.")


if __name__ == "__main__":
    main()
