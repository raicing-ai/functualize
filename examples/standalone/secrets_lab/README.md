# Secrets Lab

How a credential is declared, resolved, and — everywhere it is rendered —
withheld. Five steps, each one command.

```
secrets_lab/
├── config.base.toml     # non-secret config, per-job sections. No [secrets] block.
├── jobs/
│   ├── sync.py          # a secret with an empty default, next to a decoy
│   └── report.py        # a REQUIRED secret with no default
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

$ func builtin vault put report.token
Value: ********
Stored report.token (new).

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

**The vault outranks the environment.** Once `report.token` is stored,
`REPORT_TOKEN` no longer overrides it. An explicit `--token` on the command
still does.

### What you can ask about a secret you cannot read

```console
$ func builtin vault inspect report.token
Path:       report.token
Eligible:   yes
Stored:     yes
Origin:     direct
Readable:   readable
Would win:  vault
```

`inspect` never decrypts the value — readability is answered from a separate
check row — so this works, and tells you the truth, on a machine whose key is
wrong.

`sync.sort_key` is the lab's decoy from step 1. The vault follows the model for
exactly the same reason nothing else here uses name heuristics:

```console
$ func builtin vault inspect sync.sort_key
Path:       sync.sort_key
Eligible:   no
Stored:     no
```

### Taking it back

```console
$ func builtin vault remove report.token
Remove report.token? [y/N]: y
Removed report.token (direct).
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
from functualize.app.vault import vault_init, vault_put, vault_inspect

vault_init(key_source="env")
vault_put(app, "report.token", token)
app.refresh()          # the chain is built at boot; this picks up the change
```

`tests/test_vault_lifecycle.py` is that code, and it asserts that this whole
example imports nothing private — if the published API were incomplete for its
own headline lifecycle, that test could not be written.

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
