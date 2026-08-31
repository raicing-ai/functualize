#!/usr/bin/env bash
# Drive the whole lab end to end, from a clean slate, printing the exit code of
# every step. Nothing here is a test assertion — the point is a transcript a
# reader can run and compare against.
#
# The assertions live in tests/test_composition_lab_e2e.py, which runs these
# same sequences on both surfaces and checks the results.
#
#   ./demo.sh              # the app entry point (main.py)
#   ./demo.sh func         # the bare `func` CLI
#   ./demo.sh func /path/to/func
set -u

HERE="$(cd "$(dirname "$0")" && pwd)"
SURFACE="${1:-app}"
cd "$HERE" || exit 1

if [ "$SURFACE" = "func" ]; then
  RUN=("${2:-func}")
else
  RUN=("${2:-python}" main.py)
fi

step() {                      # step <label> <args...>
  local label="$1"; shift
  printf '\n=== %s\n$ %s %s\n' "$label" "${RUN[*]}" "$*"
  "${RUN[@]}" "$@"
  printf '[exit %s]\n' "$?"
}

printf '### 0. clean slate — freshness claims below mean nothing without it\n'
rm -rf build dist .functualize

step "1. cold: parse -> report -> publish, ordered by declarations alone" lab publish
step "2. warm: every stage fresh, nothing rebuilt"                        lab publish
step "3. why does publish not run?"                                       builtin why lab.publish
step "4. bundle — Fingerprint(generates=['dist/*.tar.gz']), a glob"        lab bundle
step "5. bundle again: the glob matches, so it is fresh"                  lab bundle
step "6. --force overrides freshness; --strict is a mid-path group flag"  --force lab --strict bundle

printf '\n=== 7. a satisfied status guard must not mask changed sources\n'
echo '# touched' >> build/report.md
step "7a. why now reports the AND"                                        builtin why lab.publish
step "7b. and it really re-runs"                                          lab publish

printf '\n=== 8. refusal is exit 3, and is neither a crash nor a skip\n'
step "8a. a failing Precondition refuses"                                 lab gated
step "8b. declared sources resolving to nothing also refuse"              lab verify
step "8c. declaring NO sources is unaffected"                             lab counter

step "9. sign-off: a second group, reading the lab group's options"       check signoff

printf '\n=== 10. the gated walk: pause, deposit, resume\n'
step "10a. blocks at the gate"                                            lab release

printf '\n### done. Re-run step 10 with --scope-id <id> after depositing input:\n'
printf '###   %s builtin workflow resume <id> approval-gate --input '"'"'{"note":"ok"}'"'"'\n' "${RUN[*]}"
printf '###   %s lab release --scope-id <id>\n' "${RUN[*]}"
