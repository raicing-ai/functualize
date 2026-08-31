"""Unit tests for the group options lab.

Two jobs here, and they are different in kind. The first group pins the job
bodies and the declarations — the same shape `secrets_lab`'s tests take. The
second pins the two facts the TUI panel work is *built on*, which is why they
are asserted here against a real project rather than left as a belief:

* the group-options trie is non-``None`` for this project (every dormant TUI
  defect is dormant only because no example ever armed it), and
* a ``Secret[str]`` group option arrives in the cached spec with
  ``secret=True``, having been declared once and touched by no CLI code.
"""

import importlib.util
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).parent.parent


def _load(name: str, relpath: str):
    spec = importlib.util.spec_from_file_location(name, _ROOT / relpath)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


# `_options` under its bare name: `web.py` and `worker.py` import it that way,
# which is how the jobs directory itself resolves it at scan time.
_options = _load("_options", "jobs/_options.py")


class TestDeclarations:
    def test_the_two_levels_bind_to_their_paths(self):
        assert _options.DeployOptions.__group_path__ == "deploy"
        assert _options.WebOptions.__group_path__ == "deploy.web"

    def test_deploy_options_defaults(self):
        opts = _options.DeployOptions()
        assert opts.env == "staging"
        assert opts.dry_run is False
        assert opts.token.get_secret_value() == ""

    def test_the_token_refuses_to_render(self):
        """The claim the README makes about leaving the log line in."""
        opts = _options.DeployOptions(token="hunter2-real")
        assert "hunter2-real" not in str(opts.token)
        assert "hunter2-real" not in repr(opts.token)
        assert opts.token.get_secret_value() == "hunter2-real"

    def test_web_options_defaults(self):
        assert _options.WebOptions().region == "us-east-1"


class TestJobBodies:
    def test_web_run_reads_both_levels(self):
        web = _load("group_options_lab_web", "jobs/web.py")
        result = web.run(
            image="v1.2",
            rc=_FakeRunContext(),
            replicas=3,
            opts=_options.DeployOptions(env="prod"),
            web=_options.WebOptions(region="eu-west-1"),
        )
        assert result == "Deploying web v1.2 x3 to prod/eu-west-1"

    def test_dry_run_changes_the_verb(self):
        web = _load("group_options_lab_web", "jobs/web.py")
        result = web.run(
            image="v1",
            rc=_FakeRunContext(),
            opts=_options.DeployOptions(dry_run=True),
            web=_options.WebOptions(),
        )
        assert result.startswith("Would deploy")

    def test_worker_inherits_one_level(self):
        worker = _load("group_options_lab_worker", "jobs/worker.py")
        result = worker.run(
            rc=_FakeRunContext(), opts=_options.DeployOptions(env="prod")
        )
        assert result == "Deploying worker on default to prod"

    def test_image_is_positional_and_required(self):
        """D4 needs a required positional to exist. Pin that it stays one."""
        import inspect

        web = _load("group_options_lab_web", "jobs/web.py")
        param = inspect.signature(web.run).parameters["image"]
        assert param.default is inspect.Parameter.empty

    def test_status_declares_no_group(self):
        """The X.3 control must stay ungrouped."""
        status = _load("group_options_lab_status", "jobs/status.py")
        assert not hasattr(status, "JOB_GROUP")


class _FakeRunContext:
    def log(self, *args, **kwargs) -> None:
        pass


@pytest.mark.slow
class TestTheProjectArmsTheTrie:
    """What makes this example worth having as a fixture, not just a demo."""

    @pytest.fixture(scope="class")
    def trie(self, monkeypatch_class=None):
        import os

        from functualize._cli.tui.cli_arg_parser import build_group_option_trie
        from functualize.app import FunctualizeApp, JobSources

        cwd = os.getcwd()
        os.chdir(_ROOT)
        try:
            app = FunctualizeApp(
                name="glab", job_sources=JobSources(directories=["jobs"], lazy=True)
            )
            yield build_group_option_trie(app)
        finally:
            os.chdir(cwd)

    def test_the_trie_exists(self, trie):
        """`None` here is what kept every TUI group-options defect dormant."""
        assert trie is not None

    def test_a_job_inherits_both_levels_outermost_first(self, trie):
        from functualize._cli.tui.cli_arg_parser import group_option_specs_on_path

        specs = group_option_specs_on_path(trie, "deploy.web.run")
        assert [s.group for s in specs] == ["deploy", "deploy.web"]

    def test_a_sibling_inherits_only_the_outer_level(self, trie):
        from functualize._cli.tui.cli_arg_parser import group_option_specs_on_path

        specs = group_option_specs_on_path(trie, "deploy.worker.run")
        assert [s.group for s in specs] == ["deploy"]

    def test_the_control_inherits_nothing(self, trie):
        from functualize._cli.tui.cli_arg_parser import group_option_specs_on_path

        assert group_option_specs_on_path(trie, "status") == []

    def test_a_secret_group_option_reaches_the_cached_spec_marked(self, trie):
        """Declared once, in `_options.py`. No CLI code was told about it.

        This is the premise the panel masking rests on: group options inherit
        `secret` through `extract_field_descriptors` for free. If this ever
        goes false, masking group rows becomes impossible without importing
        the declaring class on every panel refresh — which the import-free
        panel path cannot afford.
        """
        from functualize._cli.tui.cli_arg_parser import group_option_specs_on_path

        deploy = group_option_specs_on_path(trie, "deploy.web.run")[0]
        by_name = {f.name: f for f in deploy.fields}

        assert by_name["token"].secret is True
        assert by_name["env"].secret is False
        assert by_name["dry_run"].secret is False

    def test_a_secret_default_does_not_reach_the_cache(self, trie):
        """R9, pinned. `token` is declared `= Secret("")`; the cache holds
        `None`, because a credential's default is not written to disk. Any
        surface that omits a value for equalling its default cannot do so for
        a secret field."""
        from functualize._cli.tui.cli_arg_parser import group_option_specs_on_path

        deploy = group_option_specs_on_path(trie, "deploy.web.run")[0]
        by_name = {f.name: f for f in deploy.fields}

        assert by_name["token"].default is None
        assert by_name["env"].default == "staging"
