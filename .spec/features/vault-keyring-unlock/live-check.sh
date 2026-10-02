#!/usr/bin/env bash
# Live check for vault-keyring-unlock (spec A11; plan risks K-1, K-2).
#
# Run by the maintainer, at the keyboard, on a Linux desktop with a Secret
# Service (gnome-keyring), from the repository root of this branch:
#
#     bash .spec/features/vault-keyring-unlock/live-check.sh 2>&1 | tee live-check.out
#
# then paste live-check.out into live-check.md next to this file.
#
# SAFETY — what this touches and what it never touches:
#   * It creates ONE throwaway Secret Service collection, stores a throwaway
#     test key in it, locks/unlocks ONLY that collection, and deletes it at the
#     end. functualize is pointed at it with KEYRING_PROPERTY_PREFERRED_COLLECTION,
#     which `keyring` applies to its Secret Service backend.
#   * It never locks, unlocks or writes the default ("Login") collection. It
#     only READS that collection's `Locked` property, before and after, and
#     prints whether it changed. It aborts if the throwaway collection would be
#     the default one.
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

command -v busctl >/dev/null || { echo "busctl is required"; exit 2; }
command -v uv >/dev/null || { echo "uv is required"; exit 2; }
uv sync --frozen --all-extras --all-packages >/dev/null

say "host"
uname -a
date --iso-8601=seconds
git rev-parse --short HEAD

say "Login collection Locked property, BEFORE (read-only)"
BEFORE="$(LOGIN_LOCKED)"
echo "$BEFORE"

WORK="$(mktemp -d -t functualize-live-check.XXXXXX)"
export XDG_DATA_HOME="$WORK/data" XDG_CACHE_HOME="$WORK/cache"
unset FUNCTUALIZE_VAULT_KEY FUNCTUALIZE_VAULT_KEYRING_TIMEOUT || true

# --- the throwaway collection -------------------------------------------
say "create the throwaway collection (gnome-keyring asks for a password for it)"
COLL="$(uv run python - <<'PY'
import secretstorage
bus = secretstorage.dbus_init()
default = secretstorage.get_default_collection(bus).collection_path
coll = secretstorage.create_collection(bus, "functualize-live-check")
if coll.collection_path == default:
    raise SystemExit("ABORT: the throwaway collection is the default collection")
print(coll.collection_path)
PY
)"
echo "throwaway collection: $COLL"
export KEYRING_PROPERTY_PREFERRED_COLLECTION="$COLL"

lock_throwaway() {
  uv run python - "$COLL" <<'PY'
import sys, secretstorage
bus = secretstorage.dbus_init()
default = secretstorage.get_default_collection(bus).collection_path
path = sys.argv[1]
if path == default:
    raise SystemExit("ABORT: refusing to lock the default collection")
secretstorage.Collection(bus, path).lock()
print("locked", path)
PY
}

cleanup() {
  say "cleanup: delete the throwaway collection and the temp project"
  uv run python - "$COLL" <<'PY' || echo "delete failed; remove 'functualize-live-check' in Seahorse"
import sys, secretstorage
bus = secretstorage.dbus_init()
default = secretstorage.get_default_collection(bus).collection_path
path = sys.argv[1]
if path != default:
    secretstorage.Collection(bus, path).delete()
    print("deleted", path)
PY
  rm -rf "$WORK"
  say "Login collection Locked property, AFTER (read-only)"
  AFTER="$(LOGIN_LOCKED)"
  echo "$AFTER"
  if [ "$BEFORE" = "$AFTER" ]; then echo "Login Locked: UNCHANGED"; else echo "Login Locked: CHANGED"; fi
}
trap cleanup EXIT

say "store a throwaway vault key in the throwaway collection only"
KEY="$(uv run func builtin vault keygen)"
KEY="$KEY" uv run python - <<'PY'
import os, keyring
backend = keyring.get_keyring()
print("backend:", type(backend).__module__, type(backend).__name__)
print("preferred_collection:", getattr(backend, "preferred_collection", None))
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

run_piped() {  # run `func deploy` with stdout piped, print exit code and elapsed
  local start end rc
  start=$EPOCHREALTIME
  set +e
  # pipefail is on, so the subshell's status is func's, not cat's.
  ( cd "$PROJ" && "$@" "$FUNC" deploy | cat )
  rc=$?
  set -e
  end=$EPOCHREALTIME
  awk -v rc="$rc" -v s="$start" -v e="$end" 'BEGIN { printf "exit=%s elapsed=%.1fs\n", rc, e - s }'
}

# --- scenario 1 ----------------------------------------------------------
say "1. unlocked + piped: expect 'token ok', exit 0, no dialog"
run_piped env
ask "Did any unlock dialog appear? (y/n)"

# --- scenario 2 ----------------------------------------------------------
say "2. locked + dialog answered: lock, run piped; ANSWER the dialog within 30 s"
lock_throwaway
run_piped env
ask "Did the dialog appear, and did you answer it? (describe)"

# --- scenario 3 ----------------------------------------------------------
say "3. locked + unanswered at 10s: lock, run piped; DO NOT answer the dialog"
lock_throwaway
run_piped env FUNCTUALIZE_VAULT_KEYRING_TIMEOUT=10s
ask "K-1: after the refusal, is the unlock dialog STILL on screen? (y/n; then dismiss it)"

# --- scenario 4 ----------------------------------------------------------
say "4. two parallel jobs against a locked keyring (K-2), 20s wait each"
lock_throwaway
( cd "$PROJ" && FUNCTUALIZE_VAULT_KEYRING_TIMEOUT=20s "$FUNC" deploy | cat; echo "job A exit=${PIPESTATUS[0]}" ) &
( cd "$PROJ" && FUNCTUALIZE_VAULT_KEYRING_TIMEOUT=20s "$FUNC" deploy | cat; echo "job B exit=${PIPESTATUS[0]}" ) &
ask "K-2: how many unlock dialogs appeared? Answer ONE of them now, then press Enter."
wait
say "done"
