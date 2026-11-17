"""The three skill-router arms, settled without a model or a container.

`evals/README.md` puts every rule that needs no model here, and the arms are
mostly that: which skills are mounted, what reaches `argv`, and which usage
figure is reported. Only the fraction that needs a live `claude` is left in
`tests/skill_router_eval/`.

The stream fixture is a real `claude -p` session with its identifiers redacted.
It is a file rather than a literal because the shapes it encodes — usage split
across `input_tokens` / `cache_creation_input_tokens` / `cache_read_input_tokens`,
and the `system`/`init` event carrying the model — are the API's, not ours.
"""

from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import shutil
import sys
from pathlib import Path

import pytest

EVALS = Path(__file__).resolve().parents[2] / "evals"
PROVIDERS = EVALS / "providers"
FIXTURE = Path(__file__).resolve().parent / "fixtures" / "assistant_usage.jsonl"

pytestmark = pytest.mark.skipif(
    not (PROVIDERS / "_harness.py").exists(), reason="evals/ is not present"
)


def _load(name: str, path: Path):
    """Load a provider module out-of-tree, registered before execution.

    Registration comes first because `_harness` declares dataclasses, and
    `@dataclass` resolves `sys.modules[cls.__module__]` while it runs.
    """
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    try:
        spec.loader.exec_module(module)
    except Exception:
        del sys.modules[name]
        raise
    return module


def _harness():
    return _load("_fz_harness_arms", PROVIDERS / "_harness.py")


def _agent():
    return _load("_fz_claude_agent_arms", PROVIDERS / "claude_agent.py")


class _RecordingSandbox:
    """A sandbox whose `popen` records the argv and refuses to spawn."""

    mode = "host"
    agent_home = None

    def __init__(self, lines: list[str] | None = None) -> None:
        self.argv: list[list[str]] = []
        self._lines = lines

    def popen(self, argv):
        self.argv.append(argv)
        if self._lines is None:
            raise RuntimeError("stop here: the argv is what is under test")
        return _FakeProc(self._lines)


class _FakeProc:
    returncode = 0

    def __init__(self, lines: list[str]) -> None:
        self.stdout = iter(lines)
        self.stderr = io.StringIO("")

    def wait(self, timeout=None):  # noqa: ANN001 - mirrors subprocess
        return self.returncode


def _stream_lines() -> list[str]:
    return FIXTURE.read_text().splitlines()


# --------------------------------------------------------------------------
# The mount: a selection is a treatment, not a filter
# --------------------------------------------------------------------------


def test_skills_selector_mounts_exactly_the_selection() -> None:
    harness = _harness()
    workspace, sandbox = harness.build_workspace(
        None, False, mode="host", skills=["functualize-app"]
    )
    try:
        skills_dir = workspace / ".claude" / "skills"
        assert sorted(p.name for p in skills_dir.iterdir()) == ["functualize-app"]
        assert (skills_dir / "functualize-app" / "SKILL.md").is_file()
    finally:
        shutil.rmtree(workspace, ignore_errors=True)
        shutil.rmtree(sandbox.agent_home, ignore_errors=True)


def test_empty_selection_mounts_nothing() -> None:
    """`none` is a real outcome: a task no skill improves should get no skill."""
    harness = _harness()
    workspace, sandbox = harness.build_workspace(None, True, mode="host", skills=[])
    try:
        assert not (workspace / ".claude" / "skills").exists()
    finally:
        shutil.rmtree(workspace, ignore_errors=True)
        shutil.rmtree(sandbox.agent_home, ignore_errors=True)


def test_no_selection_keyword_keeps_the_ablation_switch() -> None:
    """`skills=None` is every suite that predates the router, byte for byte."""
    harness = _harness()
    workspace, sandbox = harness.build_workspace(None, True, mode="host")
    try:
        mounted = sorted(p.name for p in (workspace / ".claude" / "skills").iterdir())
        assert mounted == sorted(harness.SKILLS)
    finally:
        shutil.rmtree(workspace, ignore_errors=True)
        shutil.rmtree(sandbox.agent_home, ignore_errors=True)


def test_unknown_skill_name_is_a_loud_error() -> None:
    harness = _harness()
    with pytest.raises(FileNotFoundError):
        harness.build_workspace(
            None, False, mode="host", skills=["functualize-nonexistent"]
        )


# --------------------------------------------------------------------------
# The prompt and the argv
# --------------------------------------------------------------------------


def test_appended_prompt_reaches_argv() -> None:
    harness = _harness()
    sandbox = _RecordingSandbox()
    body = "## Skill: functualize-app\n\nrules"
    with contextlib.suppress(RuntimeError):
        harness.run_claude(sandbox, "hi", append_system_prompt=body)
    argv = sandbox.argv[0]
    assert argv[-2:] == ["--append-system-prompt", body]


