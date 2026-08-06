# Best Practices Checklist

A structured checklist of Python OSS best practices to verify before releasing a package. Each item specifies what to check, where to check it, what constitutes a pass, and what severity a failure produces. The audit agent walks this list during the Pre-Release Audit phase.

---

## Severity Levels

| Level | Meaning | Effect on Verdict |
|-------|---------|-------------------|
| **BLOCKING** | Must be resolved before release | Verdict = NOT_READY |
| **WARNING** | Should be resolved; release is possible without it | Verdict = READY_WITH_WARNINGS |
| **INFO** | Nice-to-have; informational only | No effect on verdict |

---

## Project Metadata

Items related to `pyproject.toml` content and package metadata.

### PM-01: `pyproject.toml` exists

| Field | Value |
|-------|-------|
| **What to check** | The file `pyproject.toml` exists at the project root |
| **Where** | `pyproject.toml` |
| **Pass criteria** | File exists and is valid TOML (parseable without error) |
| **Severity** | BLOCKING |

### PM-02: Development Status classifier

| Field | Value |
|-------|-------|
| **What to check** | A `Development Status` trove classifier is present in `[project.classifiers]` |
| **Where** | `pyproject.toml` → `[project] classifiers` |
| **Pass criteria** | At least one entry matching `Development Status :: *` exists |
| **Severity** | WARNING |

### PM-03: No legacy License classifier

| Field | Value |
|-------|-------|
| **What to check** | **No** `License ::` trove classifier appears in `[project.classifiers]` |
| **Where** | `pyproject.toml` → `[project] classifiers` |
| **Pass criteria** | Zero entries matching `License :: *` exist |
| **Severity** | BLOCKING |

