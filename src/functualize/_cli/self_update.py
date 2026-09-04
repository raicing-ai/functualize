"""Replacing a standalone binary with a newer release.

Every other install mode delegates its update to a package manager, so its
implementation is a command tuple and a `subprocess.run`. A standalone binary
has no package manager: it is one file, and updating it means fetching a release
and putting a different file in its place.

PyApp's own updater is not an option. It is hidden unless
``PYAPP_EXPOSE_UPDATE=1``, refuses outright under ``PYAPP_SKIP_INSTALL=1`` —
``"Cannot update as installation is disabled"`` — and would ``pip install
--upgrade`` from an index if it ran, dissolving the offline-complete
distribution the binary exists to be.

The module is pure but for one injected callable. ``Opener`` is the single
network seam; every test replaces it, and none makes a request.
"""

from __future__ import annotations

import contextlib
import hashlib
import io
import json
import os
import re
import stat
import tarfile
import tempfile
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Callable

    #: Fetch a URL, return its bytes. Raises for any non-success status.
    Opener = Callable[[str], bytes]

__all__ = [
    "Available",
    "ChecksumMismatchError",
    "ReleaseSource",
    "UpdateUnavailableError",
    "extract_executable",
    "latest_release",
    "perform",
    "read_release_source",
    "replace_binary",
    "verify",
]

#: Written into the distribution root by `.github/scripts/bake.sh`.
_SOURCE_FILE = "standalone-release.json"

_SUMS_ASSET = "SHA256SUMS"


class UpdateUnavailableError(RuntimeError):
    """The update cannot proceed, and the reason is not the user's fault."""


class ChecksumMismatchError(RuntimeError):
    """The downloaded archive is not the one the release published."""


@dataclass(frozen=True)
class ReleaseSource:
    """Where this binary's releases live.

    Baked in at build time rather than hard-coded in the framework. An
    application that builds its own PyApp binary over functualize writes its own
    file and points its users at its own releases, instead of being handed ours
    — the same reason detection resolves an *owning distribution* rather than
    assuming ``functualize``.
    """

    repo: str
    asset_prefix: str
    target: str

    @property
    def archive_name(self) -> str:
        suffix = "zip" if self.target.endswith("-windows-msvc") else "tar.gz"
        return f"{self.asset_prefix}-{self.target}.{suffix}"


@dataclass(frozen=True)
class Available:
    version: str
    archive_url: str
    checksums_url: str


def read_release_source(prefix: Path) -> ReleaseSource | None:
    """``<prefix>/standalone-release.json``, or ``None``.

    Absence is a supported state, not an error: a binary somebody else baked has
    release channels this code cannot know, and guessing would hand their users
    our artifact.
    """
    path = prefix / _SOURCE_FILE
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(raw, dict):
        return None
    try:
        repo = str(raw["repo"])
        asset_prefix = str(raw["asset_prefix"])
        target = str(raw["target"])
    except KeyError:
        return None
    if not (repo and asset_prefix and target):
        return None
    return ReleaseSource(repo=repo, asset_prefix=asset_prefix, target=target)


def latest_release(source: ReleaseSource, *, opener: Opener) -> Available:
    """The newest published release, and the two URLs this update needs.

    Asset URLs are taken from the release payload rather than composed from a
    template. A release that renamed or failed to upload an asset then fails
    *here*, with the name it was looking for, instead of at a 404 mid-download.
    """
    url = f"https://api.github.com/repos/{source.repo}/releases/latest"
    try:
        payload = json.loads(opener(url))
    except Exception as exc:  # noqa: BLE001 - any transport failure reads alike
        raise UpdateUnavailableError(f"could not reach {url}: {exc}") from exc

    version = str(payload.get("tag_name", "")).lstrip("v")
    if not version:
        raise UpdateUnavailableError(f"{source.repo} published no tagged release")

    assets = {
        str(a.get("name", "")): str(a.get("browser_download_url", ""))
        for a in payload.get("assets", [])
        if isinstance(a, dict)
    }
    archive = assets.get(source.archive_name, "")
    checksums = assets.get(_SUMS_ASSET, "")
    if not archive:
        raise UpdateUnavailableError(
            f"release {version} publishes no {source.archive_name}"
        )
    if not checksums:
        raise UpdateUnavailableError(f"release {version} publishes no {_SUMS_ASSET}")
    return Available(version=version, archive_url=archive, checksums_url=checksums)


