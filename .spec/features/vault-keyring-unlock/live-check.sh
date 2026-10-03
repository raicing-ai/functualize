#!/usr/bin/env bash
# Live check v2 for vault-keyring-unlock (spec A11'): a run never raises an
# unlock prompt; only `func builtin vault unlock` does.
#
# Run by the maintainer, at the keyboard, on a Linux desktop with a Secret
# Service (gnome-keyring), from the repository root of this branch:
#
#     bash .spec/features/vault-keyring-unlock/live-check.sh 2>&1 | tee live-check.out
#
# then paste live-check.out into live-check.md next to this file.
#
# SAFETY — what this touches and what it never touches:
#   * It creates ONE throwaway Secret Service collection (the keyring asks for
#     a password for it: answer that dialog — never leave it), stores a
#     throwaway test key in it, locks ONLY that collection, and deletes it at
#     the end. functualize is pointed at it with
#     KEYRING_PROPERTY_PREFERRED_COLLECTION.
#   * It never locks, unlocks or writes the default ("Login") collection. It
#     only READS that collection's `Locked` property, and the coredump count,
#     before and after, and prints whether either changed. It aborts if the
#     throwaway collection would be the default one.
#   * It never ends an unlock prompt from the client side: every dialog in
#     scenarios 3 and 4 is answered or cancelled IN THE DIALOG. The abandon-style
#     experiments (Ctrl-C, kill, a deadline) run only in sandbox/, on a private
#     bus — never here.
#   * Vaults go to a temporary XDG_DATA_HOME, so no real project vault is read
#     or written. FUNCTUALIZE_VAULT_KEY is unset for every run below.
#   * Not shipped: this file lives under .spec/features/ and is removed before
#     merge with the rest of the feature's artifacts.
set -euo pipefail

say() { printf '\n=== %s\n' "$*"; }
ask() { printf '\n>>> %s ' "$*"; read -r REPLY; printf 'answer: %s\n' "$REPLY"; }

LOGIN_LOCKED() {
  busctl --user get-property org.freedesktop.secrets \
    /org/freedesktop/secrets/aliases/default \
    org.freedesktop.Secret.Collection Locked
}

COREDUMPS() {  # read-only: how many coredumps the system has recorded
  coredumpctl list --no-pager 2>/dev/null | wc -l || echo "n/a"
}

PROMPT_OBJECTS() {  # read-only: the Secret Service's live prompt objects
  busctl --user tree --list org.freedesktop.secrets 2>/dev/null | grep -c '/prompt/' || true
}

command -v busctl >/dev/null || { echo "busctl is required"; exit 2; }
command -v uv >/dev/null || { echo "uv is required"; exit 2; }
uv sync --frozen --all-extras --all-packages >/dev/null

say "host"
uname -a
date --iso-8601=seconds
git rev-parse --short HEAD

say "BEFORE (read-only): Login Locked, coredump count"
BEFORE="$(LOGIN_LOCKED)"
DUMPS_BEFORE="$(COREDUMPS)"
echo "Login Locked: $BEFORE"
echo "coredumps:    $DUMPS_BEFORE"

WORK="$(mktemp -d -t functualize-live-check.XXXXXX)"
export XDG_DATA_HOME="$WORK/data" XDG_CACHE_HOME="$WORK/cache"
unset FUNCTUALIZE_VAULT_KEY FUNCTUALIZE_VAULT_KEYRING_TIMEOUT || true

# --- the throwaway collection -------------------------------------------
say "create the throwaway collection (ANSWER the keyring's password dialog for it)"
COLL="$(uv run python - <<'PY'
import secretstorage
bus = secretstorage.dbus_init()
default = secretstorage.Collection(bus).collection_path
coll = secretstorage.create_collection(bus, "functualize-live-check")
if coll.collection_path == default:
    raise SystemExit("ABORT: the throwaway collection is the default collection")
print(coll.collection_path)
PY
)"
echo "throwaway collection: $COLL"
export KEYRING_PROPERTY_PREFERRED_COLLECTION="$COLL"

guard() {  # every helper below refuses to act on the default collection
  uv run python - "$COLL" "$1" <<'PY'
import sys, secretstorage
bus = secretstorage.dbus_init()
default = secretstorage.Collection(bus).collection_path
path, action = sys.argv[1], sys.argv[2]
if path == default:
    raise SystemExit("ABORT: refusing to touch the default collection")
coll = secretstorage.Collection(bus, path)
if action == "lock":
    coll.lock()
    print("locked", path)
elif action == "state":
    print("throwaway Locked =", coll.is_locked())
elif action == "delete":
    coll.delete()
    print("deleted", path)
PY
}

cleanup() {
  say "cleanup: delete the throwaway collection and the temp project"
  # Deleting a LOCKED collection raises a dialog nobody announced; if that were
  # interrupted it would end a prompt from the client side (research R9). So only
  # an unlocked throwaway is deleted here; a locked one is left and reported.
  if [ "$(guard state 2>/dev/null | tail -1)" = "throwaway Locked = False" ]; then
    guard delete || echo "delete failed; remove 'functualize-live-check' in your keyring manager"
  else
    echo "the throwaway collection is still LOCKED, so it was NOT deleted."
    echo "Remove 'functualize-live-check' in your keyring manager (Passwords and Keys)."
  fi
  rm -rf "$WORK"
  say "AFTER (read-only): Login Locked, coredump count"
  AFTER="$(LOGIN_LOCKED)"
  DUMPS_AFTER="$(COREDUMPS)"
  echo "Login Locked: $AFTER"
  echo "coredumps:    $DUMPS_AFTER"
  if [ "$BEFORE" = "$AFTER" ]; then echo "Login Locked: UNCHANGED"; else echo "Login Locked: CHANGED"; fi
  if [ "$DUMPS_BEFORE" = "$DUMPS_AFTER" ]; then echo "coredumps: UNCHANGED"; else echo "coredumps: CHANGED"; fi
}
trap cleanup EXIT

