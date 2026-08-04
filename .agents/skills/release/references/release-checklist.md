# Release Checklist

The Regular Release workflow executes six sequential gates. Each gate must pass before the next is evaluated. On failure at any gate, the workflow halts immediately — no subsequent gates run.

After all gates pass, a confirmation prompt is presented. Only upon explicit user consent does the tag-and-push execution occur.

---

## Gate Execution Order

| # | Gate | What it validates |
|---|------|-------------------|
| 1 | Verification Commands | All project health commands exit 0 |
| 2 | CHANGELOG Entry | Target version has a dated heading in CHANGELOG.md |
| 3 | Root pyproject.toml Version | `version` field matches intended release version |
| 4 | Plugin Workspace Versions | Every plugin version matches root version |
| 5 | Branch & Working Tree Clean | On `master`, no uncommitted or untracked changes |
| 6 | Tag Format | Tag matches `vX.Y.Z` where X.Y.Z equals pyproject.toml version |

---

## Gate 1: Verification Commands

**Pass criteria:** Every command below exits with status code 0.

**Commands (run in sequence):**

```bash
uv run ruff check
uv run ruff format --check
uv run mypy src/
uv run lint-imports
uv run pytest -x -q --no-header
```

**Expected output:** Each command produces zero errors/warnings and exits 0.

**Failure behavior:**

- **Halt** at the first command that exits non-zero.
- **Identify gate:** "Gate 1: Verification Commands"
- **Expected vs actual:** "Expected exit code 0 from `<command>`, got exit code `<N>`"
- **Remediation:** Run the failing command locally, fix the reported issues, and re-run the release workflow. For common fixes:
  - `ruff check` — run `uv run ruff check --fix` to auto-fix lint issues
  - `ruff format --check` — run `uv run ruff format` to reformat
  - `mypy src/` — resolve type errors shown in output
  - `lint-imports` — fix disallowed imports per layer rules
  - `pytest` — fix failing tests

---

## Gate 2: CHANGELOG Entry

**Pass criteria:** CHANGELOG.md contains a heading matching `## [X.Y.Z] - YYYY-MM-DD` where `X.Y.Z` is the target release version, AND no release content intended for this version remains solely under the `## [Unreleased]` heading.

**Verification steps:**

1. Read `CHANGELOG.md`
2. Search for a heading matching the pattern `## [<target_version>] - <ISO-8601-date>`
3. Confirm the heading exists with a valid date (`YYYY-MM-DD`)
4. Confirm that `## [Unreleased]` does not contain entries that should have been moved to the version heading

**Expected output:** A version heading exists for the target version with a valid date. The `[Unreleased]` section is either empty or contains only items genuinely planned for a future release.

**Failure behavior:**

- **Halt** immediately.
- **Identify gate:** "Gate 2: CHANGELOG Entry"
- **Expected vs actual:**
  - Missing heading: "Expected heading `## [X.Y.Z] - YYYY-MM-DD` in CHANGELOG.md, but no such heading found"
  - Content still under Unreleased: "Found release content under `## [Unreleased]` that appears to belong to version X.Y.Z"
- **Remediation:** Add a version heading with today's date (`## [X.Y.Z] - YYYY-MM-DD`) and move all relevant entries from `[Unreleased]` into it. Commit the change before re-running.

---

## Gate 3: Root pyproject.toml Version

**Pass criteria:** The `version` field in the root `pyproject.toml` exactly equals the intended release version string.

**Verification steps:**

1. Read root `pyproject.toml`
2. Parse the `[project]` table
3. Extract the `version` field value
4. Compare against the target release version

**Expected output:** `version = "X.Y.Z"` where X.Y.Z matches the intended release.

**Failure behavior:**

- **Halt** immediately.
- **Identify gate:** "Gate 3: Root pyproject.toml Version"
- **Expected vs actual:** "Expected version `X.Y.Z` in root pyproject.toml, found `<actual_version>`"
- **Remediation:** Update the `version` field in root `pyproject.toml` to the target version and commit the change.

---

## Gate 4: Plugin Workspace Versions

**Pass criteria:** Every `pyproject.toml` found under `plugins/*/` has its `version` field set to the same value as the root `pyproject.toml` version.

**Verification steps:**

1. List all directories under `plugins/` that contain a `pyproject.toml`
2. For each plugin `pyproject.toml`, parse the `[project]` table and extract the `version` field
3. Compare each plugin version against the root version (from Gate 3)

**Expected output:** All plugin versions match the root version exactly.

**Failure behavior:**

- **Halt** immediately.
- **Identify gate:** "Gate 4: Plugin Workspace Versions"
- **Expected vs actual:** "Expected version `X.Y.Z` in `plugins/<name>/pyproject.toml`, found `<actual_version>`"
- **Remediation:** Update the `version` field in the listed plugin's `pyproject.toml` to match the root version. Repeat for all mismatched plugins. Commit the changes.

---

