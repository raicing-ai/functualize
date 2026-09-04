"""Replacing a standalone binary with a newer release.

Nothing here makes a network request. `self_update` takes its fetch as an
injected `Opener`, and every test substitutes one — which is the point of the
seam: the interesting behaviour is what happens to bytes that have *already*
arrived, and a test that had to reach GitHub could exercise none of it.
"""

from __future__ import annotations

import hashlib
import io
import json
import tarfile
import zipfile
from pathlib import Path

import pytest

from functualize._cli import self_update
from functualize._cli.self_update import (
    Available,
    ChecksumMismatchError,
    ReleaseSource,
    UpdateUnavailableError,
)
from functualize.app.utils import ExitCode

_SOURCE = ReleaseSource(
    repo="raicing-ai/functualize",
    asset_prefix="functualize",
    target="x86_64-unknown-linux-gnu",
)


def _tar_with(payload: bytes, name: str = "func") -> bytes:
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tf:
        info = tarfile.TarInfo(name)
        info.size = len(payload)
        tf.addfile(info, io.BytesIO(payload))
    return buf.getvalue()


def _zip_with(payload: bytes, name: str = "func.exe") -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr(name, payload)
    return buf.getvalue()


def _sums(archive: bytes, name: str) -> str:
    return f"{hashlib.sha256(archive).hexdigest()}  {name}\n"


class TestTheReleaseSource:
    def test_a_baked_file_is_read(self, tmp_path: Path) -> None:
        (tmp_path / "standalone-release.json").write_text(
            json.dumps(
                {
                    "repo": "acme/thing",
                    "asset_prefix": "thing",
                    "target": "aarch64-apple-darwin",
                }
            )
        )
        got = self_update.read_release_source(tmp_path)
        assert got == ReleaseSource("acme/thing", "thing", "aarch64-apple-darwin")

    def test_no_file_is_a_supported_state(self, tmp_path: Path) -> None:
        """A binary somebody else baked has release channels this cannot know.

        Guessing would hand their users our artifact — the same wrong-owner
        failure the two-axis detection exists to prevent.
        """
        assert self_update.read_release_source(tmp_path) is None

    @pytest.mark.parametrize(
        "content",
        [
            '{"repo": "a/b"}',
            "not json at all",
            "[]",
            '{"repo": "", "asset_prefix": "x", "target": "y"}',
        ],
    )
    def test_an_unusable_file_reads_as_absent(
        self, tmp_path: Path, content: str
    ) -> None:
        (tmp_path / "standalone-release.json").write_text(content)
        assert self_update.read_release_source(tmp_path) is None

    def test_windows_targets_want_a_zip(self) -> None:
        source = ReleaseSource("a/b", "functualize", "x86_64-pc-windows-msvc")
        assert source.archive_name == "functualize-x86_64-pc-windows-msvc.zip"

    def test_every_other_target_wants_a_tarball(self) -> None:
        assert _SOURCE.archive_name == "functualize-x86_64-unknown-linux-gnu.tar.gz"


class TestLatestRelease:
    def _payload(self, *, assets: list[str], tag: str = "v9.9.9") -> bytes:
        return json.dumps(
            {
                "tag_name": tag,
                "assets": [
                    {"name": n, "browser_download_url": f"https://dl/{n}"}
                    for n in assets
                ],
            }
        ).encode()

    def test_it_takes_urls_from_the_payload(self) -> None:
        """Composed URLs 404 mid-download; named assets fail here, by name."""
        body = self._payload(
            assets=[_SOURCE.archive_name, "SHA256SUMS", "functualize-other.tar.gz"]
        )
        got = self_update.latest_release(_SOURCE, opener=lambda _u: body)
        assert got == Available(
            version="9.9.9",
            archive_url=f"https://dl/{_SOURCE.archive_name}",
            checksums_url="https://dl/SHA256SUMS",
        )

    def test_a_missing_archive_is_named(self) -> None:
        body = self._payload(assets=["SHA256SUMS"])
        with pytest.raises(UpdateUnavailableError, match=_SOURCE.archive_name):
            self_update.latest_release(_SOURCE, opener=lambda _u: body)

    def test_a_missing_sums_file_is_named(self) -> None:
        body = self._payload(assets=[_SOURCE.archive_name])
        with pytest.raises(UpdateUnavailableError, match="SHA256SUMS"):
            self_update.latest_release(_SOURCE, opener=lambda _u: body)

    def test_a_transport_failure_is_not_a_traceback(self) -> None:
        def boom(_url: str) -> bytes:
            raise OSError("network is unreachable")

        with pytest.raises(UpdateUnavailableError, match="unreachable"):
            self_update.latest_release(_SOURCE, opener=boom)


