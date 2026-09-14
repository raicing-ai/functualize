# Research: local-vault-access

## Research question

What local-first vault experience gives a user a safe way to store and use a
secret without requiring a remote provider, a cloud account, or plaintext files?

## Starting point

This branch starts at `origin/master` `aed582e`. The current vault is an
encrypted SQLite cache populated by `vault sync`. The public seam is currently
inside `functualize.app.utils` on master; the rebased vault-access branch moved
it to `functualize.app.vault`. Any implementation must choose one canonical
surface and update the spec before coding.

Existing behavior:

- `vault list` and `vault status` expose metadata without the encryption key;
- jobs read vault values through `remote_first()`;
- missing keys or missing entries can fall through to lower config sources;
- the current user-facing setup is provider-oriented, even for local values.

## Findings

1. The first valuable local flow is direct provisioning, not provider
   configuration: prompt for one value, encrypt it, and use it on a later run.
2. `remote_first()` is a poor name for a preset whose main value can be a
   local vault. Prefer a distinct `vault_first()` or `local_vault()`, while
   keeping remote-provider semantics explicit.
3. A plaintext `vault get` command is useful for interoperability but should
   not be the safest primary way to pass secrets to another process.
4. Silent fallback to a literal annotation is tolerable for development config
   but unsafe for explicitly sensitive fields in deployment jobs.
5. Interactive overwrite, empty input, terminal output, multiline values,
   locked keychains, and CI/non-TTY behavior are part of the user experience,
   not implementation details.
6. The vault lab is a good integration fixture but is too elaborate to be the
   first-run tutorial. The direct local path should be demonstrable in a few
   commands.

## Candidate user flows

### Safe default

```text
func vault set db.password
func vault list
func deploy
```

The job receives the value through the normal config path; the value is never
printed.

### Process handoff

```text
func vault exec -- psql ...
```

The vault injects values into a child process without putting plaintext in shell
history or command output.

### Explicit reveal

```text
func vault reveal db.password --stdout
```

This is an intentionally dangerous escape hatch with a strong confirmation
message and documented output semantics.

## Open decisions

- Name and semantics of the vault-enabled preset.
- Whether a missing vault value is a warning or a refusal for `Secret[str]`.
- Whether `set` replaces by default or requires `--replace`.
- Whether values are text-only or support exact bytes/multiline preservation.
- Whether a vault key can be initialized and stored without manually exporting an
  environment variable.
- Whether local entries are individual keys or named environment bundles.

## Recommendation

Specify the smallest local-first capability first: masked `set`, metadata
inspection, safe job resolution, and an end-to-end test with no provider
installed. Design process injection and bundle sharing as follow-on surfaces,
but leave the storage/audit model extensible for them.

