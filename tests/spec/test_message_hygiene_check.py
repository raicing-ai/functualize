"""The message-hygiene check: what it refuses, what it must let through.

`.github/workflows/message-hygiene.yml` runs `.github/scripts/verify_message_hygiene.py`
over the PR title, the PR body and every commit message in the PR's range,
because a squash merge publishes all three. The classes it refuses are internal
bookkeeping (a tracker key or tracker URL, a task/run id) and a machine identity
(an agent, model, harness or automation account named as an author).

Every token below is **fabricated**. The strings the check actually exists to
refuse are internal, and a test that used a real one would write the very string
the rule keeps out of the repository, in the file most likely to be found. The
prefixes used here (`ZZZ`, `QQ`) are neither in `PERMITTED_PREFIXES` nor minted
by any tracker in use — that is what makes them refused.

The workflow is read as **text**, not through `yaml.safe_load`: YAML 1.1 parses
its bare `on:` key as the boolean `True`, so the one property most worth pinning
— that it triggers on `pull_request` and never on `pull_request_target` — is
invisible in a parsed document.
"""

from __future__ import annotations

import ast
import importlib.util
import re
import sys
from pathlib import Path
from typing import Any

import pytest

_ROOT = Path(__file__).resolve().parents[2]
_SCRIPT = _ROOT / ".github" / "scripts" / "verify_message_hygiene.py"
_WORKFLOW = _ROOT / ".github" / "workflows" / "message-hygiene.yml"
_CONTRIBUTING = _ROOT / "CONTRIBUTING.md"
_AGENTS = _ROOT / "AGENTS.md"

#: The job id. GitHub reports a job by its id, so this string is the status
#: context a ruleset entry would have to name — and the name the docs use.
CONTEXT = "message-hygiene"

REVIEWERS = ["a.maintainer@example.invalid", "b.maintainer@example.invalid"]

FAKE_KEY = "ZZZ-42"
FAKE_OTHER_KEY = "QQ-7"
FAKE_RUN_ID = "deadbeef-0bad"
FAKE_FULL_ID = "1a2b3c4d-5e6f-7a8b-9c0d-1e2f3a4b5c6d"
FAKE_IDENTITY = "fictional-harness"
FAKE_ADDRESS = "noreply@example.invalid"
FAKE_HUMAN = "a.maintainer@example.invalid"


def _checker() -> Any:
    """Load the script out-of-tree, under a name of its own.

    Registered in `sys.modules` before execution for the reason
    `tests/evals/test_suite_contracts.py::_harness` records: a module whose
    classes resolve `sys.modules[cls.__module__]` finds `None` there otherwise,
    and the error surfaces nowhere near the cause. It costs two lines to keep.
    """
    name = "_fz_message_hygiene"
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, _SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    try:
        spec.loader.exec_module(module)
    except Exception:
        del sys.modules[name]
        raise
    return module


@pytest.fixture()
def check() -> Any:
    return _checker()


def _refused(
    check: Any,
    *,
    title: str = "chore: tidy the docs",
    body: str = "",
    log: str = "",
    denylist: tuple[str, ...] = (),
    allowlist: tuple[str, ...] = tuple(REVIEWERS),
) -> list[str]:
    return check.find_violations(
        title, body, log, denylist=list(denylist), reviewer_allowlist=list(allowlist)
    )


