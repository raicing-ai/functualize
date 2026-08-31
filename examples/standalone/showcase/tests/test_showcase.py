"""Unit tests for the showcase example — every job body works when called directly.

TUI behavior (SmartBar flows, config panels, surfaces, displays) is verified
manually via the README checklist; these tests prove the job functions and
Mode A scripts are runnable code.

One exception, at the bottom: the README claims `api_key`, `db_password` and
`output_token` render **masked**. That is a claim about runtime behaviour, and
for a while it was false while every test here stayed green — the job bodies
faked it with `'*' * 8` and nothing asked the framework. Those tests start at
the declared model and follow the seam the real surfaces read, so the claim
cannot go quietly false again.
"""

import importlib.util
import os
import re
import subprocess
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

_ROOT = Path(__file__).parent.parent


def _load(name: str, relpath: str):
    """Load a module from a file path under the showcase directory."""
    spec = importlib.util.spec_from_file_location(name, _ROOT / relpath)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


_basics = _load("showcase_basics", "jobs/basics.py")
_deploys = _load("showcase_deploys", "jobs/deploys.py")
_configcheck = _load("showcase_configcheck", "jobs/configcheck.py")
_surfaces = _load("showcase_surfaces", "jobs/surfaces.py")
_unix = _load("showcase_unix", "jobs/unix_style.py")
_ai = _load("showcase_ai", "jobs/ai_jobs.py")
_hello = _load("showcase_hello", "scripts/hello.py")
_tasks = _load("showcase_tasks", "scripts/tasks.py")
_processor = _load("showcase_processor", "scripts/data_processor.py")


def _rc() -> MagicMock:
    """A minimal mock RunContext."""
    return MagicMock()


# --- basics.py -------------------------------------------------------------


def test_status():
    assert _basics.status(_rc()) == "all systems go"


def test_ping_defaults():
    result = _basics.ping(_basics.PingConfig(), _rc())
    assert result == "localhost: 3/3 packets received"


def test_send():
    result = _basics.send(_basics.SendConfig(message="hi"), _rc())
    assert result == "Sent: hi"


def test_migrate():
    config = _basics.MigrateConfig(
        database="postgres://db", target="v42", direction="up"
    )
    assert _basics.migrate(config, _rc()) == "Migrated to v42 (up)"


# --- deploys.py ------------------------------------------------------------


def test_deploy():
    config = _deploys.DeployConfig(
        service="api",
        version="v1.2.3",
        env="staging",
        region="us-east-1",
        protocol="http",
    )
    assert _deploys.deploy(config, _rc()) == "Deployed api@v1.2.3 to staging/us-east-1"


def test_deploy_rollback():
    config = _deploys.DeployRollbackConfig(
        service="api", env="production", to_version="v1.1.0"
    )
    assert _deploys.deploy_rollback(config, _rc()) == "Rolled back api to v1.1.0"


def test_deploy_status():
    config = _deploys.DeployStatusConfig(service="api")
    assert _deploys.deploy_status(config, _rc()) == "api (production): healthy"


def test_build():
    config = _deploys.BuildConfig(source_dir="./src")
    assert _deploys.build(config, _rc()) == "Built from ./src → ./dist"


def test_inspect():
    config = _deploys.InspectConfig(target="cache")
    assert _deploys.inspect(config, _rc()) == "Inspected cache"


# --- configcheck.py --------------------------------------------------------


def test_release_defaults():
    config = _configcheck.ReleaseConfig()
    result = _configcheck.release(config, _rc())
    assert result == "Released to production/us-east-1 x3"

    # The real values still resolve — asserting only on the mask would let a
    # field that stopped carrying a value at all pass as "masked".
    assert config.api_key.get_secret_value() == "sk-default-key-12345"
    assert config.db_password.get_secret_value() == "super-secret-pass"
    assert "super-secret-pass" not in str(config.db_password)


def test_analyze():
    config = _configcheck.AnalyzeConfig(depth=7)
    result = _configcheck.analyze(config, _rc())
    assert result == "Analysis complete (depth=7)"

    assert config.output_token.get_secret_value() == "tok-abc123"
    assert "tok-abc123" not in str(config.output_token)


def test_healthcheck():
    assert _configcheck.healthcheck(_rc()) == "healthy"


# --- surfaces.py (jobs that need only rc) ----------------------------------


def test_surfaces_greet():
    result = _surfaces.greet(_surfaces.GreetConfig(name="showcase"), _rc())
    assert result == "greeted showcase"


# --- unix_style.py ---------------------------------------------------------


def test_say():
    assert _unix.say("World") == "hello, World!"
    assert _unix.say("World", greeting="hey") == "hey, World!"


def test_transform():
    assert _unix.transform("abc") == "ABC"
    assert _unix.transform("ABC", format="lower") == "abc"
    assert _unix.transform("hello world", format="title") == "Hello World"


def test_ship():
    assert _unix.ship("staging", image="api:v2") == "Shipping: api:v2 → staging x3"
    assert (
        _unix.ship("prod", image="api:v2", replicas=1, dry_run=True)
        == "DRY RUN: api:v2 → prod x1"
    )


# --- ai_jobs.py ------------------------------------------------------------


def test_ai_write_concise():
    config = _ai.WriteConfig(topic="Python async", style="concise")
    result = _ai.ai_write(config, _rc())
    assert result.title == "Python async — Quick Guide"
    assert "quick-reference" in result.tags


def test_ai_write_tutorial():
    config = _ai.WriteConfig(topic="Testing", style="tutorial")
    result = _ai.ai_write(config, _rc())
    assert result.title == "Tutorial: Testing"
    assert result.word_count == 500


