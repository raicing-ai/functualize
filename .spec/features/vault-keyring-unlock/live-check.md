# Live check — vault-keyring-unlock (spec A11)

**Status: NOT RUN.** This check needs the maintainer at the keyboard of a Linux
desktop with a Secret Service (Arch/niri, gnome-keyring), to answer and to
leave unanswered real unlock dialogs. It cannot be run by an agent or on a
headless host, and task 5.2 stays `[ ]` until the output below is real.

## How to run

From the repository root of this branch:

```bash
bash .spec/features/vault-keyring-unlock/live-check.sh 2>&1 | tee live-check.out
```

What it touches: one throwaway Secret Service collection
(`functualize-live-check`), created, locked/unlocked and deleted by the
script; a temporary `XDG_DATA_HOME`. What it never touches: the default
(`Login`) collection, except to **read** its `Locked` property before and after.
The script aborts if the throwaway collection would be the default one.

## Scenarios and what passes

| # | Scenario | Pass when |
|---|---|---|
| 1 | unlocked + stdout piped | `token ok`, `exit=0`, no dialog |
| 2 | locked + dialog answered within 30 s | a dialog appears; after answering, `token ok`, `exit=0` |
| 3 | locked + unanswered, `FUNCTUALIZE_VAULT_KEYRING_TIMEOUT=10s` | `exit=3` at ≈10 s, message says "locked or did not answer"; K-1 records whether the dialog outlives the refusal |
| 4 | two parallel jobs (K-2) | records how many dialogs appear and both exit codes |
| — | `Login` collection | `Login Locked: UNCHANGED` |

## Output

_Paste `live-check.out` here._
