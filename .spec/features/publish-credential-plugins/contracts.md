## Publication boundary

`uv build --all-packages` creates the `dist` artifact. The publish job
downloads it and passes every distribution to
`pypa/gh-action-pypi-publish@release/v1`. Each PyPI project uses the same
trusted publisher tuple: owner `raicing-ai`, repository `functualize`,
workflow `release.yml`, environment `pypi`.

The bake job downloads the build artifact separately. No Python import,
entry-point, URL-scheme, CLI, or `[all]` contract changes here.
