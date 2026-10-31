# Vault Remote Redemption — `func builtin vault share` / `redeem`

Status: waves A–C implemented (2026-09-24); **revised 2026-10-31** after the
rebase onto scoped vault v3/v4 (#88, #117) and keyring unlock (#78). Waves 3–4
(T14–T21) implement the revision. Maintainer decisions O1–O4 taken
2026-11-01 (see *Decisions*). Chain item 2 of the FuncCloud
vault-redeem-journey (funccloud repo, private).

**Everything cross-repo is frozen**: the wire + crypto contracts live in the
funccloud repo (`.spec/features/vault-redeem-journey/contracts.md`, frozen v1,
2026-09-25). This feature consumes them and never redefines them. Every change
in this revision is local materialisation: what a sender puts in an item and a
label, and what a receiver does with a redeemed bundle.

Sources (Confluence, space SD): Shape Intent — Vault Remote Redemption
(SD/7602177); D3 "redeem saves to the vault by default" (SD/9273345); Scoped
Secrets and Resolution v3/v4 (SD/12779576); keyring unlock decision
(SD/12222468); Local Vault CLI and Lifecycle (SD/2031617, prior art for A8).

## Objective

An ordinary functualize user hands a working environment to a teammate,
accountlessly, and the teammate's next run just works:

```
alice$ FUNCTUALIZE_ENV=prod func builtin vault share --group deploy --field token --expires 1h
       → https://<origin>/s/<id>#k1.<key>   (anyone with this complete link can redeem it)
bob$   cd my-clone && FUNCTUALIZE_ENV=prod func builtin vault redeem <link>
       → [x] prod: --group deploy --field token     (multi-select; all storable ticked)
       → stored 1 entry in this project's vault
bob$   FUNCTUALIZE_ENV=prod func deploy ping         # resolves the redeemed token
```

The receiver needs no FuncCloud account. The default origin is the public
FuncCloud vault, configurable for any conforming host (self-hosters, tests).

## Assertions

A1 **Vendored client reproduces the locked vectors.** The funccloud Python
reference is ported into `app/vault_remote.py`; the vector file is copied
verbatim (sha256-pinned) and every vector reproduces byte-identically. The
shape intent counted 37 fail-closed cases; the ported suite measures 40 test
functions covering every category (tamper/expiry/label/name/kind/mode/
version/wrong-key/wrong-recipient). *Done (T1–T2).* Merge blocker.

A2 **No new dependencies.** `cryptography` (already core) + stdlib `urllib`.
*Done.*

A3 **Layering.** Behaviour lives in the delivery-neutral seam
(`app/vault_remote.py`), `_cli/vault_cmd.py` stays thin and reaches no
`_config`/`_engine` internals. Local-vault reads and writes go through the
`app/vault.py` seam (`resolve_vault_identity`, `vault_put`, …), never a second
path to the store. Import-linter contracts unchanged. *Done for waves A–C;
held by T14–T15.*

A4 **`func builtin vault share`** shares entries of this project's vault from
the sender's **active environment** (`FUNCTUALIZE_ENV`; there is no vault
environment flag, SD/12779576 model 6). Entries are chosen one of three ways,
and only these (maintainer, 2026-11-01): there are no `--group` / `--job` /
`--field` flags on `share`.

- **`--entry SEL`**, repeatable — the selector grammar below;
- **`--all`** — every shareable entry (refused together with `--entry`);
- **the picker** — a TTY and neither of the above. It lists every shareable
  entry grouped by group and job, **nothing ticked** (sharing is the direction
  where a secret leaves the machine). Numbers and ranges toggle (`1,3,5-7`); a
  group or job header row toggles everything under it; `a` ticks all, `n`
  none; Enter finishes. Rows that are not shareable are shown disabled with the
  reason.

No TTY and neither `--entry` nor `--all` → usage error naming both.

