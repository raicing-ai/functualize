"""The share/redeem handoff policy, driven through `functualize.app.vault_handoff`.

Two projects with the same jobs — a sender and a receiver — share one machine
key and run under ``FUNCTUALIZE_ENV=prod`` against the in-process mock origin.
Every pre-burn refusal is asserted on the mock's request tape: a refusal that
redeemed would fail as surely as one that raised the wrong reason.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from functualize.app import FunctualizeApp, JobSources
from functualize.app.vault import (
    VaultIdentity,
    VaultKeySourceError,
    VaultPathError,
    vault_put,
)
from functualize.app.vault_handoff import (
    ALL,
    ImportPlan,
    Materialize,
    RowStatus,
    Selector,
    apply_import,
    check_before_redeem,
    export_name,
    parse_selector,
    plan_import,
    select_for_share,
    share,
    shareable_entries,
)
from functualize.app.vault_remote import RedeemedBundle, VaultRedeemError, redeem_link

if TYPE_CHECKING:
    from tests.vault_remote.mock_vault import MockVault

_SECRET = "correct-horse-battery-staple-9f3a"  # gitleaks:allow

_DEPLOY = '''
from pydantic import BaseModel, Field

from functualize.job import GroupOptions
from functualize.job.decorators import job
from functualize.types import Secret

JOB_GROUP = "deploy"


class DeployOptions(GroupOptions, group="deploy"):
    token: Secret[str] = Field(default="")


class AppConfig(BaseModel):
    api_key: Secret[str] = Field(default="")
    region: str = Field(default="eu-west-1")


@job
def app(config: AppConfig, options: DeployOptions) -> None:
    """Deploy the app."""
'''

_INFRA = '''
from pydantic import Field

from functualize.job import GroupOptions
from functualize.job.decorators import job
from functualize.types import Secret

JOB_GROUP = "deploy.infra"


class InfraOptions(GroupOptions, group="deploy.infra"):
    region_key: Secret[str] = Field(default="")


@job
def plan(options: InfraOptions) -> None:
    """Plan the infra."""
'''

_TOOLS = '''
from pydantic import BaseModel, Field

from functualize.job.decorators import job
from functualize.types import Secret


class MyConfig(BaseModel):
    api_key: Secret[str] = Field(default="")


@job
def myjob(config: MyConfig) -> None:
    """A job in no group."""
'''

_TOKEN = VaultIdentity("group", "deploy", "token")
_APP_KEY = VaultIdentity("job", "deploy.app", "api_key")
_REGION = VaultIdentity("group", "deploy.infra", "region_key")
_MY_KEY = VaultIdentity("job", "myjob", "api_key")


def _project(root: Path, *modules: tuple[str, str]) -> Path:
    jobs = root / "jobs"
    jobs.mkdir(parents=True)
    for name, source in modules:
        (jobs / f"{name}.py").write_text(source)
    (root / ".functualize").mkdir()
    return root


_ALL_JOBS = (("deploy", _DEPLOY), ("infra", _INFRA), ("tools", _TOOLS))


@pytest.fixture
def env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from functualize._config.vault_keys import ENV_VAR, generate_key

    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    monkeypatch.setenv(ENV_VAR, generate_key())
    monkeypatch.setenv("FUNCTUALIZE_ENV", "prod")


def _app(root: Path) -> FunctualizeApp:
    return FunctualizeApp(
        "handoff", job_sources=JobSources(directories=[str(root / "jobs")], lazy=False)
    )


@pytest.fixture
def sender(tmp_path: Path, env: None) -> tuple[FunctualizeApp, Path]:
    root = _project(tmp_path / "sender", *_ALL_JOBS)
    app = _app(root)
    for identity in (_TOKEN, _APP_KEY, _REGION, _MY_KEY):
        vault_put(app, identity, f"{_SECRET}-{identity.field}", cwd=root)
    return app, root


@pytest.fixture
def receiver(tmp_path: Path, env: None) -> tuple[FunctualizeApp, Path]:
    root = _project(tmp_path / "receiver", *_ALL_JOBS)
    return _app(root), root


def _fields(selection: object) -> set[str]:
    return {f"{c.identity.target}:{c.identity.field}" for c in selection.chosen}  # type: ignore[attr-defined]


def _redeem_posts(mock: MockVault) -> int:
    return sum(
        1
        for r in mock.requests
        if r["method"] == "POST" and r["path"].endswith("/redeem")
    )


def _link(mock: MockVault, sender: tuple[FunctualizeApp, Path], *selectors: str) -> str:
    app, root = sender
    selection = select_for_share(
        app, [parse_selector(s) for s in selectors] or ALL, cwd=root
    )
    return share(app, selection, origin=mock.origin, cwd=root).link


def _check(
    receiver: tuple[FunctualizeApp, Path], link: str, **overrides: object
) -> object:
    app, root = receiver
    kwargs: dict[str, object] = {
        "materialize": Materialize.STORE,
        "interactive": True,
        "confirmed_without_prompt": False,
        "cwd": root,
    }
    kwargs.update(overrides)
    return check_before_redeem(app, link, **kwargs)  # type: ignore[arg-type]


# ── the selector grammar ─────────────────────────────────────────────────


class TestParseSelector:
    def test_an_exact_job_selector(self) -> None:
        assert parse_selector("group=deploy.infra,job=app,field=api_token") == Selector(
            "deploy.infra", "app", "api_token"
        )

    def test_a_wide_group_selector_has_no_field(self) -> None:
        selector = parse_selector("group=deploy")
        assert selector == Selector("deploy") and not selector.exact

    def test_a_dotted_job_names_the_split_spelling(self) -> None:
        with pytest.raises(VaultPathError, match="group=deploy,job=app") as exc:
            parse_selector("job=deploy.app")
        assert exc.value.reason == "dotted_job"

    @pytest.mark.parametrize(
        "text",
        [
            "group=",
            "group=deploy,owner=me",
            "group=deploy,group=x",
            "group = deploy",
            "group=de ploy",
            "deploy",
        ],
    )
    def test_malformed_selectors_are_refused(self, text: str) -> None:
        with pytest.raises(VaultPathError) as exc:
            parse_selector(text)
        assert exc.value.reason == "bad_selector"

    def test_a_field_alone_names_no_scope(self) -> None:
        with pytest.raises(VaultPathError) as exc:
            parse_selector("field=token")
        assert exc.value.reason == "scope_required"


# ── choosing what to share ───────────────────────────────────────────────


class TestShareableEntries:
    def test_lists_the_active_environment_with_readable_labels(
        self, sender: tuple[FunctualizeApp, Path]
    ) -> None:
        app, root = sender
        labels = {c.label for c in shareable_entries(app, cwd=root)}
        assert "prod: --group deploy --job app --field api_key" in labels
        assert "prod: --job myjob --field api_key" in labels

    def test_shared_entries_are_listed_but_not_shareable(
        self, sender: tuple[FunctualizeApp, Path], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        app, root = sender
        monkeypatch.setenv("FUNCTUALIZE_ENV", "base")
        vault_put(_app(root), _TOKEN, "shared-value", cwd=root)
        monkeypatch.setenv("FUNCTUALIZE_ENV", "prod")

        shared = [
            c
            for c in shareable_entries(app, cwd=root)
            if c.identity.environment is None
        ]
        assert shared and not shared[0].shareable
        assert "not supported yet" in str(shared[0].reason)

    def test_other_environments_are_not_offered(
        self, sender: tuple[FunctualizeApp, Path], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        app, root = sender
        monkeypatch.setenv("FUNCTUALIZE_ENV", "staging")
        vault_put(_app(root), _TOKEN, "staging-value", cwd=root)
        monkeypatch.setenv("FUNCTUALIZE_ENV", "prod")

        assert all(
            c.identity.environment in ("prod", None)
            for c in shareable_entries(app, cwd=root)
        )


class TestSelectForShare:
    def test_an_exact_selector_takes_one_entry(
        self, sender: tuple[FunctualizeApp, Path]
    ) -> None:
        app, root = sender
        selection = select_for_share(
            app, [parse_selector("group=deploy,field=token")], cwd=root
        )
        assert _fields(selection) == {"deploy:token"}

    def test_a_group_takes_its_whole_subtree(
        self, sender: tuple[FunctualizeApp, Path]
    ) -> None:
        """The spec A4 example: options, nested groups, and jobs inside."""
        app, root = sender
        selection = select_for_share(app, [parse_selector("group=deploy")], cwd=root)
        assert _fields(selection) == {
            "deploy:token",
            "deploy.app:api_key",
            "deploy.infra:region_key",
        }

    def test_group_and_job_take_every_field_of_that_job(
        self, sender: tuple[FunctualizeApp, Path]
    ) -> None:
        app, root = sender
        selection = select_for_share(
            app, [parse_selector("group=deploy,job=app")], cwd=root
        )
        assert _fields(selection) == {"deploy.app:api_key"}

    def test_a_job_alone_is_a_job_in_no_group(
        self, sender: tuple[FunctualizeApp, Path]
    ) -> None:
        app, root = sender
        selection = select_for_share(app, [parse_selector("job=myjob")], cwd=root)
        assert _fields(selection) == {"myjob:api_key"}

    def test_all_takes_every_shareable_entry(
        self, sender: tuple[FunctualizeApp, Path]
    ) -> None:
        app, root = sender
        assert len(select_for_share(app, ALL, cwd=root).chosen) == 4

    def test_overlapping_selectors_are_deduplicated(
        self, sender: tuple[FunctualizeApp, Path]
    ) -> None:
        app, root = sender
        selection = select_for_share(
            app,
            [
                parse_selector("group=deploy"),
                parse_selector("group=deploy,field=token"),
            ],
            cwd=root,
        )
        assert len(selection.chosen) == 3

    def test_a_selector_that_matches_nothing_refuses_the_share(
        self, sender: tuple[FunctualizeApp, Path]
    ) -> None:
        app, root = sender
        with pytest.raises(VaultRedeemError) as exc:
            select_for_share(
                app,
                [parse_selector("group=deploy"), parse_selector("group=nosuch")],
                cwd=root,
            )
        assert exc.value.reason == "no_match"

    def test_an_exact_typo_is_named_like_vault_put(
        self, sender: tuple[FunctualizeApp, Path]
    ) -> None:
        app, root = sender
        with pytest.raises(VaultPathError) as exc:
            select_for_share(
                app, [parse_selector("group=deploy,field=region")], cwd=root
            )
        assert exc.value.reason == "unknown_field"


# ── share on the wire ────────────────────────────────────────────────────


class TestShare:
    def test_items_carry_identities_and_the_share_its_environment(
        self, mock_origin: MockVault, sender: tuple[FunctualizeApp, Path]
    ) -> None:
        link = _link(mock_origin, sender, "group=deploy,field=token")
        bundle = redeem_link(link)

        assert [item["name"] for item in bundle.items] == [
            VaultIdentity("group", "deploy", "token", "prod").encode()
        ]
        assert bundle.items[0]["value"] == f"{_SECRET}-token"
        assert "env:prod" in bundle.labels

    def test_the_environment_label_is_reserved(
        self, mock_origin: MockVault, sender: tuple[FunctualizeApp, Path]
    ) -> None:
        app, root = sender
        selection = select_for_share(app, ALL, cwd=root)
        with pytest.raises(VaultRedeemError) as exc:
            share(
                app,
                selection,
                labels=["env:staging"],
                origin=mock_origin.origin,
                cwd=root,
            )
        assert exc.value.reason == "bad_label"
        assert mock_origin.requests == []


# ── refusals before the burn ─────────────────────────────────────────────


class TestCheckBeforeRedeem:
    def test_a_matching_share_passes_with_only_a_meta_read(
        self,
        mock_origin: MockVault,
        sender: tuple[FunctualizeApp, Path],
        receiver: tuple[FunctualizeApp, Path],
    ) -> None:
        link = _link(mock_origin, sender, "group=deploy")
        before = len(mock_origin.requests)

        _check(receiver, link)

        assert len(mock_origin.requests) == before + 1
        assert _redeem_posts(mock_origin) == 0

    def test_no_project_refuses_before_any_request(
        self,
        mock_origin: MockVault,
        sender: tuple[FunctualizeApp, Path],
        tmp_path: Path,
    ) -> None:
        link = _link(mock_origin, sender, "group=deploy")
        before = len(mock_origin.requests)
        empty = _project(tmp_path / "empty")

        with pytest.raises(VaultRedeemError) as exc:
            _check((_app(empty), empty), link)
        assert exc.value.reason == "no_project"
        assert len(mock_origin.requests) == before

    def test_print_only_needs_no_project(
        self,
        mock_origin: MockVault,
        sender: tuple[FunctualizeApp, Path],
        tmp_path: Path,
    ) -> None:
        link = _link(mock_origin, sender, "group=deploy")
        empty = _project(tmp_path / "empty")

        _check((_app(empty), empty), link, materialize=Materialize.PRINT)

    def test_no_terminal_and_no_flag_refuses_before_any_request(
        self,
        mock_origin: MockVault,
        sender: tuple[FunctualizeApp, Path],
        receiver: tuple[FunctualizeApp, Path],
    ) -> None:
        link = _link(mock_origin, sender, "group=deploy")
        before = len(mock_origin.requests)

        with pytest.raises(VaultRedeemError) as exc:
            _check(receiver, link, interactive=False)
        assert exc.value.reason == "no_tty_confirmation"
        assert len(mock_origin.requests) == before

    def test_a_typo_in_only_refuses_before_any_request(
        self,
        mock_origin: MockVault,
        sender: tuple[FunctualizeApp, Path],
        receiver: tuple[FunctualizeApp, Path],
    ) -> None:
        link = _link(mock_origin, sender, "group=deploy")
        before = len(mock_origin.requests)

        with pytest.raises(VaultPathError):
            _check(
                receiver,
                link,
                interactive=False,
                confirmed_without_prompt=True,
                only=[parse_selector("group=deploy,field=tokn")],
            )
        assert len(mock_origin.requests) == before

    def test_an_environment_mismatch_refuses_without_redeeming(
        self,
        mock_origin: MockVault,
        sender: tuple[FunctualizeApp, Path],
        receiver: tuple[FunctualizeApp, Path],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        link = _link(mock_origin, sender, "group=deploy")
        monkeypatch.setenv("FUNCTUALIZE_ENV", "staging")
        _, root = receiver

        with pytest.raises(VaultRedeemError, match="FUNCTUALIZE_ENV=prod") as exc:
            _check((_app(root), root), link)
        assert exc.value.reason == "environment_mismatch"
        assert _redeem_posts(mock_origin) == 0

    def test_a_missing_key_refuses_without_redeeming(
        self,
        mock_origin: MockVault,
        sender: tuple[FunctualizeApp, Path],
        receiver: tuple[FunctualizeApp, Path],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        from functualize._config.vault_keys import ENV_VAR

        link = _link(mock_origin, sender, "group=deploy")
        monkeypatch.delenv(ENV_VAR)
        monkeypatch.setattr(
            "functualize._config.vault_keys.default_providers", lambda: ()
        )

        with pytest.raises(VaultKeySourceError):
            _check(receiver, link)
        assert _redeem_posts(mock_origin) == 0

    def test_a_spent_share_is_answered_by_meta(
        self,
        mock_origin: MockVault,
        sender: tuple[FunctualizeApp, Path],
        receiver: tuple[FunctualizeApp, Path],
    ) -> None:
        link = _link(mock_origin, sender, "group=deploy")
        redeem_link(link)
        posts = _redeem_posts(mock_origin)

        with pytest.raises(VaultRedeemError) as exc:
            _check(receiver, link)
        assert exc.value.reason == "gone"
        assert _redeem_posts(mock_origin) == posts

    def test_a_share_without_an_environment_label_is_refused(
        self, mock_origin: MockVault, receiver: tuple[FunctualizeApp, Path]
    ) -> None:
        from functualize.app.vault_remote import share as raw_share

        link = raw_share(
            [{"name": "X", "kind": "secret", "value": "v"}], origin=mock_origin.origin
        ).link

        with pytest.raises(VaultRedeemError) as exc:
            _check(receiver, link)
        assert exc.value.reason == "not_a_vault_share"
        assert _redeem_posts(mock_origin) == 0


# ── what a redeemed bundle becomes ───────────────────────────────────────


def _planned(
    mock: MockVault,
    sender: tuple[FunctualizeApp, Path],
    receiver: tuple[FunctualizeApp, Path],
    *selectors: str,
) -> tuple[ImportPlan, RedeemedBundle]:
    bundle = redeem_link(_link(mock, sender, *selectors))
    app, root = receiver
    return plan_import(bundle, app, cwd=root), bundle


def _status(plan: ImportPlan) -> dict[str, RowStatus]:
    return {row.label: row.status for row in plan.rows}


class TestPlanImport:
    def test_new_entries_are_storable_and_ticked(
        self,
        mock_origin: MockVault,
        sender: tuple[FunctualizeApp, Path],
        receiver: tuple[FunctualizeApp, Path],
    ) -> None:
        plan, _ = _planned(mock_origin, sender, receiver, "group=deploy")

        assert set(_status(plan).values()) == {RowStatus.STORABLE}
        assert len(plan.default_selection()) == 3

    def test_an_existing_entry_starts_unticked(
        self,
        mock_origin: MockVault,
        sender: tuple[FunctualizeApp, Path],
        receiver: tuple[FunctualizeApp, Path],
    ) -> None:
        app, root = receiver
        vault_put(app, _TOKEN, "bobs-own", cwd=root)
        plan, _ = _planned(mock_origin, sender, receiver, "group=deploy,field=token")

        (row,) = plan.rows
        assert row.status is RowStatus.EXISTS and not row.default_ticked

    def test_a_synced_entry_says_where_from(
        self,
        mock_origin: MockVault,
        sender: tuple[FunctualizeApp, Path],
        receiver: tuple[FunctualizeApp, Path],
    ) -> None:
        _seed_synced(receiver, _TOKEN)
        plan, _ = _planned(mock_origin, sender, receiver, "group=deploy,field=token")

        (row,) = plan.rows
        assert row.status is RowStatus.SYNCED
        assert row.synced_from == "aws-sm://shared/deploy-token"
        assert not row.default_ticked

    def test_an_entry_this_project_cannot_hold_is_no_match(
        self,
        mock_origin: MockVault,
        sender: tuple[FunctualizeApp, Path],
        tmp_path: Path,
    ) -> None:
        root = _project(tmp_path / "partial", ("deploy", _DEPLOY))
        bundle = redeem_link(_link(mock_origin, sender, "group=deploy"))

        plan = plan_import(bundle, _app(root), cwd=root)
        assert (
            _status(plan)["prod: --group deploy.infra --field region_key"]
            is RowStatus.NO_MATCH
        )

    def test_an_unreadable_name_is_a_row_not_a_crash(
        self, receiver: tuple[FunctualizeApp, Path]
    ) -> None:
        app, root = receiver
        bundle = RedeemedBundle(
            items=[{"name": "not-json", "kind": "secret", "value": _SECRET}],
            labels=["env:prod"],
            expires_at="",
            share_id="0" * 32,
        )

        (row,) = plan_import(bundle, app, cwd=root).rows
        assert row.status is RowStatus.MALFORMED
        assert _SECRET not in repr(plan_import(bundle, app, cwd=root))


def _seed_synced(target: tuple[FunctualizeApp, Path], identity: VaultIdentity) -> None:
    from functualize._config.vault import SecretsVault
    from functualize._config.vault_key_resolver import resolve_vault_key
    from functualize._config.vault_paths import vault_path_for_project

    app, root = target
    key = resolve_vault_key("ignored").key
    assert key is not None
    SecretsVault(vault_path_for_project(root)).put(
        VaultIdentity(
            identity.scope,
            identity.target,
            identity.field,
            app.configuration.active_environment(),
        ).encode(),
        "from-aws",
        encryption_key=key,
        annotation="aws-sm://shared/deploy-token",
        provider="aws-sm",
    )


class TestApplyImport:
    def test_storable_rows_land_in_the_receivers_vault(
        self,
        mock_origin: MockVault,
        sender: tuple[FunctualizeApp, Path],
        receiver: tuple[FunctualizeApp, Path],
    ) -> None:
        from functualize.app.vault import _read_value

        app, root = receiver
        plan, bundle = _planned(mock_origin, sender, receiver, "group=deploy")

        report = apply_import(
            app, plan, bundle, plan.default_selection(), replace=False, cwd=root
        )

        assert len(report.stored) == 3
        assert _read_value(app, _APP_KEY, cwd=root) == f"{_SECRET}-api_key"
        assert _SECRET not in repr(report)

    def test_replacing_an_existing_entry_needs_replace(
        self,
        mock_origin: MockVault,
        sender: tuple[FunctualizeApp, Path],
        receiver: tuple[FunctualizeApp, Path],
    ) -> None:
        app, root = receiver
        vault_put(app, _TOKEN, "bobs-own", cwd=root)
        plan, bundle = _planned(
            mock_origin, sender, receiver, "group=deploy,field=token"
        )

        with pytest.raises(VaultRedeemError) as exc:
            apply_import(app, plan, bundle, [0], replace=False, cwd=root)
        assert exc.value.reason == "entry_exists"
        assert apply_import(app, plan, bundle, [0], replace=True, cwd=root).replaced

    def test_a_ticked_synced_row_is_superseded(
        self,
        mock_origin: MockVault,
        sender: tuple[FunctualizeApp, Path],
        receiver: tuple[FunctualizeApp, Path],
    ) -> None:
        from functualize.app.utils import vault_entries
        from functualize.app.vault import VaultOrigin

        app, root = receiver
        _seed_synced(receiver, _TOKEN)
        plan, bundle = _planned(
            mock_origin, sender, receiver, "group=deploy,field=token"
        )

        report = apply_import(app, plan, bundle, [0], replace=True, cwd=root)

        assert report.superseded
        assert {e.origin for e in vault_entries(root)} == {VaultOrigin.DIRECT}

    def test_a_different_bundle_stores_nothing(
        self,
        mock_origin: MockVault,
        sender: tuple[FunctualizeApp, Path],
        receiver: tuple[FunctualizeApp, Path],
    ) -> None:
        from functualize.app.utils import vault_entries

        app, root = receiver
        plan, _ = _planned(mock_origin, sender, receiver, "group=deploy")
        other = redeem_link(_link(mock_origin, sender, "job=myjob"))

        with pytest.raises(VaultRedeemError) as exc:
            apply_import(
                app, plan, other, plan.default_selection(), replace=False, cwd=root
            )
        assert exc.value.reason == "plan_mismatch"
        assert vault_entries(root) == []

    def test_only_selects_under_a_selector_and_skips_collisions(
        self,
        mock_origin: MockVault,
        sender: tuple[FunctualizeApp, Path],
        receiver: tuple[FunctualizeApp, Path],
    ) -> None:
        app, root = receiver
        vault_put(app, _TOKEN, "bobs-own", cwd=root)
        plan, _ = _planned(mock_origin, sender, receiver, "group=deploy")

        picked = plan.select([parse_selector("group=deploy")], replace=False)
        labels = {row.label for row in plan.rows if row.index in picked}
        assert "prod: --group deploy --field token" not in labels
        assert len(picked) == 2


# ── export names ─────────────────────────────────────────────────────────


class TestExportName:
    def test_a_job_field_uses_job_field(self) -> None:
        assert export_name(VaultIdentity("job", "deploy.infra.app", "api_token")) == (
            "DEPLOY_INFRA_APP_API_TOKEN"
        )

    def test_a_group_option_uses_scope_double_underscore_field(self) -> None:
        assert export_name(VaultIdentity("group", "deploy.infra", "api_token")) == (
            "DEPLOY_INFRA__API_TOKEN"
        )
