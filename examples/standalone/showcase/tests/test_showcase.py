"""Unit tests for the showcase example — every job body works when called directly.

TUI behavior (SmartBar flows, config panels, surfaces, displays) is verified
manually via the README checklist; these tests prove the job functions and
Mode A scripts are runnable code.
"""

import importlib.util
import sys
from pathlib import Path
from unittest.mock import MagicMock

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
    result = _configcheck.release(_configcheck.ReleaseConfig(), _rc())
    assert result == "Released to production/us-east-1 x3"


def test_analyze():
    result = _configcheck.analyze(_configcheck.AnalyzeConfig(depth=7), _rc())
    assert result == "Analysis complete (depth=7)"


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