**Selector grammar** (`--entry`, and redeem's `--only`): comma-separated
`key=value`, keys `group`, `job`, `field`, each at most once, no spaces —
`group=deploy.infra,job=app,field=api_token`. Values are names, not paths:
a `job` value containing a dot refuses with the split spelling (`dotted_job`,
as `vault put`). Unknown or repeated keys, an empty value, or no `group`/`job`
are usage errors.

| Selector | Selects |
|---|---|
| `group=G,field=F` | exactly group `G`'s option `F` |
| `group=G,job=J,field=F` | exactly field `F` of job `J` in group `G` |
| `job=J,field=F` | exactly field `F` of job `J`, which is in no group |
| `group=G` | **everything under `G`**: `G`'s options, every nested group's options, and every field of every job in `G` or a nested group |
| `group=G,job=J` | every field of job `J` in group `G` |
| `job=J` | every field of job `J`, which is in no group |

Example — group `deploy` has option `token`, job `app` in `deploy` has
`api_key`, nested group `deploy.infra` has option `region_key`:
`group=deploy` → `token`, `api_key`, `region_key`; `group=deploy,job=app` →
`api_key`.

**Shareable** means: stored for the active environment (a four-part identity
whose environment is the active one) **and** still resolving against this
project (`resolve_vault_identity`). Not shareable, with the reason shown:
shared-only entries (A12) and orphans whose group or job no longer exists.
Synced entries are shareable and marked `(synced from …)`.

Rules: every selector must match at least one shareable entry, else the share
is refused before anything is sent (a typo never silently shares less);
overlapping selectors are de-duplicated; an *exact* selector naming a
non-shareable entry refuses with its reason, while a *wide* selector or
`--all` skips it and lists it. Before the link is created, non-interactive
runs print the final list and count; the picker is its own confirmation.

The item's wire `name` is the entry's canonical `VaultIdentity.encode()`
spelling (A10). The share carries the sender's environment as a label
`env:<name>` (A11). Client-generated 32-hex share id; `User-Agent:
functualize/<version>`; prints the link **with** the fragment and the one-line
possession warning; values never logged. **Only vault entries are shared**:
`--set NAME=VALUE` and `--from-vault` are removed (O1).

A5 **`func builtin vault redeem`** parses `<origin>/s/<id>#k1.…`, warns on origin
mismatch (threat T5.1), redeems, verifies the envelope's `share_id` echo, and
decrypts locally with one indistinguishable failure class. By default it
**stores into the local vault** after a confirmation (A13, D3). `--print-only`
persists nothing and prints a summary plus export lines; `--dotenv PATH`
writes a 0600 file. Both name each item by the environment variable a run
already resolves for it (O1): `JOB_FIELD` for a job config field
(`DEPLOY_INFRA_APP_API_TOKEN`) and `SCOPE__FIELD` for a group option
(`DEPLOY_INFRA__API_TOKEN`), from `_config/resolved_field.py`
(`env_name_for`, `group_env_name_for`). `--into-vault` and `--scope` are
removed.

A6 **Burn semantics.** A spent/expired share exits nonzero with a closed
message. `func builtin vault show <link>` reads meta and **never** redeems. *Done.*

A7 **CI-safety + live opt-in.** All tests run against an in-process mock
origin speaking contracts v1. The live tier runs only with `FUNC_VAULT_LIVE=1`
(and `FUNC_VAULT_ORIGIN` for a self-hoster) and is skipped otherwise. *Done
(T12; one manual live run 2026-09-24).*

A8 **No top-level alias (removed, O4).** The verbs live under
`func builtin vault`, like every other vault command, which is what SD/2031617
recorded ("keep vault administration under `func builtin vault`; top-level
names remain available to discovered jobs"). The alias waves B–C added (T10)
is reverted: `BUILTIN_NAMES` is `{builtin}` again, and a project's own job or
group named `vault` is reachable again (the dispatcher routes builtin names
first, `_cli/dispatch.py:200`). *T20.*

A9 **Fragment hygiene.** The fragment is parsed from argv, held in memory,
never logged by functualize's log/event surfaces (grep-enforced test). *Done.*

A10 **One identity spelling on the wire.** A vault-entry item's `name` is
`VaultIdentity.encode()` — `["job","deploy.infra.app","api_token","prod"]` —
the same JSON list that is already the store key and the AES-GCM associated
data. No second codec. A shared entry has no fourth part (it is never the
string `"base"`). There are no plain items (O1).

A11 **The environment is checked before the burn.** Redeeming consumes a
redemption, and items are only readable afterwards, so everything the
receiver can check locally happens **before the origin is asked to redeem**:

- **project**: no functualize project is found from the working directory →
  refuse (nothing to validate against), naming `cd` into the project,
  `--print-only` and `--dotenv`;
- **environment**: in store mode, `redeem` first reads meta (no burn, the same
  call `vault show` makes). If the share's `env:<name>` label differs from the
  receiver's active environment, refuse and name
  `FUNCTUALIZE_ENV=<name> func builtin vault redeem …`. Every share made by this
  version carries one; a share without it was not made by `vault share` and is
  refused before the burn;
- **confirmation mode**: no TTY and none of `-y`, `--only`, `--print-only` →
  refuse (A13);
- **key**: in store mode the receiver's vault key is looked up silently
  first — a purely local check, no endpoint involved (O3; no run ever prompts,
  SD/12222468). Not FOUND → refuse with the lookup's own message;
- **share state**: the same meta read answers `gone` / `not_found` /
  `expired` without a POST.

Every refusal above sends at most the non-burning meta read and leaves the
link usable.

**Not checkable before the burn under frozen v1** (disclosed, O3): whether the
link's own key is right, and which items the bundle holds. Meta returns
labels, counts and timestamps only; `ciphertext` needs the redemption token
that only `redeem` issues. A well-formed but wrong link therefore spends a
redemption and fails `open_failed`; a `no_match` or `malformed` row, or the
user aborting the prompt, is likewise found only after the burn. Closing the
first gap needs a v2 wire change in funccloud (for example a key-check value
in meta, verifiable only by the fragment holder) — a proposal for that repo,
not a change here: Proposal — FuncCloud Vault wire v2: a non-burning encrypted
manifest before redeem (SD/23822368, 2026-11-01).

A12 **Shared entries are not shareable yet (deferred).** The local seam can
only write into the receiver's active environment (`_active_identity`,
`app/vault.py:302`), so a shared entry cannot arrive as shared. Until a local
vault change gives import an explicit-slot write, `share` refuses an entry that
resolves only through the shared fallback: "deploy.token is a shared entry;
sharing shared entries is not supported yet". Recorded as a non-goal below.

A13 **Redeem stores real identities, after a confirmation.** Each item becomes
one row, validated against the receiver's project with the checks `vault put`
uses (`_revalidate` / `resolve_vault_identity`):

| Row status | Shown as | Selectable | Default |
|---|---|---|---|
| `storable` | `prod: --group deploy --field token` | yes | ticked |
| `exists` | `… — exists, would replace` | yes | **unticked** |
| `synced` | `… (synced from aws-sm://shared/deploy-token)` | yes | **unticked** |
| `no_match` | `… — no job 'app' in group 'deploy.infra' here` | no | — |
| `malformed` | `item 3 — unreadable name` | no | — |

- `synced` (O2): redeem **may** replace an entry `vault sync` wrote. The row
  says where it was synced from and starts unticked, like `exists`. Applying it
  rewrites the entry as a direct one in a single store transaction
  (`vault_supersede_synced`; annotation, provider and `synced_at` cleared).
  Consequence, by ADR-023 §3 ("`sync` must never overwrite a direct entry"):
  the next `vault sync` reports that identity as "direct entry already exists;
  remove it before syncing". The row's detail line says so.
- `malformed`: `VaultIdentity.decode()` raises on a bad name; after the burn
  that becomes a row, never a crash.
- Modes: **TTY** → multi-select, every `storable` row ticked; **`-y/--yes`** →
  every `storable` row, no prompt, `exists` and `synced` rows skipped and
  reported unless `--replace`; **`--only SEL`** (repeatable, the A4 selector grammar, matched against the
  planned rows)
  → that subset, no prompt; **`--print-only`** → nothing stored.
- Selecting nothing, or aborting the prompt, stores nothing; the command says
  so **and that the link is already spent**.
- `--replace` without `-y`/`--only` only changes the default tick of `exists`
  and `synced` rows.

A14 **Key handling follows the keyring-unlock decision.** Every local read
(share) and write (redeem) uses `resolve_vault_key` → `KeyLookup`
(FOUND / LOCKED / NO_KEYRING / NOT_STORED / UNVERIFIED) and
`describe_key_failure`. The reason codes are the lookup's own; the old
`key_unavailable` is gone. `vault_remote` no longer resolves a key itself:
it goes through `app/vault.py` (the private `_read_value`, and
`vault_require_key`).

A15 **`base` is the shared slot, at the identity (fix to master behaviour).**
Measured 2026-10-31: `FUNCTUALIZE_ENV=base func builtin vault put --group
deploy --field token --stdin` stored `["group","deploy","token","base"]`, a
fourth environment a `prod` run never consulted, while a `config.base.*`
declaration of the same identity was shared
(`_config/vault_declarations.py:52`). `VaultIdentity` now folds `base` to "no
environment", so put, remove, inspect, run-time reads and declarations share
one spelling. #117 is in no release (`git tag --contains 91947bb` is empty), so
no released store holds a four-part `"base"` key. *T19.*

## Decisions (maintainer, 2026-11-01)

- **O1** — `--set` is removed: not idiomatic, and not the intent (an
  environment is handed over as vault entries). Export names follow the
  existing `JOB_FIELD` / `SCOPE__FIELD` convention.
- **O2** — redeem can replace a synced entry; the row is marked
  `(synced from …)`.
- **O3** — every check that can precede the burn does. The receiver's key is
  local; link-key verification before the burn is a funccloud v2 question.
- **O4** — the top-level alias is removed.
- **B** — no public plaintext read: `app.vault._read_value` stays private.
- **Share selection** — `--entry` (key=value selector) and `--all` only, no
  `--group`/`--job`/`--field` on `share`; a field-less `group=` selector takes
  the whole subtree; the picker starts with nothing ticked.
- Earlier (2026-10-31): redeem stores real identities (Option B); confirmation
  is a multi-select defaulting to all storable rows; collisions start unticked;
  the sender's environment must equal the receiver's; no project → refuse
  before the burn; sharing shared entries is deferred.

## Non-goals

Account-bound sync, team wrapping, passphrase `k2.` mode, capability/policy
(later funccloud chain items). Sharing shared entries (A12). Writing into an
environment other than the receiver's active one. A vault-only environment
flag (SD/12779576 model 6). The `vault.remote_origin` config key (not wired;
see contracts). Raw `--set` values. A top-level `func vault`.

## Evidence on merge

Durable half to `STATUS.md` per house workflow; the funccloud-side journey
closes on their eval harness (chain item 3), which pins this submodule pointer.
