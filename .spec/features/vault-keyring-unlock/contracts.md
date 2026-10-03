# Contracts — vault-keyring-unlock

External interfaces only. Internal types go in `schema.md` if the plan needs them.

## 1. Environment and settings

| Variable | Meaning | Default |
|---|---|---|
| `FUNCTUALIZE_VAULT_KEY` | 64 hex characters. First in order; when set the keyring is never touched. | unchanged |
| `FUNCTUALIZE_VAULT_KEYRING_TIMEOUT` | Env spelling of the setting below (derived: `FUNCTUALIZE_<SECTION>_<KEY>`). | `30s` |

### New func setting `vault.keyring_timeout`

```toml
# .functualize.toml (project) or ~/.config/functualize/config.toml (global)
[vault]
keyring_timeout = "30s"
```

- Type `str`, a duration in the same spelling as `FUNCTUALIZE_VAULT_MAX_AGE`
  (`30s`, `2m`). A bare number is refused, not assumed, as for `max_age`. An
  invalid value warns once and falls back to `30s` (as `resolve_max_age`).
- Precedence is the func-settings chain: default < global < project (nearest
  wins) < env.
- Registered in `FUNC_SETTINGS` (`_cli/data/func_settings.py`) and
  `_RECOGNIZED_SECTIONS` / `_RECOGNIZED_KEYS` (`_cli/config.py`); the section
  `vault` is new. It therefore also appears wherever func settings are listed or
  edited.
- Read by the **caller** (app layer, lazily and only when about to consult the
  keyring) and passed down as a plain value; `_config` does not import `_cli`.

## 2. Public protocol — `functualize.plugin.VaultKeyProvider`

**No signature changes.** Every existing method keeps its signature.

`interactive() -> bool` is redefined in prose only:

> Whether obtaining the key **requires a person at a terminal** (a prompt that a
> pipe cannot answer). A provider returning True is consulted only on a real TTY.
> A provider that may *block* on a backend but needs no terminal returns False and
> is bounded by the resolver's deadline.

`KeychainKeyProvider.interactive()` therefore changes from `True` to `False`.
`EnvKeyProvider` is unchanged.

### New optional protocol — `functualize.plugin.VaultKeyProbe`

Separate from `VaultKeyProvider`, as `VaultKeyInitializer` is (ADR-023 §5). A
provider that implements it can answer without ever prompting.

```python
class KeyAvailability(Enum):
    UNLOCKED = "unlocked"   # a read will not prompt
    LOCKED   = "locked"     # a read may prompt or block
    UNKNOWN  = "unknown"    # the backend cannot say

@runtime_checkable
class VaultKeyProbe(VaultKeyProvider, Protocol):
    def probe(self) -> KeyAvailability: ...
```

`probe()` never prompts, never blocks beyond a short fixed bound, never raises.

## 3. Resolution result (`functualize._config.vault_key_resolver`, internal layer)

`resolve_vault_key` **moves** from `_config/vault_keys.py` (which keeps only the
providers) to the new `_config/vault_key_resolver.py`, and returns a result that
carries *why* there is no key.

```python
class KeyStatus(Enum):
    FOUND        = "found"
    LOCKED       = "locked"        # locked, or deadline elapsed
    NO_KEYRING   = "no_keyring"    # no backend / extra missing / no session bus
    NOT_STORED   = "not_stored"    # a keyring answered; no entry
    UNKNOWN      = "unknown"       # SILENT access only: the backend cannot say

class KeyLookup:
    status: KeyStatus
    key: bytes | None            # set only when FOUND
    provider_id: str | None      # the provider that answered, or that failed
    waited: float                # seconds spent, for the message
```

`resolve_vault_key(project_id, providers=None, *, access=...)` — `access` selects
one of: `BOUNDED` (default, deadline), `FOREGROUND` (no deadline; `vault unlock`),
`SILENT` (never prompts: probe, then read only if `UNLOCKED`; `status`/`inspect`).
The previous `allow_interactive: bool | None` parameter is removed. Callers in
the repo: 6 (`research.md` R2).

The result of a process's first lookup is retained for the life of the process.

## 4. CLI

### `func builtin vault unlock [--json]`

| | Human | `--json` |
|---|---|---|
| Key found | `Vault key available from the 'keychain' provider.` exit **0** | `{"ok": true, "provider": "keychain"}` |
| Not found | `Error: <four-outcome message>` on stderr, exit **3** | `{"ok": false, "reason": "key_locked"\|"no_keyring"\|"key_not_stored", "message": "..."}` (same envelope as `_fail` in `_cli/vault_cmd.py`) |

Neither form ever contains the key or any part of it.

### `func builtin vault status`

Human: a new line `Key state:    available | locked | unknown | (no key provider)`.
JSON: adds `"key_state": "available" | "locked" | "unknown" | null`;
`"key_provider"` is unchanged. Additive.

### Refusal text (run path, `VaultEntryUnreadableError`)

