# Confluence source notes: local vault access

These files preserve the Confluence evidence used by
[`../research.md`](../research.md). They are working copies for branch-local
research, not new authorities and not evidence of shipped behavior.

Retrieved: **2026-09-17**  
Confluence space: **Functualize** (`FUN`)  
Cloud: `raicing-ai.atlassian.net`

## Authority order used in the research

1. The live repository is authoritative for behavior that ships today.
2. Accepted repository ADRs are authoritative for the current design until a
   later ADR replaces them.
3. Confluence Decisions and Current Reference pages would be durable product
   authority; none found in this search specifically commits the local-vault
   redesign.
4. The local-vault Shape Intent is the most specific proposed product design,
   but labels itself an active proposal rather than an implementation spec.
5. The FuncCloud thesis and roadmap supply product principles and scope
   boundaries, not exact CLI contracts.
6. The dead-code audit is accepted historical evidence at commit `79545ef`;
   every finding must be revalidated against the live branch.

The dead-code audit cannot prove an exported API is unused by external
consumers. No public API removal or rename follows from a zero internal-call
count without explicit maintainer confirmation.

## Source index

| Local note | Confluence source | Page ID | Version / status | Why it matters |
| --- | --- | --- | --- | --- |
| [`local-vault-shape-intent.md`](local-vault-shape-intent.md) | [Shape Intent — Local Vault CLI and Lifecycle](https://raicing-ai.atlassian.net/wiki/spaces/FUN/pages/2031617/Shape+Intent+Local+Vault+CLI+and+Lifecycle) | `2031617` | v2; proposal, active discussion | The exact proposed first-run flow, command family, resolution model, and exclusions. |
| [`product-design.md`](product-design.md) | [FuncCloud — Product Thesis and Control Plane](https://raicing-ai.atlassian.net/wiki/spaces/FUN/pages/1146881/FuncCloud+Product+Thesis+and+Control+Plane) | `1146881` | v5; working product thesis | CLI-first, local-first, simple-outside principles and the OSS/FuncCloud boundary. |
| [`product-design.md`](product-design.md) | [01 — Functualize Foundations and the FuncCloud Extension Boundary](https://raicing-ai.atlassian.net/wiki/spaces/FUN/pages/1048578/01+Functualize+Foundations+and+the+FuncCloud+Extension+Boundary) | `1048578` | v1 | Existing local model and the requirement to extend normal discovery/config rather than create a parallel product. |
| [`product-design.md`](product-design.md) | [02 — Team Registry, Environment Sync, and Accountless Sharing](https://raicing-ai.atlassian.net/wiki/spaces/FUN/pages/1212417/02+Team+Registry+Environment+Sync+and+Accountless+Sharing) | `1212417` | v1 | Distinguishes persistent local storage from later environment-bundle sharing. |
| [`product-design.md`](product-design.md) | [09 — Product Roadmap, Domain Model, and Open Design Decisions](https://raicing-ai.atlassian.net/wiki/spaces/FUN/pages/1146965/09+Product+Roadmap+Domain+Model+and+Open+Design+Decisions) | `1146965` | v3 | Local-first roadmap sequencing and risk controls. |
| [`product-design.md`](product-design.md) | [10 — Reference Scenarios and End-to-End Product Examples](https://raicing-ai.atlassian.net/wiki/spaces/FUN/pages/1245206/10+Reference+Scenarios+and+End-to-End+Product+Examples) | `1245206` | v2 | The later accountless handoff experience and why it is not the first local-vault increment. |
| [`dead-code-audit.md`](dead-code-audit.md) | [Research — Codebase Extensibility & Hygiene Audit (2026-09-16)](https://raicing-ai.atlassian.net/wiki/spaces/FUN/pages/3637249/Research+Codebase+Extensibility+Hygiene+Audit+2026-09-16) | `3637249` | v2; accepted historical evidence | Audit summary and the registered-but-never-consumed failure pattern. |
| [`dead-code-audit.md`](dead-code-audit.md) | [Audit Evidence — Wave 6: Discovery, Config & Plugins](https://raicing-ai.atlassian.net/wiki/spaces/FUN/pages/3604527/Audit+Evidence+Wave+6+Discovery+Config+Plugins) | `3604527` | v1; accepted historical evidence | Vault audit ledger, key-provider entry point, CLI tier, and config-specific evidence. |
| [`dead-code-audit.md`](dead-code-audit.md) | [Audit Evidence — Wave 4: Public API](https://raicing-ai.atlassian.net/wiki/spaces/FUN/pages/3637294/Audit+Evidence+Wave+4+Public+API) | `3637294` | v1; accepted historical evidence | `app.utils` god-module finding and recommended `app.vault` extraction. |

## Search coverage

The Confluence search covered the exact terms `dead code audit`,
`SecretsVault`, `remote_first`, `vault_key_providers`, `keychain`, `environment
bundle`, `local vault`, `secret`, `user experience`, `developer experience`,
`local first`, and `first value`. The most relevant full pages are indexed
above. Search also found broader capability, audit, execution, and integration
pages; they were not copied because they do not materially change this
feature's first increment.
