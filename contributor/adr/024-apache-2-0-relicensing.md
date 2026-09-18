# ADR-024: Functualize Is Apache-2.0, and the Copyright Lives in NOTICE

**Status**: accepted
**Date**: 2026-09-18
**Deciders**: maintainer
**Supersedes**: the MIT licence carried since the first commit

## Context

Functualize shipped under MIT from `v0.1.0` through `v0.2.3`. The maintainer
elected to relicense to Apache-2.0 before `v0.3.0` — the first release that has
not yet reached PyPI, so no published artefact changes licence retroactively.

The decision itself is the maintainer's and is recorded here as made. What this
ADR settles is the part that is *not* a matter of preference: where the
copyright notice goes, which of the repository's many `MIT` strings actually
describe Functualize's own licensing, and how the metadata is declared so PyPI
accepts it.

Apache-2.0 differs from MIT in three ways that touch this repository rather than
only the licence text: it carries an express patent grant and termination clause
(§3), it requires that recipients receive a copy of the licence (§4a), and it
defines a `NOTICE` propagation rule (§4d) that MIT has no analogue for.

## Decision

### The licence text is verbatim, so the copyright goes in NOTICE

`LICENSE` is the unmodified upstream text from `apache.org`
(sha256 `cfc7749b96f63bd31c3c42b5c471bf756814053e847c10f3eb003417bc523d30`),
appendix included.

That appendix carries a `Copyright [yyyy] [name of copyright owner]`
placeholder. Filling it is the common shortcut and it is **not** taken here: an
edited `LICENSE` is no longer the canonical text, and automated licence scanners
that hash or fingerprint the file stop recognising it. The attribution therefore
goes where Apache designed a home for it:

```
functualize
Copyright 2025-2026 Mohammad Hakim Adiprasetya
```

The year range extends the MIT notice's `2025` rather than replacing it —
authorship did not begin again.

A `NOTICE` file is only worth creating when it carries a notice someone must
actually propagate. This one does: it is the sole remaining home for the
copyright line, given a verbatim `LICENSE`. It deliberately contains nothing
else. No third-party attributions belong in it, because nothing under
`src/functualize/` is vendored — the repository has no third-party source
carrying its own copyright header.

### Every first-party package, and the licence text travels with each

All thirteen distributions — `functualize` and the twelve `plugins/*` — declare
`Apache-2.0` and release in lockstep, as they already did for versions.

Each plugin directory now carries its own `LICENSE` and `NOTICE`. This is not
tidiness: §4(a) requires that recipients of the Work receive a copy of the
licence, and a plugin wheel is a separately-installable artefact whose recipient
may never see the root of this repository. Under MIT the omission was harmless
in practice; under Apache-2.0 it is a compliance gap, so the files are
duplicated into each package rather than referenced across it. Verified: every
built wheel reports `License-File: LICENSE` and `License-File: NOTICE`.

### PEP 639 SPDX, and no trove classifier

The declaration is `license = "Apache-2.0"` — an SPDX expression string, which
is what PEP 639 specifies and what the repository already used for MIT. The
deprecated table forms (`{text = ...}`, `{file = ...}`) are not introduced.

No `License :: OSI Approved :: *` trove classifier is added, and none existed to
remove. PEP 639 makes the SPDX field and the legacy classifiers mutually
exclusive, and PyPI **rejects** a distribution carrying both. This is worth
stating in an ADR because nothing local catches it: `twine check --strict`
passes such a build, as `plugins/PUBLISHING.md` already records.

### What keeps its MIT string, and why

The repository contains many `MIT` occurrences that do not describe
Functualize's licence, and relicensing them would be wrong rather than merely
unnecessary:

| Kept as MIT | Because |
|---|---|
| `src/functualize/_cli/scaffold/templates/*/pyproject.toml.j2` | These populate a **user's** newly scaffolded project. Functualize's licence choice is not the user's, and imposing it would be a scaffolding behaviour change rather than a relicensing |
| `evals/package-lock.json` | npm dependency metadata — other people's licences |
| `.agents/skills/improve`, `.agents/skills/python-pypi-package-builder`, `auditing-python-security` | Vendored third-party skills. ADR-006 already requires these be *referenced, not redistributed* |
| `.github/workflows/security.yml` | Describes the scanner's licence, not ours |
| `skills/functualize-skill/SKILL.md` frontmatter example, `references/distribution.md` manifests | Examples showing a user what fields *their* skill or plugin manifest takes |
| `contributor/adr/006` | Historical record of third-party skill licensing |

The distinction applied throughout: a string is changed when it asserts what
*Functualize* is licensed under, and left alone when it asserts what someone
else is licensed under or what a generated artefact should be.

### Inbound stays inbound=outbound

`CONTRIBUTING.md` and `docs/contributing.md` now name Apache-2.0 in the same
sentence structure they used for MIT. **No CLA, DCO, copyright assignment, or
other contribution requirement is introduced.** Contributors license their
contributions under the project's licence, exactly as before; only the licence
named has changed.

## Consequences

- Downstream users gain an express patent grant and the §3 termination
  condition, neither of which MIT provided.
- Redistributors take on the §4 obligations — carrying `LICENSE`, preserving
  `NOTICE`, and stating changes — which are more than MIT's single-notice rule.
- Anyone republishing a plugin wheel now has the licence text in hand, which was
  previously not true.
- `v0.2.3` and earlier remain MIT. A relicence is not retroactive, and users who
  took those versions keep the terms they received.

## Alternatives considered

**Fill the appendix in `LICENSE` and skip `NOTICE`.** Rejected: it modifies the
canonical text for no gain, and Apache already defines where attribution goes.

**Reference the root `LICENSE` from each plugin rather than copying it.**
Rejected: build backends resolve licence files within the package directory, and
a path escaping it is not portable. A wheel that names a file it does not
contain satisfies nobody.

**Relicense the scaffold templates too, for internal consistency.** Rejected —
see the table above. Consistency across *Functualize's own* packages is the
goal; consistency with projects Functualize generates for other people is not
Functualize's call to make.
