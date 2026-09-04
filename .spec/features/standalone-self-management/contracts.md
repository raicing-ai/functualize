# Contracts

## 1. `functualize._cli.runtime`

```python
@dataclass(frozen=True)
class Detection:
    mode: InstallMode
    owning_distribution: str | None
    #: NEW. The standalone binary's own absolute path, from PyApp's `PYAPP`
    #: environment variable. `None` for every non-standalone mode, and for a
    #: standalone binary built without `PYAPP_PASS_LOCATION=1` or whose
    #: `current_exe()` lookup failed.
    standalone_binary: str | None

    @property
    def degraded(self) -> bool: ...
```

`degraded` becomes:

```python
if self.mode is InstallMode.STANDALONE:
    return self.standalone_binary is None
return self.mode.degraded or self.owning_distribution is None
```

`detect()` gains no parameters: `standalone_binary` is read from the `environ`
mapping it already takes, so it stays exercisable in every mode from a test.

## 2. `functualize._cli.package_ops`

```python
def script_name(environ: Mapping[str, str] | None = None) -> str:
    """The command the user typed. Never `-c`."""
```

Resolution order: `PYAPP_COMMAND_NAME`, then `argv[0]`'s basename when it is not
`-c` and not empty, then `func`.

`install_commands` / `uninstall_commands`, `STANDALONE` case:

```python
(owned_python(), "-m", "pip", "install", package)
(owned_python(), "-m", "pip", "uninstall", "-y", package)
```

`update_commands` raises `StandaloneUpdateError` — a sentinel, not a command tuple —
for `STANDALONE`, because replacing a file is not a subprocess:

```python
class StandaloneUpdateError(Exception):
    """`self update` on a standalone install is handled in-process."""
```

The `distribution is None` guard in all three moves *after* the `STANDALONE`
case, so standalone no longer trips it.

## 3. `functualize._cli.self_update` (new module)

```python
@dataclass(frozen=True)
class ReleaseSource:
    repo: str          # "owner/name"
    asset_prefix: str  # "functualize" -> functualize-<target>.tar.gz
    target: str        # "x86_64-unknown-linux-gnu"

def read_release_source(prefix: Path) -> ReleaseSource | None:
    """`<prefix>/standalone-release.json`, or None when absent/unreadable."""

@dataclass(frozen=True)
class Available:
    version: str
    archive_url: str
    checksums_url: str

def latest_release(source: ReleaseSource, *, opener: Opener) -> Available:
    """Raises UpdateUnavailable when the release or its asset is missing."""

def verify(archive: bytes, checksums: str, asset_name: str) -> None:
    """Raises ChecksumMismatch. An asset absent from SHA256SUMS is a mismatch."""

def extract_executable(archive: bytes, *, is_zip: bool) -> bytes:
    """The single executable member. Raises UpdateUnavailable otherwise."""

def replace_binary(target: Path, payload: bytes) -> None:
    """Write beside `target` on the same filesystem, chmod, `os.replace`."""

def perform(detection, *, prefix, opener, echo, confirm) -> int:
    """The whole flow. Returns an ExitCode value."""
```

`Opener` is `Callable[[str], bytes]` — the single network seam, replaced
wholesale in tests. No HTTP library is added; `urllib.request` is stdlib.

## 4. Baked artifact

`<distribution root>/standalone-release.json`, written by
`.github/scripts/bake.sh`:

```json
{
  "repo": "raicing-ai/functualize",
  "asset_prefix": "functualize",
  "target": "x86_64-unknown-linux-gnu"
}
```

Its absence is a supported state, not an error: a consumer application baking
its own binary either writes its own file or gets a clean refusal.

## 5. Build inputs

`.github/workflows/release.yml`, `binaries` job:

```yaml
PYAPP_PASS_LOCATION: "1"
```
