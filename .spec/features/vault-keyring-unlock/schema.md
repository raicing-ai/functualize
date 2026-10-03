# Schema — vault-keyring-unlock

Internal types only. External shapes are in `contracts.md`.

## `functualize._types.enums`

```python
class KeyAvailability(Enum):
    UNLOCKED = "unlocked"
    LOCKED   = "locked"
    UNKNOWN  = "unknown"
```

## `functualize._types.protocols`

```python
@runtime_checkable
class VaultKeyProbe(VaultKeyProvider, Protocol):
    def probe(self) -> KeyAvailability: ...
```

Re-exported from `functualize.plugin` with `KeyAvailability`.

## `functualize._config.vault`

```python
DEFAULT_KEYRING_TIMEOUT: Final = timedelta(seconds=30)
ENV_KEYRING_TIMEOUT: Final = "FUNCTUALIZE_VAULT_KEYRING_TIMEOUT"

class KeyringLockedError(VaultError): ...       # locked, or the unlock prompt was dismissed
class KeyringUnavailableError(VaultError): ...  # no backend / no daemon / no session bus

def resolve_keyring_timeout(configured: str | None = None) -> float: ...   # seconds
#   env > configured > default; reuses the max_age duration parser;
#   invalid -> one warning, default

def app_keyring_timeout(app: Any | None) -> float: ...
#   the single getattr(app._config_sources, "vault_keyring_timeout", None) chain
```

## `functualize._config.vault_key_resolver` (new)

```python
class KeyAccess(Enum):
    BOUNDED    = "bounded"
    FOREGROUND = "foreground"
    SILENT     = "silent"

class KeyStatus(Enum):
    FOUND = "found"; LOCKED = "locked"; NO_KEYRING = "no_keyring"
    NOT_STORED = "not_stored"; UNKNOWN = "unknown"

@dataclass(frozen=True, slots=True)
class KeyLookup:
    status: KeyStatus
    key: bytes | None = None          # only when FOUND; excluded from repr
    provider_id: str | None = None
    waited: float = 0.0
    timed_out: bool = False           # distinguishes "deadline" from "dismissed" inside LOCKED

class VaultKeyResolver:
    def __init__(self, project_id: str, providers: Sequence[VaultKeyProvider] | None = None,
                 *, timeout: float = 30.0) -> None: ...
    @classmethod
    def fixed(cls, key: bytes, provider_id: str = "fixed") -> VaultKeyResolver: ...  # tests, and "already known"
    def lookup(self, access: KeyAccess = KeyAccess.BOUNDED) -> KeyLookup: ...
    # instance state: _outcome: KeyLookup | None, _lock: threading.Lock

def resolve_vault_key(project_id, providers=None, *, access=KeyAccess.BOUNDED,
                      timeout=30.0) -> KeyLookup: ...      # one-shot, no memo shared

def describe_key_failure(lookup: KeyLookup, *, qualified: str | None = None,
                         direct: bool | None = None, timeout: float | None = None) -> str: ...
```

`KeyLookup.__repr__` must never include the key (a test asserts it).

### `lookup` decision table

| access | memo read | order | on failure |
|---|---|---|---|
| BOUNDED | yes (FOUND or failure) | env -> (TTY-needing providers only if a TTY) -> each remaining provider under the deadline | memoise |
| FOREGROUND | FOUND only | same, **no deadline** | do not memoise |
| SILENT | FOUND only | env; then `probe()`: UNLOCKED -> read bounded 5 s, LOCKED -> `LOCKED`, UNKNOWN/no probe -> `UNKNOWN` | do not memoise |

A provider exception maps: `KeyringLockedError` -> LOCKED; `KeyringUnavailableError`
or `is_available() is False` -> NO_KEYRING; `None` from a live provider -> keeps
trying, ends NOT_STORED if none had a key and at least one was available; any other
`VaultError` (bad hex) **propagates** unchanged.

## `functualize._config.vault_source`

```python
VaultSource(vault_path, *, key: VaultKeyResolver, providers=(), max_age=None)
```

`encryption_key` and `key_provider_id` are removed.

## `functualize.app.config`

```python
ConfigSources.vault_keyring_timeout: str | None = None   # like vault_max_age; env outranks it
```

## `functualize._cli.config`

```python
CliConfig.vault_keyring_timeout: str | None = None
CliConfig.config_sources(self) -> ConfigSources          # replaces 5 inline constructions
```

## `functualize._cli.data.func_settings`

`_spec("vault", "keyring_timeout", "str", "...", default="30s")`; `_RECOGNIZED_SECTIONS`
gains `"vault"`; `_RECOGNIZED_KEYS["vault"] = {"keyring_timeout"}`.

## `functualize.app.utils`

`VaultStatusReport.key_state: str | None` (`"available" | "locked" | "unknown" | None`).


---

# Addendum 1 schema (2026-10-02)

## `functualize._config.vault_keyring` (new) and the adapters

```python
class AdapterOutcome(Enum):
    FOUND = "found"; LOCKED = "locked"; NO_KEYRING = "no_keyring"
    NOT_STORED = "not_stored"; UNVERIFIED = "unverified"

@dataclass(frozen=True, slots=True)
class AdapterRead:
    outcome: AdapterOutcome
    key: bytes | None = None      # only FOUND; excluded from repr

def select_adapter(*, platform: str | None = None, backend: object | None = None) -> KeyringAdapter: ...
#   pure of side effects apart from lazy imports; `platform`/`backend` injectable for tests
```

Adapters (each in its own module, imported only on its platform):
`vault_keyring_secretservice.SecretServiceAdapter`, `vault_keyring_macos.MacKeychainAdapter`,
`vault_keyring_windows.WindowsCredentialAdapter`, `vault_keyring_generic.GenericAdapter`.

## Resolver changes

`KeyStatus` gains `UNVERIFIED`. `KeyAccess.BOUNDED` and `SILENT` both use `read_silent()`;
collapse them if nothing distinguishes them any more. `KeyAccess.FOREGROUND` -> `unlock()`.
`_run_bounded` remains as a hung-backend guard only. Memoise FOUND and BOUNDED failures
exactly as before; `vault_key_state` keeps its own short-TTL cache **on the instance**.

## `functualize.app.vault`

`VaultKeyStatus`, `VaultKeyState`, `vault_key_state`, `UnlockAbandoned` (contracts §9).

## `functualize.app.utils`

`VaultStatusReport.key_state` is derived from `VaultKeyState.status`
(`unlocked`->`available`, `locked`->`locked`, otherwise `unknown`, `not_applicable`->`None`).
