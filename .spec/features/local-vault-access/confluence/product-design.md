# Confluence product-design synthesis

Retrieved: 2026-09-17. This note collects only the portions that constrain the
local-vault UX/DX. The linked Confluence pages remain canonical.

## Product principles

From [FuncCloud — Product Thesis and Control Plane](https://raicing-ai.atlassian.net/wiki/spaces/FUN/pages/1146881/FuncCloud+Product+Thesis+and+Control+Plane)
(page `1146881`, v5):

- **CLI first.** The CLI/TUI remains the primary operational surface; web and
  mobile are later control/approval surfaces.
- **Local first, remote when valuable.** Normal work should execute where the
  operator already is. Remote execution earns its complexity only for
  privileged credentials, protected networks, reproducibility, convenience,
  or policy.
- **Complex inside, simple outside.** Users should see small, legible states and
  verbs even when provenance, policy, encryption, and verification are complex.
- **Accountless adoption.** A user should receive value before registration
  where technically feasible.
- **Authority instead of credentials.** In later collaborative scenarios,
  prefer sharing permission to run a bounded operation over distributing its
  underlying credential.
- Functualize OSS remains the developer-facing runtime. FuncCloud adds team
  synchronization, distribution, identity, policy, approvals, remote
  execution, connections, and managed audit; it does not replace local
  Functualize.

## Existing-product boundary

From [01 — Functualize Foundations and the FuncCloud Extension Boundary](https://raicing-ai.atlassian.net/wiki/spaces/FUN/pages/1048578/01+Functualize+Foundations+and+the+FuncCloud+Extension+Boundary)
(page `1048578`, v1):

- The current product is a local/project-oriented CLI and runtime built around
  discovery, layered configuration, workflows, plugins, builtins, and
  introspection.
- New managed behavior should extend those existing primitives rather than
  create a parallel execution/configuration model.
- The CLI is the stable user interface even when later execution placement can
  vary.
- Local execution preserves low latency, debuggability, filesystem/network
  access, and low operating cost.

For the local vault, that means a secret is another source in ordinary config
resolution. It should not require a separate kind of job, a cloud-specific
runtime object, or a second execution engine.

## What belongs later

[02 — Team Registry, Environment Sync, and Accountless Sharing](https://raicing-ai.atlassian.net/wiki/spaces/FUN/pages/1212417/02+Team+Registry+Environment+Sync+and+Accountless+Sharing)
(page `1212417`, v1) describes a later shareable unit as an **environment
bundle**: related secret values, non-secret configuration, target metadata,
expiry, redemption limits, and provenance. The receiver should see metadata
before redemption, use a copyable CLI flow without an account, and receive the
bundle in the safest practical local form.

[10 — Reference Scenarios and End-to-End Product Examples](https://raicing-ai.atlassian.net/wiki/spaces/FUN/pages/1245206/10+Reference+Scenarios+and+End-to-End+Product+Examples)
(page `1245206`, v2) makes that sequence concrete: accountless metadata view,
explicit redemption, local execution, then an optional account invitation.

That is not the first local-vault increment. Bundle creation/redemption,
cross-user sharing, burn links, shell/session injection, and managed sync each
add identity, transport, expiry, and custody questions. The local feature only
needs to preserve an evolution path toward them.

## Roadmap constraint

[09 — Product Roadmap, Domain Model, and Open Design Decisions](https://raicing-ai.atlassian.net/wiki/spaces/FUN/pages/1146965/09+Product+Roadmap+Domain+Model+and+Open+Design+Decisions)
(page `1146965`, v3) puts preservation of the OSS/local foundation before
accountless sharing, identity, team environments, remote capability execution,
and managed audit. Its relevant decision rules are:

- preserve local-first Functualize;
- minimize accounts and onboarding before first value;
- avoid making the CLI dependent on cloud connectivity;
- do not invent concepts that fail to map onto current jobs, config, and
  workflows;
- build the smallest primitive that naturally evolves into the next layer.

The concrete implication is that direct local `init` + `put` + ordinary job
resolution comes before bundles, sharing, process injection, or governance.