class TestVerification:
    def test_a_matching_digest_passes(self) -> None:
        archive = b"the real thing"
        self_update.verify(archive, _sums(archive, "a.tar.gz"), "a.tar.gz")

    def test_a_substituted_payload_is_refused(self) -> None:
        """What a compromised mirror looks like from the client side."""
        published = _sums(b"the real thing", "a.tar.gz")
        with pytest.raises(ChecksumMismatchError):
            self_update.verify(b"something else entirely", published, "a.tar.gz")

    def test_an_unlisted_asset_is_refused(self) -> None:
        """Absence of evidence is not a pass.

        "No line for this name" and "the line does not match" are the same
        security outcome, and treating the first as benign is how an unsigned
        artifact gets installed.
        """
        archive = b"x"
        with pytest.raises(ChecksumMismatchError, match="not listed"):
            self_update.verify(archive, _sums(archive, "other.tar.gz"), "a.tar.gz")

    def test_a_binary_marker_in_the_sums_line_is_tolerated(self) -> None:
        """`sha256sum -b` writes ` *name`, and releases do get built that way."""
        archive = b"payload"
        line = f"{hashlib.sha256(archive).hexdigest()} *a.tar.gz\n"
        self_update.verify(archive, line, "a.tar.gz")


class TestExtraction:
    def test_a_tarball_yields_its_single_member(self) -> None:
        assert (
            self_update.extract_executable(_tar_with(b"ELF..."), is_zip=False)
            == b"ELF..."
        )

    def test_a_zip_yields_its_single_member(self) -> None:
        assert (
            self_update.extract_executable(_zip_with(b"MZ..."), is_zip=True) == b"MZ..."
        )

    def test_more_than_one_member_is_refused(self) -> None:
        buf = io.BytesIO()
        with tarfile.open(fileobj=buf, mode="w:gz") as tf:
            for name in ("func", "extra"):
                info = tarfile.TarInfo(name)
                info.size = 1
                tf.addfile(info, io.BytesIO(b"x"))
        with pytest.raises(UpdateUnavailableError, match="found 2"):
            self_update.extract_executable(buf.getvalue(), is_zip=False)


class TestReplacement:
    def test_the_new_payload_lands_and_is_executable(self, tmp_path: Path) -> None:
        target = tmp_path / "func"
        target.write_bytes(b"old")
        target.chmod(0o755)
        self_update.replace_binary(target, b"new")
        assert target.read_bytes() == b"new"
        assert target.stat().st_mode & 0o111

    def test_it_stages_beside_the_target(self, tmp_path: Path) -> None:
        """`os.replace` is atomic only within a filesystem, and /tmp is
        routinely a different one — so staging elsewhere would turn the atomic
        rename into a copy that can be interrupted half-written."""
        seen: list[Path] = []
        real = self_update.tempfile.mkstemp

        def spy(*args: object, **kwargs: object):  # type: ignore[no-untyped-def]
            seen.append(Path(str(kwargs.get("dir"))))
            return real(*args, **kwargs)  # type: ignore[arg-type]

        target = tmp_path / "nested" / "func"
        target.parent.mkdir()
        target.write_bytes(b"old")
        self_update.tempfile.mkstemp = spy  # type: ignore[assignment]
        try:
            self_update.replace_binary(target, b"new")
        finally:
            self_update.tempfile.mkstemp = real  # type: ignore[assignment]
        assert seen == [target.parent]

    def test_a_write_failure_leaves_no_debris(self, tmp_path: Path) -> None:
        target = tmp_path / "func"
        target.write_bytes(b"old")

        def explode(_self: object, _data: object) -> int:
            raise OSError("disk full")

        import builtins

        real_open = builtins.open
        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(
                self_update.os,
                "fdopen",
                lambda *a, **k: (_ for _ in ()).throw(OSError("disk full")),
            )
            with pytest.raises(OSError, match="disk full"):
                self_update.replace_binary(target, b"new")
        assert real_open is builtins.open
        assert target.read_bytes() == b"old"
        assert list(tmp_path.iterdir()) == [target]