def verify(archive: bytes, checksums: str, asset_name: str) -> None:
    """Check ``archive`` against the release's ``SHA256SUMS``.

    An asset the file does not mention is a mismatch, not a pass. "No line for
    this name" and "the line does not match" are the same security outcome, and
    treating the first as absence of evidence is how an unsigned artifact gets
    installed.
    """
    digest = hashlib.sha256(archive).hexdigest()
    for line in checksums.splitlines():
        parts = line.split()
        if len(parts) != 2:
            continue
        published, name = parts[0], parts[1].lstrip("*")
        if name == asset_name:
            if published.lower() == digest:
                return
            raise ChecksumMismatchError(
                f"{asset_name}: published {published}, downloaded {digest}"
            )
    raise ChecksumMismatchError(f"{asset_name} is not listed in {_SUMS_ASSET}")


def extract_executable(archive: bytes, *, is_zip: bool) -> bytes:
    """The single executable member of a verified archive.

    Called only after :func:`verify`. Feeding `tarfile` unverified bytes is
    itself the attack surface, so the ordering is a property of the flow rather
    than a convention — `perform` has exactly one call site for each.
    """
    if is_zip:
        with zipfile.ZipFile(io.BytesIO(archive)) as zf:
            names = [n for n in zf.namelist() if not n.endswith("/")]
            if len(names) != 1:
                raise UpdateUnavailableError(
                    f"expected one file in the archive, found {len(names)}"
                )
            return zf.read(names[0])

    with tarfile.open(fileobj=io.BytesIO(archive), mode="r:gz") as tf:
        members = [m for m in tf.getmembers() if m.isfile()]
        if len(members) != 1:
            raise UpdateUnavailableError(
                f"expected one file in the archive, found {len(members)}"
            )
        handle = tf.extractfile(members[0])
        if handle is None:  # pragma: no cover - isfile() already excludes this
            raise UpdateUnavailableError("the archive member could not be read")
        return handle.read()


