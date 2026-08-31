"""Harness contracts for `evals/` that need no model, and so must not be paid for.

`evals/README.md` states the rule: "If a rule can be settled without a model, it
belongs in `tests/skills/` and should be deleted from here." These are those
rules for the eval harness itself.

The var-expansion guards exist because of one promptfoo behaviour that fails
*silently* and reads as a broken skill rather than a broken harness: a
list-valued `var` is a **var-expansion axis**, not a list value. Left alone it
does two things:

1. `setup` / `checks` reach the provider as a bare string, so `for cmd in setup`
   iterates CHARACTERS and launches one container per letter — `uv sync` never
   runs and the agent starts in a workspace with no `.venv`.
2. A 2-element `checks` fans one case out into 2 rows that each verify only half
   the contract, inflating spend while weakening the assertion.
"""

from __future__ import annotations

import contextlib
import importlib.util
import re
import sys
from pathlib import Path

import pytest

yaml = pytest.importorskip("yaml")

EVALS = Path(__file__).resolve().parents[2] / "evals"
SUITES = sorted(EVALS.glob("suites/*.yaml"))

pytestmark = pytest.mark.skipif(not SUITES, reason="evals/ is not present")


def _load(path: Path) -> dict:
    return yaml.safe_load(path.read_text())


def _list_valued_vars(suite: dict) -> dict[str, list]:
    """Every var in the suite whose value is a YAML list."""
    found: dict[str, list] = {}
    scopes = [(suite.get("defaultTest") or {}).get("vars") or {}]
    scopes += [(test.get("vars") or {}) for test in suite.get("tests") or []]
    for scope in scopes:
        for name, value in scope.items():
            if isinstance(value, list):
                found[name] = value
    return found


@pytest.mark.parametrize("path", SUITES, ids=lambda p: p.name)
def test_list_valued_vars_disable_expansion(path: Path) -> None:
    """A suite with a list-valued var must opt out of promptfoo's expansion."""
    suite = _load(path)
    list_vars = _list_valued_vars(suite)
    if not list_vars:
        return

    options = (suite.get("defaultTest") or {}).get("options") or {}
    assert options.get("disableVarExpansion") is True, (
        f"{path.name} has list-valued vars {sorted(list_vars)} but does not set "
        "defaultTest.options.disableVarExpansion: true. Without it promptfoo "
        "flattens each list into a string (the provider then iterates it one "
        "character per container) and fans multi-element lists out into extra "
        "rows that each verify only part of the contract."
    )


