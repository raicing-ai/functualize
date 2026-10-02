# Spec — vault-keyring-unlock

- Tracked privately (story and field report; a related agent-routes report is linked, not absorbed).
- Binding text: ADR-016 §5 (ordering clause — **contradicted here, to be superseded**), ADR-023 §1 and §4 (**preserved**).
- Findings that shaped this: `research.md` (R1–R8).

## Problem

A developer stores the vault key in their OS keyring with `vault init`. A run that
needs a stored secret works in a terminal and fails the moment stdout is piped,
captured by an agent's Bash tool, or served over stdio MCP — with a message
("no vault key is available on this machine") that is false, and a fix list that
offers to destroy the only copy of the secret.

The cause is a proxy. ADR-016 §5 wants "an unattended run must not hang on a
prompt"; the code implements "stdin **and** stdout are TTYs"
(`_config/vault_keys.py:307`). That also blocks a *silent* read of a keyring the
developer already unlocked, which is the common case.

## Intent

A developer unlocks their native keyring once, from any terminal. For as long as
the keyring itself stays unlocked — its own policy and expiry — every functualize
run reads the key silently. functualize holds no key cache and no timer. The key
is needed only to open a vault item, so **a run that needs no vault item never
touches or waits on the keyring.**

## User stories

1. **Pipe / agent.** I unlocked my keyring this morning. `func report | jq`, a
   Claude Code Bash call and a stdio MCP job all get my stored secret.
2. **Failed, then unlock elsewhere.** An agent's job fails because my keyring is
   locked. I unlock it in another terminal and rerun; it works, with nothing to
   reconfigure.
3. **Unrelated job.** My project has a vault, but today's job reads no stored
   secret. It starts and finishes with no keyring call, no delay, no dialog —
   including `func --help` and completions.
4. **Unattended.** In CI, Lambda or a container I export `FUNCTUALIZE_VAULT_KEY`.
   Nothing touches a keyring, and a machine with no keyring fails immediately,
   not after a wait.
5. **Honest failure.** When the key cannot be had, the message says which of
   *locked / timed out / no keyring / nothing stored* happened and tells me the
   one next step. It never tells me to delete a secret that is fine.

## Behavior

### B1. When the key is resolved — lazily

- The vault key is resolved the first time a run must **open a stored entry**
  (decrypt it, or check the key against the store). A key that merely *could*
  be needed is not resolved.
- A run that reads no stored vault entry performs **zero** key-provider calls:
  no env read beyond the one already made, no keyring import, no D-Bus traffic.
- "A stored entry is requested" is decided from the store's clear-text key
  names, which need no key (ADR-023 §1 / `research.md` R1).
- `func --help`, completions and `builtin info` never resolve the key.

