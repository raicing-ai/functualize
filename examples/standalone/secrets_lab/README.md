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
