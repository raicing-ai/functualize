# Releasing payments-api

1. Bump the version in `pyproject.toml`.
2. Update `CHANGELOG.md` with a heading for the new version.
3. Run `uv run pytest` and confirm green.
4. Tag `v<version>` and push the tag.
5. Announce in #payments-releases.
