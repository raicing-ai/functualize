"""The decision to run a job, or not (§D.2, §D.3).

Everything a job declares about *whether* it should run — `Guards`
(preconditions, status checks, platforms) and `Fingerprint` (file staleness) —
converges here into one :class:`~functualize._engine.guards.GuardVerdict`, and
the executor consults exactly one thing before running anything.

**This module exists because those pieces already did, and nothing called
them.** `GuardEvaluator`, `fingerprint.evaluate`, and the `func why` renderer
shipped at the S3 stage gate with full unit tests and zero production callers,
so `@job(guards=...)` and `@job(cache=...)` were accepted, validated, cached —
and inert. The components were never wrong; there was no seam joining them to
`execute()`. This is that seam.

Two responsibilities, deliberately paired:

- :meth:`Preflight.check` decides, before the job runs.
- :meth:`Preflight.record` writes the fingerprint after it succeeds.

They belong together because a check that reads a record nobody writes is a
guard that never fires — the failure mode this module was written to end.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from functualize._engine.guards import GuardEvaluator, GuardState, GuardVerdict
from functualize._primitives.fingerprint import (
    build_source_map,
    compute_args_hash,
    evaluate,
    expand_sources,
    fingerprint_key,
    make_record,
    reusable_return_value,
)

if TYPE_CHECKING:
    from functualize._primitives.state_store import StateStore

__all__ = ["Preflight", "PreflightDecision"]


class PreflightDecision:
    """A verdict plus the key it was computed under.

    The key is carried so :meth:`Preflight.record` writes to the same place
    :meth:`Preflight.check` read from. Recomputing it independently is how a
    check and its record silently drift apart.
    """

    __slots__ = ("key", "recorded_value", "verdict")

    def __init__(
        self, verdict: GuardVerdict, key: str, recorded_value: Any = None
    ) -> None:
        self.verdict = verdict
        self.key = key
        self.recorded_value = recorded_value

    @property
    def should_run(self) -> bool:
        return self.verdict.state is GuardState.RUN


class Preflight:
    """Evaluates guards and file staleness for one job.

    Args:
        store: State store holding fingerprint records. None disables
            fingerprinting entirely — guards still evaluate, so a job with
            only `Guards` behaves identically with or without a store.
        evaluator: Guard evaluator; a default one is built if omitted.
        root: Directory that ``Fingerprint.sources`` patterns are relative to.
    """

    def __init__(
        self,
        store: StateStore | None = None,
        *,
        evaluator: GuardEvaluator | None = None,
        root: Path | str | None = None,
    ) -> None:
        self._store = store
        self._evaluator = evaluator or GuardEvaluator(shell_runner=_run_shell_check)
        self._root = Path(root) if root is not None else Path.cwd()

    def check(
        self,
        job_name: str,
        declaration: Any,
        *,
        config: Any = None,
        args_hash: str | None = None,
    ) -> PreflightDecision:
        """Decide whether ``job_name`` should run.

        ``args_hash`` defaults to the hash of an argument-free invocation
        rather than to the empty string. An empty default is the drift this
        pipeline is most prone to: the executor computed a real hash, a caller
        that omitted it addressed a different fingerprint key, and a job that
        had just run reported "no previous run recorded". Making the default
        *correct* removes the class rather than fixing each caller.
        """
        if args_hash is None:
            args_hash = compute_args_hash(config, {})
        cache = getattr(declaration, "cache", None)
        guards = getattr(declaration, "guards", None)
        exec_decl = getattr(declaration, "exec", None)

        method = getattr(cache, "method", "checksum") if cache is not None else "none"
        key = fingerprint_key(job_name, args_hash, method)

        fingerprint_verdict = None
        has_file_signal = False
        if cache is not None and self._store is not None:
            sources = list(getattr(cache, "sources", ()) or ())
            generates = list(getattr(cache, "generates", ()) or ())
            has_file_signal = method != "none" and bool(sources)
            record = self._store.get_fingerprint(key)
            source_map = build_source_map(
                self._root,
                expand_sources(self._root, sources),
                previous=(record or {}).get("sources"),
            )
            fingerprint_verdict = evaluate(
                record,
                root=self._root,
                source_map=source_map,
                generates=generates,
                method=method,
            )

        verdict = self._evaluator.evaluate(
            platforms=getattr(exec_decl, "platforms", None),
            preconditions=getattr(guards, "preconditions", ()) or (),
            status=getattr(guards, "status", ()) or (),
            config=config,
            fingerprint=fingerprint_verdict,
            has_file_signal=has_file_signal,
        )
        # Carry the recorded value with the verdict. A job skipped as fresh
        # still has an answer — it is in the record the freshness check just
        # read — and returning None instead would make `rc.invoke("build")`
        # hand its caller nothing the moment the cache went warm.
        recorded = None
        if not verdict.state.is_skip:
            pass
        elif cache is not None and self._store is not None:
            recorded = reusable_return_value(
                self._store.get_fingerprint(key), job_name=job_name
            )
        return PreflightDecision(verdict, key, recorded)

    def record(
        self,
        job_name: str,
        declaration: Any,
        *,
        key: str,
        return_value: Any = None,
    ) -> None:
        """Write the fingerprint for a run that just succeeded.

        A no-op when the job declares no `Fingerprint` — recording staleness
        for a job nobody asked to cache would make the store grow without
        anything ever reading it.
        """
        cache = getattr(declaration, "cache", None)
        if cache is None or self._store is None:
            return

        sources = list(getattr(cache, "sources", ()) or ())
        generates = list(getattr(cache, "generates", ()) or ())
        previous = (self._store.get_fingerprint(key) or {}).get("sources")
        source_map = build_source_map(
            self._root, expand_sources(self._root, sources), previous=previous
        )
        self._store.put_fingerprint(
            key,
            make_record(
                source_map,
                generates=generates,
                recorded_at=datetime.now(UTC).isoformat(),
                return_value=return_value,
            ),
        )


def _run_shell_check(command: str) -> bool:
    """Run a guard's shell string; True on exit 0.

    Guards are a pre-flight question, so this deliberately captures output and
    never inherits the terminal: a precondition that printed to the user's
    screen — or worse, read from it — would turn asking "should this run?" into
    a side effect.
    """
    import subprocess

    try:
        completed = subprocess.run(  # noqa: S602 - guard strings are author-declared
            command,
            shell=True,
            capture_output=True,
            timeout=60,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return completed.returncode == 0
