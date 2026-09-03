# Shape Intent: A GitHub Action for functualize

**Status: specified, not yet implemented — and the first question is whether it should be.**
**Date: 2026-09-03** (opened while specifying standalone distribution; comparables surveyed
2026-09-03)
**Scope: one composite or JS action, plus its release wiring. No `src/functualize/` change.
Depends on [standalone-distribution](standalone-distribution.md) shipping binaries.**

Give a repository one line to get `func` onto a runner, so functualize can be used as a task
runner in CI by projects that are not Python projects.

---

## The honest starting question

**For a Python repository, an action buys almost nothing.** This already works today, needs
no action, and is one line:

```yaml
- uses: astral-sh/setup-uv@v6
- run: uv tool install "functualize[cli]"
```

So an action has to justify itself on cases that line does not serve:

| Case | Does the one-liner serve it? |
|---|---|
| A Python repo running jobs in CI | **yes** — no action needed |
| A **non-Python** repo using functualize as its task runner | no — installing Python and uv first is the cost the binary exists to remove |
| Pinning the version from `pyproject.toml` / `.functualize.toml` | no — the caller must parse it themselves |
| Caching the tool across runs | no |
| Verifying a checksum | no |

**The forcing case is the third audience the binary was built for**: a repository with no
Python that wants `func` as a task runner. That is the same user, in CI. If that audience is
real, the action is real; if it is not, this document should be closed and the README should
document the two-line uv recipe instead.

**B1 (below) is that question, and it gates everything else.**

## What the comparables do

Surveyed 2026-09-03.

| Tool | Action | Lives in | Shape |
|---|---|---|---|
| uv | `astral-sh/setup-uv` | **separate repo** | Rich: version resolution from config files, GHA cache, checksum, `python-version`, venv activation, problem matchers |
| Hatch | `pypa/hatch@install` | **the main repo** | Minimal: install and PATH |
| Task | `go-task/setup-task@v1` | separate repo | Middle: version + token |

Two viable homes, and the choice is not cosmetic:

- **In-repo** (`raicing-ai/functualize@install`, Hatch's shape) — the action versions with the
  tool and cannot drift from it. Its tag is the tool's tag, so `@v0.3.0` means the obvious
  thing. Harder to iterate on independently.
- **Separate repo** (`raicing-ai/setup-functualize`, the majority convention) — independent
  versioning, matches what users expect from the `setup-*` naming, but is a second repository
  to release and a second place for the install logic to live.

## Assertions

### 1. What exists to build on

| # | Assertion | Verdict |
|---|---|---|
| `EX.1` | Release artifacts are named by target triple, so an action can compute a filename from `runner.os` and `runner.arch` | **GAP, specified** — `standalone-distribution` `contracts.md` §8 |
| `EX.2` | Every release publishes a checksum file, so the action can verify what it downloads | **GAP, specified** — `AC24a` |
| `EX.3` | An `install.sh` / `install.ps1` already does platform and libc detection, so the action can delegate rather than reimplement | **GAP, specified** — tier 2, `AC24b`/`AC24c` |
| `EX.4` | The repo already uses `astral-sh/setup-uv` in release CI, so the pattern is familiar here | **PASS** — `.github/workflows/release.yml:87-88` |
| `EX.5` | Installing the binary is recorded in the install manifest like any other installation | **GAP** — follows from the registry design; a CI runner registers once and is discarded, which is harmless but means the record is never reused |

### 2. What the action must do

| # | Assertion | Verdict |
|---|---|---|
| `AC.1` | Installs `func` and puts it on `PATH`, so later steps just run `func …` | **GAP** |
| `AC.2` | Resolves a version from an input, defaulting to the latest release | **GAP** |
| `AC.3` | Verifies the downloaded artifact against the published checksum **by default**, not opt-in | **GAP** — uv exposes `checksum` as an input; defaulting to off would make the safe path the one nobody takes |
| `AC.4` | Works on `ubuntu-*`, `macos-*` and `windows-*` runners | **GAP, and it constrains the parent feature** — `PY.1` currently specifies linux and macOS only. **An action without Windows is an action that fails on a third of GitHub's runners** |
| `AC.5` | Caches the download across runs, keyed on version and platform | **GAP** |
| `AC.6` | Pins by SHA or major tag as GitHub recommends; the action does not fetch unpinned code at runtime | **GAP** |
| `AC.7` | Fails loudly when no artifact matches the runner, naming the triple it looked for | **GAP** — a silent fallback to "install from PyPI instead" would defeat the purpose and hide a gap in the release matrix |

### 3. What it must *not* do

| # | Assertion | Verdict |
|---|---|---|
| `NO.1` | It does not install Python, or require one. That is the entire point | **GAP (constraint)** |
| `NO.2` | It does not silently fall back to `pip`/`uv` when a binary is missing (`AC.7`) | **GAP (constraint)** |
| `NO.3` | It does not run `func` — installing and using are separate steps, so a caller controls their own workflow | **GAP (constraint)** |
| `NO.4` | It does not enable `func builtin self update` on the runner. A CI install is disposable; self-management belongs to a real installation | **GAP (constraint)** |

## Open decisions

| # | Question | Why it cannot be defaulted |
|---|---|---|
| **B1** | **Ship an action at all**, or document the two-line uv recipe in the README? | Rests entirely on whether the non-Python-repo audience is real. Everything else is downstream |
| **B2** | In-repo (`functualize@install`) or separate repo (`setup-functualize`)? | Hatch and uv chose differently and both are defensible — see the table above |
| **B3** | Composite action (shell, delegates to `install.sh`) or JS/TypeScript (uses `@actions/tool-cache`, cross-platform without shell differences)? | Composite is far less code and reuses the install script; JS gets caching and Windows handling that composite must hand-roll |
| **B4** | Does it install the **binary** or `functualize[cli]` **from PyPI** when Python is already present? | Two audiences, and serving both makes the action's behavior depend on the runner's state — which `AC.7` argues against |

**B1 first.** If the answer is "document the recipe", this closes with a README section and
costs nothing further.

## Sequencing

**This is blocked on `standalone-distribution` shipping binaries** — there is nothing to
install until then, and `AC.4` may push that feature's `PY.1` to add Windows.

Nothing in the parent feature depends on this. It can be dropped or deferred without
affecting anything already specified.

## Test tiers

Only meaningful if B1 resolves to "ship".

| # | Criterion | Tier |
|---|---|---|
| T1 | The action installs and `func builtin version` runs, on `ubuntu-latest`, `macos-latest` and `windows-latest` | CI matrix, in this repo |
| T2 | A corrupted artifact fails the step; it does not install (`AC.3`) | CI, with a deliberately wrong checksum |
| T3 | An unsupported runner fails naming the triple it looked for (`AC.7`) | CI |
| T4 | A second run in the same workflow hits the cache (`AC.5`) | CI |
| T5 | The action never invokes a Python interpreter (`NO.1`) | CI, on a runner image with Python removed or masked |

> T5 is the one that actually proves the premise. Everything else tests an installer; T5 tests
> that this installer is the one worth having.
