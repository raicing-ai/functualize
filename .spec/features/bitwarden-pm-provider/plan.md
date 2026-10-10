# Plan: bitwarden-pm-provider

## Alignment

Approved shape: SD page **15007756** — *Shape Intent — Bitwarden Password
Manager Vault-Sync Provider (bwpm://)* (v1, under "10 — Shape Intents",
labels `shape-intent`, `area-vault`).

Provenance of the approval, stated exactly: this runtime has **no Atlassian
tools assigned**, so the page's `Authority` field could not be re-read here;
the page was created at `Proposed` by the run that wrote it. The approval this
plan builds on is the maintainer's live comment on the tracking issue —
comment `01a12504-9e9c-7a46-870a-c80590db76a6`, 2026-10-10T08:53:42Z, and it
is a reply in the thread that carries the page-creation report — verbatim:

> I approve the page, and use bwpm

That comment both approves that page and settles the shape's one open decision
(the scheme string) in favour of `bwpm`. In the shape's own words as recorded
by the page-creation report in the same thread: the grammar is
`bwpm://<item>/<field>`; "The field is never defaulted: one of `password`,
`username`, `totp`, `notes`, `uri` or `field:<name>`"; "A table of four
distinct refusals, plus the secrecy rules"; the selected model is the
2026-10-06 decision recorded in the issue body — "use the session the user has
already unlocked in the `bw` CLI (`BW_SESSION`), call `bw` as a subprocess,
add no new dependency, and fail closed when the session is missing".

Surfaces **in** scope, in the shape's words: the `bwpm` scheme inside
`[[vault_secret]]` declarations (vault v3 form — inline provider URIs are
legacy and refused); provider registration through the existing
`functualize.remote_providers` entry-point group; README + CHANGELOG
documentation. Surfaces **out** of scope: self-login/2FA/master-password
handling, new `BW_*` variables, `bw serve`, publication timing.

## Architecture gate

### Retrieval disclosure

The Plan-phase retrieval tools named by `.claude/rules/spec-workflow.md`
(zvec-grep, serena, graphify MCP) are **not available in this runtime** — no
MCP servers and no `zg` binary exist here; this is a Multica task workdir, not
the maintainer's machine. The three passes were executed with what exists:
`rg`/`git grep` sweeps for every mention of the seam (`remote_providers`,
`bws`, `reject_inline_provider`, `vault_secret`), full reads of every hit, and
`git log`/`git show` archaeology for the archived spec formats. Counts and
negatives below were verified by running the command that would falsify them.

### BEFORE (master `b6a200d`)

```
core _config.registry  ── entry-point group "functualize.remote_providers"
                                │
                                ▼
functualize_secrets_bitwarden  (plugins/credentials/, post-rename)
  __init__.py    SecretsManagerProvider  ("bws")  + package facade/exports
  _reference.py  bws:// grammar (uuid-or-key, overrides, unknown-key refusal)
  _client.py     bitwarden-sdk transport (Rust SDK, env-only config)
  tests/         fakes over the SDK's ResponseFor… wrapper shapes
```

Smells the BEFORE carries, by catalogue name:

- **The facade's contract is stale documentation, not code** (`__init__.py`
  docstring: "One provider, one identifier: ``bws``"). Not one of the six
  catalogue names — a doc-drift fact, named because the AFTER removes it.
- The package genuinely carries **no** Forbidden-Patterns smell: two small
  modules plus a facade, no cross-layer imports, no global state beyond the
  SDK-client cache the vault-keyring work already reviewed.

### AFTER

```
core (UNCHANGED — zero core diff; the entry-point group and
      vault sync accept any registered provider)
        │
        ▼
functualize_secrets_bitwarden
  __init__.py     SecretsManagerProvider ("bws")        (unchanged class)
             +    PasswordManagerProvider ("bwpm")     NEW class, same seam
             +    exports/exceptions/docstring          NEW names
  _reference.py   bws:// grammar                        (unchanged)
  _pm_reference.py  bwpm:// grammar                     NEW
                  (imports _is_uuid from _reference — same package)
  _client.py      bitwarden-sdk transport               (unchanged)
  _pm_client.py   bw CLI subprocess transport           NEW
  tests/          + fake-`bw` shim suite, integration module
```

