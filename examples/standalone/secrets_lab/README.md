# Secrets Lab

How a credential is declared, resolved, and — everywhere it is rendered —
withheld. Five steps, each one command.

```
secrets_lab/
├── config.base.toml     # non-secret config, per-job sections. No [secrets] block.
├── jobs/
│   ├── sync.py          # a secret with an empty default, next to a decoy
│   ├── report.py        # a REQUIRED secret with no default
│   └── publish.py       # a target chosen at run time; its group secret, read
└── pyproject.toml
```

Run everything from this directory.

## 1. Declare it

`jobs/sync.py` marks one field secret and leaves a decoy beside it:

```python
credential: Secret[str] = Field(default=Secret(""))
sort_key:   str         = Field(default="created_at")   # not a secret
```

`sort_key` matches every name-based "is this a secret?" heuristic ever written.
It is not one, and nothing masks it. Detection follows the model.

## 2. Find out what the job needs

```console
$ func builtin env sync
export SYNC_API_URL=https://api.example.com  # source: file
export SYNC_CREDENTIAL=''                    # source: default
export SYNC_LEGACY_TOKEN=''                  # source: default
export SYNC_SORT_KEY=created_at              # source: default
export SYNC_PAGE_SIZE=100                    # source: file
```

The credential is **empty**, and reads as empty. It is not rendered as `•••`,
because masking nothing would invent a credential that is not there.

## 3. Set it, and see the difference

```console
$ SYNC_CREDENTIAL=hunter2-real func builtin env sync
export SYNC_CREDENTIAL='•••'  # source: env
```

Masked, and distinguishable from step 2 — which is the whole point. Add
`--include-secrets` when you actually need the value.

## 4. Watch a required one report itself as missing

`report` declares `token` with no default at all.

```console
$ func builtin env report
export REPORT_OUTPUT_DIR=./out  # source: file
# REPORT_TOKEN=  # REQUIRED — not set
```

Commented out, named, and labelled. Redirect it into `.env` and fill in the
blank — the output is already the skeleton.

Every surface agrees. `func builtin info --job report` shows the same field the
same way, and so does the config table in `func`'s inline TUI (`Ctrl+R`).

## 5. Run it

```console
$ SYNC_CREDENTIAL=hunter2-real func sync
credential = •••
```

The job holds the real value — `config.credential.get_secret_value()` returns
it — but `str()`, `repr()`, logs and JSON serialization all refuse. The log line
above is safe to leave in.

A plain `model_dump()` is the one place the wrapper is kept rather than masked,
because that is how the framework hands a config from one job to another
(`rc.invoke("child", config=config)`). Masking there replaced the credential
with `•••` and the child authenticated with the mask.

```console
$ func report
```

With no `REPORT_TOKEN`, this asks for it if the surface can ask, and otherwise
fails naming the variable rather than dying on a 90-line traceback.

## 6. Supply it once, instead of every time

Everything above is about how a credential is *declared* and withheld. This is
where the value comes from.

`REPORT_TOKEN` in your shell works, and is the right answer in CI. On a
workstation it means exporting it in every new terminal, or keeping it in a
dotfile — which is the thing the mask in step 5 exists to avoid.

Store it once instead. On a workstation with an OS keyring, `func builtin vault
init` creates and stores a key for you and never prints it. Everything below
uses the **environment** route instead, because it needs nothing installed and
is what CI uses:

```console
$ export FUNCTUALIZE_VAULT_KEY=$(func builtin vault keygen)
$ func builtin vault init --key-source env
A vault key is already available from 'env'.
Nothing was written.

$ func builtin vault put --job report --field token
Value: ********
Stored --job report --field token (new).

$ func report
output_dir = ./out
token      = •••
```

Look at the last line. The job logs its token on purpose (step 5), and the value
that came out of the vault is masked exactly like every other route — the vault
changes where a secret comes from, not what it is.

Three things that are not obvious:

**`init` is run once per machine, not once per project.** One key opens every
project's vault; the vaults themselves stay separate, one encrypted file each.

**`init --key-source env` writes nothing.** It validates that the variable is
set and well-formed, which is worth a line in CI: you find out at "check
secrets" rather than four steps later. Creating a key is something only the
keychain route can do — only you can set an environment variable.

**With no keyring and no variable, `init` refuses and names both ways forward**
— `pip install 'functualize[keychain]'`, or `keygen` and export. It never falls
back to printing a key: `keygen` exists for that, and where the key then lives
is your decision.

**The vault outranks the environment.** Once job `report` field `token` is stored,
`REPORT_TOKEN` no longer overrides it. An explicit `--token` on the command
still does.

### What you can ask about a secret you cannot read

```console
$ func builtin vault inspect --job report --field token
Scope:      job
Target:     report
Field:      token
Eligible:   yes
Stored:     yes
Origin:     direct
Readable:   readable
Would win:  vault
```

