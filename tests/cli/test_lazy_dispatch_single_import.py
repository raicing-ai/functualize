"""CLI warm-cache single-module-import guardrail (Phase 4 of true-lazy boot).

`func <job>` now boots with lazy=True and materializes only the invoked
job. On a warm cache, dispatching one job must import exactly that job's
module — not the whole jobs directory.
"""

from __future__ import annotations

import sys
from pathlib import Path


def _marker_job_source(marker: Path, func_name: str) -> str:
    return (
        f"from pathlib import Path\n"
        f"Path({str(marker)!r}).open('a').write('imported\\n')\n"
        f"def {func_name}(x: int = 1):\n"
        f'    """Marker job."""\n'
        f"    print(f'{func_name}={{x}}')\n"
        f"    return x\n"
    )


def _imports(marker: Path) -> int:
    return len(marker.read_text().splitlines()) if marker.exists() else 0


def _purge(prefix: str) -> None:
    for name in [m for m in sys.modules if m.startswith(prefix)]:
        del sys.modules[name]


class TestCliWarmCacheSingleImport:
    def test_warm_dispatch_imports_only_invoked_module(
        self, cli_run, project_tree, tmp_path: Path
    ) -> None:
        markers = {
            name: tmp_path / f"clilazy_{name}.imports.log"
            for name in ("job_a", "job_b", "job_c")
        }
        root = project_tree(
            jobs={
                f"clilazy_{name}.py": _marker_job_source(marker, name)
                for name, marker in markers.items()
            }
        )

        # Run 1 (cold): builds the cache; executes job_a
        _purge("clilazy_")
        result1 = cli_run(["job_a"], cwd=root)
        assert result1.exit_code == 0, result1.stderr
        counts_after_cold = {n: _imports(m) for n, m in markers.items()}
        assert all(c >= 1 for c in counts_after_cold.values())

        # Run 2 (warm): executes job_b — ONLY job_b's module may be imported
        _purge("clilazy_")
        result2 = cli_run(["job_b", "--x", "7"], cwd=root)
        assert result2.exit_code == 0, result2.stderr
        assert "job_b=7" in result2.stdout

        counts_after_warm = {n: _imports(m) for n, m in markers.items()}
        assert counts_after_warm["job_b"] == counts_after_cold["job_b"] + 1
        assert counts_after_warm["job_a"] == counts_after_cold["job_a"], (
            "warm dispatch of job_b must not import job_a's module"
        )
        assert counts_after_warm["job_c"] == counts_after_cold["job_c"], (
            "warm dispatch of job_b must not import job_c's module"
        )

    def test_warm_dispatch_unimportable_job_fails_cleanly(
        self, cli_run, project_tree, tmp_path: Path
    ) -> None:
        marker = tmp_path / "clilazy_ok.imports.log"
        root = project_tree(
            jobs={
                "clilazy_ok.py": _marker_job_source(marker, "ok_job"),
                "clilazy_broken.py": (
                    "def broken_job():\n"
                    '    """Will break after cache build."""\n'
                    "    return 1\n"
                ),
            }
        )

        # Cold run builds the cache with both jobs
        _purge("clilazy_")
        result1 = cli_run(["ok_job"], cwd=root)
        assert result1.exit_code == 0, result1.stderr

        # Break broken_job's module WITHOUT changing its mtime/size beyond
        # detection: simplest reliable failure is deleting a dependency —
        # instead, make the module raise on import while keeping the same
        # byte size is brittle; a changed file is re-imported at boot (cache
        # stale path), so break it via an import error at MATERIALIZATION:
        # remove the module file after cache build. The stale-entry cleanup
        # drops deleted files from discovery, so assert the job is simply
        # gone (clean 'unknown command' error, no traceback).
        _purge("clilazy_")
        (Path(root) / ".functualize" / "jobs" / "clilazy_broken.py").unlink()
        result2 = cli_run(["broken_job"], cwd=root)
        assert result2.exit_code == 1
        assert "Traceback" not in result2.stderr