class TestRefused:
    """One test per class, because each is a separate way the record rots."""

    @pytest.mark.parametrize("source", ["title", "body", "log"])
    def test_a_tracker_key_is_refused_in_every_one_of_the_three_texts(
        self, check: Any, source: str
    ) -> None:
        """Title, body and commit message all reach `master` via the squash."""
        text = f"Ports the store, tracked as {FAKE_KEY}."
        reported = _refused(
            check,
            **{source: text},  # type: ignore[arg-type]
        )
        assert any(FAKE_KEY in violation for violation in reported), reported

    def test_an_unknown_key_prefix_is_refused(self, check: Any) -> None:
        """Precision is a permission list, so no tracker prefix is written down.

        `PERMITTED_PREFIXES` is what decides, which is why a tracker can be
        swapped for another without this repository being edited — and why an
        unforeseen benign token needs an entry rather than a loosened pattern.
        """
        assert FAKE_KEY.split("-")[0] not in check.PERMITTED_PREFIXES
        assert _refused(check, body=FAKE_KEY)

    @pytest.mark.parametrize(
        "url",
        [
            f"https://tracker.example.invalid/browse/{FAKE_KEY}",
            # No key at all: a board URL carries the bare project prefix.
            "https://tracker.example.invalid/projects/ZZZ/boards/2",
        ],
    )
    def test_a_tracker_url_is_refused_even_when_it_carries_no_key(
        self, check: Any, url: str
    ) -> None:
        assert _refused(check, body=f"Board: {url}"), url

    def test_a_cache_busting_path_under_the_repository_is_not_a_tracker_url(
        self, check: Any
    ) -> None:
        """The URL arm refuses an unknown uppercase path segment, so a git ref
        has to be permitted explicitly — `/blob/HEAD/...` is a normal link."""
        body = "See https://github.com/raicing-ai/functualize/blob/HEAD/CHANGELOG.md"
        assert _refused(check, body=body) == []

    @pytest.mark.parametrize("internal_id", [FAKE_RUN_ID, FAKE_FULL_ID])
    def test_an_internal_identifier_is_refused(
        self, check: Any, internal_id: str
    ) -> None:
        """A truncated run id and a full UUID are one shape, so one arm."""
        reported = _refused(check, body=f"Run {internal_id} did it.")
        assert any(internal_id in violation for violation in reported), reported

    def test_a_content_digest_is_not_an_identifier(self, check: Any) -> None:
        """32 hex characters and no hyphen: a digest, never a run id."""
        digest = "3f4a9b2c8d1e0f5a6b7c8d9e0f1a2b3c"
        assert _refused(check, body=f"sha256 {digest}") == []

    def test_a_machine_named_as_a_co_author_is_refused_by_the_allow_list(
        self, check: Any
    ) -> None:
        """The structural half, with a populated allow-list and no deny-list.

        A denial list cannot name an agent that has not been seen yet; an
        allow-list of people refuses every machine by default, which is what
        makes this arm the one that does not need maintaining.
        """
        reported = _refused(check, body=f"Body.\n\nCo-authored-by: {FAKE_ADDRESS}")
        assert any(FAKE_ADDRESS in violation for violation in reported), reported

    def test_an_attributed_trailer_without_an_address_is_refused(
        self, check: Any
    ) -> None:
        """A trailer that attributes the change must name somebody."""
        reported = _refused(check, body=f"Body.\n\nCo-authored-by: {FAKE_IDENTITY}")
        assert any("names no address" in violation for violation in reported), reported

    def test_an_unset_allow_list_refuses_every_attributed_trailer(
        self, check: Any
    ) -> None:
        """Fail closed. An unconfigured repository checks nothing otherwise, and
        "the check ran and passed" is indistinguishable from "it was never set up"."""
        reported = _refused(
            check,
            body=f"Body.\n\nCo-authored-by: {FAKE_HUMAN}",
            allowlist=(),
        )
        assert any("cannot be validated" in violation for violation in reported), (
            reported
        )

    def test_a_configured_deny_list_refuses_an_identity_in_prose(
        self, check: Any
    ) -> None:
        """The other identity arm, and the one that grows: the strings live in a
        repository variable, so the names never enter a file."""
        reported = _refused(
            check,
            body=f"Generated by the {FAKE_IDENTITY} run.",
            denylist=(FAKE_IDENTITY,),
        )
        assert any(FAKE_IDENTITY in violation for violation in reported), reported

    def test_a_prose_mention_is_not_read_as_attribution(self, check: Any) -> None:
        """git's own trailer shape is a paragraph's *trailing* run of `Key: value`.

        An address named mid-sentence is prose. It is refused when it is on the
        deny-list, not because it was mistaken for a trailer — the boundary this
        rule draws is attribution, and it is drawn where git draws it.
        """
        body = (
            f"Note: {FAKE_ADDRESS} wrote this.\n"
            "The sentence continues on the next line.\n"
            "\n"
            "Fixes #123"
        )
        assert _refused(check, body=body) == []


