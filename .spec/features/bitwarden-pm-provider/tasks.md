# Tasks: bitwarden-pm-provider

Atomized tasks. Wave ordering is binding: never start a task in wave N+1
while wave N has unchecked tasks.

## 1. The two new modules

- [x] 1.1 `_pm_reference.py`: the `bwpm://<item>/<field>` grammar — exact
      two-segment split on the first `/`, uuid-or-name item, the five
      built-in fields plus `field:<name>`, unknown-field/empty-field/query
      refusals with a close-match suggestion, frozen dataclass with a
      value-free `label`. Imports `_is_uuid` from `_reference`.
      Files: `src/functualize_secrets_bitwarden/_pm_reference.py`
- [x] 1.2 `_pm_client.py`: the `bw` subprocess transport — binary probe,
      `bw status` state machine (unauthenticated/locked/unlocked) cached per
      process behind a lock with `clear_cli_state_cache()`, uuid-form
      `bw get item <uuid> --raw`, name-form `bw list items --raw` with exact
      match and ambiguity, `--nointeraction` + `stdin=DEVNULL` + 20 s timeout,
      ambient env passing (never a `--session` argv), field extraction
      (totp seed not code, first uri, `field:` exact match, None/empty
      refuses, missing-login-block refuses).
      Files: `src/functualize_secrets_bitwarden/_pm_client.py`

## 2. Wire the provider in

- [x] 2.1 `PasswordManagerProvider` in `__init__.py`: `identifier() ->
      "bwpm"`, `is_ready()` (binary + unlocked, cached probe), `fetch()`
      (parse → probe → fetch → extract); export it and the new exceptions;
      rewrite the package docstring for two providers and record the
      Vaultwarden flip where the old "Not Vaultwarden" note stood.
      Files: `src/functualize_secrets_bitwarden/__init__.py`
- [x] 2.2 `pyproject.toml`: add the `bwpm` entry point beside `bws`. No
      dependency changes.
      Files: `pyproject.toml`

## 3. Tests

- [x] 3.1 `conftest.py`: a fake `bw` executable installed on `PATH`
      (state from files, invocation log for argv assertions), plus the
      autouse `BW_SESSION` hygiene fixture.
      Files: `tests/conftest.py`
- [x] 3.2 `test_pm_reference.py`: grammar — uuid vs name, built-ins,
      `field:` incl. names with `/`, unknown field suggestion, empty
      segments, query refusal.
      Files: `tests/test_pm_reference.py`
- [x] 3.3 `test_pm_provider.py`: the four refusals each naming its state;
      uuid and name fetch paths; ambiguity (item and custom field); field
      semantics (seed passthrough, first uri, no-value refusal, missing
      login block); secrecy (no `--session` argv, no session key or values
      in errors, provider holds no state); probe caching; protocol contract
      (`identifier == "bwpm"`, satisfies `RemoteProvider`).
      Files: `tests/test_pm_provider.py`
- [x] 3.4 `test_integration_vaultwarden.py`: module-skips without an
      unlocked `bw` and `FUNCTUALIZE_BWPM_INTEGRATION=1`; seeds a
      uuid-tagged item, asserts every field path, removes it.
      Files: `tests/test_integration_vaultwarden.py`

## 4. Documentation

- [x] 4.1 README: both schemes and their products; the Vaultwarden note
      flipped (bwpm is the compatible one); the grammar table; the refusal
      table; the ambient-session operational reality (expiry, human
      re-unlock, never persisted/logged/on argv); no invented `BW_*` vars;
      v3 `[[vault_secret]]` examples for both schemes (replacing the legacy
      inline examples the parser now refuses); runtime-dependency note.
      Files: `README.md`
- [x] 4.2 `CHANGELOG.md`: hand-written `[Unreleased]` → Added entry.
      Files: `CHANGELOG.md`
- [x] 4.3 `docs/guides/configuration.md`: the install-comment line that
      names the distribution's schemes.
      Files: `docs/guides/configuration.md`

## 5. Gates

- [x] 5.1 `uv run ruff check --fix src/ tests/ plugins/ examples/` and
      `uv run ruff format` clean.
- [x] 5.2 `uv run mypy src/` clean (plus the plugin sources ad hoc).
- [x] 5.3 `uv run lint-imports` zero violations.
- [x] 5.4 `uv run pytest plugins/credentials/functualize-secrets-bitwarden/tests/ -q`
      green.
- [x] 5.5 tests-for-diff mapper run; its selection green (exit 3 would mean
      the tip tier, which is CI's to run — never backgrounded locally).

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1.1", "1.2"] },
    { "id": 1, "tasks": ["2.1", "2.2"] },
    { "id": 2, "tasks": ["3.1", "3.2", "3.3", "3.4"] },
    { "id": 3, "tasks": ["4.1", "4.2", "4.3"] },
    { "id": 4, "tasks": ["5.1", "5.2", "5.3", "5.4", "5.5"] }
  ]
}
```