say "store a throwaway vault key in the throwaway collection only"
KEY="$(uv run func builtin vault keygen)"
KEY="$KEY" uv run python - <<'PY'
import os, keyring
backend = keyring.get_keyring()
print("backend:", type(backend).__module__, type(backend).__name__)
assert getattr(backend, "preferred_collection", None) == os.environ["KEYRING_PROPERTY_PREFERRED_COLLECTION"]
keyring.set_password("functualize-vault", "vault-key", os.environ["KEY"])
print("stored functualize-vault/vault-key in the throwaway collection")
PY

# --- a project with one stored direct entry ------------------------------
PROJ="$WORK/project"
mkdir -p "$PROJ/.functualize" "$PROJ/jobs"
cat > "$PROJ/pyproject.toml" <<'TOML'
[tool.functualize]
jobs_directories = ["jobs"]
TOML
cat > "$PROJ/jobs/live.py" <<'PY'
from pydantic import BaseModel, Field

from functualize.job.decorators import job
from functualize.types import Secret


class DeployConfig(BaseModel):
    api_token: Secret[str] = Field(description="Required credential")


@job
def deploy(config: DeployConfig) -> None:
    value = config.api_token.get_secret_value()
    print("token ok" if value == "live-check-token" else "token MISMATCH")
PY
FUNC="$(pwd)/.venv/bin/func"
( cd "$PROJ" && printf 'live-check-token' | FUNCTUALIZE_VAULT_KEY="$KEY" "$FUNC" builtin vault put deploy.api_token --stdin )

run_piped() {  # `func deploy` with stdout piped: exit code, elapsed, prompt objects
  local start end rc prompts_before prompts_after
  prompts_before="$(PROMPT_OBJECTS)"
  start=$EPOCHREALTIME
  set +e
  # pipefail is on, so the subshell's status is func's, not cat's.
  ( cd "$PROJ" && "$@" "$FUNC" deploy | cat )
  rc=$?
  set -e
  end=$EPOCHREALTIME
  prompts_after="$(PROMPT_OBJECTS)"
  awk -v rc="$rc" -v s="$start" -v e="$end" -v pb="$prompts_before" -v pa="$prompts_after" \
    'BEGIN { printf "exit=%s elapsed=%.1fs prompt-objects before=%s after=%s\n", rc, e - s, pb, pa }'
}

# --- scenario 1 ----------------------------------------------------------
say "1. unlocked + piped: expect 'token ok', exit 0, no dialog"
guard state   # must say False
run_piped env
ask "Did any unlock dialog appear? (expected: n)"

# --- scenario 2 ----------------------------------------------------------
say "2. locked + piped: expect a refusal in under 2 s, exit 3, NO dialog, no prompt object"
guard lock
guard state   # must say True
run_piped env FUNCTUALIZE_VAULT_KEYRING_TIMEOUT=30s
ask "Did any unlock dialog appear? (expected: n)"

# --- scenario 3 ----------------------------------------------------------
say "3. locked, then 'vault unlock' in this terminal: ANSWER the dialog (type the throwaway password)"
guard state   # must say True
( cd "$PROJ" && "$FUNC" builtin vault unlock ) || echo "vault unlock exit=$?"
guard state   # must say False
run_piped env
ask "Did exactly one dialog appear, during 'vault unlock' only? (expected: y)"

# --- scenario 4 ----------------------------------------------------------
say "4. locked, 'vault unlock', and press CANCEL in the dialog: expect exit 3; then unlock again and ANSWER"
guard lock
set +e
( cd "$PROJ" && "$FUNC" builtin vault unlock ); echo "vault unlock (cancelled) exit=$?"
set -e
guard state   # must say True
( cd "$PROJ" && "$FUNC" builtin vault unlock ) || echo "vault unlock exit=$?"
guard state   # must say False
ask "Did the second dialog appear and unlock normally after the cancel? (expected: y)"

# --- scenario 5 ----------------------------------------------------------
say "5. two parallel piped jobs on a locked keyring: both refuse at once, ZERO dialogs"
guard lock
guard state   # must say True
( set +e; cd "$PROJ" && "$FUNC" deploy | cat; echo "job A exit=${PIPESTATUS[0]}" ) &
( set +e; cd "$PROJ" && "$FUNC" deploy | cat; echo "job B exit=${PIPESTATUS[0]}" ) &
wait
ask "How many unlock dialogs appeared? (expected: 0)"

# --- finish --------------------------------------------------------------
say "finish: unlock the throwaway ('vault unlock' will show ONE dialog: ANSWER it) so cleanup can delete it"
( cd "$PROJ" && "$FUNC" builtin vault unlock ) || echo "vault unlock exit=$?"
guard state   # must say False
say "done"