def replace_binary(target: Path, payload: bytes) -> None:
    """Put ``payload`` at ``target``, atomically.

    Written beside the target rather than in a temporary directory, because
    ``os.replace`` is only atomic within a filesystem and ``/tmp`` is routinely
    a different one. An interrupted update therefore leaves either the old
    binary or the new one, never a half-written file.

    POSIX unlinks by inode, so replacing a *running* executable is safe: the
    live process keeps its image. Windows holds the file open and refuses, so
    the running executable is renamed aside first and swept on a later run.
    """
    directory = target.parent
    handle, staged_name = tempfile.mkstemp(prefix=f".{target.name}.", dir=directory)
    staged = Path(staged_name)
    try:
        with os.fdopen(handle, "wb") as fh:
            fh.write(payload)
        staged.chmod(staged.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
        try:
            os.replace(staged, target)
        except PermissionError:
            # Windows: the running image cannot be overwritten, but it can be
            # renamed. The stale copy is best-effort swept, and left in place
            # rather than failing the update if it cannot be.
            stale = target.with_suffix(target.suffix + ".old")
            stale.unlink(missing_ok=True)
            os.replace(target, stale)
            os.replace(staged, target)
    except BaseException:
        staged.unlink(missing_ok=True)
        raise


def sweep_stale(target: Path) -> None:
    """Remove the ``.old`` copy a Windows replacement left behind."""
    stale = target.with_suffix(target.suffix + ".old")
    # Still held open by something is fine: the copy is stale, not load-bearing.
    with contextlib.suppress(OSError):  # pragma: no cover - Windows only
        stale.unlink(missing_ok=True)


def _is_newer(available: str, current: str) -> bool:
    """Whether ``available`` should be installed over ``current``.

    A numeric comparison over dot-separated leading digits, falling back to
    inequality. Deliberately not a full PEP 440 implementation: the only
    decision it makes is "offer the update", the user sees both versions before
    confirming, and pulling in a version parser for this would be the tail
    wagging the dog.
    """

    def key(v: str) -> tuple[int, ...]:
        return tuple(int(p) for p in re.findall(r"\d+", v)[:4])

    a, c = key(available), key(current)
    if a and c:
        return a > c
    return available != current


def default_opener(url: str) -> bytes:
    """The production fetch. ``urllib`` from the standard library.

    No HTTP dependency is added for this. The binary is the install method for
    a machine that may have nothing else on it, and every megabyte of payload
    is a decision — one that a request library would make on behalf of a single
    command.
    """
    import urllib.request

    request = urllib.request.Request(  # noqa: S310 - https, composed above
        url, headers={"Accept": "application/octet-stream, application/json"}
    )
    with urllib.request.urlopen(request, timeout=60) as response:  # noqa: S310
        data: bytes = response.read()
    return data


def perform(
    *,
    binary: Path,
    prefix: Path,
    current_version: str,
    assume_yes: bool,
    echo: Callable[[str], None],
    confirm: Callable[[str], bool],
    opener: Opener | None = None,
) -> int:
    """Fetch, verify and install a newer release over ``binary``.

    Returns an :class:`~functualize.app.utils.ExitCode` value. Refusals are
    ``REFUSED`` (3) so a script can tell "declined to act" from "acted and
    failed"; a genuine failure mid-update is ``JOB_RAISED``, matching how the
    rest of the CLI reports work that was attempted and did not finish.
    """
    from functualize.app.utils import ExitCode

    fetch = default_opener if opener is None else opener

    source = read_release_source(prefix)
    if source is None:
        echo(
            "This binary carries no release source, so there is nothing to "
            "check for updates.\n"
            "It was built by something other than functualize's own release "
            "pipeline; upgrade it the way it was installed."
        )
        return int(ExitCode.REFUSED)

    try:
        available = latest_release(source, opener=fetch)
    except UpdateUnavailableError as exc:
        echo(f"Cannot check for updates: {exc}")
        return int(ExitCode.JOB_RAISED)

    if not _is_newer(available.version, current_version):
        echo(f"Already at {current_version}; {source.repo} publishes no newer release.")
        return int(ExitCode.OK)

    echo(
        "This will replace:\n"
        f"  {binary}\n"
        f"  {current_version} -> {available.version}\n"
        f"  from {available.archive_url}\n"
        f"  verified against {available.checksums_url}"
    )
    if not assume_yes and not confirm("Proceed?"):
        return int(ExitCode.REFUSED)

    try:
        archive = fetch(available.archive_url)
        checksums = fetch(available.checksums_url).decode("utf-8", "replace")
    except Exception as exc:  # noqa: BLE001 - any transport failure reads alike
        echo(f"Download failed, nothing was changed: {exc}")
        return int(ExitCode.JOB_RAISED)

    # Before extraction, not merely before installation: handing `tarfile`
    # unverified bytes is itself the attack surface.
    try:
        verify(archive, checksums, source.archive_name)
    except ChecksumMismatchError as exc:
        echo(f"Refusing to install: {exc}\nThe binary was not touched.")
        return int(ExitCode.JOB_RAISED)

    try:
        payload = extract_executable(
            archive, is_zip=source.archive_name.endswith(".zip")
        )
    except (UpdateUnavailableError, tarfile.TarError, zipfile.BadZipFile) as exc:
        echo(f"The archive could not be unpacked: {exc}\nThe binary was not touched.")
        return int(ExitCode.JOB_RAISED)

    try:
        replace_binary(binary, payload)
    except OSError as exc:
        echo(f"Could not replace {binary}: {exc}")
        return int(ExitCode.JOB_RAISED)

    sweep_stale(binary)
    echo(f"Updated to {available.version}.")
    return int(ExitCode.OK)
