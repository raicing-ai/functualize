"""V5 — a stale vault warns, and the run continues (ADR-016).

The vault exists so that the network is touched when somebody runs
``vault sync``, never because a job ran. The price of that is a cache, and the
price of a cache is that it can be out of date: a credential rotated in AWS
three days ago is still the old one here, and the job fails somewhere far away
from the reason.

So every run past ``[vault] max_age`` says so. What it must **not** do is
refuse — auto-syncing when stale was rejected in ADR-016 precisely because it
puts the network back on the run path, and failing when stale would be worse
still. A developer on a plane with a four-day-old vault has to keep working.
That "warn *and* succeed" pair is the acceptance criterion, and
:class:`TestAStaleVaultStillRuns` asserts both halves of it in one run.
"""

from __future__ import annotations

import logging
import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pytest
from pydantic import BaseModel

from functualize._app.state import AppState
from functualize._config.registry import ProviderRegistry
from functualize._config.vault import (
    DEFAULT_MAX_AGE,
    KEY_BYTES,
    MAX_AGE_VAR,
    InvalidDurationError,
    SecretsVault,
    format_duration,
    parse_duration,
    resolve_max_age,
)
from functualize._config.vault_source import VaultSource
from functualize.app.config import ConfigSources
from functualize.app.core import FunctualizeApp
from functualize.app.presets import remote_first
from functualize.job import RunStatus

if TYPE_CHECKING:
    from collections.abc import Generator

_KEY = b"\x2b" * KEY_BYTES
_KEY_HEX = _KEY.hex()

#: Long and distinctive on purpose, same discipline as `test_vault_miss.py`:
#: a short value can satisfy a leak assertion by coincidence.
_CONSPICUOUS = "PLAINTEXT-4f10ab77-must-never-be-logged"  # gitleaks:allow

_ANNOTATION = "fake-sm://prod/db-password"


# --------------------------------------------------------------------------
# Reading a duration
# --------------------------------------------------------------------------


class TestReadingADurationString:
    @pytest.mark.parametrize(
        ("text", "expected"),
        [
            ("30s", timedelta(seconds=30)),
            ("45m", timedelta(minutes=45)),
            ("24h", timedelta(hours=24)),
            ("7d", timedelta(days=7)),
            ("2w", timedelta(weeks=2)),
        ],
    )
    def test_each_unit(self, text: str, expected: timedelta) -> None:
        assert parse_duration(text) == expected

    @pytest.mark.parametrize(
        ("text", "expected"),
        [
            ("1d12h", timedelta(days=1, hours=12)),
            ("1w2d", timedelta(weeks=1, days=2)),
            ("1h30m15s", timedelta(hours=1, minutes=30, seconds=15)),
        ],
    )
    def test_terms_add_up(self, text: str, expected: timedelta) -> None:
        assert parse_duration(text) == expected

    @pytest.mark.parametrize("text", ["24H", " 24h ", "1d 12h"])
    def test_case_and_spacing_are_forgiven(self, text: str) -> None:
        """Forgiven because none of them is *ambiguous*. Every rejection below
        is a case where two readers would disagree about what was meant."""
        assert parse_duration(text) in (
            timedelta(hours=24),
            timedelta(days=1, hours=12),
        )

    def test_zero_is_a_legitimate_threshold(self) -> None:
        """'Always remind me' is a real preference, not a mistake."""
        assert parse_duration("0s") == timedelta(0)

    @pytest.mark.parametrize(
        "text", ["", "   ", "soon", "24hours", "1.5h", "-3h", "3h4x", "h", "24h,7d"]
    )
    def test_what_will_not_parse(self, text: str) -> None:
        with pytest.raises(InvalidDurationError):
            parse_duration(text)

    def test_a_bare_number_is_refused_rather_than_guessed(self) -> None:
        """The headline rejection. ``max_age = "3600"`` reads as an hour to
        whoever wrote it; read as days it is a decade. There is no safe guess,
        so there is no guess."""
        with pytest.raises(InvalidDurationError, match="needs a unit"):
            parse_duration("3600")

    def test_the_error_lists_the_units(self) -> None:
        with pytest.raises(InvalidDurationError) as exc:
            parse_duration("soon")
        for unit in ("w", "d", "h", "m", "s"):
            assert unit in str(exc.value)

    def test_the_error_quotes_what_was_written(self) -> None:
        with pytest.raises(InvalidDurationError, match="'24hours'"):
            parse_duration("24hours")

    def test_years_are_not_a_unit(self) -> None:
        """Deliberate: not a fixed length, so a threshold using one would
        quietly mean something different in a leap year."""
        with pytest.raises(InvalidDurationError):
            parse_duration("1y")

    def test_an_uppercase_m_is_refused_rather_than_folded_to_minutes(self) -> None:
        """The one exception to case-folding, and it was this test that found
        it. `24H` is an unambiguous typo; `1M` is not — whoever writes it means
        a month, and folding it to `m` makes it a minute. That is a factor of
        43,200 applied silently, which is the exact failure shape this whole
        feature exists to remove."""
        with pytest.raises(InvalidDurationError, match="'M' is not a unit"):
            parse_duration("1M")

    def test_the_uppercase_m_error_says_what_to_write_instead(self) -> None:
        with pytest.raises(InvalidDurationError, match="days or weeks"):
            parse_duration("1M")

    def test_a_lowercase_m_is_still_minutes(self) -> None:
        """The refusal must not have cost the unit it protects."""
        assert parse_duration("30m") == timedelta(minutes=30)


