## Release path

```text
BEFORE
build (uv build --all-packages)
  └─ dist artifact ─┬─> publish download ─> remove two wheels ─> PyPI
                   └─> bake download ─> standalone binary

AFTER
build (uv build --all-packages)
  └─ dist artifact ─┬─> publish download ─> PyPI
                   └─> bake download ─> standalone binary
```

The boundary is the uploaded `dist` artifact. Removing the publish-only
filter leaves the bake path as it is. The two credential projects and the
already-included decision provider require PyPI bootstrap before merge.

## Design guidance consulted

`python-design-patterns` and `design-patterns-refactoring`: keep the existing
build and consumer responsibilities separate. This change removes a release
filter and adds no component or abstraction.

## Files and checks

- `.github/workflows/release.yml`: remove the deferred-package step.
- `plugins/PUBLISHING.md`: update the current classification, upload mapping,
  and trusted-publisher guidance.
- Check both jobs' artifact downloads, the two upload rows, counts, and a
  negative search for the removed filter. Run repository verification commands.

## Surviving smells

None identified in this release path: build produces one artifact, and publish
and bake consume separate downloads. The external PyPI bootstrap is an explicit
release precondition, not an in-repository workaround. No maintainer review of
an architectural compromise is needed.