Under [PEP 639](https://peps.python.org/pep-0639/) the SPDX `license` field (PM-07)
and the legacy `License ::` classifiers are mutually exclusive, and PyPI **must
reject** any distribution carrying both. A package emitting `License-Expression:
MIT` *and* `Classifier: License :: OSI Approved :: MIT License` fails at upload.

The trap: **`twine check` and `twine check --strict` both pass such a build.** This
was verified against a real pre-fix wheel — neither command inspects the license
fields for conflict. Nothing local catches it, so treat this checklist item as the
gate. See also the TestPyPI dry run, which does catch it because it runs the same
Warehouse validation as PyPI.

### PM-04: Python version classifier

| Field | Value |
|-------|-------|
| **What to check** | A `Programming Language :: Python :: 3.x` classifier is present |
| **Where** | `pyproject.toml` → `[project] classifiers` |
| **Pass criteria** | At least one entry matching `Programming Language :: Python :: 3.*` exists (specific minor version, not just `Programming Language :: Python :: 3`) |
| **Severity** | WARNING |

### PM-05: Typing classifier

| Field | Value |
|-------|-------|
| **What to check** | The `Typing :: Typed` classifier is present |
| **Where** | `pyproject.toml` → `[project] classifiers` |
| **Pass criteria** | Exact entry `Typing :: Typed` exists in classifiers list |
| **Severity** | WARNING |

### PM-06: Project URLs

| Field | Value |
|-------|-------|
| **What to check** | `[project.urls]` section exists with at least one URL entry |
| **Where** | `pyproject.toml` → `[project.urls]` |
| **Pass criteria** | Section exists and contains at least one key-value pair with a valid URL (starts with `http://` or `https://`) |
| **Severity** | INFO |

### PM-07: License field

| Field | Value |
|-------|-------|
| **What to check** | A `license` field is specified in the project metadata |
| **Where** | `pyproject.toml` → `[project] license` |
| **Pass criteria** | An SPDX expression string — `license = "MIT"` — is present and non-empty. The table forms `license = {text = "..."}` and `license = {file = "..."}` are deprecated by PEP 639; `{file = ...}` remains valid for non-SPDX licenses |
| **Severity** | WARNING |

Pairs with PM-03: if this field is set, no `License ::` classifier may accompany it.

---

## Type Safety

Items related to PEP 561 compliance and type-checking support.

### TS-01: PEP 561 `py.typed` marker

| Field | Value |
|-------|-------|
| **What to check** | The `py.typed` marker file exists in the package source directory |
| **Where** | `src/functualize/py.typed` |
| **Pass criteria** | File exists (may be empty — presence alone is sufficient per PEP 561) |
| **Severity** | BLOCKING |

---

## CI/CD

Items related to continuous integration and deployment workflows.

### CI-01: CI workflow exists

| Field | Value |
|-------|-------|
| **What to check** | A CI workflow file exists |
| **Where** | `.github/workflows/ci.yml` |
| **Pass criteria** | File exists and is valid YAML |
| **Severity** | BLOCKING |

### CI-02: CI has linting step

| Field | Value |
|-------|-------|
| **What to check** | The CI workflow includes a linting step |
| **Where** | `.github/workflows/ci.yml` → `jobs.*.steps` |
| **Pass criteria** | At least one step references a linting tool (e.g., `ruff check`, `flake8`, `pylint`) in its `run` command or uses a known linting action |
| **Severity** | BLOCKING |

### CI-03: CI has type-checking step

| Field | Value |
|-------|-------|
| **What to check** | The CI workflow includes a type-checking step |
| **Where** | `.github/workflows/ci.yml` → `jobs.*.steps` |
| **Pass criteria** | At least one step references a type checker (e.g., `mypy`, `pyright`, `pytype`) in its `run` command or uses a known type-checking action |
| **Severity** | BLOCKING |

### CI-04: CI has test-execution step

| Field | Value |
|-------|-------|
| **What to check** | The CI workflow includes a test-execution step |
| **Where** | `.github/workflows/ci.yml` → `jobs.*.steps` |
| **Pass criteria** | At least one step references a test runner (e.g., `pytest`, `unittest`, `tox`) in its `run` command |
| **Severity** | BLOCKING |

### CI-05: Release workflow uses Trusted Publishing (OIDC)

| Field | Value |
|-------|-------|
| **What to check** | The release workflow uses PyPI Trusted Publishing via OIDC |
| **Where** | `.github/workflows/release.yml` → `permissions` and `jobs.*.steps` |
| **Pass criteria** | The workflow (or the relevant job) declares `id-token: write` in its `permissions` block AND uses `pypa/gh-action-pypi-publish` in at least one step |
| **Severity** | BLOCKING |

---

## Community Files

Items related to standard OSS community and documentation files.

### CF-01: LICENSE file

| Field | Value |
|-------|-------|
| **What to check** | A LICENSE file exists at the project root with content |
| **Where** | `LICENSE` (also accept `LICENSE.md`, `LICENSE.txt`) |
| **Pass criteria** | File exists and contains at least 1 non-whitespace character |
| **Severity** | BLOCKING |

### CF-02: README.md file

| Field | Value |
|-------|-------|
| **What to check** | A README file exists at the project root with content |
| **Where** | `README.md` (also accept `README.rst`, `README`) |
| **Pass criteria** | File exists and contains at least 1 non-whitespace character |
| **Severity** | BLOCKING |

### CF-03: CONTRIBUTING.md file

| Field | Value |
|-------|-------|
| **What to check** | A contributing guide exists |
| **Where** | `CONTRIBUTING.md` |
| **Pass criteria** | File exists and contains at least 1 non-whitespace character |
| **Severity** | WARNING |

### CF-04: SECURITY.md file

| Field | Value |
|-------|-------|
| **What to check** | A security policy exists |
| **Where** | `SECURITY.md` |
| **Pass criteria** | File exists and contains at least 1 non-whitespace character |
| **Severity** | WARNING |

### CF-05: CODE_OF_CONDUCT.md file

| Field | Value |
|-------|-------|
| **What to check** | A code of conduct exists |
| **Where** | `CODE_OF_CONDUCT.md` |
| **Pass criteria** | File exists and contains at least 1 non-whitespace character |
| **Severity** | WARNING |

### CF-06: CHANGELOG.md file

| Field | Value |
|-------|-------|
| **What to check** | A changelog exists with proper structure |
| **Where** | `CHANGELOG.md` |
| **Pass criteria** | File exists, contains at least 1 non-whitespace character, has an `## [Unreleased]` heading, and has at least one version heading matching `## [X.Y.Z] - YYYY-MM-DD` (or `## [X.Y.Z]`) |
| **Severity** | WARNING |

---

## GitHub Specifics

Items related to GitHub repository configuration and templates.

### GH-01: Issue templates

| Field | Value |
|-------|-------|
| **What to check** | Issue templates directory exists with at least one template |
| **Where** | `.github/ISSUE_TEMPLATE/` |
| **Pass criteria** | Directory exists and contains at least 1 file (`.md` or `.yml`) |
| **Severity** | INFO |

### GH-02: Pull request template

| Field | Value |
|-------|-------|
| **What to check** | A PR template exists |
| **Where** | `.github/PULL_REQUEST_TEMPLATE.md` (also accept `.github/pull_request_template.md`) |
| **Pass criteria** | File exists and contains at least 1 non-whitespace character |
| **Severity** | INFO |

---

## Quick Reference: Severity Summary

| ID | Item | Severity |
|----|------|----------|
| PM-01 | `pyproject.toml` exists | BLOCKING |
| PM-02 | Development Status classifier | WARNING |
| PM-03 | No legacy License classifier | BLOCKING |
| PM-04 | Python version classifier | WARNING |
| PM-05 | Typing classifier | WARNING |
| PM-06 | Project URLs | INFO |
| PM-07 | License field | WARNING |
| TS-01 | PEP 561 `py.typed` marker | BLOCKING |
| CI-01 | CI workflow exists | BLOCKING |
| CI-02 | CI linting step | BLOCKING |
| CI-03 | CI type-checking step | BLOCKING |
| CI-04 | CI test-execution step | BLOCKING |
| CI-05 | Trusted Publishing (OIDC) | BLOCKING |
| CF-01 | LICENSE file | BLOCKING |
| CF-02 | README.md file | BLOCKING |
| CF-03 | CONTRIBUTING.md | WARNING |
| CF-04 | SECURITY.md | WARNING |
| CF-05 | CODE_OF_CONDUCT.md | WARNING |
| CF-06 | CHANGELOG.md | WARNING |
| GH-01 | Issue templates | INFO |
| GH-02 | PR template | INFO |
