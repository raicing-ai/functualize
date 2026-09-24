# Vault Remote Redemption — tasks

Wave A (T1–T5) is done and green. Gates below are measured, single-line
counting commands per house format (`tests/spec/test_task_gates_still_hold.py`);
the recorded `after:` is the value the finished work produced.

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

### [ ] T6 (B1) app seam: share()/redeem()/import_to_vault(); extend the
          no-value-leaves reflection test to the new report types

The CLI mounts stay off `_config` — the seam module is the only place the
store is reached, which this pre-records for B1 as its layering gate:

```bash
rg -c 'from functualize\._config|from functualize\._engine' src/functualize/_cli/vault_cmd.py
```
after: `0`

### [ ] T7 (B2) `func vault share` (explicit --set + local-vault items)

### [ ] T8 (B3) `func vault redeem` (+ --into-vault, --dotenv 0600, export lines)

### [ ] T9 (B4) optional `func vault show <link>` (meta-only, never burns)

### [ ] T10 (B5) top-level `func vault` alias mount; `func builtin vault` intact

### [ ] T11 (B6) spent/expired/tampered CLI failure tests; hygiene grep (A9)

### [ ] T12 (C1) live tier behind FUNC_VAULT_LIVE; one manual live run recorded

### [ ] T13 (C2) docs: vault_cmd docstrings + docs/ page stub; STATUS entry

Merge blocker: T2 vectors PASS. Cross-repo witness: funccloud eval.