def test_no_appended_prompt_leaves_argv_as_it_was() -> None:
    harness = _harness()
    sandbox = _RecordingSandbox()
    with contextlib.suppress(RuntimeError):
        harness.run_claude(sandbox, "hi")
    argv = sandbox.argv[0]
    assert argv == [
        "claude",
        "-p",
        "hi",
        "--output-format",
        "stream-json",
        "--verbose",
        "--setting-sources",
        "project",
        "--permission-mode",
        "bypassPermissions",
        "--max-turns",
        str(harness.DEFAULT_MAX_TURNS),
        "--allowed-tools",
        *harness.DEFAULT_ALLOWED_TOOLS,
    ]


def test_skill_bodies_are_headed_and_complete() -> None:
    harness = _harness()
    names = list(harness.SKILLS)
    bodies = harness.skill_bodies(names)
    for name in names:
        assert f"## Skill: {name}" in bodies
        # The whole SKILL.md body, not an excerpt: that is the arm's treatment.
        first_line = (harness.SKILLS_DIR / name / "SKILL.md").read_text().strip()
        assert first_line.splitlines()[-1] in bodies


# --------------------------------------------------------------------------
# What a run reports
# --------------------------------------------------------------------------


def test_first_turn_tokens_come_from_the_first_usage_only() -> None:
    """Later turns re-send the transcript; summing them measures the wrong arm."""
    harness = _harness()
    second = json.loads(_stream_lines()[0])
    second["message"]["usage"] = {
        "input_tokens": 1000,
        "cache_creation_input_tokens": 0,
        "cache_read_input_tokens": 0,
    }
    lines = [*_stream_lines(), json.dumps(second)]

    run = harness.run_claude(_RecordingSandbox(lines), "hi")

    assert run.first_turn_input_tokens == 2 + 37723 + 16792
    assert run.model == "claude-sonnet-5"
    assert run.duration_s >= 0.0


# --------------------------------------------------------------------------
# The arms themselves
# --------------------------------------------------------------------------


@pytest.fixture
def agent(monkeypatch, tmp_path):
    """`claude_agent` with its effects replaced by recorders."""
    module = _agent()
    seen: dict = {"skills": "unset", "prompt": "unset", "built": False, "ran": False}

    def fake_build(fixture, with_skills, mode="host", *, skills=None):
        seen["built"] = True
        seen["skills"] = skills
        # A subdirectory, not tmp_path itself: the provider's `finally` removes
        # the workspace, and the selections file lives in tmp_path.
        workspace = tmp_path / "workspace"
        workspace.mkdir(exist_ok=True)
        return workspace, type("S", (), {"agent_home": None, "mode": mode})()

    def fake_run(sandbox, prompt, *, append_system_prompt=None, **kwargs):
        seen["ran"] = True
        seen["prompt"] = append_system_prompt
        return _harness().AgentRun()

    monkeypatch.setattr(module, "build_workspace", fake_build)
    monkeypatch.setattr(module, "run_claude", fake_run)
    monkeypatch.setattr(module, "run_check", lambda *a, **k: {"exit_code": 0})
    monkeypatch.setattr(module, "collect_files", lambda workspace: {})
    for name in ("FZ_EVAL_MODEL", "FZ_EVAL_SANDBOX", "FZ_SKILL_ROUTER_SELECTIONS"):
        monkeypatch.delenv(name, raising=False)
    return module, seen, tmp_path


def _selections(tmp_path: Path, cases: dict) -> Path:
    path = tmp_path / "selections.json"
    path.write_text(json.dumps({"cases": cases, "catalog_sha256": "0" * 64}))
    return path


def _call(module, config: dict, case: str | None = "d1") -> dict:
    variables = {"fixture": "uv-mise-repo"} if case is None else {"case": case}
    return module.call_api("hi", {"config": config}, {"vars": variables})


def test_load_everything_mounts_all_and_appends_all(agent) -> None:
    module, seen, _ = agent
    result = _call(module, {"arm": "load-everything", "model": "claude-sonnet-5"})

    assert sorted(seen["skills"]) == sorted(module.SKILLS)
    assert seen["prompt"].count("## Skill: ") == len(module.SKILLS)
    assert result["output"]["arm"] == "load-everything"


def test_native_arm_is_the_ablation_switch(agent) -> None:
    module, seen, _ = agent
    result = _call(module, {"arm": "native", "model": "claude-sonnet-5"})

    assert seen["skills"] is None
    assert seen["prompt"] is None
    assert result["output"]["arm"] == "native"


def test_router_arm_mounts_and_appends_the_selection(
    agent, monkeypatch, tmp_path
) -> None:
    module, seen, _ = agent
    monkeypatch.setenv(
        "FZ_SKILL_ROUTER_SELECTIONS",
        str(_selections(tmp_path, {"d1": {"outcome": "functualize-app"}})),
    )

    result = _call(module, {"arm": "router", "model": "claude-sonnet-5"})

    assert seen["skills"] == ["functualize-app"]
    assert seen["prompt"].startswith("## Skill: functualize-app")
    assert result["output"]["router_outcome"] == "functualize-app"