class TestSayingADurationAloud:
    @pytest.mark.parametrize(
        ("delta", "expected"),
        [
            (timedelta(0), "0s"),
            (timedelta(seconds=45), "45s"),
            (timedelta(minutes=90), "1h 30m"),
            (timedelta(hours=24), "1d"),
            (timedelta(days=2, hours=3), "2d 3h"),
            (timedelta(weeks=1, days=2), "1w 2d"),
        ],
    )
    def test_rendering(self, delta: timedelta, expected: str) -> None:
        assert format_duration(delta) == expected

    def test_at_most_two_units(self) -> None:
        """The reader is deciding whether to re-sync; the seconds never change
        that answer, and '2d 3h 14m 9s' is harder to read than '2d 3h'."""
        rendered = format_duration(timedelta(days=2, hours=3, minutes=14, seconds=9))
        assert rendered == "2d 3h"

    def test_a_negative_duration_says_so(self) -> None:
        assert format_duration(timedelta(hours=-3)) == "-3h"

    def test_it_round_trips_through_the_parser(self) -> None:
        """What the warning prints must be something the setting accepts —
        otherwise the message tells you a threshold you cannot write down."""
        for delta in (timedelta(hours=24), timedelta(days=2, hours=3)):
            assert parse_duration(format_duration(delta).replace(" ", "")) == delta


# --------------------------------------------------------------------------
# Which threshold is in force
# --------------------------------------------------------------------------