Exit code **3**. Reason strings: `key_locked`, `no_keyring`, `key_not_stored`
(plus the existing wrong-key reason). The required content per outcome is in
`spec.md` B3 and is checked by test, including the **absence** of `vault remove`,
`vault clear` and (for direct entries) `vault sync` in the locked and no-keyring
messages.

## 5. Public Python API — `functualize.app.vault`

No new public functions. `VaultKeySourceError` (raised by `vault_put`) gains the
same three reason strings; its existing `key_unavailable` reason is kept for
compatibility and maps to `no_keyring`.

## 6. Not a contract

How the deadline is enforced (thread, subprocess, or the Secret Service API
directly), where the memoized result lives, and how `VaultSource` receives a
lazy key are plan-phase decisions.


---

# Addendum 1 contracts (2026-10-02)

## 8. Provider protocols (public, `functualize.plugin`)

- **`VaultKeyProvider.get_key`** gains a stated contract: it **must not prompt** and must
  return promptly; it returns `None` when it has no key and may raise a typed
  locked/unavailable error. Signatures are unchanged.
- **`interactive()`** keeps its meaning: obtaining the key requires a person at a terminal.
- New optional Protocol, separate from the provider (as `VaultKeyInitializer` is):

```python
@runtime_checkable
class VaultKeyUnlocker(VaultKeyProvider, Protocol):
    def unlock(self) -> bool: ...   # MAY prompt; True when a key is available afterwards
```

`VaultKeyProbe.probe()` is unchanged (never prompts).

## 9. The state API (public, `functualize.app.vault`)

```python
class VaultKeyStatus(Enum):
    UNLOCKED       = "unlocked"
    LOCKED         = "locked"
    UNKNOWN        = "unknown"        # the backend cannot say, or the probe hit its cap
    NO_KEYRING     = "no_keyring"
    NOT_APPLICABLE = "not_applicable" # this project has no vault file

@dataclass(frozen=True, slots=True)
class VaultKeyState:
    status: VaultKeyStatus
    source: str | None        # "env", or the adapter name, or None
    key_stored: bool | None   # on an unlocked keyring: is an entry present? None if unknown

def vault_key_state(app: Any | None = None, cwd: str | Path | None = None) -> VaultKeyState: ...
```

Guarantees: never prompts, never unlocks, never reads the secret, never raises (failure ->
`UNKNOWN`), returns within about 250 ms, cached briefly per resolver instance. When
`FUNCTUALIZE_VAULT_KEY` is set it returns `UNLOCKED`/`"env"` without touching a keyring.

`vault_unlock(app=None, cwd=None) -> KeyLookup` (existing) additionally raises
`UnlockAbandoned` after a second interrupt (B4').

## 10. CLI

- `func builtin vault unlock [--json]`: outcomes and exit codes per spec B4'. `--json`
  reasons: `already_unlocked`, `unlocked`, `cancelled`, `no_prompt`, `nothing_to_unlock`,
  `key_locked`, `no_keyring`, `key_not_stored`.
- `func builtin vault status` is unchanged except that `key_state` comes from
  `vault_key_state`.
- **`func --help` and every other help output are unchanged.**

## 11. Internal adapter contract (not public; `functualize._config`)

```python
class KeyringAdapter(Protocol):
    name: str
    def read_silent(self) -> AdapterRead: ...   # never prompts; bounded
    def state(self) -> KeyAvailability: ...      # never prompts; bounded ~1 s
    def unlock(self) -> AdapterRead: ...         # the only call that may prompt
```

`AdapterRead` is `FOUND(key)` | `LOCKED` | `NO_KEYRING` | `NOT_STORED` | `UNVERIFIED`
(generic adapter only: silence cannot be proven). The factory in
`_config/vault_keyring.py` selects by `sys.platform` and the active `keyring` backend; the
allowlist is the Secret Service family, macOS Keychain and Windows Credential Manager.

### 11a. Review amendment (2026-10-03): storing never prompts either

The first review found `vault init` reading through `unlock()` and writing through
`keyring.set_password` (which unlocks a locked Secret Service collection first) — a second
prompting path, against B4'. The port gains one operation:

```python
    def store_silent(self, secret: str) -> AdapterOutcome: ...   # never prompts
```

`FOUND` — stored, and a later `read_silent()` finds it; `LOCKED` — locked, nothing written,
no prompt; `NO_KEYRING` — no keyring, or nowhere to store without one; `UNVERIFIED` —
the generic adapter, which writes as little as it reads. `KeychainKeyProvider.initialize_key`
reads with `read_silent()` and writes with `store_silent()`; a locked keyring refuses
`vault init` with the B3' locked text pointing at `func builtin vault unlock`.

On macOS the silent read and the store carry the per-call
`kSecUseAuthenticationUI = kSecUseAuthenticationUIFail` option instead of switching the
process-wide `SecKeychainSetUserInteractionAllowed` flag, so two adapter instances in one
process cannot interleave into a prompting read. `unlock()` alone still allows interaction.
