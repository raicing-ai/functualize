# composition_lab

Every other example demonstrates **one** feature. This one demonstrates the
**seams between** features — where the questions actually are:

- Does `Fingerprint` still fire if my job takes a `Log`?
- Does `FromJob` deliver anything if the upstream was skipped as fresh?
- Does a failing `Precondition` look like a crash to my CI?
- `Guards(status=...)` **and** `Fingerprint` — which one wins?
- Where does `config: ReportConfig` come from, and does changing it bust the cache?

The guide that reads this project is
[`docs/guides/composition.md`](../../../docs/guides/composition.md). Every claim
on that page is executed by `examples/docs/scenarios/n-composition.toml`.

## Run it

```bash
cd examples/standalone/composition_lab
func lab publish            # the whole graph: parse -> report -> publish
func builtin why lab.publish
```

### Two surfaces, one declaration set

The lab ships **both** entry points, because they are two different builders
over the same jobs and they have disagreed:

```bash
func lab publish            # the bare CLI: pre-boot dispatch, live signature
python main.py lab publish  # a FunctualizeApp: click's tree, cached descriptors
```

`./demo.sh` walks the whole lab and prints the exit code of every step —
`./demo.sh` for the app, `./demo.sh func` for the CLI. It is a transcript, not
a test; the assertions are in `tests/test_composition_lab_e2e.py`, which runs
every sequence against **each** surface.

## One job per combination

| Job | Pins |
|---|---|
| `lab parse` | `Fingerprint` × `Sources` × `Log`, and a pydantic **return** type |
| `lab report` | a config **parameter**, a `FromJob` parameter and a pydantic return in one signature |
| `lab publish` | `Deps` × `Guards(status)` × `Fingerprint` — the R10a AND |
| `lab gated` | a failing `Precondition` **refuses** (exit 3); the body never runs |
| `lab verify` | declared sources resolving to **nothing** also refuse |
| `lab emit` | `Stdout` × `--output json`; a return value is programmatic |
| `lab probe` | `Shell` × `Exec(retry=...)` |
| `lab fanout` / `lab worker` | `Invoke.parallel` × `State` — each child's `State` is its own |
| `lab counter` | `State` does **not** persist; a file you own does |
| `lab bundle` | `Fingerprint(generates=[<glob>])` — a **pattern**, not a literal path, plus `GroupOptions` |
| `check signoff` | a **second group**; `Deps` crossing a group boundary, and a `GroupOptions` type read from outside its own group |
| `lab release` | `@workflow` × `Gate` — a walk that pauses for approval and resumes with `--scope-id` |

## One flag, every job in the group

`--strict` is declared once, by `LabOptions(GroupOptions, group="lab")` in
`jobs/release.py`, and read by both `lab bundle` and `check signoff` — the
latter from outside the `lab` group entirely. There is **one** lever per group
option, not one per job:

```bash
func --force lab --strict bundle        # the flag: this command line only
LAB__STRICT=true func check signoff     # the env var: every job, one variable
```

```toml
# config.base.toml — the file layer, same reach as the env var, lower precedence
[lab]
strict = true
```

The env variable is `GROUP__FIELD` — **double** underscore, prefix taken from
the class's `group=`, not from the job's name. A job's own config field uses
the single-underscore job-name form instead (`LAB_REPORT_TITLE` above).

**The flag does not cross into a walk.** `func lab release` runs `lab bundle`
as a *step*, and with `func lab --strict release` that step still reports
`strict=False`: a mid-path flag belongs to the path it was typed at, and is not
inherited by jobs the run reaches afterwards — steps, `Deps` upstreams and
`rc.invoke` children alike. To steer the whole walk, set a layer each job reads
for itself:

```bash
LAB__STRICT=true func lab release       # every step sees strict=True
```

[`docs/guides/group-options.md`](../../../docs/guides/group-options.md) has the
rule and shows how to set the same value from Python.

## Verification checklist

Each of these is asserted by the scenario; run them by hand if you are changing
the framework underneath.

- [ ] `func lab parse` prints `PARSED n=2 total=8` and `declared=True`
- [ ] a second `func lab parse` prints nothing — fresh
- [ ] `func lab parse --help` does **not** list a `SOURCES` argument
- [ ] `func lab report` picks up `title` from `[lab.report]` in `config.base.toml`
- [ ] `LAB_REPORT_TITLE=...` overrides the file; `--title` overrides the env
- [ ] `func lab report --title A` then `--title B` re-runs; back to `A` is fresh
- [ ] touching `build/report.md` makes `why lab.publish` say
      `status satisfied, but sources changed`
- [ ] `func lab gated` exits **3**, prints no `GATED BODY RAN`
- [ ] `func lab verify` exits **3** with `declared sources resolved to no files`
- [ ] `rm build/report.md` makes `lab report` run again with inputs unchanged
- [ ] `func --output json lab emit` prints JSON; `func lab emit --output json` errors
- [ ] `func lab fanout` reports `parent_state=None`
- [ ] `func lab bundle` twice: the second is fresh, because `dist/*.tar.gz` matches
- [ ] `func --force lab --strict bundle` re-runs and reports `strict=True`
- [ ] `LAB__STRICT=true func check signoff` reports `strict=True` — the flag is
      not on this job's command line, but the env layer still reaches it
- [ ] from a clean slate, `func lab --strict release` reports `strict=False` at
      the bundle step — a mid-path flag is not inherited by a walk
- [ ] `LAB__STRICT=true func lab release` reports `strict=True` at that step
- [ ] `func lab release` exits **5** and names `--scope-id` in the message
- [ ] depositing the gate's input and re-running with `--scope-id <id>` exits
      **0** and prints `RELEASE complete` — on **both** surfaces
