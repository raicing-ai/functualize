# Live check v2 — vault-keyring-unlock (spec A11')

**Status: NOT RUN (v2).** The first live check (v1) found the daemon crash
recorded in `research.md` R9 and changed the design; this is the check for the
design that followed. It needs the maintainer at the keyboard of a Linux
desktop with a Secret Service (Arch/niri, gnome-keyring) to answer and to
cancel real unlock dialogs. Task R8.2 stays `[ ]` until real output replaces the
placeholder below.

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

_Paste `live-check.out` here, then mark scenarios 1–5 pass/fail with the evidence._
