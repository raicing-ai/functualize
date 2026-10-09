# Publish credential plugin distributions

Execute against `623d3db5e5b43c1bd451959444c634e7c55fef66`.
The PyPI bootstrap gates merge, not these repository edits. D3 extends the
same change after tasks 1.1–2.1 were completed and pushed.

## Tasks

- [x] **1.1 Remove the publish filter.** [F]
  `.github/workflows/release.yml`. Acceptance: a search for
  `Remove deferred packages` or either `dist/functualize_secrets_*-*`
  filter has no match; both publish and bake retain their own artifact
  downloads. Baseline filter hit set: one file, two lines (125 and 127).
- [x] **1.2 Align the publishing guide.** [F] `plugins/PUBLISHING.md`.
  Acceptance: fourteen uploaded distributions and publishers are stated;
  both credential rows say `Uploaded`; no `Built, not uploaded`,
  `twelve in total`, or current AWS deferral exception remains. Baseline
  hit set: this file, including lines 215–216, 236, 244–247, 263–264,
  and 272–274.
- [x] **2.1 Verify the initial release-only change.** [F] no production file.
  Acceptance: task 1.1 and 1.2 gates pass, `git diff` touches only the two
  intended production files at that checkpoint, `pyproject.toml` was
  unchanged before D3, and applicable checks were reported.
- [x] **3.1 Make AWS opt-in packaging.** [F] `pyproject.toml`,
  `uv.lock`, `examples/project/weather_app/uv.lock`,
  `examples/project/monorepo_children/uv.lock`.
  Acceptance: TOML parsing reports `[all]` with two core extras and exactly
  eleven plugins, excluding both secrets distributions; the AWS and
  Bitwarden workspace entries remain; no `[aws]` extra is added. Baseline:
  fourteen `[all]` entries, twelve of them plugins, with AWS on line 128
  and its boto3 comment on lines 124–127. Refresh all three lockfiles and
  pass `uv lock --check` in their respective project roots. Baseline
  lockfile hit set: those three files each carry an AWS
  `extra == 'all'` metadata edge.
- [x] **4.1 Align the catalog and guard the decision.** [F]
  `src/functualize/_cli/data/plugin_catalog.toml`,
  `tests/cli/test_plugin_catalog.py`. Acceptance: AWS remains listed but
  `recommended = false`; the test asserts both secrets providers are
  excluded from `[all]` and recommendation, while the manifest parity test
  and targeted CLI tests pass. Baseline: AWS recommendation on catalog line
  145; the catalog parity test is at lines 87–98.
- [x] **4.2 Correct installation and publishing prose.** [F]
  `plugins/PUBLISHING.md`, `docs/getting-started/installation.md`,
  `docs/guides/configuration.md`. Acceptance: the guide counts eleven
  `[all]` plugins, still lists fourteen upload names, and both install guides
  tell standalone users to add AWS with `func builtin plugin install
  functualize-secrets-aws`. No claim says AWS is bundled by default.
  Baseline hits: publishing guide lines 231–232, installation guide lines
  54–55, configuration guide line 571.
- [x] **5.1 Verify the combined change.** [F] no production file.
  Acceptance: lint, type, import, targeted tests, and build metadata checks
  pass; the test selector's shared-infrastructure verdict is reported; the
  dead-code delta is measured from dispatch base to delivered head.
- [ ] **6.1 Align installed-extension tests with opt-in AWS.** [F]
  `tests/_cli/test_plugin_cmd.py`. Acceptance: discovery and CLI listing
  exercise Bitwarden's `functualize.remote_providers` entry point, which the
  plugin loader ignores; neither test requires AWS to be installed. The
  separate catalog test continues to guard AWS's absence from `[all]`.
  Baseline: discovery assertions at lines 53–69 and listing assertions at
  lines 145–153 require AWS; CI installs `--all-extras` and only sees `bws`.
- [ ] **6.2 Validate the corrected PR head.** [F] no production file.
  Acceptance: targeted tests and the native lint, type, and import gates pass;
  PR validation has green `test-fast` and all `test-full` matrix legs before
  spec artifact cleanup. `spec-artifacts-cleared` is expected to remain red
  while the feature files are tracked.
- [ ] **7.1 Clear feature artifacts.** [F]
  `.spec/features/publish-credential-plugins/`. Acceptance: after task 6.2,
  the final commit deletes only this tracked feature tree, the native task
  graph gate passes against the commit range, and the PR's
  `spec-artifacts-cleared` check passes.

## Task Dependency Graph

```json
{"waves": [{"id": 0, "tasks": ["1.1", "1.2"]}, {"id": 1, "tasks": ["2.1"]}, {"id": 2, "tasks": ["3.1"]}, {"id": 3, "tasks": ["4.1", "4.2"]}, {"id": 4, "tasks": ["5.1"]}, {"id": 5, "tasks": ["6.1", "6.2"]}, {"id": 6, "tasks": ["7.1"]}]}
```