class TestPerform:
    def _run(self, tmp_path: Path, **over: object) -> tuple[int, list[str]]:
        archive = _tar_with(b"NEW-BINARY")
        listing = json.dumps(
            {
                "tag_name": "v9.9.9",
                "assets": [
                    {
                        "name": _SOURCE.archive_name,
                        "browser_download_url": "https://dl/archive",
                    },
                    {"name": "SHA256SUMS", "browser_download_url": "https://dl/sums"},
                ],
            }
        ).encode()
        # Always the *published* archive's digest, never the served one: a
        # substituted payload has to be measured against what the release said,
        # or the tampering test verifies a checksum of the tampering.
        sums = _sums(archive, _SOURCE.archive_name).encode()

        def opener(url: str) -> bytes:
            if url.endswith("releases/latest"):
                return listing
            if url == "https://dl/sums":
                return over.get("sums", sums)  # type: ignore[return-value]
            return over.get("archive", archive)  # type: ignore[return-value]

        (tmp_path / "standalone-release.json").write_text(
            json.dumps(
                {
                    "repo": _SOURCE.repo,
                    "asset_prefix": _SOURCE.asset_prefix,
                    "target": _SOURCE.target,
                }
            )
        )
        binary = tmp_path / "func"
        binary.write_bytes(b"OLD-BINARY")
        said: list[str] = []
        code = self_update.perform(
            binary=binary,
            prefix=tmp_path,
            current_version=str(over.get("current", "0.1.0")),
            assume_yes=bool(over.get("assume_yes", True)),
            echo=said.append,
            confirm=lambda _p: bool(over.get("confirmed", True)),
            opener=opener,
        )
        return code, said

    def test_a_newer_release_replaces_the_binary(self, tmp_path: Path) -> None:
        code, said = self._run(tmp_path)
        assert code == int(ExitCode.OK)
        assert (tmp_path / "func").read_bytes() == b"NEW-BINARY"
        assert any("9.9.9" in line for line in said)

    def test_no_release_source_refuses(self, tmp_path: Path) -> None:
        """AC8. Exit 3 so a script can tell this from a failed update."""
        binary = tmp_path / "func"
        binary.write_bytes(b"OLD")
        said: list[str] = []
        code = self_update.perform(
            binary=binary,
            prefix=tmp_path,
            current_version="0.1.0",
            assume_yes=True,
            echo=said.append,
            confirm=lambda _p: True,
            opener=lambda _u: pytest.fail("must not fetch"),
        )
        assert code == int(ExitCode.REFUSED)
        assert binary.read_bytes() == b"OLD"

    def test_an_already_current_binary_downloads_nothing(self, tmp_path: Path) -> None:
        """AC10 — the listing is fetched, the 100 MB archive is not."""
        code, said = self._run(tmp_path, current="9.9.9")
        assert code == int(ExitCode.OK)
        assert (tmp_path / "func").read_bytes() == b"OLD-BINARY"
        assert any("Already at" in line for line in said)

    def test_a_tampered_archive_never_reaches_the_disk(self, tmp_path: Path) -> None:
        """AC9. The binary is untouched, and extraction was never attempted —
        handing `tarfile` unverified bytes is itself the attack surface."""
        code, said = self._run(tmp_path, archive=_tar_with(b"EVIL"))
        assert code == int(ExitCode.JOB_RAISED)
        assert (tmp_path / "func").read_bytes() == b"OLD-BINARY"
        assert any("Refusing to install" in line for line in said)

    def test_declining_changes_nothing(self, tmp_path: Path) -> None:
        code, _ = self._run(tmp_path, assume_yes=False, confirmed=False)
        assert code == int(ExitCode.REFUSED)
        assert (tmp_path / "func").read_bytes() == b"OLD-BINARY"

    def test_yes_skips_the_prompt_but_not_the_printing(self, tmp_path: Path) -> None:
        """AC12 — `--yes` is for automation, and a log of what ran is what
        automation leaves behind."""
        _, said = self._run(tmp_path, assume_yes=True)
        joined = "\n".join(said)
        assert "This will replace" in joined
        assert "https://dl/archive" in joined


class TestVersionComparison:
    @pytest.mark.parametrize(
        ("available", "current", "newer"),
        [
            ("0.3.0", "0.2.1", True),
            ("0.2.1", "0.2.1", False),
            ("0.2.0", "0.2.1", False),
            ("1.0.0", "0.9.9", True),
            ("0.10.0", "0.9.0", True),
        ],
    )
    def test_numeric_order(self, available: str, current: str, newer: bool) -> None:
        assert self_update._is_newer(available, current) is newer

    def test_unparseable_versions_fall_back_to_inequality(self) -> None:
        assert self_update._is_newer("nightly", "stable") is True
        assert self_update._is_newer("nightly", "nightly") is False
