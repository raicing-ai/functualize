# Publish credential plugin distributions

Execute against `623d3db5e5b43c1bd451959444c634e7c55fef66`.
The PyPI bootstrap gates merge, not these repository edits.

## Tasks

- [ ] **1.1 Remove the publish filter.** [F]
  `.github/workflows/release.yml`. Acceptance: a search for
  `Remove deferred packages` or either `dist/functualize_secrets_*-*`
  filter has no match; both publish and bake retain their own artifact
  downloads. Baseline filter hit set: one file, two lines (125 and 127).
- [ ] **1.2 Align the publishing guide.** [F] `plugins/PUBLISHING.md`.
  Acceptance: fourteen uploaded distributions and publishers are stated;
  both credential rows say `Uploaded`; no `Built, not uploaded`,
  `twelve in total`, or current AWS deferral exception remains. Baseline
  hit set: this file, including lines 215–216, 236, 244–247, 263–264,
  and 272–274.
- [ ] **2.1 Verify the release-only change.** [F] no production file.
  Acceptance: task 1.1 and 1.2 gates pass, `git diff` touches only the two
  intended production files, `pyproject.toml` is unchanged, and applicable
  repository lint, type, import, and test checks are reported.

## Task Dependency Graph

```json
{"waves": [{"id": 0, "tasks": ["1.1", "1.2"]}, {"id": 1, "tasks": ["2.1"]}]}
```
