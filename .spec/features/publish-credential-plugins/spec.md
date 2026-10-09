## Purpose

The release build produces the two renamed credential plugin distributions, but
the publish job removes them before PyPI upload. Publish the complete built set
at the next release, after the three unpublished projects are bootstrapped.

## Name and publication contract

| Distribution | This change | PyPI bootstrap |
|---|---|---|
| `functualize-secrets-aws` | Include in the upload | Ordinary trusted publisher |
| `functualize-secrets-bitwarden` | Include in the upload | Ordinary trusted publisher |
| `functualize-decision-jev` | Already in the upload set | Ordinary trusted publisher |
| `functualize-aws`, `functualize-bitwarden` | Never upload | None; no legacy shims |

The published `functualize[all]==0.3.0` and `==0.4.0` metadata cannot be
changed and remains unsatisfiable. The next core release, `0.5.0`, is the
resolution anchor. This change does not bump versions or publish artifacts.

## Scope

- Remove the credential wheel deletion from the `publish` job in
  `.github/workflows/release.yml`.
- Update `plugins/PUBLISHING.md` so its release table and counts describe all
  fourteen built distributions as included in the upload, with one publisher
  per project.
- Preserve the independent `bake` artifact download and leave
  `pyproject.toml` unchanged.

## Open question — outside this change

Does `functualize-secrets-aws` remain in the `[all]` extra? The maintainer has
not decided. That answer also determines whether the standalone binary,
which bakes `[all]`, keeps the AWS providers. Keep today's `[all]` and bake
configuration untouched; this spec does not decide their future membership.

## Acceptance

1. The publish job downloads the complete build artifact and passes it to
   `pypa/gh-action-pypi-publish` without removing either credential wheel.
   The bake job continues to download its own copy of that artifact.
2. The publishing guide names fourteen uploaded distributions (core plus
   thirteen plugins), marks both credential plugins as uploaded, and states
   that fourteen ordinary trusted publishers are needed.
3. `pyproject.toml` and all runtime source remain unchanged. No legacy
   distribution is introduced.
4. Before merge or a `v*` tag, the maintainer creates
   `functualize-secrets-aws`, `functualize-secrets-bitwarden`, and
   `functualize-decision-jev` on PyPI and configures each ordinary trusted
   publisher for `raicing-ai/functualize`, `release.yml`, environment `pypi`.
   The `0.5.0` resolver and live upload checks run after release.