class TestStillPermitted:
    """The false-positive surface, pinned to the measurement behind the list."""

    @pytest.mark.parametrize(
        "token",
        [
            "ADR-027",
            "AC-4",
            "TD-1",
            "PM-03",
            "NFR-1",
            "GH-01",
            "CI-05",
            "US-2",
            "TS-01",
            "IF-02",
            "ORD-001",
            "PR-1",
            "UTF-8",
            "SHA-256",
            "ISO-8601",
            "RFC-2119",
            "PEP-723",
            "LICENSE-2",
            "BSD-3",
            "LGPL-3",
            "GPL-2",
            "AES-256",
        ],
    )
    def test_a_measured_document_token_is_permitted(
        self, check: Any, token: str
    ) -> None:
        """Every one of these is in the repository today, and in its history."""
        assert token.split("-")[0] in check.PERMITTED_PREFIXES
        assert (
            _refused(check, body=f"See {token} for that.", log=f"The {token} rule.")
            == []
        )

    @pytest.mark.parametrize(
        "text", ["Fixes #123", "Relates to #456", "a subject (#49)"]
    )
    def test_a_github_issue_reference_is_permitted(self, check: Any, text: str) -> None:
        """The repository's own tracker is public and is not the refused class.

        `(#49)` matters separately: GitHub appends the PR number to a squash
        subject, so a rule that refused it would refuse nearly every commit on
        `master` the moment it was enforced.
        """
        assert _refused(check, title="chore: tidy the docs (#49)", body=text) == []

    def test_an_allow_listed_human_co_author_is_permitted(self, check: Any) -> None:
        """The rule is about machines, not about collaboration."""
        body = f"Body.\n\nCo-authored-by: A Maintainer <{FAKE_HUMAN}>"
        assert _refused(check, body=body) == []

    @pytest.mark.parametrize("text", ["2026-09-25", "released v0.4.0 on 2026-09-24"])
    def test_a_date_is_not_a_tracker_key(self, check: Any, text: str) -> None:
        """A leading letter is required, which is what excludes `2026-09`."""
        assert _refused(check, body=text) == []