class TestWhichThresholdIsInForce:
    @pytest.fixture(autouse=True)
    def _no_ambient_override(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv(MAX_AGE_VAR, raising=False)

    def test_nothing_configured_is_the_default(self) -> None:
        assert resolve_max_age() == parse_duration(DEFAULT_MAX_AGE)

    def test_the_app_setting_is_honoured(self) -> None:
        assert resolve_max_age("7d") == timedelta(days=7)

    def test_the_environment_outranks_the_app(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Matches the settings store's documented default < project < env
        order, so registering `vault.max_age` in the catalog later changes no
        behaviour. An operator offline must be able to quieten a warning the
        app author never anticipated."""
        monkeypatch.setenv(MAX_AGE_VAR, "30d")
        assert resolve_max_age("1h") == timedelta(days=30)

    def test_the_environment_outranks_the_default(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv(MAX_AGE_VAR, "30d")
        assert resolve_max_age() == timedelta(days=30)

    def test_an_empty_environment_value_is_not_a_setting(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv(MAX_AGE_VAR, "")
        assert resolve_max_age("7d") == timedelta(days=7)


class TestAnUnusableThresholdNeverStopsTheTool:
    """The governing rule: this setting controls a *warning* that never fails a
    run. Letting a typo in it raise would make the misspelling more disruptive
    than the thing it is warning about.
    """

    @pytest.fixture(autouse=True)
    def _no_ambient_override(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv(MAX_AGE_VAR, raising=False)

    def test_a_bad_app_setting_falls_back_to_the_default(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        with caplog.at_level(logging.WARNING):
            resolved = resolve_max_age("soon")
        assert resolved == parse_duration(DEFAULT_MAX_AGE)

    def test_a_bad_app_setting_is_still_loud(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        with caplog.at_level(logging.WARNING):
            resolve_max_age("soon")
        message = caplog.records[0].getMessage()
        assert "remote_first(max_age=...)" in message
        assert "'soon'" in message

    def test_a_bad_environment_value_names_the_variable(
        self, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ) -> None:
        monkeypatch.setenv(MAX_AGE_VAR, "whenever")
        with caplog.at_level(logging.WARNING):
            resolve_max_age()
        assert f"${MAX_AGE_VAR}" in caplog.records[0].getMessage()

    def test_a_bad_environment_value_falls_to_the_app_setting_not_the_default(
        self, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Skipping the unusable candidate means continuing *down* the
        precedence order, not jumping to the bottom of it."""
        monkeypatch.setenv(MAX_AGE_VAR, "whenever")
        with caplog.at_level(logging.WARNING):
            resolved = resolve_max_age("7d")
        assert resolved == timedelta(days=7)

    def test_both_unusable_still_yields_the_default(
        self, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ) -> None:
        monkeypatch.setenv(MAX_AGE_VAR, "whenever")
        with caplog.at_level(logging.WARNING):
            resolved = resolve_max_age("soon")
        assert resolved == parse_duration(DEFAULT_MAX_AGE)
        assert len(caplog.records) == 2


class TestTheDefaultHasOneSpelling:
    """`app/config.py` cannot import `_config.vault` — that module pulls in
    `cryptography`, and `app/config.py` is on the cold boot path of every app,
    including the ones that never open a vault. So the default is expressed as
    "unconfigured" there and as a literal here, and these tests are what stop
    the two from drifting.
    """

    def test_the_field_defaults_to_unconfigured(self) -> None:
        assert ConfigSources().vault_max_age is None

    def test_unconfigured_resolves_to_the_documented_default(self) -> None:
        assert DEFAULT_MAX_AGE == "24h"
        assert resolve_max_age(ConfigSources().vault_max_age) == timedelta(hours=24)

    def test_the_preset_leaves_it_unconfigured_by_default(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv(MAX_AGE_VAR, raising=False)
        assert remote_first().vault_max_age is None

    def test_the_preset_carries_an_explicit_threshold(self) -> None:
        assert remote_first(max_age="7d").vault_max_age == "7d"

    def test_no_other_preset_grew_the_field(self) -> None:
        from functualize.app.presets import classic, env_only, twelve_factor

        for preset in (classic, twelve_factor, env_only):
            assert preset().vault_max_age is None

    def test_the_environment_variable_is_spelled_as_the_store_would(self) -> None:
        """`vault.max_age` under FUNCTUALIZE_<SECTION>_<KEY>. Registering the
        setting in the catalog later must not rename what operators already
        export."""
        from functualize._types.settings import AppSettingsSchema, Setting

        schema = AppSettingsSchema(settings=())
        setting = Setting(name="vault.max_age", type="str", description="")
        assert schema.env_var_for(setting) == MAX_AGE_VAR


# --------------------------------------------------------------------------
# How old is the vault
# --------------------------------------------------------------------------


def _vault(path: Path, *, keys: tuple[str, ...] = ("database.password",)) -> Path:
    store = SecretsVault(path)
    for key in keys:
        store.put(
            key,
            _CONSPICUOUS,
            annotation=_ANNOTATION,
            provider="fake-sm",
            encryption_key=_KEY,
        )
    return path


def _backdate(path: Path, key: str, delta: timedelta) -> None:
    """Rewrite one row's `synced_at`, the way real time would have."""
    stamp = (datetime.now(UTC) - delta).isoformat()
    conn = sqlite3.connect(path)
    with conn:
        conn.execute("UPDATE secrets SET synced_at = ? WHERE key = ?", (stamp, key))
    conn.close()


class TestHowOldIsTheVault:
    def test_an_empty_vault_has_no_age(self, tmp_path: Path) -> None:
        """Nothing stored cannot be out of date. Warning about the freshness of
        no values would be noise on a first run, before anyone has had the
        chance to sync."""
        assert SecretsVault(tmp_path / "v.db").age() is None

    def test_a_fresh_entry_is_about_zero(self, tmp_path: Path) -> None:
        age = SecretsVault(_vault(tmp_path / "v.db")).age()
        assert age is not None
        assert age < timedelta(minutes=1)

    def test_a_backdated_entry_reports_its_age(self, tmp_path: Path) -> None:
        path = _vault(tmp_path / "v.db")
        _backdate(path, "database.password", timedelta(days=3))
        age = SecretsVault(path).age()
        assert age is not None
        assert timedelta(days=3) <= age < timedelta(days=3, minutes=1)

    def test_the_oldest_entry_decides(self, tmp_path: Path) -> None:
        """A vault is only as fresh as the value most likely to have been
        rotated behind it. Judging on the newest would let one re-synced key
        vouch for twenty stale ones."""
        path = _vault(tmp_path / "v.db", keys=("a.one", "b.two"))
        _backdate(path, "a.one", timedelta(days=9))
        age = SecretsVault(path).age()
        assert age is not None
        assert age >= timedelta(days=9)

    def test_a_clock_that_moved_backwards_reads_as_fresh(self, tmp_path: Path) -> None:
        """Negative, deliberately left unclamped: skew must not be able to
        manufacture a staleness warning."""
        path = _vault(tmp_path / "v.db")
        _backdate(path, "database.password", timedelta(hours=-6))
        age = SecretsVault(path).age()
        assert age is not None
        assert age < timedelta(0)

    def test_now_can_be_supplied(self, tmp_path: Path) -> None:
        path = _vault(tmp_path / "v.db")
        later = datetime.now(UTC) + timedelta(days=5)
        age = SecretsVault(path).age(now=later)
        assert age is not None
        assert age >= timedelta(days=5)

    def test_a_naive_timestamp_is_read_as_utc(self, tmp_path: Path) -> None:
        """A hand-edited or older row must produce an answer, not a TypeError
        from subtracting an aware datetime from a naive one."""
        path = _vault(tmp_path / "v.db")
        naive = (datetime.now(UTC) - timedelta(days=2)).replace(tzinfo=None).isoformat()
        conn = sqlite3.connect(path)
        with conn:
            conn.execute("UPDATE secrets SET synced_at = ?", (naive,))
        conn.close()

        age = SecretsVault(path).age()
        assert age is not None
        assert timedelta(days=2) <= age < timedelta(days=2, minutes=1)

    def test_listing_also_survives_a_naive_timestamp(self, tmp_path: Path) -> None:
        path = _vault(tmp_path / "v.db")
        naive = datetime(2024, 1, 1, 12, 0, 0).isoformat()  # noqa: DTZ001
        conn = sqlite3.connect(path)
        with conn:
            conn.execute("UPDATE secrets SET synced_at = ?", (naive,))
        conn.close()

        entry = SecretsVault(path).list_entries()[0]
        assert entry.synced_at.tzinfo is not None


# --------------------------------------------------------------------------
# The warning on the run path
# --------------------------------------------------------------------------


def _source(path: Path, *, max_age: timedelta | None, key: bytes | None = _KEY) -> Any:
    return VaultSource(
        path, encryption_key=key, providers=("fake-sm",), max_age=max_age
    )


class TestTheWarningOnTheRunPath:
    @pytest.fixture
    def stale(self, tmp_path: Path) -> Path:
        path = _vault(tmp_path / "v.db")
        _backdate(path, "database.password", timedelta(days=3))
        return path

    def test_a_stale_vault_warns_on_the_first_read(
        self, stale: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        with caplog.at_level(logging.WARNING):
            _source(stale, max_age=timedelta(hours=24)).get("password", "database")
        assert len(caplog.records) == 1
        assert "stale" in caplog.records[0].getMessage()

    def test_the_warning_names_the_age_and_the_threshold(
        self, stale: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        with caplog.at_level(logging.WARNING):
            _source(stale, max_age=timedelta(hours=24)).get("password", "database")
        message = caplog.records[0].getMessage()
        assert "3d" in message
        assert "1d" in message

    def test_the_warning_names_the_fix(
        self, stale: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        with caplog.at_level(logging.WARNING):
            _source(stale, max_age=timedelta(hours=24)).get("password", "database")
        assert "vault sync" in caplog.records[0].getMessage()

    def test_the_value_still_comes_back(self, stale: Path) -> None:
        """Warn *and* run. A stale value is what offline work is made of."""
        assert (
            _source(stale, max_age=timedelta(hours=24)).get("password", "database")
            == _CONSPICUOUS
        )

    def test_no_plaintext_reaches_the_log(
        self, stale: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        """ADR-008. Asserted against `msg` and `args` as well as the rendered
        message, because a %s-style record carries its arguments separately and
        a structured handler renders those."""
        with caplog.at_level(logging.WARNING):
            _source(stale, max_age=timedelta(hours=24)).get("password", "database")
        record = caplog.records[0]
        assert _CONSPICUOUS not in record.getMessage()
        assert _CONSPICUOUS not in str(record.msg)
        assert _CONSPICUOUS not in str(record.args)

    def test_it_warns_once_per_run_not_once_per_read(
        self, stale: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        source = _source(stale, max_age=timedelta(hours=24))
        with caplog.at_level(logging.WARNING):
            for _ in range(5):
                source.get("password", "database")
        assert len(caplog.records) == 1

    def test_a_miss_still_only_warns_once(
        self, stale: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        """The staleness check hangs off the read, not off a hit — a vault too
        old to hold the key you want is exactly when you need to hear it."""
        source = _source(stale, max_age=timedelta(hours=24))
        with caplog.at_level(logging.WARNING):
            assert source.get("nowhere", "database") is None
            assert source.get("password", "database") == _CONSPICUOUS
        assert len(caplog.records) == 1

    def test_a_fresh_vault_says_nothing(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        path = _vault(tmp_path / "v.db")
        with caplog.at_level(logging.WARNING):
            _source(path, max_age=timedelta(hours=24)).get("password", "database")
        assert caplog.records == []

    def test_just_under_the_threshold_is_silent(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        path = _vault(tmp_path / "v.db")
        _backdate(path, "database.password", timedelta(hours=23, minutes=59))
        with caplog.at_level(logging.WARNING):
            _source(path, max_age=timedelta(hours=24)).get("password", "database")
        assert caplog.records == []

    def test_just_over_the_threshold_warns(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        """The pair pins the comparison's direction. Either one alone passes
        under a comparison that never fires, or one that always does."""
        path = _vault(tmp_path / "v.db")
        _backdate(path, "database.password", timedelta(hours=24, minutes=1))
        with caplog.at_level(logging.WARNING):
            _source(path, max_age=timedelta(hours=24)).get("password", "database")
        assert len(caplog.records) == 1

    def test_no_threshold_disables_the_check(
        self, stale: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        with caplog.at_level(logging.WARNING):
            _source(stale, max_age=None).get("password", "database")
        assert caplog.records == []

    def test_an_unusable_vault_never_checks_its_age(
        self, stale: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        """No key means every lookup falls through anyway, and boot has already
        said so once. Repeating it here would drown that message."""
        with caplog.at_level(logging.WARNING):
            assert (
                _source(stale, max_age=timedelta(hours=24), key=None).get(
                    "password", "database"
                )
                is None
            )
        assert caplog.records == []

    def test_a_missing_vault_file_never_checks_its_age(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        with caplog.at_level(logging.WARNING):
            _source(tmp_path / "absent.db", max_age=timedelta(hours=24)).get(
                "password", "database"
            )
        assert caplog.records == []

    def test_constructing_a_source_reads_nothing(
        self, stale: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Deferred to the first read so `func --help` and completions stay
        quiet: a stale vault is only worth mentioning to someone about to use
        it."""
        with caplog.at_level(logging.WARNING):
            _source(stale, max_age=timedelta(hours=24))
        assert caplog.records == []


# --------------------------------------------------------------------------
# The acceptance criterion, end to end
# --------------------------------------------------------------------------


class _FakeRemoteProvider:
    """Registered where the entry-point scan would put it, so the test does not
    depend on which provider plugins happen to be installed."""

    def identifier(self) -> str:
        return "fake-sm"

    def is_ready(self) -> bool:
        return True

    def fetch(self, reference: str) -> str:  # pragma: no cover - sync is 4.1
        return f"fetched:{reference}"


class Credentials(BaseModel):
    password: str


@pytest.fixture
def project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Generator[Path]:
    """An isolated project with its own XDG data dir, so the vault this test
    writes is the vault `vault_path_for_project()` finds."""
    root = tmp_path / "project"
    (root / ".functualize").mkdir(parents=True)
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    monkeypatch.setenv("FUNCTUALIZE_VAULT_KEY", _KEY_HEX)
    monkeypatch.delenv(MAX_AGE_VAR, raising=False)
    monkeypatch.chdir(root)

    def _register(self: ProviderRegistry) -> None:
        self.register_remote_provider(_FakeRemoteProvider())

    monkeypatch.setattr(
        ProviderRegistry, "_discover_remote_entry_points", _register, raising=True
    )
    AppState.reset()
    yield root
    AppState.reset()


def _fill_project_vault(days_old: float) -> Path:
    from functualize._config.vault import vault_path_for_project

    path = vault_path_for_project()
    SecretsVault(path).put(
        "report.password",
        _CONSPICUOUS,
        annotation=_ANNOTATION,
        provider="fake-sm",
        encryption_key=_KEY,
    )
    if days_old:
        _backdate(path, "report.password", timedelta(days=days_old))
    return path


def _run(max_age: str | None = None) -> Any:
    app = FunctualizeApp(name="staletest", config_sources=remote_first(max_age=max_age))

    def report(config: Credentials) -> str:
        return f"used:{config.password}"

    app.register_dynamic_job("report", report, config_class=Credentials)
    return app.execute("report")


@pytest.mark.usefixtures("project")
class TestAStaleVaultStillRuns:
    """The acceptance criterion, both halves in one run.

    A test that only asserted the warning would pass just as well if the run
    had been refused, and a test that only asserted SUCCESS would pass with the
    warning deleted. Neither of those is the behaviour ADR-016 decided on.
    """

    def test_it_warns_and_the_job_succeeds(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        _fill_project_vault(days_old=4)
        with caplog.at_level(logging.WARNING):
            result = _run()

        assert result.status is RunStatus.SUCCESS
        stale = [r for r in caplog.records if "stale" in r.getMessage()]
        assert len(stale) == 1, [r.getMessage() for r in caplog.records]

    def test_the_job_receives_the_stale_value(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Offline work stays possible means the old value is *used*, not that
        the run merely survives."""
        _fill_project_vault(days_old=4)
        with caplog.at_level(logging.WARNING):
            result = _run()

        assert result.return_value == f"used:{_CONSPICUOUS}"

    def test_a_fresh_vault_runs_without_a_word(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        _fill_project_vault(days_old=0)
        with caplog.at_level(logging.WARNING):
            result = _run()

        assert result.status is RunStatus.SUCCESS
        assert [r for r in caplog.records if "stale" in r.getMessage()] == []

    def test_a_wider_threshold_silences_it(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """`remote_first(max_age=...)` is the knob, reached through boot."""
        _fill_project_vault(days_old=4)
        with caplog.at_level(logging.WARNING):
            result = _run(max_age="30d")

        assert result.status is RunStatus.SUCCESS
        assert [r for r in caplog.records if "stale" in r.getMessage()] == []

    def test_the_environment_can_silence_it_too(
        self, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ) -> None:
        """The operator's override reaches the run path, not just
        `resolve_max_age` in isolation."""
        _fill_project_vault(days_old=4)
        monkeypatch.setenv(MAX_AGE_VAR, "30d")
        with caplog.at_level(logging.WARNING):
            result = _run(max_age="1h")

        assert result.status is RunStatus.SUCCESS
        assert [r for r in caplog.records if "stale" in r.getMessage()] == []

    def test_a_narrower_threshold_reaches_the_run_path(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """The other direction, so the knob is proven to do something rather
        than to be ignored in a way that happens to look right."""
        _fill_project_vault(days_old=0)
        with caplog.at_level(logging.WARNING):
            result = _run(max_age="0s")

        assert result.status is RunStatus.SUCCESS
        assert [r for r in caplog.records if "stale" in r.getMessage()] != []

    def test_the_plaintext_never_reaches_the_log(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        _fill_project_vault(days_old=4)
        with caplog.at_level(logging.WARNING):
            _run()

        for record in caplog.records:
            assert _CONSPICUOUS not in record.getMessage()
            assert _CONSPICUOUS not in str(record.args)
