# Research — vault-keyring-unlock

Findings that **change the shape** of the feature. Findings that are simply true
went into `spec.md`. Every number below is the output of the command beside it,
run in this worktree on 2026-10-02.

## R1. "Needs a vault item" is answerable without the key

`VaultSource._stored_keys` reads the stored key *names* in clear
(`_config/vault_source.py`, "Metadata is stored in clear precisely so this is
possible"). So the question "does this run need to open an entry?" is
`qualified in stored_keys` and costs no key and no keyring.

**Consequence.** Laziness does not need a new idea: `VaultSource.get` already
reaches the key only on the path that is about to fall through or decrypt. What
is wrong is *when the key is resolved* (R2), not what the source does with it.

## R2. The key is resolved eagerly, at boot, whenever a vault file exists

```
rg -n "resolve_vault_key\(" src plugins -g '*.py'     # 6 call sites
```

| Site | What it is | Needs the key? |
|---|---|---|
| `_app/boot.py:1303` | `remote_first()` source, built at boot | only on a stored/declared lookup |
| `_app/boot.py:1364` | dormant (ordinary app) source, built at boot **when `vault_path.exists()`** | only on a stored lookup |
| `app/vault.py:502` (`_resolve_key`) | `vault put` | always (encrypts) |
| `app/vault.py:643` (`vault_inspect`) | readability report | diagnostic; must not prompt |
| `app/utils.py:1835` (`vault_status`) | status report | diagnostic; already `allow_interactive=False` |
| `app/utils.py:1977` (`vault_sync`) | sync | always (writes) |

The two boot sites resolve before any job is chosen. Today that is harmless to
latency only because the keychain is skipped off-TTY; **once the TTY gate goes,
an eager boot-time read would put a keyring call (and possibly a dialog) on
every `func --help`, completion and unrelated job in any project that has a
vault file.** `boot.py:1360-1363` records this exact cost as "accepted" under the
TTY rule. Under this feature it is not acceptable, so the boot sites must stop
resolving eagerly. This is what the maintainer called out ("if the job doesn't
require a vault item it doesn't make sense to get blocked").

`VaultSource` has 4 constructors, all in `_app/boot.py`
(`rg -n "VaultSource\(" src plugins`). The blast radius of making the key lazy
is that file plus `_config/vault_source.py`.

## R3. There is no `[vault]` config section; the knob cannot be `[vault] keyring_timeout`

```
rg -n "\[vault\]|vault\.max_age" docs/guides/configuration.md   # prose only, line 662
rg -n "vault_max_age" src -g '*.py'                             # 5 hits
```

`max_age` reaches the vault two ways only: the `remote_first(max_age=...)` preset
argument (→ `ConfigSources.vault_max_age`) and `$FUNCTUALIZE_VAULT_MAX_AGE`. An
*ordinary* app (the dormant source) passes `max_age=None` and has no config-file
route at all. The Jira comment on FOSS-31 and the story FOSS-88 said
`[vault] keyring_timeout`; **that was wrong** and is corrected there.

**Consequence.** `[vault]` has to be *created*. The existing way to add a
setting is the func settings catalog (`FUNC_SETTINGS` in
`_cli/data/func_settings.py` + `_RECOGNIZED_SECTIONS`/`_RECOGNIZED_KEYS` in
`_cli/config.py`, guarded by a drift-catcher test). That gives the env spelling
for free: `FUNCTUALIZE_<SECTION>_<KEY>` = `FUNCTUALIZE_VAULT_KEYRING_TIMEOUT`.
`app/adapters/surface_gate.py` already reads `FuncSettingsStore.discover()` from
the app layer, best-effort. Layering hazard: `_config/vault_keys.py` must not
import `_cli.data`; the app-layer caller reads the value and hands it down.
Maintainer decision 2026-10-02: env var **and** `[vault]` in `.functualize.toml`.

## R4. `VaultKeyProvider` is public, but has no implementer outside core

`functualize.plugin` exports `VaultKeyProvider` and `VaultKeyInitializer`
(`plugin/__init__.py:54-55,129-130`).

```
rg -n "class .*KeyProvider|def interactive" src plugins -g '*.py'
```

returns only `EnvKeyProvider` and `KeychainKeyProvider` (`_config/vault_keys.py`)
and the protocol itself. The entry-point group was removed (module docstring), so
third parties wire a provider by hand. A change that **keeps every existing
signature** and only redefines what `interactive()` promises breaks nobody; a
signature change would break a public protocol for zero known users. Prefer the
first. A new capability goes in a *separate optional protocol*, the move ADR-023
§5 already made for `VaultKeyInitializer`.

## R5. The TTY gate has exactly two legitimate remaining jobs

```
rg -n "isatty" src/functualize/_config src/functualize/_cli/vault_cmd.py \
   src/functualize/app/vault.py src/functualize/app/utils.py src/functualize/_app/boot.py
```

→ `_config/vault_keys.py:298,307` (the gate this feature removes) and
`_cli/vault_cmd.py:486,707` (hidden-input prompt in `put`, confirmation in
`remove`). The latter two ask a human a question and stay.

## R6. Prior art (read from source, 2026-10-02)

- `gh`: `internal/keyring/keyring.go` wraps get/set in a goroutine and abandons
  it after a fixed deadline, returning a typed `TimeoutError`. `GH_TOKEN`
  short-circuits it.
- `git-credential-libsecret`: connects with `secret_service_get_sync` and
  searches with `SECRET_SEARCH_UNLOCK`; fails fast when there is no session bus.
  Git calls the helper regardless of terminal and gates only its last-resort
  prompt (`GIT_TERMINAL_PROMPT`).
- `ssh-agent`: the unlock state lives outside the process, found through an
  ambient channel; lifetime is the agent's.

None gates *reading* on a stream being a TTY. Each puts a deadline or an opt-out
on the *prompt*.

## R7. This host (Arch / niri / gnome-keyring)

`org.freedesktop.secrets` is owned by `gnome-keyring-daemon`; the `Login`
collection reports `Locked = false`. `secret-tool`, `busctl`,
`gnome-keyring-daemon`, `kwalletd6` are installed. `keyring` 25.7.0 pulls
`secretstorage` and `jeepney` on Linux (`uv.lock`). gnome-keyring has **no
built-in idle timer** — "8 hours" is whatever the user's keyring is configured
to do (KWallet and KeePassXC have timers). functualize owns no expiry.

**Live testing must never touch `Login`**: locking it would break the user's
`gh` token and git credentials, both stored there.

## R8. Hazard not in the ticket: N lookups, N waits

A run resolves many config fields. If each failed lookup re-attempted the
keyring, a locked keyring would cost `N × 30s`. The outcome (found *or* failed)
must be remembered for the life of the process.
