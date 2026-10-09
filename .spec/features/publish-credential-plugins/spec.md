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
- Remove `functualize-secrets-aws` from the core `[all]` extra. It stays
  separately installable and included in the PyPI upload.
- Refresh the root and two example project `uv.lock` files so their package
  metadata matches the extra.
- Keep the curated plugin catalog's recommended set aligned with `[all]`.
  Update the installation and configuration guides for binary users who need
  AWS providers.
- Preserve the independent `bake` artifact download. Its contents change
  because it installs `[all]`.

## Accepted standalone consequence

The standalone binary bakes `functualize[all]`; after AWS leaves that extra,
the binary no longer includes the `aws-sm://` or `aws-ssm://` providers by
default. Users can add `functualize-secrets-aws` to a standalone installation
  with `func builtin plugin install functualize-secrets-aws`.

## Open question — outside this change

An opt-in `functualize[aws]` extra is undecided. Do not add it here.

## Acceptance

1. The publish job downloads the complete build artifact and passes it to
   `pypa/gh-action-pypi-publish` without removing either credential wheel.
   The bake job continues to download its own copy of that artifact.
2. The publishing guide names fourteen uploaded distributions (core plus
   thirteen plugins), marks both credential plugins as uploaded, and states
   that fourteen ordinary trusted publishers are needed.
3. `[all]` contains `functualize[cli]`, `functualize[keychain]`, and eleven
   plugins; neither secrets provider is included. The catalog still lists
   both providers, with neither recommended. No `[aws]` extra or legacy
   distribution is introduced. All three lockfiles match the new metadata.
4. The standalone binary still bakes `[all]` and therefore excludes AWS
   providers by default. The two guides identify the opt-in installation
   route, including `func builtin plugin install` for binary users.
5. Before merge or a `v*` tag, the maintainer creates
   `functualize-secrets-aws`, `functualize-secrets-bitwarden`, and
   `functualize-decision-jev` on PyPI and configures each ordinary trusted
   publisher for `raicing-ai/functualize`, `release.yml`, environment `pypi`.
   Among the three new projects, only `functualize-decision-jev` remains an
   `[all]` prerequisite. The `0.5.0` resolver and live upload checks run
   after release.
