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