def test_provider_never_iterates_a_string() -> None:
    """`_as_commands` is the backstop for a suite that forgets the option."""
    spec = importlib.util.spec_from_file_location(
        "_fz_claude_agent", EVALS / "providers" / "claude_agent.py"
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    command = "uv sync --quiet 2>/dev/null || true"
    assert module._as_commands(command) == [command]
    assert module._as_commands(None) == []
    assert module._as_commands("   ") == []
    assert module._as_commands(["a", "b"]) == ["a", "b"]


# --------------------------------------------------------------------------
# Cost and validity invariants of the harness itself
# --------------------------------------------------------------------------


def _harness():
    """Load `providers/_harness.py` out-of-tree, under its own module name.

    It must be registered in `sys.modules` *before* execution: `@dataclass`
    resolves `sys.modules[cls.__module__]` while processing the class, and an
    unregistered name makes that None — `AttributeError: 'NoneType' object has
    no attribute '__dict__'` at import, nowhere near the cause.
    """
    name = "_fz_harness"
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(
        name, EVALS / "providers" / "_harness.py"
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    try:
        spec.loader.exec_module(module)
    except Exception:
        del sys.modules[name]
        raise
    return module


def test_source_snapshot_excludes_the_rest_of_the_repo() -> None:
    """`/src` is the installable subset, not the working tree.

    The snapshot is mounted read-only into every container. When it was the
    whole tree, agents answered questions by reading `examples/`, `tests/` and
    `contributor/` — and one case failed all three repeats because the agent
    found `tests/tui_audit`, ran it green and reported "no bug in the source"
    instead of handing framework work back. A real user has site-packages and
    nothing else, so a skill that needs the source tree is not the skill being
    measured. `evals/suites/` in particular is the answer key.
    """
    paths = _harness()._tracked_files()
    assert paths, "snapshot resolved to nothing — did the pathspec break?"

    forbidden = (
        "evals/",
        "examples/",
        "tests/",
        "contributor/",
        "docs/",
        ".github/",
        "AGENTS.md",
        "CLAUDE.md",
    )
    leaked = sorted({p for p in paths if p.startswith(forbidden)})
    assert not leaked, f"these must not be readable at /src: {leaked[:12]}"

    # ...and the parts a `functualize @ path` build genuinely needs.
    assert any(p.startswith("src/functualize/") for p in paths)
    assert any(p.startswith("skills/") for p in paths)
    assert "pyproject.toml" in paths


def test_empty_allowed_tools_means_no_tools() -> None:
    """`allowed_tools=[]` must not fall back to the Bash-enabled default set.

    The grader passes `[]` so a rubric verdict cannot be reached by going and
    looking at the workspace. `allowed_tools or DEFAULT` treated that as unset
    and handed it every tool, including Bash.
    """
    harness = _harness()
    calls: list[list[str]] = []

    class FakeSandbox:
        mode = "host"

        def popen(self, argv):  # noqa: D102 - test double
            calls.append(argv)
            raise RuntimeError("stop here: the argv is what is under test")

    for tools, expect_flag in ((None, True), ([], False), (["Read"], True)):
        calls.clear()
        # run_claude may swallow the double's error and log it instead of
        # re-raising; either way the argv is already captured.
        with contextlib.suppress(Exception):
            harness.run_claude(FakeSandbox(), "hi", allowed_tools=tools)
        assert calls, "run_claude never built an argv"
        argv = calls[0]
        assert ("--allowed-tools" in argv) is expect_flag, (
            f"allowed_tools={tools!r} produced {argv}"
        )
        if tools:
            assert argv[argv.index("--allowed-tools") + 1 :][: len(tools)] == tools


def test_uv_cache_is_shared_across_containers() -> None:
    """A host volume, outside the workspace and outside the snapshot.

    The image sets `UV_CACHE_DIR`, but every container is `--rm` with no volume,
    so each `uv sync` re-downloaded the whole dependency set. The cache must
    also stay out of the workspace, or `collect_files()` grades it as code the
    agent wrote.
    """
    harness = _harness()
    cache = harness.uv_cache_dir()
    assert cache.is_dir()

    sandbox = harness.Sandbox(
        mode="docker", workspace=Path("/tmp/fz-ws"), source=Path("/tmp/fz-src")
    )
    argv = sandbox.wrap(["true"])
    assert f"{cache}:{harness.CONTAINER_UV_CACHE}" in argv
    assert f"UV_CACHE_DIR={harness.CONTAINER_UV_CACHE}" in argv
    assert cache not in Path("/tmp/fz-ws").parents and cache != Path("/tmp/fz-ws")


def test_no_suite_is_run_through_a_merging_glob() -> None:
    """`-c 'suites/*.yaml'` merges every suite into ONE cross-product eval.

    promptfoo runs provider x prompt x test across all merged configs, so four
    suites become 5 providers x 35 tests rather than 35 cases — most of them
    nonsense, all of them billed. The npm scripts and the workflow must loop.
    """

    def offending(text: str) -> list[str]:
        # Comments are where this trap gets *documented*, so a naive substring
        # search over the whole file flags the warning against itself.
        bad = []
        for line in text.splitlines():
            code = line.split("#", 1)[0]
            # package.json embeds shell in JSON, so its quotes arrive as `\"`.
            # Dropping backslashes first is what makes `-c \"suites/*.yaml\"`
            # visible to the same pattern as the bare form.
            code = code.replace("\\", "")
            if re.search(r"-c\s+['\"]?[^\s'\"]*\*[^\s'\"]*\.yaml", code):
                bad.append(line.strip())
        return bad

    package = offending((EVALS / "package.json").read_text())
    assert not package, f"an npm script globs suites into one eval: {package}"

    workflow = EVALS.parent / ".github" / "workflows" / "skill-evals.yml"
    if workflow.exists():
        text = workflow.read_text()
        assert not offending(text), (
            f"the workflow globs suites into one eval: {offending(text)}"
        )
        # A shell variable can smuggle the glob past a line-local check.
        assert "target='suites/*.yaml'" not in text
        assert 'target="suites/*.yaml"' not in text


@pytest.mark.parametrize("path", SUITES, ids=lambda p: p.name)
def test_worker_timeout_exceeds_the_harness_timeout(path: Path) -> None:
    """promptfoo's `timeout` (ms) must outlast the harness's `timeout_s`.

    They are two different clocks with confusingly similar names. `timeout_s` is
    a key `providers/claude_agent.py` reads; `timeout` is promptfoo's own
    PythonWorkerPool kill, in milliseconds, and unset it defaults to 300s. Two
    cases in the first real run died as "Python worker timed out after
    300000ms" while the suite believed it had allowed 1200s — and a worker kill
    reports no case, no trace and no reason, so it reads as a harness error
    rather than the budget being wrong.
    """
    for provider in _load(path).get("providers") or []:
        config = (provider or {}).get("config") or {}
        seconds = config.get("timeout_s")
        if seconds is None:
            continue
        millis = config.get("timeout")
        label = provider.get("label", provider.get("id"))
        assert millis is not None, (
            f"{path.name}:{label} sets timeout_s={seconds} but no promptfoo "
            "`timeout` — the worker is killed at 300s regardless"
        )
        assert millis > seconds * 1000, (
            f"{path.name}:{label} timeout={millis}ms does not outlast "
            f"timeout_s={seconds}s ({seconds * 1000}ms), so promptfoo kills the "
            "worker before the harness can report which case timed out and why"
        )