def test_ai_review_security():
    config = _ai.ReviewConfig(repo="my-org/api", focus="security")
    result = _ai.ai_review(config, _rc())
    assert result.issues_found == 3
    assert result.critical_issues == ["SQL injection in user_handler.py"]


def test_ai_review_default():
    config = _ai.ReviewConfig(repo="my-org/api")
    result = _ai.ai_review(config, _rc())
    assert result.issues_found == 2
    assert result.critical_issues == []


# --- scripts/ (Mode A single-file jobs) ------------------------------------


def test_hello_greet():
    rc = _rc()
    config = _hello.GreetConfig(name="World", enthusiasm=3)
    assert _hello.greet(config, rc) == "Hello, World!!!"
    rc.log.assert_called_once_with("Hello, World!!!")


def test_tasks():
    assert _tasks.deploy() == "Deployed to staging"
    assert _tasks.deploy(target="production") == "Deployed to production"
    assert _tasks.status() == "All systems operational"


def test_data_processor_process_and_summarize():
    rc = _rc()
    process_config = _processor.ProcessConfig(input_path="./sample.csv", format="csv")
    result = _processor.process(process_config, rc)
    assert result["records_processed"] == 300
    assert result["output_format"] == "csv"

    summary = _processor.summarize(
        _processor.SummarizeConfig(input_path="./sample.csv"), rc
    )
    assert summary["previous_runs"] >= 1
    assert summary["last_format"] == "csv"


# --- masking, from the declaration to the rendered surface -----------------
#
# `wiring-discipline.md` §8: a masking test must start where the declaration
# starts. Never a hand-made `SimpleNamespace(secret=True)` — that stand-in left
# 2181 tests green while every surface leaked, because a missing attribute on a
# stub is indistinguishable from a wire that was never connected.
#
# These start at the declared `ReleaseConfig` / `AnalyzeConfig` and read what a
# real surface prints:
#
#     Secret[str] in the model
#       -> discovery + the cached descriptor
#       -> resolution (FieldDescriptor.secret -> ResolvedField.secret)
#       -> `func builtin env <job>`, rendered
#
# Run as a subprocess rather than by building a second `FunctualizeApp` in this
# process: two apps over different directories in one interpreter leave the
# second discovering **no jobs at all**, so an in-process version passes alone
# and fails whenever another example's app is built first.

MASK = "\u2022\u2022\u2022"

_SECRET_FIELDS = {"release": ("api_key", "db_password"), "analyze": ("output_token",)}
_PLAIN_FIELDS = {"release": ("region", "replicas", "timeout"), "analyze": ("depth",)}


def _builtin_env(job_name: str, *extra: str) -> dict[str, tuple[str, str]]:
    """`{field: (rendered value, source)}` as `func builtin env <job>` prints it."""
    proc = subprocess.run(
        [sys.executable, "-m", "functualize", "builtin", "env", job_name, *extra],
        cwd=_ROOT,
        capture_output=True,
        text=True,
        env={**os.environ, "PYTHONIOENCODING": "utf-8"},
    )
    assert proc.returncode == 0, f"builtin env {job_name} failed:\n{proc.stderr}"

    prefix = f"{job_name.upper()}_"
    parsed: dict[str, tuple[str, str]] = {}
    for line in proc.stdout.splitlines():
        match = re.match(r"export (\w+)=(.*?)\s+# source: (\w+)$", line.strip())
        if not match:
            continue
        name, raw, source = match.groups()
        if not name.startswith(prefix):
            continue
        parsed[name[len(prefix) :].lower()] = (raw.strip("'"), source)
    assert parsed, f"no fields parsed from:\n{proc.stdout}"
    return parsed


@pytest.fixture(scope="module")
def rendered():
    """One subprocess per job, shared across the assertions below."""
    return {job: _builtin_env(job) for job in ("release", "analyze")}


@pytest.mark.parametrize(
    ("job_name", "field_name"),
    [(j, f) for j, fields in _SECRET_FIELDS.items() for f in fields],
)
def test_a_declared_secret_renders_masked(rendered, job_name, field_name):
    value, source = rendered[job_name][field_name]

    assert value == MASK, (
        f"{field_name!r} is declared Secret[str] but the surface rendered "
        f"{value!r} — a credential in cleartext"
    )
    assert source != "unset", "nothing resolved this field, so masking proves nothing"


@pytest.mark.parametrize(
    ("job_name", "field_name"),
    [(j, f) for j, fields in _PLAIN_FIELDS.items() for f in fields],
)
def test_a_plain_field_shows_its_value(rendered, job_name, field_name):
    """Guard the guard: without this, "mask everything" would pass above."""
    value, _ = rendered[job_name][field_name]

    assert value not in ("", MASK)


def test_the_mask_hides_a_value_that_is_really_there(rendered):
    """Masking must not be indistinguishable from an empty field.

    `--include-secrets` is the deliberate reveal, so it is also the only way to
    prove the masked cell had something behind it.
    """
    assert rendered["release"]["api_key"][0] == MASK

    revealed = _builtin_env("release", "--include-secrets")
    assert revealed["api_key"][0] == "sk-from-base-config-77777"


def test_the_api_key_still_comes_from_the_file(rendered):
    """Masking must not cost provenance.

    A secret's declared default is dropped from the discovery cache (ADR-009
    decision 3); the *file* value is not. If this flips to `default`, the
    README's config-chain walkthrough is wrong and something real regressed.
    """
    assert rendered["release"]["api_key"][1] == "file"


def test_the_job_body_does_not_hand_roll_a_mask():
    """The framework masks. A hand-rolled `'*' * 8` beside a real Secret taught
    the reader that it cannot be trusted to."""
    body = (_ROOT / "jobs" / "configcheck.py").read_text()
    assert "'*' * 8" not in body