Dependency direction is unchanged: plugin → (entry-point registration) →
core's registry; provider modules import nothing from `functualize` at all.
Everything sits in the plugin's own package, so all seven import-linter
contracts are untouched by construction.

### Candidate-AFTER smell check

- Sharing `_is_uuid` across the package's two grammar modules: **accepted**
  (Rule-of-Three threshold not met for a third consumer; a shared
  "grammar helpers" module for one function would be *speculative
  generality*).
- Not extracting a common "provider" base class for the two schemes: they
  share three one-line methods by coincidence of the protocol; inheritance
  would be a *refused bequest* risk for zero duplication removed.
- Two transports (SDK vs subprocess) as sibling modules, not a strategy
  hierarchy: two variants with no third foreseen — a hierarchy here would be
  speculative generality again. Plain siblings.

## Technical approach

1. `_pm_reference.py` — the grammar; pure parsing, no I/O, refuses before any
   subprocess spawns (a typo costs a clear message, not a `bw` invocation).
2. `_pm_client.py` — fresh state probe per fetch, subprocess calls, JSON extraction,
   the four session/binary refusals, field semantics (totp seed not code,
   first uri, empty refuses).
3. `__init__.py` — `PasswordManagerProvider` + exports + docstring rewrite
   (two providers, one package; the Vaultwarden flip recorded where the old
   "Not Vaultwarden" section stood).
4. `pyproject.toml` — the second entry point; no dependency changes.
5. Tests — fake `bw` executable on `PATH` (state via files, invocations
   logged for argv assertions); integration module behind
   `FUNCTUALIZE_BWPM_INTEGRATION=1` + unlocked-session gate, module-skips
   otherwise.
6. README (both schemes, v3 `[[vault_secret]]` examples — the current bws
   examples still show the legacy inline form the parser now refuses, so the
   rewrite fixes that too) and CHANGELOG `[Unreleased]` → Added.

## Files to change

- `plugins/credentials/functualize-secrets-bitwarden/src/functualize_secrets_bitwarden/__init__.py`
- `plugins/credentials/functualize-secrets-bitwarden/src/functualize_secrets_bitwarden/_pm_reference.py` (new)
- `plugins/credentials/functualize-secrets-bitwarden/src/functualize_secrets_bitwarden/_pm_client.py` (new)
- `plugins/credentials/functualize-secrets-bitwarden/pyproject.toml`
- `plugins/credentials/functualize-secrets-bitwarden/README.md`
- `plugins/credentials/functualize-secrets-bitwarden/tests/conftest.py`
- `plugins/credentials/functualize-secrets-bitwarden/tests/test_pm_reference.py` (new)
- `plugins/credentials/functualize-secrets-bitwarden/tests/test_pm_provider.py` (new)
- `plugins/credentials/functualize-secrets-bitwarden/tests/test_integration_vaultwarden.py` (new)
- `CHANGELOG.md`
- `docs/guides/configuration.md` (one install-comment line names the
  distribution's schemes)
- `.spec/features/bitwarden-pm-provider/**` (these artifacts; cleared before
  merge per the two-push sequence)

## Risks

- **`bw` JSON shape drift.** The extraction reads documented keys of `bw`'s
  item JSON. Mitigation: the integration module exists precisely to check the
  real shapes; unit fakes pin what the code assumes.
- **A `bw` invocation that prompts** would hang a sync. Mitigation:
  `--nointeraction` + `stdin=DEVNULL` + a 20 s subprocess timeout under core's
  30 s per-value wrapper.
- **Session state changing mid-sync.** Each fetch probes again, so a lock or
  unlock between values is reflected in the next value's sync report.

## Surviving smells

- **Sibling transports under one facade** (`_client.py` vs `_pm_client.py`):
  same product, same package, deliberately different transports. Not
  *duplicated code* — nothing is copied; the shared pieces (uuid test, error
  style, exception conventions) are the package's idiom. Needs no maintainer
  review.
- **O(vault) name-form fetch** (`bw list items` per name-form value): the same
  trade the `bws` provider makes with its organization listing, chosen over a
  process-lifetime cache of decrypted items. Needs no maintainer review.
- No new Forbidden-Patterns smell is introduced: no peer-layer imports,
  global mutable state, ABC, or `_cli` import. The original probe-result
  module singleton was removed during review remediation; the older SDK
  client cache remains outside this change's scope.
