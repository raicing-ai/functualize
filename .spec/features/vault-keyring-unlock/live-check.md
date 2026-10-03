# Live check v2 — vault-keyring-unlock (spec A11')

**Status: RUN 2026-10-03 (v2) — scenarios 1-5 pass; one evidence gap in
scenario 5, see below.** The first live check (v1) found the daemon crash
recorded in `research.md` R9 and changed the design; this is the check for the
design that followed, run by the maintainer at the keyboard of an Arch/niri
desktop (gnome-keyring 50.0) against commit `afaa5cb`.

## How to run

From the repository root of this branch:

```bash
bash .spec/features/vault-keyring-unlock/live-check.sh 2>&1 | tee live-check.out
```

What it touches: one throwaway Secret Service collection
(`functualize-live-check`) — created (answer its password dialog), locked and
deleted by the script — and a temporary `XDG_DATA_HOME`. What it never touches:
the default (`Login`) collection, except to **read** its `Locked` property; the
coredump list, which it only counts. It aborts if the throwaway collection
would be the default one.

**Every dialog is ended inside the dialog** — answered, or cancelled with its
own Cancel button. Nothing here ends a prompt from the client side. The
abandon-style experiments (Ctrl-C, SIGTERM, SIGKILL, a deadline, `Dismiss`) are
what crashed the daemon in R9, so they run **only** in `sandbox/`, on a private
D-Bus session with its own daemon (`sandbox/run_sandbox.sh`), never on the real
session.

## Scenarios — what each proves

| # | Scenario | Pass when | Proves |
|---|---|---|---|
| 1 | unlocked + stdout piped | `token ok`, `exit=0`, no dialog, prompt objects unchanged | A1: a pipe reads an unlocked keyring silently |
| 2 | locked + stdout piped (`keyring_timeout=30s`) | `exit=3` in **under 2 s**, the neutral "keyring is locked" text, **no dialog**, prompt objects unchanged | A4': a run never raises an unlock prompt; the 30 s bound is not a prompt wait |
| 3 | locked, then `func builtin vault unlock`, dialog answered | `Unlocked.` (exit 0), then the piped run prints `token ok` | B4' and the unlock-elsewhere story |
| 4 | locked, `vault unlock`, **Cancel** pressed in the dialog | exit 3 ("cancelled"), the collection still locked; a second `vault unlock` then works | a cancel in the dialog is safe and leaves the daemon usable (R9: not a crash trigger) |
| 5 | two parallel piped jobs on a locked keyring | both `exit=3`, **zero dialogs** | K-2 resolved by design |
| — | before / after | `Login Locked: UNCHANGED`, `coredumps: UNCHANGED` | the real session was not disturbed |

## Manual checklist — macOS and Windows

Not scripted (no throwaway-keychain flow is safe to automate on a user's own
machine). Each line is pass/fail, written down with the OS version:

**macOS**

1. With the login keychain unlocked: `func <a job that reads a stored secret> | cat`
   prints the value, no dialog.
2. Lock the login keychain (Keychain Access → Lock, or `security lock-keychain`):
   the same piped run exits 3 **at once** with "The keyring is locked …", and
   **no** keychain dialog appears.
3. `func builtin vault unlock` in Terminal shows the keychain's dialog; answer
   it; it prints `Unlocked.`; the piped run then works.
4. Repeat 3, pressing Cancel: exit 3, "cancelled"; the next `vault unlock` still
   shows a dialog.
5. `func builtin vault status` while locked: `Key state: locked`, no dialog.

**Windows**

1. `func <a job that reads a stored secret> | more` prints the value.
2. `func builtin vault unlock` prints "Nothing to unlock" and exits 0.
3. `func builtin vault status`: `Key state: available`.

## Output

Run on 2026-10-03 with `bash live-check.sh 2>&1 | tee live-check.r82.out` (host
name redacted).

| # | Scenario | Result | Evidence |
|---|---|---|---|
| 1 | unlocked + piped | **pass** | `token ok`, `exit=0`, maintainer: no dialog, prompt objects 1 -> 1 |
| 2 | locked + piped | **pass** | `exit=3`, neutral "the keyring is locked ..." text, maintainer: no dialog, prompt objects 1 -> 1. `elapsed=1.8s` equals scenario 1's `1.8s`, so that is process start-up and the refusal added **no wait** |
| 3 | `vault unlock`, dialog answered | **pass** | `Unlocked. ... runs read it silently while the keyring stays unlocked.`, state False, piped run `token ok` `exit=0`; maintainer: exactly one dialog, during `vault unlock` only |
| 4 | `vault unlock`, **Cancel** in the dialog | **pass** | `The unlock was cancelled in the keyring's dialog ...`, `exit=3`, state stayed True (locked); the second `vault unlock` showed a dialog and unlocked normally |
| 5 | two parallel piped jobs, locked | **pass on the main criterion; evidence gap** | both printed the neutral refusal, maintainer: **0** dialogs. The `job A/B exit=` lines were **not printed**: a script bug (`set -e` plus `pipefail` aborted each subshell before its `echo`), now fixed in `live-check.sh`. Exit codes and timing for this scenario are covered by the automated end-to-end test `test_two_parallel_piped_runs_both_refuse_at_once_without_a_prompt` (added to the R6.4 file after this run: two real `func` processes at once against a locked keyring, both exit 3, no unlock requested), not by this run |
| - | before / after | **unchanged** | `Login Locked: UNCHANGED` (false -> false), `coredumps: UNCHANGED` (9 -> 9); independently re-read afterwards: same daemon PID, no new `gnome-keyring` coredump, Login unlocked |

