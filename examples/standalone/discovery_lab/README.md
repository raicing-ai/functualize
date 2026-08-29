# Discovery Lab — one jobs tree, every filter

The discovery filters demonstrated from a **single directory**. The project
config enables no filters (baseline convention mode); each filter is switched
on per-run with a `FUNCTUALIZE_DISCOVERY_*` env var or a CLI flag, and the job
listing changes accordingly.

```bash
cd examples/standalone/discovery_lab
```

## The jobs tree

Each file is crafted to pass a *different* subset of filters:

| File | `job_` prefix | `_task` postfix | imports functualize | `__functualize__` marker | has decorated fn |
|------|:---:|:---:|:---:|:---:|:---:|
| `jobs/job_deploy.py` (`deploy`†, `rollback`) | ✔ | – | ✔ | – | ✔ |
| `jobs/job_build.py` (`build`) | ✔ | – | – | – | – |
| `jobs/cleanup_task.py` (`cleanup`) | – | ✔ | – | – | – |
| `jobs/marked.py` (`audit`) | – | – | – | ✔ | – |
| `jobs/helpers.py` (`helper_info`) | – | – | – | – | – |
| `jobs/_private.py` (`secret`) | never discovered (underscore filename) | | | | |
| `global/snippets.py` (`snippet_hello`, `snippet_date`) | merged via `extra_directories` | | | | |

† `deploy` is decorated with `@job`; `rollback` is not — the pair
exists to show the file/function split: file-level filters take both, the
job-level decorator filter takes only `deploy`.

## Step-by-step verification

Run the command and compare the listing against **Expect**. No cache clearing
between steps — the cache header fingerprints the filter settings, so changing one
invalidates it automatically. Piped (`func | cat`) gives the plain listing; a bare `func` in a
terminal opens the inline TUI with the same job set.

| # | Run | Expect in the listing |
|---|-----|-----------------------|
| 1 | `func` | Baseline: `audit build cleanup deploy helper_info rollback snippet_date snippet_hello` — and never `secret` |
| 2 | `FUNCTUALIZE_DISCOVERY_REQUIRE_FILE_PREFIX=job_ func` | Only `build deploy rollback`. Note the global snippets vanished — filters apply to `extra_directories` too |
| 3 | `FUNCTUALIZE_DISCOVERY_REQUIRE_FILE_POSTFIX=_task func` | Only `cleanup` |
| 4 | `FUNCTUALIZE_DISCOVERY_REQUIRE_FILE_IMPORT=functualize func` | Only `deploy rollback` (sole file importing functualize) |
| 5 | `FUNCTUALIZE_DISCOVERY_REQUIRE_FILE_MARKER=__functualize__ func` | Only `audit` |
| 6 | `FUNCTUALIZE_DISCOVERY_REQUIRE_JOB_DECORATORS=job func` | Only `deploy` — this filter is **function-level**: `rollback` shares the file but carries no decorator, so it does not ride along |
| 7 | `FUNCTUALIZE_DISCOVERY_REQUIRE_JOB_PREFIX=snippet_ func` | Only `snippet_date snippet_hello` — also function-level, judged on the function name |
| 8 | `FUNCTUALIZE_DISCOVERY_REQUIRE_JOB_POSTFIX=_info func` | Only `helper_info` |
| 9 | Combined (AND): `FUNCTUALIZE_DISCOVERY_REQUIRE_FILE_PREFIX=job_ FUNCTUALIZE_DISCOVERY_REQUIRE_FILE_IMPORT=functualize func` | Only `deploy rollback` — every enabled filter must pass |
| 10 | `FUNCTUALIZE_DISCOVERY_EXCLUDE_PATTERNS='job_*.py' func` | Baseline minus `build deploy rollback` (patterns match the path relative to the scanned directory — no leading `**/` needed for top-level files) |

Steps 6–8 are the job level; the rest are the file level. The difference is
visible in step 6 versus step 4: `require_file_import` admits `deploy` **and**
`rollback` because they share a qualifying *file*, while
`require_job_decorators` admits only the decorated *function*.

- [ ] `FUNCTUALIZE_DISCOVERY_REQUIRE_JOB_DECORATORS=job func rollback`
  reports an unknown command — a filtered-out job is unreachable by name, not
  merely hidden from the listing

The two levels reach the cache differently, and neither needs a manual clear.
Job-level filters (steps 6-8) are applied when the cache is *read*, so the cache
stays a superset of what any one of them admits. File-level filters (steps 1-5,
9-10) decide what gets *written*, so they cannot work that way — instead the cache
header fingerprints the filter settings and a change discards the cache and
rescans. Either way a filter change takes effect on your next command.

### Same thing with CLI flags (highest precedence)

```bash
func --require-file-prefix job_          # = step 2
func --require-file-import functualize   # = step 4
func --require-file-marker __functualize__   # = step 5
func --require-job-decorators job   # = step 6
func --require-job-prefix snippet_       # = step 7
func --require-job-postfix _info         # = step 8

# CLI beats env on the same key: env says "cleanup", the flag says "job_"
FUNCTUALIZE_DISCOVERY_REQUIRE_FILE_PREFIX=cleanup func --require-file-prefix job_
```

- [ ] Each flag reproduces its env-var step
- [ ] In the last command the listing is `build deploy rollback` (the flag won);
  drop the flag and the same env var alone lists only `cleanup`

Note that env vars and flags on *different* keys don't override each other —
they stack (AND), like any other filter combination.

### Run one job to close the loop

```bash
func deploy --target production   # → Deployed to production
func snippet-hello --name Lab     # a "global" job runs like any project job → Hello, Lab!
```

## Filters demonstrated here, configured persistently

In a real project the winning filter combination goes into config instead of
env vars — any of:

```toml
# pyproject.toml
[tool.functualize.discovery]
require_file_prefix = "job_"
require_file_import = "functualize"
```

```toml
# .functualize.toml (non-Python projects — see ../showcase/.functualize.toml)
[discovery]
require_file_prefix = "job_"
```

or the global `~/.config/functualize/config.toml` (see
[`../config_lab/`](../config_lab/) for how the layers interact).

## Tests

```bash
uv run pytest examples/standalone/discovery_lab/ -v
```

## Related documentation

- [Discovery Filtering](../../../docs/cli/discovery.md) — full filter reference
- [CLI Modes](../../../docs/cli/modes.md) · [Global Config Directory](../../../docs/cli/global-config-directory.md)
