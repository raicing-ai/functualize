# Vault Sharing — `func builtin vault share` / `redeem` / `show`

Hand a working environment to a teammate, accountlessly. The sender shares
entries of their project's vault as one link; the receiver redeems it into
the same project's vault on their machine, and their next run uses it.

```console
# sender, in the project
$ FUNCTUALIZE_ENV=prod func builtin vault share --entry group=deploy --expires 1h
Sharing 3 entries:
  prod: --group deploy --field token
  prod: --group deploy --job app --field api_key
  prod: --group deploy.infra --field region_key
https://funccloud-vault.raicing-ai.workers.dev/s/<id>#k1.<key>
Anyone with this complete link can redeem it. …

# receiver, in their clone of the same project
$ FUNCTUALIZE_ENV=prod func builtin vault redeem <link>
Redeemed 3 item(s) · redemption 1 of 1 · expires …
Store into this project's vault:
  [x]  1  group deploy
  [x]  2    prod: --group deploy --field token
  …
Toggle (e.g. 1,3,5-7) · a = all · n = none · Enter = done · q = cancel:
  stored     prod: --group deploy --field token
  …
```

The values are encrypted locally under a fresh key before anything leaves the
machine; the vault server stores only the sealed envelope. The link's `#k1.…`
fragment **is** that key, and the server never sees it — which is why the
complete link must travel over a channel you trust as much as the values
inside it.

## Commands

| Command | What it does |
| --- | --- |
| `func builtin vault share` | Seal entries of this project's vault into one redeemable link |
| `func builtin vault redeem <link>` | Check everything it can, consume one redemption, store into this project's vault |
| `func builtin vault show <link>` | Preview labels, redemptions and expiry — **never** redeems |

There is no top-level `func vault`: like every vault command these live
under `func builtin vault`, and a project's own job or group named `vault`
keeps its name.

## Environments

A share belongs to one environment: the sender's **active environment**
(`FUNCTUALIZE_ENV`, as for every vault command — there is no vault
environment flag). Only entries stored for that environment are offered, and
the link carries the environment as a label (`env:prod`).

The receiver must redeem into the same environment. A `prod` share redeemed
with `FUNCTUALIZE_ENV=staging` is refused **before** the link is used, with
the command to run instead. `FUNCTUALIZE_ENV=base` addresses shared entries on
both sides. Sharing a shared entry from a named environment is not supported
yet; it is listed with that reason.

## `share`

Choose entries one of three ways:

| You give | Shares |
| --- | --- |
| `--entry SELECTOR` (repeatable) | what the selectors name — see below |
| `--all` | every shareable entry |
| nothing, at a terminal | a checklist of every shareable entry, **nothing ticked** |

With no terminal and neither `--entry` nor `--all`, `share` refuses.

### Selectors

Comma-separated `key=value`, with keys `group`, `job` and `field`, no spaces.
`job` is one job's name, never a dotted path.

| Selector | Shares |
| --- | --- |
| `group=deploy,field=token` | exactly the group option `token` of `deploy` |
| `group=deploy,job=app,field=api_key` | exactly the field `api_key` of job `app` in `deploy` |
| `job=myjob,field=api_key` | exactly that field of `myjob`, a job in no group |
| `group=deploy` | **everything under `deploy`**: its options, its nested groups' options, and every field of every job in it or below it |
| `group=deploy,job=app` | every field of that job |
| `job=myjob` | every field of that job |

Every selector must match at least one shareable entry, or nothing is shared
— a typo never silently sends less. An exact selector naming an entry that
cannot be shared is refused with the reason; a wide selector or `--all` skips
such entries and lists them. Entries written by `vault sync` are shareable
and marked `(synced from …)`.

### The checklist

Numbers and ranges toggle rows (`1,3,5-7`); a group or job row toggles
everything under it; `a` ticks all, `n` none; Enter finishes; `q` cancels.
Rows that cannot be shared are shown with `[-]` and the reason.

### Other options

- `--labels a,b` — labels mirrored into the envelope's authenticated
  metadata. Labels starting `env:` are reserved.
- `--expires 1h` — validity window (`90m`, `2d`…; 1..168 whole hours).
- `--redemptions N` — how many distinct claims the link allows (1..10).
  Every redemption is atomic: exactly N winners under any concurrency.
- `--origin URL` — see *Origin* below.
- `--json` — the link, labels and the entries shared; never a value.

## `redeem`

### Checked before the link is used

Redeeming consumes one of the link's redemptions, and what is inside can only
be read afterwards. So `redeem` first checks everything it can without
spending it, and refuses — leaving the link usable — when:

1. there is no project here to store into (the directory has no jobs);
2. there is no terminal to confirm on and neither `-y`, `--only` nor
   `--print-only` was given;
3. an exact `--only` selector names nothing in this project;
4. the share is spent, expired or unknown (read from its preview, which
   never redeems);
5. the share was made for another environment, or not by `vault share`;
6. no vault key is available (it is read silently and never prompts; run
   `func builtin vault unlock` first if the keyring is locked).

Checks 1, 2, 5 and 6 apply only when storing into the vault.

What cannot be checked first: whether the link's own key is right (a
mistyped but well-formed link spends a redemption and then fails), and which
entries the bundle holds. Anything found only after the redemption is used
says so.

### What it stores

Each redeemed entry is checked against this project the way `vault put`
checks, and shown as one row:

| Row | Shown as | Default |
| --- | --- | --- |
| new | `prod: --group deploy --field token` | ticked |
| already stored | `… — exists, would replace` | unticked |
| written by `vault sync` | `… — synced from aws-sm://…` | unticked |
| not in this project | `… — no job 'app' in group 'deploy.infra' here` | cannot be stored |
| unreadable | `item 3 — unreadable item name` | cannot be stored |

Replacing a synced entry makes it a direct entry: from then on `vault sync`
reports that entry until it is removed, because sync never overwrites a value
someone stored directly.

| You give | Stores |
| --- | --- |
| nothing, at a terminal | the checklist; Enter takes what is ticked |
| `-y` / `--yes` | every new entry, without asking |
| `--only SELECTOR` (repeatable) | new entries under the selectors, without asking |
| `--replace` | with `-y` / `--only`: also existing and synced entries; with the checklist: ticks them too |

Ticking nothing, or cancelling, stores nothing — and the link's redemption
has been used.

### Without the vault

- `--print-only` — print `export NAME=value` lines and store nothing. Works
  outside a project.
- `--dotenv PATH` — write the same lines, without `export`, to a `0600`
  file, and store nothing in the vault. The file holds the values **in plain
  text**; keep it out of version control.

The names are the environment variables a run already reads for each entry:
`JOB_FIELD` for a job config field (`DEPLOY_APP_API_KEY`) and `SCOPE__FIELD`
for a group option (`DEPLOY__TOKEN`, `DEPLOY_INFRA__REGION_KEY`).

`--json` reports what was stored, replaced and skipped (with reasons) and
never carries a value.

## Failures

A spent or expired share (`gone`), an unknown one (`not_found`), and a wrong
or tampered bundle (one indistinguishable class) are each one closed message.
No failure includes a value or key material. Usage mistakes exit `2`;
refusals exit `3`.

## Origin

Resolution order: `--origin` → `$FUNC_VAULT_ORIGIN` → the public FuncCloud
vault (`https://funccloud-vault.raicing-ai.workers.dev`). Any host
implementing the same contract is a valid origin, which is what self-hosting
and tests use. Redeeming a link whose origin differs from the configured one
prints a note (the share id does travel there; the values still decrypt
locally).