- **Consequences of laziness** (found by the plan's architecture gate):
  - **Listing never needs the key.** *(Confirmed by the maintainer 2026-10-02.)*
    Which keys the vault holds is answered from
    clear-text metadata. Resolving a config *section* that contains a stored entry
    that cannot be opened therefore **refuses** (ADR-023 §1), where it used to
    omit that entry silently. A section with no stored entries never touches the
    keyring.
  - **The `remote_first()` no-key warning moves.** *(Confirmed by the maintainer
    2026-10-02.)* It used to print at boot. A
    boot that resolves nothing cannot print it, so it prints **once, at the first
    declared-remote value that falls through** — the first moment the key is
    needed. A `remote_first()` app whose values all come from env or files no
    longer warns.

### B2. How the key is resolved — order and bound

1. `FUNCTUALIZE_VAULT_KEY`, if set. Unchanged. When it is set the keyring is
   never touched.
2. The OS keyring, **whether or not stdin/stdout are terminals**, behind a
   deadline of **30 seconds**. The deadline is the func setting
   `vault.keyring_timeout`: set in `.functualize.toml` under `[vault]`, in the
   global config, or by `FUNCTUALIZE_VAULT_KEYRING_TIMEOUT`, with the same
   precedence as every other func setting (default < global < project < env).
3. A provider that can only work by prompting at a terminal (none ships) is still
   consulted only on a real TTY. The TTY rule survives for *prompting*, not for
   *reading*.

- A locked keyring may show its own unlock dialog during the 30 seconds. If it
  is unlocked within the window the run proceeds; otherwise it is refused.
- Where no keyring can answer at all (no backend, no session bus) the outcome is
  immediate; the deadline is not waited out.
- The outcome — success **or** failure — is remembered for the life of the
  process. A run with many lookups waits at most once (`research.md` R8).
- functualize does not cache the key across processes and does not implement a
  timer. When the keyring relocks, the next run finds it locked.

### B3. Four outcomes, four messages

| Outcome | Meaning | Message must say |
|---|---|---|
| found | a provider returned a key | — |
| locked / timed out | a keyring exists but did not release the key in time | it is locked or did not answer within N s; unlock it, or run `func builtin vault unlock` in another terminal, or export `FUNCTUALIZE_VAULT_KEY`; then retry |
| no keyring | no backend, extra not installed, or no session bus | no keyring is reachable here; export `FUNCTUALIZE_VAULT_KEY`, or install `functualize[keychain]` |
| nothing stored | a keyring answered, no entry | no key is stored; `func builtin vault init` or export `FUNCTUALIZE_VAULT_KEY` |

- The refusal for a stored entry keeps ADR-023 §1: **refuse, never fall through**;
  exit code **3** (`ExitCode.REFUSED`).
- For *locked / timed out* and *no keyring* — states where the key may well exist —
  the message **never** offers `vault remove` or `vault clear` as a fix, and
  **never** offers `vault sync` for a `direct` entry.
- For *nothing stored* and *key does not open this store* — where the key really
  is gone — `remove` / `clear` may be listed **last**, with the warning that they
  destroy the entry and that for a `direct` entry it is the only copy.
- `vault status` carries the same rule for its "different key" message.

### B4. `func builtin vault unlock`

- Resolves the key in the **foreground with no deadline**, so a person can answer
  the keyring's own dialog.
- Reports which provider answered. **Never prints, logs or returns the key.**
- Succeeds (exit 0) if a key was found. Otherwise exits 3 with the same
  four-outcome message. `--json` follows the sibling commands' envelope.
- It does not unlock anything functualize owns; it triggers the keyring's own
  unlock and reports. The keyring decides how long it stays unlocked.

### B5. `vault status` and `vault inspect` never prompt

- They never raise a dialog and never wait on one.
- Where the keyring can be asked "are you locked?" without a prompt (Linux Secret
  Service), `status` reports the key as **available**, **locked**, or — if the
  backend cannot say — **unknown**. A keyring that is unlocked is read silently;
  one that is locked is *reported*, not opened.
- `status --json` gains a `key_state` field (additive); `key_provider` is
  unchanged.

### B6. What a terminal still decides

- `vault put`'s hidden-input prompt and `vault remove`'s confirmation continue to
  require a real TTY (`_cli/vault_cmd.py:486,707`). Unchanged.

### B7. Preserved

- One key per user (ADR-023 §4): service `functualize-vault`, account `vault-key`.
- ADR-023 §1: a stored entry that cannot be opened refuses the run.
- `FUNCTUALIZE_VAULT_KEY` wins over the keyring.
- `keyring` remains the optional `functualize[keychain]` extra; its absence is a
  reported state, not a crash.

## Acceptance criteria

Behavior only. Each is falsifiable; the plan phase assigns the command.

- **A1 — pipe works.** With a stored direct entry and an unlocked keyring, a run
  with stdout piped exits 0 and receives the value. *Fails against `master`.*
- **A2 — unrelated job is untouched.** With a vault file present and a keyring
  backend that raises on *any* call, a job that reads no stored entry exits 0
  and the backend records 0 calls. `func --help` likewise.
- **A3 — env short-circuits.** With `FUNCTUALIZE_VAULT_KEY` set, the backend
  records 0 calls even for a run that opens a stored entry.
- **A4 — bounded wait.** With a backend that blocks forever,
  a run needing a stored entry exits 3 after the configured timeout (±1 s) —
  tested with `FUNCTUALIZE_VAULT_KEYRING_TIMEOUT` at a small value — and the
  message states "locked or did not answer", names `vault unlock` and
  `FUNCTUALIZE_VAULT_KEY`, and does not contain `vault remove`, `vault clear`
  or (for a direct entry) `vault sync`.
- **A5 — no wait where none can help.** With no backend (`fail.Keyring`) the run
  exits 3 in well under the timeout, with the *no keyring* message.
- **A6 — one wait per process.** A run with ≥10 lookups against the blocking
  backend takes ≈ one timeout, not ten; the backend records one call.
- **A7 — `vault unlock`.** Exit 0 and a provider name when a key is found, with
  the key absent from stdout, stderr and `--json`; exit 3 with the matching
  message otherwise; no deadline applied.
- **A8 — status never prompts.** Against a *locked* collection `vault status`
  returns without invoking the unlock path, reporting `locked`; against an
  unlocked one it reports `available`; against a backend that cannot say,
  `unknown`.
- **A9 — TTY questions unchanged.** The existing `put` / `remove` tests for the
  non-terminal refusals still pass unmodified.
- **A10 — no import tax.** A run that resolves no key imports neither `keyring`
  nor `secretstorage`; the warm-boot import count is unchanged.
- **A11 — live, on this host.** On a throwaway Secret Service collection (never
  `Login`): unlocked → silent success under a pipe; locked + dialog answered →
  success; locked + unanswered → exit 3 at the timeout. Recorded as output in
  `verify`.
- **A12a — the setting is real.** `vault.keyring_timeout` is in the func settings
  catalog and the recognized-keys table (the drift-catcher test in
  `tests/cli/test_func_settings_store.py::TestCatalog` stays green); a value in a
  project `.functualize.toml` `[vault]` table changes the wait; the env var
  outranks the file; an invalid value warns once and falls back to 30 s, and a
  run with `FUNCTUALIZE_VAULT_KEY` set never reads the setting at all.
- **A12 — documented.** ADR-016 carries an "Amended by" note; the
  `VaultKeyProvider` docstring, `vault_keys.py` module docstring, the key table
  in `docs/guides/configuration.md` (the "Interactive" column) and `CHANGELOG.md`
  state the new rule; the private decision record (Proposed → Accepted) exists;
  and the shipped behavior is described in the private reference.

## Out of scope

- A functualize-side key cache, agent process, or timer.
- macOS and Windows "is it locked?" probes (they report `unknown`).
- Cross-process de-duplication of dialogs when `builtin parallel` starts several
  processes against a locked keyring (risk, noted in the plan).
- The file-path invocation defect (`func jobs/report.py report` never consults
  the vault) — to be filed separately.
- A `remote_first(keyring_timeout=...)` argument. The setting is a per-machine
  func setting, not a per-app one (decided 2026-10-02).

## Decided

- **Timeout surface (2026-10-02):** the env var, plus a new `[vault]` section in
  `.functualize.toml` / global config, both through the func settings catalog.
  Not a preset argument.

- **`put` and `sync` (2026-10-02):** use the same bounded 30 s access as a job
  run. They also run from scripts, where an unbounded wait is the hang this
  feature removes. `vault unlock` is the only command that waits without a limit.

## Open questions

None. (Plan's architecture gate may send work back here; see
`.claude/rules/spec-workflow.md`.)


---

# Addendum 1 — a run never raises an unlock prompt (2026-10-02)

Decided by the maintainer after the live check (`research.md` R9-R12). Where this
addendum conflicts with B2-B5 or A4-A8/A11 above, **the addendum wins**; the original
text stays as the record of what was first agreed.

## What changed, in one paragraph

The first design let a locked keyring raise its own unlock dialog during a run and waited
up to 30 s. On gnome-keyring 50.0 that is unsafe: ending an active unlock prompt from the
client side (a timeout followed by exit, Ctrl-C, an agent kill, `Dismiss`) can crash the
keyring daemon and re-lock **every** keyring. So a run reads the key **silently** or fails
at once; the only thing that ever asks the keyring to unlock is `func builtin vault unlock`,
run by a person, which waits for the dialog's own outcome.

## B2'. How a run gets the key

1. `FUNCTUALIZE_VAULT_KEY`, if set (unchanged; the keyring is not touched).
2. Otherwise the OS keyring, **read silently**: if it is unlocked the key is returned; if it
   is locked the run is **refused at once** (exit 3), with no wait, no dialog and no
   unlock request. This holds for every caller: pipes, agent shells, MCP, cron, jobs
   started from the TUI, `vault put`, `vault sync`.
3. `vault.keyring_timeout` (default 30 s, setting and env name unchanged) now only bounds
   a *hung* backend; reaching it yields "the keyring did not answer". It is never a way to
   walk away from a prompt.
4. A keyring backend that is not on the proven-silent allowlist (B9) is not read by a run;
   the refusal says so.

## B3'. Messages are provider-neutral

No message names a product (no gnome-keyring, KWallet, Keychain, Credential Manager,
Secret Service). The locked text:

> The keyring is locked. Unlock it with your system's keyring manager, or run
> `func builtin vault unlock` in a terminal, or set `FUNCTUALIZE_VAULT_KEY`, then retry.

`vault remove` / `vault clear` remain absent from the locked and no-keyring messages
(unchanged from B3).

## B4'. `func builtin vault unlock`

- The **only** operation that may ask the keyring to unlock. It waits, with no deadline,
  for the prompt's own outcome. It never cancels a prompt from the client side.
- Already unlocked: says so, exit 0. Unlocked now: names the adapter, exit 0 (never prints
  the key). The user pressed Cancel in the dialog: neutral message, exit 3. No prompt
  appeared (adapter-detected): neutral message, exit 3. A platform with nothing to unlock
  (Windows): says so, exit 0.
- Signals: while a prompt is outstanding, the **first** SIGINT/SIGTERM prints guidance
  ("waiting for the unlock prompt; answer or cancel it there") and keeps waiting; a
  **second** one exits with a warning that the keyring may misbehave. Handlers are
  restored afterwards.

## B8. The vault key state, for any surface

A public, side-effect-free function `functualize.app.vault.vault_key_state()` (contracts §9)
answers *unlocked / locked / unknown / no keyring / not applicable* plus where the answer
came from. It never prompts, never unlocks, never reads the secret, is capped at about
250 ms (UNKNOWN on timeout) and is cached briefly. `vault_status()` uses it for its
`key_state`, so there is one implementation.

- **Where it is shown (maintainer decision 2026-10-02):** the TUI status bar, updated from a
  thread worker, and `func builtin vault status`. **`func --help` is not changed.**
- The state probe is the one key-provider call a surface may make without being asked to
  resolve a key; A2/A10 are amended accordingly (A2').

## B9. Cross-platform behavior

- The keyring layer sits behind a small adapter contract — `read_silent()`, `unlock()`,
  `state()` — implemented per platform (Linux Secret Service family, macOS, Windows) and a
  fail-safe generic adapter. Platform code is imported lazily and only on its platform.
- **Allowlist rule:** a run reads only through an adapter proven silent. An unrecognised
  `keyring` backend is not read by a run; the refusal points to the env var or
  `vault unlock`.
- **Support levels are stated, not implied:** Linux is field-verified; macOS and Windows are
  implemented and CI-smoked but not field-verified until a user confirms. The docs say so.
- Verification is tiered (plan Addendum 1, D16): contract tests with fakes everywhere; a
  real-OS smoke on macOS/Windows/Linux runners; an unlock-elsewhere step where a
  no-dialog unlock exists (a spike); and a manual tier for the dialog itself.

## B10. The test suite and CI never touch a real session keyring

Already enforced by the suite-wide `_isolate_os_keyring` fixture; CI jobs use private
keychains/D-Bus sessions only. No script in this repository may raise an unlock prompt on a
user's real session, and the abandon-style experiments live in a private sandbox only.

## Acceptance changes

| Was | Now |
|---|---|
| A4: locked + piped waits then exits 3 at the timeout | **A4'**: locked + piped exits 3 in **under 2 s**; neutral message; the backend recorded **no** prompt request; on the live check, no new daemon coredump |
| A2/A10: no key-provider call for `--help` and unrelated runs | **A2'**: no secret read and no unlock ever; the only allowed call is the bounded, side-effect-free state probe, and only from a surface that displays it |
| A7: `vault unlock` reports provider, no deadline | **A7'**: adds the already-unlocked / cancelled / no-prompt / nothing-to-unlock outcomes and the two-signal policy |
| A8: `vault status` never prompts | covered by **A13** |
| A11: live check with dialog answered / unanswered / parallel | **A11'**: live check v2 (tasks R7.2/R8.2): unlocked+piped; locked+piped refuses fast with no dialog and no coredump; `vault unlock` answered; `vault unlock` cancelled; parallel locked runs show zero dialogs |

New criteria:
- **A13** `vault_key_state`: env set -> `unlocked` from `env` with no keyring call; no vault
  file -> `not_applicable`; locked fake -> `locked` with zero secret reads and zero prompts;
  a hung backend returns within the cap; repeated calls are served from the cache.
- **A14** the TUI shows the state from a thread worker and a hung probe does not block the
  event loop (`tests/tui_audit/`); `func --help` output is byte-identical to before.
- **A15** every adapter passes the same contract suite against fakes.
- **A16** with `sys.platform` forced to `darwin`/`win32`, importing and constructing the
  provider imports no Linux-only library; `mypy --platform darwin|win32` is clean on the
  keyring modules.
- **A17** the macOS/Windows/Linux CI smoke passes (tier 1); tier 2 passes or is dropped
  per platform with the reason recorded.
- **A18** no user-facing message names a keyring product (a test greps them).

## Out of scope (unchanged) and newly out of scope

Unchanged: a key cache or timer in functualize; per-key fresh fetch (tracked separately); the
file-path invocation defect. Newly: fixing gnome-keyring itself (we avoid its crash path and
may file upstream evidence); the pre-existing Windows type errors in `shell.py` and
`fresh_format.py`; the pre-existing order-dependent test
`test_default_when_nothing_sets_it`.

## Open items (small; defaults stand unless the maintainer says otherwise)

1. **Default of `vault.keyring_timeout`.** It is now only a hung-backend bound, so 30 s is
   generous; 5-10 s might fit better. Default stays 30 s.
