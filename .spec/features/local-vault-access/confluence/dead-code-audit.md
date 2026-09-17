# Confluence dead-code audit: vault-relevant evidence

Retrieved: 2026-09-17.

Primary source: [Research — Codebase Extensibility & Hygiene Audit (2026-09-16)](https://raicing-ai.atlassian.net/wiki/spaces/FUN/pages/3637249/Research+Codebase+Extensibility+Hygiene+Audit+2026-09-16)
(page `3637249`, v2).  
Detailed config source: [Audit Evidence — Wave 6: Discovery, Config & Plugins](https://raicing-ai.atlassian.net/wiki/spaces/FUN/pages/3604527/Audit+Evidence+Wave+6+Discovery+Config+Plugins)
(page `3604527`, v1).  
Detailed public-API source: [Audit Evidence — Wave 4: Public API](https://raicing-ai.atlassian.net/wiki/spaces/FUN/pages/3637294/Audit+Evidence+Wave+4+Public+API)
(page `3637294`, v1).

## Scope and authority

The audit is accepted **historical** evidence at commit `79545ef` on
`feat/plugin-host-protocol`, dated 2026-09-16. It explicitly says the live
repository remains authoritative and every finding must be revalidated before
delivery. The audit reported 155 deduplicated findings and identified
“registered but never consumed” as the repository's signature failure mode.

An additional maintainer constraint applies to this research: **absence of an
in-repository caller does not establish that a public API is dead**. External
consumers are outside the audit's reference graph. No public API deletion,
rename, or compatibility break is authorized by this audit; it requires an
explicit maintainer decision after the public contract and external-consumer
risk are reviewed.

## Findings that constrain this feature

### 1. The key-provider extension point is declared but not consumed

The audit's third-ranked finding says the
`functualize.vault_key_providers` entry-point group is declared while
`resolve_vault_key()` uses hard-coded defaults. Live-branch revalidation agrees:

- `pyproject.toml` publishes `env` and `keychain` in the entry-point group;
- `_config/vault_keys.py::default_providers()` constructs those two classes
  directly;
- all production calls invoke `resolve_vault_key(project_id)` without a loaded
  provider list;
- no production loader reads the entry-point group.

Concrete consequence: the new work should wire third-party key providers end
to end, or leave the existing extension point unchanged pending an explicit
maintainer decision. The audit alone is not authority to remove the public
protocol or entry-point group. `init` must not deepen a public seam that still
has no production reader.

### 2. The vault audit ledger is write-only in production

Wave 6 findings D13/D14 show `SecretsVault._audit()` writing on sync/read while
`audit_records()` has no shipped reader. Live-branch `rg` still finds readers
only in tests. This is not harmless future-proofing: it adds I/O and schema to
every use while users cannot inspect or rely on it.

Concrete consequence: direct local writes must not automatically widen this
ledger as if an audit product existed. The implementation must choose one of:

- expose a deliberately redacted metadata history with a defined retention and
  user contract; or
- remove the write-only ledger from the redesigned store.

The narrow first increment should choose removal unless history is explicitly
added to the feature specification.

### 3. `app.utils` is already a god module

Wave 4 identifies `src/functualize/app/utils.py` as a 2,380-line public module
with five unrelated responsibilities and specifically recommends extracting
the ADR-016 vault section to `functualize.app.vault`. The live branch still has
the vault seam in `app.utils`; no `app/vault.py` exists.

Concrete consequence: adding `init`, `put`, `remove`, `inspect`, source
provenance, and reset behavior directly to `app.utils` would knowingly enlarge
an audited design problem. A focused public `app.vault` module is the preferred
home for new implementation, while the existing `app.utils` exports remain
available unless the maintainer explicitly approves their removal. A thin
re-export can preserve that public door without duplicating behavior.

### 4. The nominal CLI config tier is empty

Wave 6 D8/D9 found every production `CliSource` constructed with `{}` and the
adapter that could populate it reachable only from tests. The live code still
constructs empty `CliSource` objects. Explicit job CLI arguments do win, but
they do so through command binding/execution, not because the resolution-chain
CLI source carries values.

Concrete consequence: document precedence in user terms—explicit job argument
beats vault—without pretending `CliSource` currently implements that behavior.
Tests must exercise the real public invocation path.

### 5. `remote_first()` is live but is not the generic UX

The audit preserved `remote_first()` as ADR-decided, not dead. Live code does
wire it to `VaultSource`, but ordinary `func` construction uses plain
`ConfigSources` in multiple dispatch paths. Therefore the existing vault is
reachable for explicitly configured apps and provider-sync tests, yet absent
from the normal local-first first-run path proposed in Confluence.

Concrete consequence: adding commands alone is insufficient. The composition
root must make a dormant local source part of ordinary resolution while
preserving behavior when no usable entry exists.

## Audit-derived verification rule

This feature is unusually exposed to the repository's recurring
built-and-tested-but-unreachable defect. Component tests of `SecretsVault.put`
or a command callback are necessary but insufficient. Completion requires an
ordinary discovered job declaring an eligible secret, public CLI invocation on
cold and warm discovery paths, an intentionally broken source wire that makes
that test fail, and negative leak scans across all output.
