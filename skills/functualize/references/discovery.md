# Discovery — why a job is or is not there

Discovery is convention plus filters. A perfectly valid function can be
invisible, and editing the function is rarely the fix.

**Always start here:**

```bash
func builtin why <job>     # explains whether a job would run, and why
func builtin info          # everything currently discovered
```

## What makes a function a job

In the simplest mode, a module-level function in a scanned file. No decorator is
required — `@job` declares behavior (dependencies, retries, guards,
fingerprints), it does not perform registration.

## The filters

Every one of these narrows discovery, and each is available both as a CLI flag
and as project config. A job missing from `builtin info` has usually failed one:

| Filter | Narrows to |
| --- | --- |
| `--require-file-import` | files importing a given module |
| `--require-file-prefix` / `--require-file-postfix` | files by name |
| `--require-file-marker` | files declaring a module-level marker variable |
| `--require-job-prefix` / `--require-job-postfix` | functions by name |
| `--require-job-decorators` | functions carrying named decorators |
| `--exclude` | glob patterns (max 20) |
| `--discovery-depth` | directory levels below CWD (0–5) |
| `--import-libs` | directories added to `sys.path` before import |

Strict projects set the `require-*` filters in config permanently, which is the
opt-in convention-discovery mode. A function that does not satisfy them is not
broken; it is out of scope.

## Naming

Job and group names are canonical: **lowercase, hyphenated**. Input is
normalized at resolution rather than aliased, so `MyJob` and `my_job` resolve to
`my-job`. Write the canonical form; do not try to register an alternate spelling.

## The cache

Discovery results are cached. A stale cache can hide a change, and the warm-cache
path is historically where "it works cold, does nothing warm" bugs live:

```bash
func builtin cache        # inspect / clear
```

If a change to filters or job files does not show up, clear the cache before
concluding anything about the code.

## Debug order

1. `func builtin why <job>` — the direct answer.
2. `func builtin info` — is the *file* being scanned at all?
3. Clear the cache; re-run.
4. Widen the filter that excluded it, or move the file into scope.

Only after those does editing the function make sense.