Observations:

- No dialog was raised by any run; the only five dialogs were the ones the
  script announced (creation, the scenario 3 unlock, the scenario 4 cancel and
  unlock, the final unlock), each ended inside the dialog.
- The throwaway collection was deleted by cleanup. **Four older locked
  `functualize-live-check` collections from the first (v1) runs remain**; they are
  not part of this run and need an announced unlock-and-delete or removal in the
  keyring manager.
- The Secret Service reports one live prompt object before and after the run; it
  predates this run and is unchanged by it.

Raw output:

```text
Checked 218 packages in 25ms

=== host
Linux <host> 7.2.3-1-cachyos #1 SMP PREEMPT_DYNAMIC Sun, 06 Sep 2026 22:01:30 +0000 x86_64 GNU/Linux
2026-10-03T07:53:26+07:00
afaa5cb

=== BEFORE (read-only): Login Locked, coredump count
Login Locked: b false
coredumps:    9

=== create the throwaway collection (ANSWER the keyring's password dialog for it)
throwaway collection: /org/freedesktop/secrets/collection/functualize_2dlive_2dcheck_5f4

=== store a throwaway vault key in the throwaway collection only
backend: keyring.backends.SecretService Keyring
stored functualize-vault/vault-key in the throwaway collection
Stored deploy.api_token (new).

=== 1. unlocked + piped: expect 'token ok', exit 0, no dialog
throwaway Locked = False
token ok
exit=0 elapsed=1.8s prompt-objects before=1 after=1

>>> Did any unlock dialog appear? (expected: n) answer: n

=== 2. locked + piped: expect a refusal in under 2 s, exit 3, NO dialog, no prompt object
locked /org/freedesktop/secrets/collection/functualize_2dlive_2dcheck_5f4
throwaway Locked = True
Error: Cannot open the stored vault entry 'deploy.api_token': the keyring is locked. Unlock it with your system's keyring manager, or run `func builtin vault unlock` in a terminal, or set `FUNCTUALIZE_VAULT_KEY`, then retry.

Refusing rather than falling through to the environment or a config file: the value stored for 'deploy.api_token' is the one you provisioned, and running on a different one would look like success.
exit=3 elapsed=1.8s prompt-objects before=1 after=1

>>> Did any unlock dialog appear? (expected: n) answer: n

=== 3. locked, then 'vault unlock' in this terminal: ANSWER the dialog (type the throwaway password)
throwaway Locked = True
Unlocked. The vault key is available from the system keyring, and runs read it silently while the keyring stays unlocked.
throwaway Locked = False
token ok
exit=0 elapsed=1.8s prompt-objects before=1 after=1

>>> Did exactly one dialog appear, during 'vault unlock' only? (expected: y) answer: y

=== 4. locked, 'vault unlock', and press CANCEL in the dialog: expect exit 3; then unlock again and ANSWER
locked /org/freedesktop/secrets/collection/functualize_2dlive_2dcheck_5f4
Error: The unlock was cancelled in the keyring's dialog. Run `func builtin vault unlock` again when you are ready.
vault unlock (cancelled) exit=3
throwaway Locked = True
Unlocked. The vault key is available from the system keyring, and runs read it silently while the keyring stays unlocked.
throwaway Locked = False

>>> Did the second dialog appear and unlock normally after the cancel? (expected: y) answer: y

=== 5. two parallel piped jobs on a locked keyring: both refuse at once, ZERO dialogs
locked /org/freedesktop/secrets/collection/functualize_2dlive_2dcheck_5f4
throwaway Locked = True
Error: Cannot open the stored vault entry 'deploy.api_token': the keyring is locked. Unlock it with your system's keyring manager, or run `func builtin vault unlock` in a terminal, or set `FUNCTUALIZE_VAULT_KEY`, then retry.

Refusing rather than falling through to the environment or a config file: the value stored for 'deploy.api_token' is the one you provisioned, and running on a different one would look like success.
Error: Cannot open the stored vault entry 'deploy.api_token': the keyring is locked. Unlock it with your system's keyring manager, or run `func builtin vault unlock` in a terminal, or set `FUNCTUALIZE_VAULT_KEY`, then retry.

Refusing rather than falling through to the environment or a config file: the value stored for 'deploy.api_token' is the one you provisioned, and running on a different one would look like success.

>>> How many unlock dialogs appeared? (expected: 0) answer: 0

=== finish: unlock the throwaway ('vault unlock' will show ONE dialog: ANSWER it) so cleanup can delete it
Unlocked. The vault key is available from the system keyring, and runs read it silently while the keyring stays unlocked.
throwaway Locked = False

=== done

=== cleanup: delete the throwaway collection and the temp project
deleted /org/freedesktop/secrets/collection/functualize_2dlive_2dcheck_5f4

=== AFTER (read-only): Login Locked, coredump count
Login Locked: b false
coredumps:    9
Login Locked: UNCHANGED
coredumps: UNCHANGED
```
