"""One fingerprint-key derivation, agreed on by every reader and the writer.

Six call sites computed the key three different ways, and the divergence was
invisible from any single one of them:

- The **writer** hashed `config + the whole of call_kwargs`, which by pre-flight
  time holds the DI-injected capability instances. `canonical_json` falls back
  to `repr`, and `object.__repr__` carries a memory address — so a job with a
  `Log` parameter wrote a *different* key every run, could never report fresh,
  and grew its state file without bound.
- Three **readers** (`_from_job_needs_run`, `_from_job_value`,
  `_return_value_note`) addressed `compute_args_hash(None, {})`, substituting
  `None` for a config they could have resolved. For any job with a config class
  they read a key nobody ever wrote.

The second one's worst effect is not a wrong explanation, it is silent data
loss: a `FromJob` consumer of a *fresh* upstream got no value, no error, and
exit 0. The job body never ran and nothing said so.

These tests run the pipeline in **separate processes** on purpose. In one
process the upstream's live return value is still in hand, which masks a failed
record read entirely — that masking is why the defect survived.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).parent.parent.parent

# Four upstream shapes. The config-class rows are the ones that were broken:
# with a config class the reader's `compute_args_hash(None, {})` addresses a
# key the writer never wrote.
UPSTREAMS = {
    "bare": "def produce() -> Envelope:",
    "capability": "def produce(log: Log) -> Envelope:",
    "config": "def produce(cfg: Cfg) -> Envelope:",
    "config-and-capability": "def produce(cfg: Cfg, log: Log) -> Envelope:",
}

_JOBS_TEMPLATE = '''
from __future__ import annotations

from typing import Annotated

from pydantic import BaseModel

from functualize.job import Fingerprint, FromJob, Log, job

JOB_GROUP = "fj"


class Cfg(BaseModel):
    factor: int = 3


class Envelope(BaseModel):
    n: int


@job(group=JOB_GROUP, cache=Fingerprint(sources=["input.txt"]))
{signature}
    return Envelope(n=7)


@job(group=JOB_GROUP)
def consume(up: Annotated[Envelope, FromJob("fj.produce")]) -> None:
    print(f"CONSUMED n={{up.n}}")
'''


def _write_project(tmp_path: Path, signature: str) -> Path:
    (tmp_path / ".functualize.toml").write_text('jobs_directories = ["jobs"]\n')
    (tmp_path / "config.base.toml").write_text('[general]\napp_name = "fj"\n')
    (tmp_path / ".functualize").mkdir()
    (tmp_path / "input.txt").write_text("unchanged\n")
    jobs = tmp_path / "jobs"
    jobs.mkdir()
    (jobs / "fj.py").write_text(_JOBS_TEMPLATE.format(signature=signature))
    return tmp_path


def _run(*args: str, cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["uv", "run", "--project", str(PROJECT_ROOT), "func", *args],
        capture_output=True,
        text=True,
        cwd=str(cwd),
        timeout=120,
    )


def _fingerprint_keys(project: Path) -> list[str]:
    state = project / ".functualize" / "state.json"
    if not state.exists():
        return []
    return sorted(json.loads(state.read_text()).get("fingerprints", {}))


@pytest.mark.parametrize("shape", sorted(UPSTREAMS), ids=sorted(UPSTREAMS))
def test_from_job_delivers_across_processes(tmp_path: Path, shape: str) -> None:
    """The consumer receives the recorded value in a *separate* process.

    Whether the upstream declares a config class, a capability, both or
    neither must make no difference — the reader resolves the same config the
    writer did.
    """
    project = _write_project(tmp_path, UPSTREAMS[shape])

    first = _run("fj", "produce", cwd=project)
    assert first.returncode == 0, first.stderr

    second = _run("fj", "consume", cwd=project)
    assert second.returncode == 0, second.stderr
    # The failure this guards is silent: body never runs, no error, exit 0.
    assert "CONSUMED n=7" in second.stdout, (
        f"upstream shape {shape!r}: consumer body did not run.\n"
        f"stdout={second.stdout!r} stderr={second.stderr!r}"
    )


@pytest.mark.parametrize("shape", sorted(UPSTREAMS), ids=sorted(UPSTREAMS))
def test_repeated_runs_write_exactly_one_key(tmp_path: Path, shape: str) -> None:
    """Four unchanged runs, one key.

    A capability instance in the key made this four keys — the state file grew
    forever and the job was never fresh. Asserting the *count* rather than
    freshness is what catches the growth directly.
    """
    project = _write_project(tmp_path, UPSTREAMS[shape])

    for _ in range(4):
        result = _run("fj", "produce", cwd=project)
        assert result.returncode == 0, result.stderr

    keys = _fingerprint_keys(project)
    assert len(keys) == 1, f"upstream shape {shape!r} wrote {len(keys)} keys: {keys}"


@pytest.mark.parametrize("shape", sorted(UPSTREAMS), ids=sorted(UPSTREAMS))
def test_why_agrees_with_the_run_that_just_happened(tmp_path: Path, shape: str) -> None:
    """`why` must never contradict the run before it.

    `explain` resolves config through the engine's own resolver now, so the key
    it reads is the key the run wrote — by construction, not convention.
    """
    project = _write_project(tmp_path, UPSTREAMS[shape])

    assert _run("fj", "produce", cwd=project).returncode == 0

    why = _run("builtin", "why", "fj.produce", cwd=project)
    combined = why.stdout + why.stderr
    assert "up to date" in combined, (
        f"upstream shape {shape!r}: `why` says the job would run, immediately "
        f"after a successful run.\n{combined}"
    )