class TestMainContract:
    """The environment the workflow sets, and the exit code it depends on."""

    def _env(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
        *,
        log_text: str = "chore: tidy the docs\n",
        **over: str,
    ) -> None:
        (tmp_path / "messages.txt").write_text(log_text, encoding="utf-8")
        values = {
            "MESSAGE_HYGIENE_TITLE": "chore: tidy the docs",
            "MESSAGE_HYGIENE_BODY": "A body that says why.",
            "MESSAGE_HYGIENE_LOG": str(tmp_path / "messages.txt"),
            "MESSAGE_HYGIENE_IDENTITY_DENYLIST": FAKE_IDENTITY,
            "MESSAGE_HYGIENE_REVIEWER_ALLOWLIST": ",".join(REVIEWERS),
        }
        values.update(over)
        for key, value in values.items():
            monkeypatch.setenv(key, value)

    def test_a_clean_pr_exits_zero(
        self, check: Any, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: Any
    ) -> None:
        self._env(monkeypatch, tmp_path)
        assert check.main() == 0
        assert "OK:" in capsys.readouterr().out

    def test_a_leaking_pr_exits_one_with_an_error_annotation(
        self, check: Any, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: Any
    ) -> None:
        self._env(
            monkeypatch,
            tmp_path,
            MESSAGE_HYGIENE_TITLE=f"feat(x): port it ({FAKE_KEY})",
        )
        assert check.main() == 1
        out = capsys.readouterr().out
        assert "::error::" in out and FAKE_KEY in out

    def test_a_missing_title_fails_closed(
        self, check: Any, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: Any
    ) -> None:
        """An event payload that did not arrive must not read as a clean PR."""
        self._env(monkeypatch, tmp_path, MESSAGE_HYGIENE_TITLE="")
        assert check.main() == 1
        assert "nothing was checked" in capsys.readouterr().out

    def test_an_unreadable_log_fails_closed(
        self, check: Any, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: Any
    ) -> None:
        """The range walk is the workflow's job; its failure is this one's too."""
        self._env(monkeypatch, tmp_path, MESSAGE_HYGIENE_LOG=str(tmp_path / "gone.txt"))
        assert check.main() == 1
        assert "cannot read" in capsys.readouterr().out

    def test_the_variables_split_on_commas_and_newlines(
        self, check: Any, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """`vars` values are typed by hand in a settings box, so both separators
        are accepted and blank entries are ignored."""
        self._env(
            monkeypatch,
            tmp_path,
            MESSAGE_HYGIENE_BODY=f"Written by second-name.\n\nSigned-off-by: <{FAKE_HUMAN}>",
            MESSAGE_HYGIENE_IDENTITY_DENYLIST="ignored,\n second-name ",
            MESSAGE_HYGIENE_REVIEWER_ALLOWLIST=" ,\n" + ",".join(REVIEWERS),
        )
        assert check.main() == 1


class TestTheWorkflowCannotSilentlyStopChecking:
    """Properties a later edit could remove without any test going red."""

    @pytest.fixture()
    def workflow(self) -> str:
        assert _WORKFLOW.is_file(), f"{_WORKFLOW} is missing"
        return _WORKFLOW.read_text(encoding="utf-8")

    def test_the_job_id_is_the_context(self, workflow: str) -> None:
        """A job's id is the status context, so the id IS what a ruleset names.

        An admins-only ruleset entry is what turns this job into a gate; until
        then it reports. The docs must name the same string either way, or the
        rule is described under a name nothing reports.
        """
        assert re.search(rf"^  {CONTEXT}:", workflow, re.M), workflow
        assert CONTEXT in _CONTRIBUTING.read_text(encoding="utf-8")
        assert CONTEXT in _AGENTS.read_text(encoding="utf-8")

    def test_it_runs_on_pull_request_and_never_on_pull_request_target(
        self, workflow: str
    ) -> None:
        """`pull_request_target` runs with a write-scoped token in the base
        repo's context for a fork PR. This check only reads text, so it takes the
        narrow trigger — the file may still *say* why."""
        assert not re.search(r"(?m)^\s*pull_request_target\s*:", workflow)
        assert re.search(r"(?m)^on:\n  pull_request:", workflow)

    def test_it_reads_the_whole_range_with_a_read_only_token(
        self, workflow: str
    ) -> None:
        assert "fetch-depth: 0" in workflow, (
            "without full history the commit range cannot be walked, and an "
            "empty range is the one case that would pass while checking nothing"
        )
        assert "permissions:\n  contents: read" in workflow

    def test_identity_strings_live_in_repository_variables(self, workflow: str) -> None:
        """The whole point of the deny-list mechanism: the strings that must not
        be committed are repository settings, and the files name none of them."""
        assert "vars.MESSAGE_HYGIENE_IDENTITY_DENYLIST" in workflow
        assert "vars.MESSAGE_HYGIENE_REVIEWER_ALLOWLIST" in workflow
        for path in (_WORKFLOW, _SCRIPT):
            # An address, not an action ref: `actions/checkout@v4` is not one.
            addresses = re.findall(
                r"[\w.+-]+@[\w-]+\.[a-z]{2,}", path.read_text(encoding="utf-8")
            )
            assert not addresses, f"{path} hard-codes {addresses}"

    def test_the_script_is_stdlib_only(self) -> None:
        """The job runs `python3 .github/scripts/...` with no `uv sync`, the way
        the cleanup-predecessor gate does. A third-party import breaks it only
        in CI, which is the slowest possible place to find out."""
        tree = ast.parse(_SCRIPT.read_text(encoding="utf-8"))
        modules: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                modules |= {alias.name.split(".")[0] for alias in node.names}
            elif isinstance(node, ast.ImportFrom):
                modules.add((node.module or "").split(".")[0])
        assert modules <= {"os", "re", "sys", "pathlib", "__future__"}, modules

    def test_the_job_actually_runs_the_checker(self, workflow: str) -> None:
        """A job that never calls the script passes forever."""
        assert "python3 .github/scripts/verify_message_hygiene.py" in workflow
