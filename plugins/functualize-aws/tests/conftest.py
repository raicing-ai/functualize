"""Fixtures for the AWS provider tests.

The unit tests never touch AWS. `_FakeClient` stands in for a boto3 client and
carries the two things that matter: what it was *asked* for, and a way to raise
the service's own not-found exception, which botocore builds per client rather
than exporting as an importable class.
"""

from __future__ import annotations

from typing import Any

import pytest
from functualize_aws import clear_credential_cache


@pytest.fixture(autouse=True)
def no_leaked_credentials() -> Any:
    """The assume-role cache is module state; never let it cross a test."""
    clear_credential_cache()
    yield
    clear_credential_cache()


@pytest.fixture(autouse=True)
def no_ambient_aws(request: Any, monkeypatch: Any, tmp_path: Any) -> None:
    """Cut every path boto3 uses to find real credentials.

    Without this, a developer with working AWS credentials runs a different
    test suite from CI — and, worse, a unit test that accidentally reaches the
    network passes on their machine.

    Exempt for `@pytest.mark.integration`, which is the one place that is
    *supposed* to reach an endpoint. Without the exemption this fixture wipes
    the emulator's own settings back out from under the module that set them,
    and every integration test fails with `NoRegionError`.
    """
    if request.node.get_closest_marker("integration"):
        return
    for var in (
        "AWS_PROFILE",
        "AWS_ACCESS_KEY_ID",
        "AWS_SECRET_ACCESS_KEY",
        "AWS_SESSION_TOKEN",
        "AWS_DEFAULT_REGION",
        "AWS_REGION",
        "AWS_ENDPOINT_URL",
    ):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("AWS_CONFIG_FILE", str(tmp_path / "no-config"))
    monkeypatch.setenv("AWS_SHARED_CREDENTIALS_FILE", str(tmp_path / "no-creds"))
    # botocore consults IMDS as a last resort; off EC2 that is a slow no-op.
    monkeypatch.setenv("AWS_EC2_METADATA_DISABLED", "true")


class _Exceptions:
    """Stands in for `client.exceptions`, whose classes botocore builds per
    client rather than exporting."""

    def __init__(self, names: tuple[str, ...]) -> None:
        for name in names:
            setattr(self, name, type(name, (Exception,), {}))


class FakeClient:
    """A boto3 client that records its calls and returns canned responses."""

    def __init__(
        self,
        *,
        responses: dict[str, Any] | None = None,
        raises: str | None = None,
        exception_names: tuple[str, ...] = (),
    ) -> None:
        self.responses = responses or {}
        self.exceptions = _Exceptions(exception_names)
        self.raises = raises
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def _record(self, op: str, **kwargs: Any) -> Any:
        self.calls.append((op, kwargs))
        if self.raises is not None:
            raise getattr(self.exceptions, self.raises)()
        return self.responses[op]

    def get_secret_value(self, **kwargs: Any) -> Any:
        return self._record("get_secret_value", **kwargs)

    def get_parameter(self, **kwargs: Any) -> Any:
        return self._record("get_parameter", **kwargs)