## Gate 5: Branch & Working Tree Clean

**Pass criteria:** All three conditions are met:
1. Current branch is `master`
2. No uncommitted staged or unstaged changes
3. No untracked files in the working tree

**Verification commands:**

```bash
# Check current branch
git branch --show-current
# Expected output: master

# Check for uncommitted changes (staged + unstaged)
git status --porcelain
# Expected output: empty (no output)
```

**Expected output:** Branch is `master` and `git status --porcelain` produces no output.

**Failure behavior:**

- **Halt** immediately.
- **Identify gate:** "Gate 5: Branch & Working Tree Clean"
- **Expected vs actual:**
  - Wrong branch: "Expected branch `master`, currently on `<branch_name>`"
  - Uncommitted changes: "Expected clean working tree, found uncommitted changes: `<list of files>`"
  - Untracked files: "Expected no untracked files, found: `<list of files>`"
- **Remediation:**
  - Wrong branch: "Switch to master branch: `git checkout master`"
  - Uncommitted changes: "Commit or stash pending changes: `git stash` or `git commit`"
  - Untracked files: "Add untracked files to .gitignore, commit them, or remove them"

---

## Gate 6: Tag Format

**Pass criteria:** The Release Tag to be created matches the pattern `vX.Y.Z` where `X.Y.Z` is identical to the `version` field in the root `pyproject.toml`.

**Verification steps:**

1. Construct the expected tag: `v` + root pyproject.toml version
2. Confirm the tag string matches the regex `^v\d+\.\d+\.\d+$`
3. Confirm the tag does not already exist locally or remotely

**Verification commands:**

```bash
# Check if tag already exists locally
git tag -l "vX.Y.Z"
# Expected output: empty (tag does not exist)

# Check if tag exists on remote
git ls-remote --tags origin "refs/tags/vX.Y.Z"
# Expected output: empty (tag does not exist)
```

**Expected output:** Tag format is valid and the tag does not already exist.

**Failure behavior:**

- **Halt** immediately.
- **Identify gate:** "Gate 6: Tag Format"
- **Expected vs actual:**
  - Invalid format: "Expected tag matching `vX.Y.Z` pattern, constructed tag `<value>` is invalid"
  - Tag exists: "Tag `vX.Y.Z` already exists — cannot create a duplicate"
- **Remediation:**
  - Invalid format: "Ensure root pyproject.toml version is a valid semver string (e.g., `1.2.3`)"
  - Tag exists: "If the existing tag is incorrect, delete it with `git tag -d vX.Y.Z && git push origin :refs/tags/vX.Y.Z` and re-run. If the tag is correct, this version has already been released."

---

## Confirmation Prompt

After all six gates pass, present the following summary to the user and request explicit confirmation:

```markdown
## Release Summary

- **Version**: X.Y.Z
- **Tag**: vX.Y.Z
- **Packages**:
  - functualize X.Y.Z
  - functualize-inline X.Y.Z
  - functualize-state X.Y.Z
  - ... (all discovered plugins)
- **Changelog entry**:
  (first 5 lines of the ## [X.Y.Z] CHANGELOG section)
- **Trigger**: git push origin vX.Y.Z → GitHub Actions → PyPI (Trusted Publishing)

Proceed? [confirm/abort]
```

The user must explicitly confirm before any mutating action occurs.

---

## Post-Confirmation Execution

Upon user confirmation, execute the following steps in order:

### Step 1: Create tag

```bash
git tag vX.Y.Z
```

If this fails because the tag already exists (race condition — another process created it between gate check and now):
- **Report:** "Tag `vX.Y.Z` already exists. Aborting release."
- **Action:** Do not push. Abort cleanly.

### Step 2: Push tag

```bash
git push origin vX.Y.Z
```

If push succeeds:
- Proceed to Step 3.

If push fails:
- **Report:** "Push failed: `<error message from git>`. The local tag `vX.Y.Z` remains in place."
- **Action:** Leave the local tag for the user to retry manually (`git push origin vX.Y.Z`) or remove (`git tag -d vX.Y.Z`). Do not attempt automatic retry.

### Step 3: Report workflow trigger

```markdown
Release tag `vX.Y.Z` pushed successfully.

The GitHub Actions release workflow has been triggered.
Monitor progress: https://github.com/<owner>/<repo>/actions

The workflow will:
1. Build sdist and wheel for functualize + all plugins
2. Publish to PyPI via Trusted Publishing (OIDC)
```

---

## Error Handling Summary

| Scenario | Behavior |
|----------|----------|
| Tag already exists (at Gate 6) | Gate fails, halt with remediation guidance |
| Tag already exists (at execution) | Abort, report conflict, do not push |
| Push fails | Report reason, leave local tag in place |
| User declines confirmation | Abort cleanly, no tag created, no side effects |
| Gate 1 command fails | Halt, show which command failed and its output |
| Gate 2–6 check fails | Halt, show expected vs actual, provide remediation |