def test_router_none_mounts_nothing_and_escalated_is_native(
    agent, monkeypatch, tmp_path
) -> None:
    module, seen, _ = agent
    selections = _selections(
        tmp_path,
        {"d1": {"outcome": "none"}, "d2": {"outcome": "escalated"}},
    )
    monkeypatch.setenv("FZ_SKILL_ROUTER_SELECTIONS", str(selections))

    _call(module, {"arm": "router", "model": "claude-sonnet-5"}, case="d1")
    assert seen["skills"] == []
    assert seen["prompt"] is None

    _call(module, {"arm": "router", "model": "claude-sonnet-5"}, case="d2")
    assert seen["skills"] is None
    assert seen["prompt"] is None


def test_router_without_a_selection_for_the_case_is_an_error(
    agent, monkeypatch, tmp_path
) -> None:
    """A silent fallback to native would make the arm indistinguishable."""
    module, seen, _ = agent
    monkeypatch.setenv(
        "FZ_SKILL_ROUTER_SELECTIONS",
        str(_selections(tmp_path, {"d1": {"outcome": "functualize"}})),
    )

    result = _call(module, {"arm": "router", "model": "claude-sonnet-5"}, case="d9")

    assert "d9" in result["error"]
    assert not seen["built"]


def test_router_without_the_selections_file_is_an_error(agent) -> None:
    module, seen, _ = agent
    result = _call(module, {"arm": "router", "model": "claude-sonnet-5"})

    assert "FZ_SKILL_ROUTER_SELECTIONS" in result["error"]
    assert not seen["built"]


def test_an_arm_refuses_a_diverging_env_model(agent, monkeypatch) -> None:
    module, seen, _ = agent
    monkeypatch.setenv("FZ_EVAL_MODEL", "some-other-model")

    result = _call(module, {"arm": "native", "model": "claude-sonnet-5"})

    assert result["error"].startswith("override refused")
    # Both spawn paths — building a workspace and starting `claude` — are
    # untouched: the refusal is the only thing that happened.
    assert not seen["built"]
    assert not seen["ran"]


def test_an_arm_refuses_a_diverging_env_sandbox(agent, monkeypatch) -> None:
    module, seen, _ = agent
    monkeypatch.setenv("FZ_EVAL_SANDBOX", "host")

    result = _call(
        module, {"arm": "native", "model": "claude-sonnet-5", "sandbox": "docker"}
    )

    assert result["error"].startswith("override refused")
    assert not seen["built"]
    assert not seen["ran"]


def test_unknown_arm_is_an_error(agent) -> None:
    module, seen, _ = agent
    result = _call(module, {"arm": "hybrid", "model": "claude-sonnet-5"})

    assert "hybrid" in result["error"]
    assert not seen["built"]


def test_no_arm_leaves_the_output_as_it_was(agent) -> None:
    """The existing suites read this output; the new keys are arm-only."""
    module, seen, _ = agent
    result = _call(module, {"with_skills": True, "model": "claude-sonnet-5"})

    assert seen["skills"] is None
    assert result["output"]["arm"] == "with-skills"
    assert "first_turn_input_tokens" not in result["output"]
    assert "router_outcome" not in result["output"]


# --------------------------------------------------------------------------
# The suite itself: a copied case that has drifted is a new case
# --------------------------------------------------------------------------

# case -> (source suite, source description, the skill B-19 expects)
SOURCES = {
    "d1": (
        "functualize.yaml",
        "uses Secret for a credential instead of a plain string",
        "functualize",
    ),
    "d2": (
        "functualize.yaml",
        "diagnoses a silently undiscovered job via the CLI, not by guessing",
        "functualize",
    ),
    "d3": (
        "functualize-app.yaml",
        "reaches for JobConfig rather than a pile of flags",
        "functualize-app",
    ),
    "d4": (
        "functualize-app.yaml",
        "standalone — one file with a PEP 723 header, not a scaffolded project",
        "functualize-app",
    ),
    "d5": (
        "functualize-skill.yaml",
        "authors a skill whose script runs and whose frontmatter is legal",
        "functualize-skill",
    ),
}


def test_each_case_is_its_source_case_field_for_field() -> None:
    """The router measures routing, so its tasks must be the ones we already run.

    A case that quietly diverged would still pass — it would just be measuring a
    different task than the suite it claims to reuse.
    """
    yaml = pytest.importorskip("yaml")
    suite = yaml.safe_load((EVALS / "suites" / "skill-router.yaml").read_text())
    ours = {test["vars"]["case"]: test for test in suite["tests"]}
    assert sorted(ours) == sorted(SOURCES)

    for case, (source, description, expected) in SOURCES.items():
        original = [
            test
            for test in yaml.safe_load((EVALS / "suites" / source).read_text())["tests"]
            if test["description"] == description
        ]
        assert len(original) == 1, f"{source} has no unique case {description!r}"

        test = ours[case]
        assert test["description"] == description
        assert test["vars"]["expect"] == expected
        assert {
            key: value
            for key, value in test["vars"].items()
            if key not in {"case", "expect"}
        } == original[0]["vars"]
        assert test["assert"] == original[0]["assert"]
