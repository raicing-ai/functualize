"""Shared plumbing for the skill evals.

Every provider here runs a real `claude -p` session inside a throwaway
workspace, then reports what the agent *did* (tool calls, skills loaded) and
what its output *does* (verification commands run against the workspace).

The ablation is the whole point: the same prompt runs in a workspace that has
`skills/` mounted and in one that does not. `--setting-sources project` keeps
the operator's own `~/.claude/skills` out of both arms, so the only difference
between them is this repo's skills.

Three containment measures, because an eval runs unattended with
`bypassPermissions` and Bash:

1. Fixtures depend on a **snapshot** of the repo, never the live worktree, and
   never as an editable install. An agent that misdiagnoses a fixture bug as a
   framework bug edits the copy.
2. The child process gets an **allowlisted** environment, not `os.environ`.
3. With `sandbox: docker`, the agent and the verification commands both run in
   a container with the snapshot mounted read-only. See `evals/docker/`.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

EVALS_DIR = Path(__file__).resolve().parent.parent
REPO_ROOT = EVALS_DIR.parent
SKILLS_DIR = REPO_ROOT / "skills"
FIXTURES_DIR = EVALS_DIR / "fixtures"

# Kept low on purpose: a runaway agent is a cost incident, not a data point.
DEFAULT_MAX_TURNS = 30
DEFAULT_TIMEOUT_S = 900

# Enough to do real work, nothing that reaches the operator's machine outside
# the workspace.
DEFAULT_ALLOWED_TOOLS = ["Bash", "Read", "Write", "Edit", "Glob", "Grep", "Skill"]

# Non-credential variables passed through to the agent. Anything not named
# here does not reach it — no cloud credentials, no SSH agent socket, no
# GH_TOKEN.
BASE_ENV_ALLOWLIST = (
    "ANTHROPIC_BASE_URL",
    "LANG",
    "LC_ALL",
    "PATH",
    "TERM",
    "TZ",
)

# Mutually exclusive ways to authenticate, in the order the harness prefers
# them. `claude` itself picks ANTHROPIC_API_KEY when several are set, so
# forwarding all of them silently defeats a deliberately-exported subscription
# token: the stale key in a shell profile wins and the run 401s. Exactly one is
# forwarded, and which one is reported.
CREDENTIAL_VARS = (
    "CLAUDE_CODE_OAUTH_TOKEN",
    "ANTHROPIC_API_KEY",
    "ANTHROPIC_AUTH_TOKEN",
)

# Back-compat for callers that just want to display what may be passed.
ENV_ALLOWLIST = tuple(sorted(BASE_ENV_ALLOWLIST + CREDENTIAL_VARS))


def select_credential() -> str | None:
    """The single credential variable to forward, or None.

    `FZ_EVAL_AUTH` forces a choice by variable name (or its short forms
    `oauth` / `api-key`). Otherwise a subscription token wins over an API key,
    because the harness tells subscription users to export it and a leftover
    `ANTHROPIC_API_KEY` in a shell profile is the usual accident.
    """
    forced = os.environ.get("FZ_EVAL_AUTH", "").strip()
    if forced:
        alias = {
            "oauth": "CLAUDE_CODE_OAUTH_TOKEN",
            "subscription": "CLAUDE_CODE_OAUTH_TOKEN",
            "api-key": "ANTHROPIC_API_KEY",
            "apikey": "ANTHROPIC_API_KEY",
        }.get(forced.lower(), forced)
        if alias not in CREDENTIAL_VARS:
            raise RuntimeError(
                f"FZ_EVAL_AUTH={forced!r} is not one of "
                f"{', '.join(CREDENTIAL_VARS)} (or 'oauth' / 'api-key')"
            )
        if not os.environ.get(alias):
            raise RuntimeError(f"FZ_EVAL_AUTH selects {alias}, but it is not set")
        return alias

    for name in CREDENTIAL_VARS:
        if os.environ.get(name):
            return name
    return None


def credential_conflicts() -> list[str]:
    """Credential variables that are set but will NOT be forwarded."""
    chosen = select_credential()
    return [n for n in CREDENTIAL_VARS if os.environ.get(n) and n != chosen]


CONTAINER_IMAGE = os.environ.get("FZ_EVAL_IMAGE", "functualize-evals:latest")
CONTAINER_SOURCE = "/src"
CONTAINER_WORKSPACE = "/work"
CONTAINER_UV_CACHE = "/tmp/uv-cache"


def uv_cache_dir() -> Path:
    """Host directory backing the containers' shared uv cache.

    Outside the workspace and outside the snapshot: it must survive `--rm` and
    be shared by every concurrent worker, and it must not end up in
    `collect_files()` and be graded as something the agent wrote.
    """
    path = Path(
        os.environ.get(
            "FZ_EVAL_UV_CACHE", Path(tempfile.gettempdir()) / "fz-eval-uv-cache"
        )
    )
    path.mkdir(parents=True, exist_ok=True)
    return path


# --------------------------------------------------------------------------
# Source snapshot
# --------------------------------------------------------------------------

SNAPSHOT_ROOT = Path(os.environ.get("FZ_EVAL_SNAPSHOT_DIR", tempfile.gettempdir()))
_SNAPSHOT: Path | None = None


# What a fixture's `functualize @ path` dependency actually needs to build, and
# nothing else. Mirrors pyproject's sdist `only-include`, plus the two files a
# path build reads.
#
# The snapshot used to be the whole working tree, which handed every agent a
# read-only checkout at /src: evals/ (including the suites that grade it),
# examples/, plugins/, contributor/, docs/. Traces from the first real run show
# agents reading /src/examples and /src/skills rather than asking the installed
# app about itself, and one opened /src/evals/suites — the answer key. A skill
# that only works with the framework's source tree mounted is not the skill we
# are measuring: a real user has site-packages and nothing else.
SNAPSHOT_INCLUDE = (
    "src/functualize",
    "skills",
    "pyproject.toml",
    "uv.lock",
    "README.md",
    "LICENSE",
    "CHANGELOG.md",
    # The root pyproject declares a uv workspace over `plugins/*` and points
    # `tool.uv.sources` at every member, so uv refuses to resolve *anything*
    # unless it can see them: "references a workspace in tool.uv.sources but is
    # not a workspace member". Their manifests are enough for that — no fixture
    # installs a plugin extra, so no plugin is ever built and their source
    # stays out of /src. Add `plugins/<name>/src` here if a fixture ever needs
    # one.
    "plugins/*/pyproject.toml",
)


def _tracked_files() -> list[str]:
    """The installable subset of the working tree, minus ignored junk.

    Still `ls-files --others`, so uncommitted framework changes are under test;
    narrowed by pathspec, so the rest of the repo is not the agent's to read.
    """
    listing = subprocess.run(
        [
            "git",
            "-C",
            str(REPO_ROOT),
            "ls-files",
            "-z",
            "--cached",
            "--others",
            "--exclude-standard",
            "--",
            *SNAPSHOT_INCLUDE,
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    return [p for p in listing.stdout.split("\0") if p]


def _fingerprint(paths: list[str]) -> str:
    """Content key for the snapshot: path + size + mtime of every file.

    Cheap (one stat each) and sensitive to edits that leave `git status`
    unchanged, which a HEAD-plus-porcelain key would miss.
    """
    digest = hashlib.sha256(str(REPO_ROOT).encode())
    for relative in paths:
        try:
            stat = (REPO_ROOT / relative).stat()
        except OSError:
            continue
        digest.update(f"{relative}:{stat.st_size}:{stat.st_mtime_ns}".encode())
    return digest.hexdigest()[:16]


def source_snapshot() -> Path:
    """A disposable copy of the repo for fixtures to depend on.

    Never the live worktree: an agent that decides to "fix the framework" edits
    this copy and the real checkout is untouched.

    Shared across processes. promptfoo forks a worker per concurrent call, so a
    module-global cache misses every time and six workers would each copy the
    repo. The directory is keyed by a content fingerprint, so concurrent
    workers converge on one copy and a later run reuses it until the source
    actually changes.
    """
    global _SNAPSHOT
    if _SNAPSHOT is not None and (_SNAPSHOT / ".fz-ready").exists():
        return _SNAPSHOT

    paths = _tracked_files()
    destination = SNAPSHOT_ROOT / f"fz-eval-src-{_fingerprint(paths)}"
    ready = destination / ".fz-ready"

    if ready.exists():
        _SNAPSHOT = destination
        return destination

    # Elect exactly one builder; the rest wait for the marker.
    staging = destination.with_name(destination.name + f".build-{os.getpid()}")
    try:
        destination.mkdir(parents=True, exist_ok=False)
        winner = True
    except FileExistsError:
        winner = False

    if not winner:
        for _ in range(600):  # up to 5 minutes
            if ready.exists():
                _SNAPSHOT = destination
                return destination
            time.sleep(0.5)
        raise RuntimeError(f"Timed out waiting for a source snapshot at {destination}")

    log_progress(f"snapshot building ({len(paths)} files)…")
    began = time.monotonic()
    for relative in paths:
        source = REPO_ROOT / relative
        if not source.is_file():  # submodule entries, deleted-but-staged paths
            continue
        target = staging / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)

    # Publish atomically-ish: fill the claimed directory, then mark it ready.
    for item in staging.iterdir():
        shutil.move(str(item), str(destination / item.name))
    shutil.rmtree(staging, ignore_errors=True)
    ready.write_text(time.strftime("%Y-%m-%dT%H:%M:%S"))

    _SNAPSHOT = destination
    log_progress(
        f"snapshot ready in {time.monotonic() - began:.0f}s → {destination.name}"
    )
    _reap_stale_snapshots(destination)
    return destination


def _reap_stale_snapshots(keep: Path, max_age_hours: float = 24.0) -> None:
    """Delete snapshots from earlier source states.

    The fingerprint key means every edit to the framework mints a fresh one, so
    a day of iterating leaves a pile of ~380-file copies in $TMPDIR. Only the
    builder reaps, only *ready* snapshots older than a day, and never the
    current one — a run in flight is holding an older directory open and must
    not have it pulled out from under it.
    """
    cutoff = time.time() - max_age_hours * 3600
    for candidate in SNAPSHOT_ROOT.glob("fz-eval-src-*"):
        if candidate == keep or not candidate.is_dir():
            continue
        marker = candidate / ".fz-ready"
        try:
            if not marker.exists() or marker.stat().st_mtime > cutoff:
                continue
            shutil.rmtree(candidate, ignore_errors=True)
        except OSError:
            continue  # someone else's, or racing us — leave it


# --------------------------------------------------------------------------
# Progress
# --------------------------------------------------------------------------

LOG_PATH = Path(os.environ.get("FZ_EVAL_LOG", EVALS_DIR / "results" / "progress.log"))

# promptfoo forks a worker process per concurrent call and prefixes every line
# with "Python worker stderr: ", which eats ~22 columns. Lines are therefore
# kept short, and tagged with the worker's pid so interleaved output from six
# concurrent cases can still be followed.
_WORKER = f"w{os.getpid() % 10000:04d}"


def log_progress(message: str) -> None:
    """Say what is happening, to stderr and to a tailable file.

    A case is a minute of silence otherwise: promptfoo's bar advances only on
    completion, so a run that is working and a run that is wedged look
    identical. `npm run watch` tails the file.

    Wall clock, never elapsed-since-process-start: each worker is a fresh
    process, so a per-process clock reads ~0s on every line and tells you
    nothing about how long the run has been going.
    """
    line = f"{time.strftime('%H:%M:%S')} {_WORKER} {message}"
    print(line, file=sys.stderr, flush=True)
    try:
        LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        with LOG_PATH.open("a", encoding="utf-8") as handle:
            handle.write(line + "\n")
    except OSError:
        pass  # progress reporting must never fail a run


# --------------------------------------------------------------------------
# Sandboxing
# --------------------------------------------------------------------------

SANDBOX_MODES = ("host", "docker")


def resolve_sandbox_mode(config_value: object, default: str) -> str:
    """Decide where a run happens. `FZ_EVAL_SANDBOX` wins over the suite YAML.

    The env var is the operator's override, so it has to beat a `sandbox:` key
    baked into a suite — otherwise it is documented but inert, which is worse
    than not offering it. A typo raises rather than silently falling back to
    the host: `FZ_EVAL_SANDBOX=Docker` quietly running unconfined is exactly
    the failure this knob exists to prevent.
    """
    override = os.environ.get("FZ_EVAL_SANDBOX")
    chosen = (
        override or (config_value if isinstance(config_value, str) else None) or default
    )
    chosen = chosen.strip().lower()

    if chosen not in SANDBOX_MODES:
        source = "FZ_EVAL_SANDBOX" if override else "the suite's `sandbox:` key"
        raise RuntimeError(
            f"Unknown sandbox mode {chosen!r} from {source}; "
            f"expected one of {', '.join(SANDBOX_MODES)}"
        )
    return chosen


def container_engine() -> str:
    """Prefer rootless podman; fall back to docker."""
    override = os.environ.get("FZ_EVAL_ENGINE")
    if override:
        return override
    for candidate in ("podman", "docker"):
        if shutil.which(candidate):
            return candidate
    raise RuntimeError(
        "sandbox: docker was requested but neither podman nor docker is on PATH"
    )


def resolve_image(engine: str, image: str = CONTAINER_IMAGE) -> str:
    """The name this engine will actually accept for a locally built image.

    podman refuses an unqualified short name ("did not resolve to an alias and
    no unqualified-search registries are defined") and stores local builds
    under `localhost/`. docker uses the bare name. Rather than encode that
    rule, ask the engine which spelling it has.
    """
    candidates = [image] if "/" in image else [image, f"localhost/{image}"]
    for candidate in candidates:
        probe = subprocess.run(
            [engine, "image", "inspect", candidate], capture_output=True
        )
        if probe.returncode == 0:
            return candidate
    return image  # let the run fail with the engine's own message


@dataclass
class Sandbox:
    """Where a command runs. `mode` is 'host' or 'docker'."""

    mode: str = "host"
    workspace: Path = Path()
    source: Path = Path()
    agent_home: Path | None = None

    @property
    def source_mountpoint(self) -> str:
        """The path fixtures should reference for the functualize source."""
        return CONTAINER_SOURCE if self.mode == "docker" else str(self.source)

    def wrap(self, argv: list[str]) -> list[str]:
        if self.mode != "docker":
            return argv
        engine = container_engine()
        command = [
            engine,
            "run",
            "--rm",
            "--interactive=false",
            "--network",
            "bridge",
            "--security-opt",
            "no-new-privileges",
            "--memory",
            os.environ.get("FZ_EVAL_MEMORY", "4g"),
            "--pids-limit",
            "512",
            "-v",
            f"{self.workspace}:{CONTAINER_WORKSPACE}",
            "-w",
            CONTAINER_WORKSPACE,
            "-e",
            "HOME=/tmp/agent",
            # A shared, writable uv cache. The Dockerfile sets UV_CACHE_DIR
            # inside the image, but every container is `--rm` with no volume,
            # so each `uv sync` re-downloaded the whole dependency set — ~7s
            # and ~40 MB per case, times every case times every repeat.
            "-v",
            f"{uv_cache_dir()}:{CONTAINER_UV_CACHE}",
            "-e",
            f"UV_CACHE_DIR={CONTAINER_UV_CACHE}",
        ]
        if self.source != Path():
            # Read-only: even the snapshot is not the agent's to edit.
            command += ["-v", f"{self.source}:{CONTAINER_SOURCE}:ro"]
        # The agent must not be root inside the container: Claude Code refuses
        # `--permission-mode bypassPermissions` under uid 0, and rootless
        # podman maps the caller to root by default, so the default is exactly
        # the broken case.
        if engine == "podman":
            # keep-id maps the caller to the *same* uid inside, which both
            # avoids root and keeps bind-mounted files owned by them.
            command += ["--userns", "keep-id"]
        else:
            # docker would otherwise leave root-owned files in the bind mount.
            command += ["--user", f"{os.getuid()}:{os.getgid()}"]
        # Same single-credential rule inside the container: `-e NAME` without a
        # value forwards it from this process's environment.
        forwarded = [n for n in BASE_ENV_ALLOWLIST if n != "PATH" and n in os.environ]
        chosen = select_credential()
        if chosen:
            forwarded.append(chosen)
        for name in forwarded:
            command += ["-e", name]
        command.append(resolve_image(engine))
        return command + argv

    def launch_env(self) -> dict[str, str]:
        """The environment for the command we actually spawn.

        Under docker that command is `podman`/`docker`, not the agent — and the
        engine needs the operator's own environment to work at all. Rootless
        podman locates its image store under `$HOME`, so handing it a throwaway
        HOME makes every local image invisible and it tries to *pull* instead,
        failing with an unqualified-short-name error that looks nothing like
        the actual cause.

        The agent's own environment is unaffected: the `-e` flags in `wrap()`
        forward exactly the allowlist into the container, and the container
        sets `HOME=/tmp/agent` for the process inside.
        """
        if self.mode != "docker":
            return child_env(self.agent_home)
        env = {**os.environ}
        env.pop("CLAUDECODE", None)
        env.pop("CLAUDE_CODE_ENTRYPOINT", None)
        return env

    def run(self, argv: list[str], timeout_s: int) -> subprocess.CompletedProcess:
        return subprocess.run(
            self.wrap(argv),
            cwd=self.workspace if self.mode == "host" else None,
            env=self.launch_env(),
            # Never inherit stdin: `claude` waits on it and the run looks hung.
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            timeout=timeout_s,
        )

    def popen(self, argv: list[str]) -> subprocess.Popen:
        """Line-buffered, for streaming a long run's output as it arrives.

        `start_new_session` puts the child in its own process group so the
        whole tree can be killed. Killing only the direct child leaves its
        grandchildren — `claude` shells out constantly — holding the stdout
        pipe open, and the reader blocks forever on a timeout that already
        fired.
        """
        return subprocess.Popen(
            self.wrap(argv),
            cwd=self.workspace if self.mode == "host" else None,
            env=self.launch_env(),
            # Never inherit stdin: `claude` waits on it and the run looks hung.
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
            start_new_session=True,
        )


def child_env(agent_home: Path | None = None) -> dict[str, str]:
    """An allowlisted environment — never a copy of the operator's shell.

    `HOME` is mandatory even though it is not on the allowlist: without one,
    `claude` cannot resolve its config directory and blocks waiting for
    interactive auth, which reads as a timeout with no diagnostic. It points at
    a throwaway directory so the agent still cannot see the operator's
    `~/.claude` — unless `FZ_EVAL_INHERIT_HOME=1` is set, which trades that
    isolation for the convenience of an existing `claude` login.
    """
    env = {name: os.environ[name] for name in BASE_ENV_ALLOWLIST if name in os.environ}
    env.setdefault("PATH", "/usr/local/bin:/usr/bin:/bin")

    # Exactly one credential, never the whole set — see CREDENTIAL_VARS.
    chosen = select_credential()
    if chosen:
        env[chosen] = os.environ[chosen]

    if os.environ.get("FZ_EVAL_INHERIT_HOME") == "1" and os.environ.get("HOME"):
        env["HOME"] = os.environ["HOME"]
    else:
        env["HOME"] = str(agent_home or Path(tempfile.gettempdir()) / "fz-eval-home")
    Path(env["HOME"]).mkdir(parents=True, exist_ok=True)

    # A nested session would otherwise confuse the child.
    env.pop("CLAUDECODE", None)
    env.pop("CLAUDE_CODE_ENTRYPOINT", None)
    return env


def has_credential() -> bool:
    return bool(select_credential()) or os.environ.get("FZ_EVAL_INHERIT_HOME") == "1"


# --------------------------------------------------------------------------
# Agent runs
# --------------------------------------------------------------------------


@dataclass
class AgentRun:
    """What one `claude -p` session did."""

    text: str = ""
    tool_calls: list[dict] = field(default_factory=list)
    skills_loaded: list[str] = field(default_factory=list)
    num_turns: int = 0
    cost_usd: float = 0.0
    error: str | None = None
    # Set when the stream reports something no amount of waiting will fix, so
    # the run can be abandoned instead of sitting out the retry schedule.
    fatal: str | None = None

    def bash_commands(self) -> list[str]:
        return [
            call["input"].get("command", "")
            for call in self.tool_calls
            if call["name"] == "Bash" and isinstance(call.get("input"), dict)
        ]

    def used_tool(self, name: str) -> bool:
        return any(call["name"] == name for call in self.tool_calls)


def build_workspace(
    fixture: str | None, with_skills: bool, mode: str = "host"
) -> tuple[Path, Sandbox]:
    """Create a temp workspace, optionally seeded from a fixture and skills."""
    workspace = Path(tempfile.mkdtemp(prefix="fz-eval-"))
    # Beside the workspace, not inside it: agent HOME junk must not show up
    # in collect_files() and be graded as something the agent authored.
    agent_home = Path(str(workspace) + "-home")
    agent_home.mkdir(exist_ok=True)
    # Only a fixture needs the source: it is what `{{REPO_ROOT}}` resolves to.
    # The grader builds a workspace with no fixture, and used to pay for (and
    # mount) a whole snapshot to hold nothing.
    sandbox = Sandbox(
        mode=mode,
        workspace=workspace,
        source=source_snapshot() if fixture else Path(),
        agent_home=agent_home,
    )

    if fixture:
        source = FIXTURES_DIR / fixture
        if not source.is_dir():
            raise FileNotFoundError(f"No such fixture: {source}")
        shutil.copytree(source, workspace, dirs_exist_ok=True)
        _expand_tokens(workspace, sandbox.source_mountpoint)

    claude_dir = workspace / ".claude"
    claude_dir.mkdir(exist_ok=True)

    if with_skills:
        # Copy rather than symlink: file tools may refuse to follow links that
        # leave the working directory, and a container would not see them.
        shutil.copytree(SKILLS_DIR, claude_dir / "skills", dirs_exist_ok=True)

    # Project settings only; nothing inherited from the operator.
    (claude_dir / "settings.json").write_text(
        json.dumps({"permissions": {"defaultMode": "bypassPermissions"}}, indent=2)
    )
    return workspace, sandbox


def _expand_tokens(workspace: Path, source_path: str) -> None:
    """Rewrite `{{REPO_ROOT}}` in copied fixtures to the snapshot path.

    Fixtures depend on functualize by path, and that path differs per run — a
    temp snapshot on the host, `/src` inside a container — so it cannot be
    committed literally.
    """
    for path in workspace.rglob("*"):
        if not path.is_file() or path.suffix not in {
            ".toml",
            ".cfg",
            ".ini",
            ".txt",
            ".md",
        }:
            continue
        try:
            body = path.read_text()
        except (UnicodeDecodeError, OSError):
            continue
        if "{{REPO_ROOT}}" in body:
            path.write_text(body.replace("{{REPO_ROOT}}", source_path))


def _kill_tree(proc: subprocess.Popen) -> None:
    """Kill the child and everything it spawned.

    A container run is `podman run` holding a pipe for the whole container, and
    a host run is `claude` with a tree of tool subprocesses. Either way the
    grandchildren keep stdout open, so signalling the process group is the only
    thing that actually ends the read.
    """
    try:
        os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
    except (ProcessLookupError, PermissionError, OSError):
        with contextlib.suppress(OSError):
            proc.kill()


def run_claude(
    sandbox: Sandbox,
    prompt: str,
    *,
    model: str | None = None,
    max_turns: int = DEFAULT_MAX_TURNS,
    allowed_tools: list[str] | None = None,
    timeout_s: int = DEFAULT_TIMEOUT_S,
) -> AgentRun:
    """Run one headless Claude Code session and parse its event stream."""
    argv = [
        "claude",
        "-p",
        prompt,
        "--output-format",
        "stream-json",
        "--verbose",
        "--setting-sources",
        "project",
        "--permission-mode",
        "bypassPermissions",
        "--max-turns",
        str(max_turns),
    ]
    # `[]` is a deliberate "no tools at all" — the grader passes it so a rubric
    # verdict cannot be reached by going and looking at the workspace. `or`
    # treated that as unset and handed it the full Bash-enabled toolset.
    tools = DEFAULT_ALLOWED_TOOLS if allowed_tools is None else allowed_tools
    if tools:
        argv += ["--allowed-tools", *tools]
    if model:
        argv += ["--model", model]

    run = AgentRun()
    label = " ".join(prompt.split())[:44]
    log_progress(f"▶ agent [{sandbox.mode}] {label}…")
    began = time.monotonic()

    # Streamed, not captured: `claude -p` emits one JSON event per line as it
    # works, so reading them live is the difference between a minute of silence
    # and a running commentary of what the agent is doing.
    try:
        proc = sandbox.popen(argv)
    except (OSError, RuntimeError) as exc:
        run.error = str(exc)
        log_progress(f"✖ agent ERROR {exc}")
        return run

    # A watchdog, not an in-loop check: a `claude` that emits nothing at all —
    # the shape every hang takes — never returns from the read, so a timeout
    # tested inside the loop would never fire.
    timed_out = threading.Event()

    def _reap() -> None:
        timed_out.set()
        log_progress(f"✖ agent TIMEOUT after {timeout_s}s — killing")
        _kill_tree(proc)

    watchdog = threading.Timer(timeout_s, _reap)
    watchdog.daemon = True
    watchdog.start()

    assert proc.stdout is not None
    try:
        for line in proc.stdout:
            line = line.strip()
            if not line.startswith("{"):
                continue
            with contextlib.suppress(json.JSONDecodeError):
                _absorb(run, json.loads(line), announce=True)
            if run.fatal:
                log_progress(f"✖ agent {run.fatal}")
                _kill_tree(proc)
                run.error = run.fatal
                return run
        proc.wait(timeout=30)
    except subprocess.TimeoutExpired:
        proc.kill()
    finally:
        watchdog.cancel()

    if timed_out.is_set():
        run.error = f"timeout after {timeout_s}s"
        return run

    if not run.text and proc.returncode != 0:
        stderr = (proc.stderr.read() if proc.stderr else "") or ""
        run.error = stderr.strip()[:2000] or f"exit {proc.returncode}"

    mark = "✖" if run.error else "✔"
    skills = ",".join(run.skills_loaded) or "none"
    log_progress(
        f"{mark} agent {time.monotonic() - began:.0f}s · {run.num_turns} turns · "
        f"${run.cost_usd:.3f} · {len(run.tool_calls)} calls · skills={skills}"
        + (f" · {run.error[:80]}" if run.error else "")
    )
    return run


def _describe(name: str, tool_input: dict) -> str:
    """One short line for a tool call — the part a watcher actually wants."""
    if name == "Bash":
        return f"$ {' '.join(str(tool_input.get('command', '')).split())[:58]}"
    if name == "Skill":
        return f"Skill({tool_input.get('skill', '?')})"
    if name in {"Read", "Write", "Edit"}:
        return f"{name}({tool_input.get('file_path', '?')})"
    if name in {"Grep", "Glob"}:
        # Without this every search collapses to a bare `Grep` in the log, and
        # the one thing worth knowing — what the agent went looking for, i.e.
        # the question the skill failed to answer — is gone.
        detail = tool_input.get("pattern") or tool_input.get("query") or "?"
        where = tool_input.get("path") or tool_input.get("glob")
        return f"{name}({detail}{f' in {where}' if where else ''})"
    return name


def _absorb(run: AgentRun, event: dict, announce: bool = False) -> None:
    """Fold one stream-json event into the run record.

    With `announce`, each tool call is reported as it happens. That is the
    whole point of streaming: a routing probe should say `Skill(functualize)`
    the moment it decides, not sixty seconds later in a summary.
    """
    event_type = event.get("type")

    if event_type == "assistant":
        for block in event.get("message", {}).get("content", []) or []:
            if block.get("type") != "tool_use":
                continue
            name = block.get("name", "")
            tool_input = block.get("input", {}) or {}
            run.tool_calls.append({"name": name, "input": tool_input})
            if name == "Skill":
                skill = tool_input.get("skill")
                if skill:
                    run.skills_loaded.append(skill)
            if announce:
                log_progress(f"  · {_describe(name, tool_input)}")

    elif event_type == "system":
        subtype = event.get("subtype")

        if subtype == "init" and announce:
            log_progress(
                f"  · model={event.get('model', '?')} "
                f"auth={event.get('apiKeySource', '?')}"
            )

        elif subtype == "api_retry":
            status = event.get("error_status")
            reason = event.get("error", "?")
            attempt = event.get("attempt", "?")
            if announce:
                log_progress(
                    f"  ! API {status} {reason} — retry {attempt}/"
                    f"{event.get('max_retries', '?')}"
                )
            # 401/403 never recover, and claude retries ten times with
            # exponential backoff — over two minutes of silence that reads as
            # a hang. Abandon immediately and say why.
            if status in (401, 403):
                run.fatal = (
                    f"credential rejected by the API ({status} {reason}). "
                    "The key is set but not valid for this account."
                )

    elif event_type == "result":
        run.text = event.get("result", "") or run.text
        run.num_turns = event.get("num_turns", 0)
        run.cost_usd = event.get("total_cost_usd", 0.0) or 0.0
        if event.get("is_error"):
            run.error = event.get("subtype") or "result error"


def run_check(sandbox: Sandbox, command: str, timeout_s: int = 300) -> dict:
    """Run one verification command where the agent ran. Never raises.

    Must share the sandbox: a `.venv` built inside a container is not runnable
    from the host, so a host-side check against a container run would report a
    failure the agent never caused.
    """
    began = time.monotonic()
    try:
        proc = sandbox.run(["sh", "-lc", command], timeout_s=timeout_s)
        log_progress(
            f"{'✔' if proc.returncode == 0 else '✖'} check {time.monotonic() - began:.0f}s "
            f"{command[:56]}"
        )
        return {
            "command": command,
            "exit_code": proc.returncode,
            "stdout": proc.stdout[-4000:],
            "stderr": proc.stderr[-4000:],
        }
    except subprocess.TimeoutExpired:
        log_progress(f"check  [TIMEOUT] {command[:70]}")
        return {"command": command, "exit_code": 124, "stdout": "", "stderr": "timeout"}
    except (OSError, RuntimeError) as exc:
        log_progress(f"check  [ERROR] {exc} — {command[:60]}")
        return {"command": command, "exit_code": 125, "stdout": "", "stderr": str(exc)}


def collect_files(workspace: Path, limit: int = 400) -> dict[str, str]:
    """Snapshot text files the agent produced, for grep-style assertions."""
    collected: dict[str, str] = {}
    skip = {".git", ".claude", "node_modules", ".venv", "__pycache__", ".pytest_cache"}
    keep_suffixes = {".py", ".toml", ".md", ".ini", ".yaml", ".yml", ".txt", ".json"}

    for path in sorted(workspace.rglob("*")):
        if len(collected) >= limit:
            break
        if not path.is_file() or any(part in skip for part in path.parts):
            continue
        if path.suffix not in keep_suffixes:
            continue
        try:
            collected[str(path.relative_to(workspace))] = path.read_text()[:60_000]
        except (UnicodeDecodeError, OSError):
            continue
    return collected