`inspect` never decrypts the value — readability is answered from a separate
check row — so this works, and tells you the truth, on a machine whose key is
wrong.

Job `sync` field `sort_key` is the lab's decoy from step 1. The vault follows the model for
exactly the same reason nothing else here uses name heuristics:

```console
$ func builtin vault inspect --job sync --field sort_key
Scope:      job
Target:     sync
Field:      sort_key
Eligible:   no
Stored:     no
```

### Taking it back

```console
$ func builtin vault remove --job report --field token
Remove --job report --field token? [y/N]: y
Removed --job report --field token (direct).
Warning: no upstream copy; this value is gone
```

The warning is only printed for a value you typed in. One fetched by
`vault sync` comes back on the next sync; this one does not come back at all.

`remove` and `clear` need no key — which matters, because the situation you most
need them in is the one where the key is what you lost.

### From your own code

The same lifecycle is a public API, so an application that embeds functualize
does not shell out to `func`:

```python
from functualize.app.vault import VaultIdentity, vault_init, vault_inspect, vault_put

report_token = VaultIdentity("job", "report", "token")  # scope, target, field

vault_init(key_source="env")
vault_put(app, report_token, token)
app.refresh()          # the chain is built at boot; this picks up the change
vault_inspect(app, report_token)   # origin and readability, never the value
```

The identity carries the same three things as `--job report --field token`. A
group option is `VaultIdentity("group", "<group path>", "<option>")`, and it is
a different entry from a job field with the same names.

`tests/test_vault_lifecycle.py` is that code, and it asserts that this whole
example imports nothing private — if the published API were incomplete for its
own headline lifecycle, that test could not be written.

### When the job only learns its target while running

Every secret so far reaches its job because the job declared a field for it.
`jobs/publish.py` cannot work that way: its target arrives in a config field,
so the address is only known per run. It asks the injected `Vault` for that
address instead, and passes the value on as a `Secret`:

```python
token: Secret[str] = vault.read(config.target, "api_token")
```

`read` asks for the address it is given, then that address's nearest ancestors,
so one credential stored at `cloudflare.d1` answers for every target beneath it
— `cloudflare.d1.main`, `cloudflare.d1.canary`, and any target added later. The
target arrives in a config field, so one job serves all of them:

```console
$ func builtin vault put --group cloudflare.d1 --field api_token --stdin
Stored --group cloudflare.d1 --field api_token (dev, new; default).

$ func publish --target cloudflare.d1.canary
published to cloudflare.d1.canary with a 35-character credential

$ func publish --target cloudflare.eu.main
no credential provisioned for cloudflare.eu.main; nothing published
```

The target is `--target`, the credential's own value is never rendered, and
addressing a target nobody provisioned costs one log line rather than a failed
run.

Three failures of that read are not the same, and the job treats them differently:

| what the vault holds | what happens |
| --- | --- |
| nothing, at the address or above it | `VaultEntryMissingError` — caught, the target is skipped, the run succeeds |
| an entry the available key does not open | `VaultEntryUnreadableError` — deliberately not caught: a credential that exists and will not decrypt is a broken key, and skipping the target would hide it |
| an entry whose stored bytes do not authenticate | `VaultDecryptionError` — also not caught: the store is damaged or foreign, not keyed wrongly, and no alternate key repairs it |

`CloudflareD1Options` is what makes any of this storable: the vault only accepts
a field its group declares `Secret[str]`, so without that class the `vault put
--group cloudflare.d1` above is refused as an unknown group. Where the class may
live depends on the provider that scans the tree. A cached provider discovers a
declaration that sits alone in a job-free `jobs/deploy/_group.py`; the eager
direct sources this lab boots — `JobSources(..., lazy=False)` in
`tests/test_group_vault_read.py` — discover a group only in a module that also
holds a job injecting its options. `group_status` is that job here: it reaches
the same entry the config way, which `func group-status` reports. `publish`
injects nothing, because a job that declares the group's options has them
resolved and injected before its body runs — which is exactly what an explicit
read must not depend on.

`tests/test_group_vault_read.py` drives all of it through a plain
`FunctualizeApp` — including the wrong-key and damaged-store runs — and never
asserts a plaintext. The stored identity, the candidate order and the three
error classes are in
[configuration.md](../../../docs/guides/configuration.md#reading-a-groups-secret-from-a-job).

## Tests

```bash
uv run pytest examples/standalone/secrets_lab/ -v
```

## What is deliberately absent

There is **no `[secrets]` section**, and no `${env:VAR}` interpolation in config
files. Both were considered and rejected: a config file has no way to hold a
credential safely, and a syntax that merely *points* at an environment variable
resolves to the same variable the field would have read anyway. It buys nothing
but the appearance of a secrets feature — and that appearance is what invites
someone to paste the real value in "just for now".

A credential is a field in its job's own section, marked secret. One concept.
