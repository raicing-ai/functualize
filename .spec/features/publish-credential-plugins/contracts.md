## Publication boundary

`uv build --all-packages` creates the `dist` artifact. The publish job
downloads it and passes every distribution to
`pypa/gh-action-pypi-publish@release/v1`. Each PyPI project uses the same
trusted publisher tuple: owner `raicing-ai`, repository `functualize`,
workflow `release.yml`, environment `pypi`.

The bake job downloads the build artifact separately and installs
`functualize[all]`. That extra contains two core extras and eleven plugins;
`functualize-secrets-aws` and `functualize-secrets-bitwarden` are both
opt-in distributions outside it. The curated catalog keeps the AWS entry
discoverable but sets `recommended = false`, matching the extra.

The standalone binary thus excludes `aws-sm://` and `aws-ssm://` providers
until the user runs `func builtin self install functualize-secrets-aws`.
Python import, entry-point, URL-scheme, and CLI syntax contracts do not change.
