# Vault Sharing — `func vault share` / `redeem` / `show`

Hand a working environment to someone else, accountlessly. Two commands,
one link:

```console
# sender — anywhere functualize is installed
$ func vault share --set SLACK_BOT_TOKEN=xoxb-… --labels demo --expires 1h
https://funccloud-vault.raicing-ai.workers.dev/s/<id>#k1.<key>
Anyone with this complete link can redeem it. …

# receiver — any machine, no account, no config
$ func vault redeem <link>
Redeemed 1 item(s) (demo) · redemption 1 of 1 · expires 2026-09-24T…
export SLACK_BOT_TOKEN=xoxb-…
```

The values are encrypted locally under a fresh key before anything leaves
the machine; the vault server stores only the sealed envelope. The link's
`#k1.…` fragment **is** that key — the server never sees it, which is why
the complete link must travel over a channel you trust as much as the
values inside it.

## Commands

| Command | What it does |
| --- | --- |
| `func vault share` | Seal `--set NAME=VALUE` items and/or `--from-vault KEY` entries into one redeemable link |
| `func vault redeem <link>` | Consume one redemption, decrypt locally, materialize |
| `func vault show <link>` | Preview labels/redemptions/expiry — **never** redeems |

`func builtin vault …` keeps working and is the same group; `func vault …`
is the top-level alias.

### `share` options

- `--set NAME=VALUE` — repeatable; explicit items.
- `--from-vault KEY` — repeatable; entries read and decrypted from this
  project's vault at seal time.
- `--labels a,b` — ≤8 labels of ≤64 chars; mirrored into the envelope's
  authenticated metadata.
- `--expires 1h` — validity window (`90m`, `2d`…; 1..168 whole hours).
- `--redemptions N` — how many distinct claims the link allows (1..10).
  Every redemption is atomic: exactly N winners under any concurrency.
- `--origin URL` — see below.

### `redeem` materializations (mutually exclusive)

- *(default, or `--export-lines`)* — `export NAME=VALUE` lines on your
  terminal. Nothing is persisted anywhere.
- `--into-vault [--scope SCOPE]` — store into the local secrets vault,
  namespaced `SCOPE.NAME` when a scope is given. Refuses to overwrite an
  existing entry.
- `--dotenv PATH` — write a `0600` env-style file.

Failures are one closed message — a spent or expired share (`gone`), an
unknown one (`not_found`), a wrong or tampered bundle (one
indistinguishable class) — and never include values or key material.

## Origin

Resolution order: `--origin` → `$FUNC_VAULT_ORIGIN` → the public FuncCloud
vault (`https://funccloud-vault.raicing-ai.workers.dev`). Any host
implementing the same contract is a valid origin, which is what
self-hosting and tests use. Redeeming a link whose origin differs from the
configured one prints a note (the share id does travel there; the values
still decrypt locally).
