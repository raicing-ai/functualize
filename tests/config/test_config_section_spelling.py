"""Config-file sections use the same job-name spelling policy as discovery."""

from __future__ import annotations

from pathlib import Path

import pytest

from functualize._config.errors import ConfigurationError
from functualize._config.providers.toml import TomlFormatProvider
from functualize._config.resolved_field import env_name_for
from functualize._config.sources import FileSource
from functualize._primitives.locator import ResourceLocator


def _source(tmp_path: Path, document: str) -> FileSource:
    (tmp_path / "functualize.toml").write_text(document, encoding="utf-8")
    return FileSource(
        ResourceLocator().search_explicit(str(tmp_path)),
        format_providers={".toml": TomlFormatProvider()},
        pattern="functualize.toml",
        remote_providers=("aws-sm",),
    )


def test_written_section_supplies_canonical_job(tmp_path: Path) -> None:
    source = _source(tmp_path, '["job_aaǆ"]\nx = 1\n')
    assert source.get("x", section="job-aadž") == 1
    assert source.keys("job-aadž") == {"x"}


def test_written_section_rejects_inline_secret_provider(tmp_path: Path) -> None:
    source = _source(tmp_path, '["job_aaǆ"]\ntoken = "aws-sm://secret"\n')
    with pytest.raises(ValueError, match="legacy inline provider syntax"):
        source.reject_inline_provider("job-aadž", "token")


@pytest.mark.parametrize(
    ("section", "document"),
    [
        (
            "env-cfg",
            '[env-cfg]\ntoken = "safe"\n[env_cfg]\ntoken = "aws-sm://secret"\n',
        ),
        (
            "job-aadž",
            '["job-aadž"]\ntoken = "safe"\n["job_aadž"]\ntoken = "safe"\n'
            '["job_aaǆ"]\ntoken = "aws-sm://secret"\n',
        ),
        (
            "job-aadž",
            '["job_aadž"]\ntoken = "safe"\n["job_aaǆ"]\ntoken = "aws-sm://secret"\n',
        ),
        (
            "group.job-aadž",
            '["group"."job-aadž"]\ntoken = "safe"\n'
            '["group"."job_aaǆ"]\ntoken = "aws-sm://secret"\n',
        ),
    ],
)
def test_shadowed_inline_provider_is_rejected(
    tmp_path: Path, section: str, document: str
) -> None:
    source = _source(tmp_path, document)
    assert source.get("token", section=section) == "safe"
    with pytest.raises(ValueError, match="legacy inline provider syntax"):
        source.reject_inline_provider(section, "token")


def test_normalized_collision_names_both_keys(tmp_path: Path) -> None:
    source = _source(tmp_path, '["job-aaǆ"]\nx = 1\n["job_aaǆ"]\nx = 2\n')
    with pytest.raises(ConfigurationError) as error:
        source.get("x", section="job-aadž")
    assert "job-aaǆ" in str(error.value)
    assert "job_aaǆ" in str(error.value)


def test_legacy_spelling_takes_precedence_over_normalized_match(tmp_path: Path) -> None:
    source = _source(tmp_path, '["job_aadž"]\nx = 1\n["job_aaǆ"]\nx = 2\n')
    assert source.get("x", section="job-aadž") == 1


def test_exact_canonical_section_precedes_underscore_spelling(tmp_path: Path) -> None:
    source = _source(tmp_path, "[env_cfg]\nx = 1\n[env-cfg]\nx = 2\n")
    assert source.get("x", section="env-cfg") == 2


def test_dotted_walk_normalizes_each_level(tmp_path: Path) -> None:
    source = _source(tmp_path, '["ǆ_ops"."job_aaǆ"]\nx = 1\n')
    assert source.get("x", section="dž-ops.job-aadž") == 1


def test_environment_name_stays_derived_from_registered_name() -> None:
    assert env_name_for("job-aadž", "field") == "JOB_AADŽ_FIELD"
