# Vault Remote Redemption — tasks

All waves done and green. Gates are measured, single-line counting commands
per house format (`tests/spec/test_task_gates_still_hold.py`); each
recorded `after:` is the value the finished work produced. The live-tier
run (T12) was executed once, manually, against the public vault on
2026-09-24 (`FUNC_VAULT_LIVE=1 … test_live.py` — 1 passed in 3.05s:
share → preview → redeem → spent-gone).

### [x] T1 (A1) port crypto core (envelope + canonical) → app/vault_remote.py

The crypto half of `app/vault_remote.py` is vendored from the funccloud
reference (behavior-faithful; names kept: `seal_envelope`, `canonical`,
`encode_fragment_key`, …). The module owns exactly one client error class —
the transport/UX surface — while the crypto layer keeps its own single
indistinguishable class:

```bash
rg -c 'class .*Error' src/functualize/app/vault_remote.py
```
after: `1`

And the port added no dependency of its own — the module's imports are
stdlib, `cryptography`, and one lazy `functualize.__version__`:

```bash
rg -c '^import |^from ' src/functualize/app/vault_remote.py
```
after: `15`

### [x] T2 (A2) copy vectors verbatim; port the fail-closed suite; green

`tests/vault_remote/vectors.json` is byte-identical to the frozen file
(sha256 pinned by its own test). The suite is real pytest — 40 test
functions covering every fail-closed category of both reference suites
(tamper/expiry/label/name/kind/mode/version/wrong-key/wrong-recipient):

```bash
rg -c '7eed69b0' tests/vault_remote/test_vectors.py
```
after: `2`

```bash
rg -c 'def test_' tests/vault_remote/test_vectors.py
```
after: `40`

### [x] T3 (A3) port http client (UA, timeout, origin check, id-echo, errors)

One `VaultRedeemError` with a stable `reason`; UA obligation held (bare
`python-urllib` is 403'd by the edge — measured); fragment discipline in
the transport: only paths are sent.

```bash
rg -c 'user-agent' src/functualize/app/vault_remote.py
```
after: `1`

```bash
rg -c 'k1\.' src/functualize/app/vault_remote.py
```
after: `6`

### [x] T4 (A4) mock origin fixture speaking contracts v1

`tests/vault_remote/mock_vault.py`: in-process ThreadingHTTPServer, atomic
claim behind one lock, 410 semantics, error-body shape, request tape. Its
own conformance is tested because every later test trusts it:

```bash
rg -c 'threading.Lock' tests/vault_remote/mock_vault.py
```
after: `1`

```bash
rg -c 'funccloud-vault' tests/vault_remote/mock_vault.py
```
after: `1`

### [x] T5 (A5) client↔mock journeys: round-trip, burn, race, hygiene

18 test functions: preview-never-burns, spent→`gone`, expiry→`gone`,
8-way race on 3 redemptions → exactly 3 winners, wrong-key/tampered → one
`open_failed` class, malformed links, fragment-never-on-the-wire (tape
assertion), UA obligation, mock conformance (labels mirror, id conflict):

```bash
rg -c 'def test_' tests/vault_remote/test_client.py
```
after: `18`

```bash
rg -c 'exactly_n_winners' tests/vault_remote/test_client.py
```
after: `1`

```bash
rg -c 'labels_mismatch' tests/vault_remote/test_client.py
```
after: `1`

One origin per test, started and stopped by the suite's own fixture:

```bash
rg -c 'mock_origin' tests/vault_remote/conftest.py
```
after: `1`

### [x] T6 (B1) app seam: share()/redeem()/import_to_vault() + reflection

The CLI mounts stay off `_config` — the seam module is the only place the
store is reached:

```bash
rg -c 'from functualize\._config|from functualize\._engine' src/functualize/_cli/vault_cmd.py
```
after: `0`

The new report types joined the no-value-leaves reflection test
(`RedeemedBundle` is deliberately absent — it is the material, not a
report):

```bash
rg -c 'ShareReport' tests/app/test_vault_paths.py
```
after: `3`

### [x] T7 (B2) `func vault share` (explicit --set + local-vault items)

Origin chain lives in the seam — `--origin` beats the environment beats
the public vault:

```bash
rg -c 'FUNC_VAULT_ORIGIN' src/functualize/app/vault_remote.py
```
after: `2`

### [x] T8 (B3) `func vault redeem` (+ --dotenv 0600, export lines; `--into-vault`/`--scope` superseded by T15/T17, spec A13)

### [x] T9 (B4) `func vault show <link>` (meta-only, never burns)

### [x] T10 (B5) top-level `func vault` alias mount; `func builtin vault` intact (superseded: removed by T20, O4)

The alias is mounted by the builtin registrar itself, so every group any
caller builds — CLI, TUI, embedding apps — answers the same at top level,
and `BUILTIN_NAMES` stays exactly "what sits at top level after
registration". The alias is the same group object as the builtin mount, so
the two spellings cannot drift:

```bash
rg -c 'add_command\(vault_app, name="vault"\)' src/functualize/_cli/builtins/__init__.py
```
after: `0` — superseded: the alias was mounted here (recorded `1` on 2026-09-24)
and removed by T20 on the maintainer's decision O4 (2026-11-01).

### [x] T11 (B6) spent/expired/tampered CLI failure tests; hygiene grep

21 CLI test functions through a real click group against the mock origin —
journeys, failures, materializations, alias, and the fragment-hygiene
assertion over output and captured log records:

```bash
rg -c 'def test_' tests/vault_remote/test_cli.py
```
after: `21`

```bash
rg -c 'k1\.' tests/vault_remote/test_cli.py
```
after: `3`

### [x] T12 (C1) live tier behind FUNC_VAULT_LIVE; one manual live run recorded

```bash
rg -c 'FUNC_VAULT_LIVE' tests/vault_remote/test_live.py
```
after: `3`

### [x] T13 (C2) docs: vault_cmd docstrings + docs page; STATUS entry

```bash
rg -c 'vault share' docs/cli/vault-share.md
```
after: `3`

Merge blocker: T2 vectors PASS (held — the suite runs in CI).
Cross-repo witness: funccloud eval (chain item 3, pins this submodule).

### [x] T19 (D6) the `base` environment is the shared slot (SD/12779576), at the identity

Measured 2026-10-31: `FUNCTUALIZE_ENV=base func builtin vault put --group deploy
--field token --stdin` stored `["group","deploy","token","base"]`, a fourth
environment no other run can see; SD/12779576 says `base` addresses shared
entries, and `vault sync` declarations already map it to shared
(`_config/vault_declarations.py:52`). Fixed once, in `VaultIdentity`, so put,
remove, inspect, run-time reads and declarations cannot disagree:

```bash
rg -c 'SHARED_SLOT' src/functualize/_primitives/vault_identity.py
```
after: `3`

### [x] T20 (D7) remove the top-level `func vault` alias (O4; spec A8)

Hit set: the branch's own alias hunks (plan.md → *Files to change*). Source
reverts to master's shape; the listed tests return to master's version; the
fixture job `vault` in `test_secret_surface_parity.py` gets its name back.

```bash
rg -c '"vault"' src/functualize/_cli/builtins/__init__.py
```
after: `1`

```bash
rg -c 'name="vault"' src/functualize/_cli/builtins/__init__.py
```
after: `0`

### [x] T21 (D8) local-vault seam: private `_read_value`, `vault_supersede_synced`, `vault_require_key`, `SecretsVault.supersede`

Every store touch the handoff needs goes through `app/vault.py`. `supersede`
changes origin, annotation, provider and `synced_at` in one transaction:

```bash
rg -c '^def (_read_value|vault_supersede_synced|vault_require_key)' src/functualize/app/vault.py
```
after: `3`

```bash
rg -c 'def supersede' src/functualize/_config/vault.py
```
after: `1`

**Transitional (disclosed 2026-11-01):** built and tested directly
(`tests/app/test_vault_seam.py` — `TestSupersedeSynced`, `TestRequireKey`,
`TestReadValue`; `tests/config/test_vault_store.py` — `TestSupersede`), but
**no production caller yet**: `app/vault_handoff.py` (T14) is the first. The
reachability check for these three functions is carried by T14.

### [ ] T14 (D1) `app/vault_handoff.py`: selector grammar · shareable entries · select (exact/subtree/all) · env label · pre-burn checks · plan/apply · export names

```bash
rg -c '^def (parse_selector|shareable_entries|select_for_share|share|check_before_redeem|plan_import|apply_import|export_name)' src/functualize/app/vault_handoff.py
```
after: `8`

```bash
rg -c 'from functualize\._config\.vault import|_project_id' src/functualize/app/vault_handoff.py
```
after: `0`

Reachability for T21 (carried here): `share` → `select_for_share` →
`app.vault._read_value`; redeem → `check_before_redeem` → `vault_require_key`;
`apply_import` → `vault_supersede_synced`. Each verified by breaking the call
after a commit and watching a handoff test fail.

### [ ] T16 (D3) trim `app/vault_remote.py` to crypto + wire; no key or store code left

```bash
rg -c 'resolve_vault_key|_project_id|SecretsVault|def import_to_vault|def load_vault_items' src/functualize/app/vault_remote.py
```
after: `0`

### [ ] T17 (D4) CLI: `share` via `--entry`/`--all`/picker (no `--group`/`--job`/`--field`/`--set`); `redeem` modes (TTY multi-select, `-y`, `--only`, `--replace`, `--print-only`, `--dotenv`), pre-burn order

```bash
rg -c '"--set"|"--from-vault"|"--into-vault"|"--scope"' src/functualize/_cli/vault_cmd.py
```
after: `0`

```bash
rg -c '"--entry"|"--all"' src/functualize/_cli/vault_cmd.py
```
after: `2`

```bash
rg -c 'check_before_redeem' src/functualize/_cli/vault_cmd.py
```
after: `1`

### [ ] T18 (D5) mock-origin tests for every row status and every pre-burn refusal; docs; STATUS

Every pre-burn refusal asserts the mock's tape holds no `POST …/redeem`:

```bash
rg -c 'def test_' tests/vault_remote/test_handoff.py
```
after: `24`

```bash
rg -c 'func vault ' docs/cli/vault-share.md
```
after: `0`

## Task Dependency Graph

```json
{"waves": [
  {"id": 0, "tasks": ["T1", "T2", "T3", "T4", "T5"]},
  {"id": 1, "tasks": ["T6", "T7", "T8", "T9", "T10", "T11"]},
  {"id": 2, "tasks": ["T12", "T13"]},
  {"id": 3, "tasks": ["T19", "T20", "T21"]},
  {"id": 4, "tasks": ["T14"]},
  {"id": 5, "tasks": ["T16", "T17"]},
  {"id": 6, "tasks": ["T18"]}
]}
```
