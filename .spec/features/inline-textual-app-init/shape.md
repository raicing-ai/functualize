# Inline Textual prompts render in the terminal

| Field | Value |
| --- | --- |
| Document type | Shape Intent |
| Status | Exploring |
| Authority | Proposed |
| Owner | Functualize maintainers |
| Product | Functualize |
| Last reviewed | 2026-11-28 |
| Carried by | MCH-288, A2 of MCH-298 |
| Depends on | None |
| Related | SD/3080295 v3, Template - Shape Intent |

## 1. The shape at a glance

In a real terminal, with `functualize-inline` installed:

```text
$ cd plugins/adapters/functualize-inline/examples/prompted_deploy
$ func deploy.py run
┌─ Deploy to production? ───────────────────┐
│ Destructive confirmation   [Cancel] [Yes] │
└────────────────────────────────────────────┘
```

The operator acts on a Textual widget in the terminal. After confirmation, a region-selection widget appears in the same terminal flow. Selecting `eu-west-1` completes the job with `Deploying to eu-west-1...` and `Deploy complete`. The sketch fixes the kind and sequence of interaction, not Textual's border pixels or key labels.

## 2. Problem

Today the same command attempts to create a Textual app and logs:

```text
InlinePlugin: Textual inline failed (App.__init__() got an unexpected keyword argument 'inline'), falling back to CLI
```

The user is then asked through plain CLI input rather than the promised widgets. All inline prompt intents share that failing app construction path.

## 3. Current reality

At `d58500f76ba65ba169451e3cb4af3820e271e266`, `plugins/adapters/functualize-inline/src/functualize_inline/apps.py:45` calls `super().__init__(inline=True, **kwargs)`. `plugin.py:155-161` constructs the app and calls `app.run()`; `plugin.py:179-184` catches an exception and falls back to CLI. `plugins/adapters/functualize-inline/pyproject.toml:21` declares `textual>=0.40.0`. The issue records the error above on Textual 8.2.7. The proposed behavior below is not yet verified.

| Before | After |
| --- | --- |
| A real-terminal prompt logs the constructor error and asks through CLI fallback. | A real-terminal prompt draws and accepts the corresponding inline Textual widget. |
| The dependency permits Textual 0.40.0 without evidence that it can run the widget path. | The declared minimum is the lowest Textual release actually demonstrated to pass the widget pilot and the published PTY scenario. |

## 4. Use cases

### UC-1: Operator deploys to a region

**Actor and goal:** An operator wants to answer the published deployment prompts in a terminal.

**Walkthrough:** Run the command in §1. Confirm in the destructive-confirmation widget, then select `eu-west-1` in the region widget. The terminal retains the surrounding command output; each widget completes before the next prompt appears.

**Outcome:** The job reports `Deploying to eu-west-1...` and `Deploy complete`, returns the selected region, and exits successfully.

### UC-2: Operator declines deployment

**Actor and goal:** An operator wants to stop a production deployment.

**Walkthrough:** Run the same command and choose Cancel in the destructive-confirmation widget. No region widget appears.

**Outcome:** The job reports `Deploy cancelled` and returns `cancelled`; no deployment action is taken.

### UC-3: CI checks the published surface

**Actor and goal:** CI needs to catch a regression in the interactive path.

**Walkthrough:** An app pilot starts a real widget without replacing the availability check or `input`. A PTY driver starts `func deploy.py run`, observes the destructive-confirmation widget, answers it, observes the region widget, and chooses a region.

**Outcome:** Both checks pass only when the widget path renders and accepts input. Their chosen Textual version establishes the declared dependency floor.

## 5. The shape, surface by surface

| Surface | Concrete shape |
| --- | --- |
| Authoring / library API | The existing `rc.prompts.confirm("Deploy to production?", destructive=True, default=False)` and `rc.prompts.choice("Which region?", ["us-east-1", "eu-west-1", "ap-southeast-1"], default="us-east-1")` in `deploy.py` remain the author's calls. |
| Command line | The full command and sequential widgets appear in §1; the cancel path appears in UC-2. The job keeps its existing success and cancellation output. |
| Configuration | No new user setting. The package dependency in `plugins/adapters/functualize-inline/pyproject.toml` is `textual>=<verified-minimum>`; the exact number is chosen from the passing minimum-version test, then the workspace lock is updated consistently. |
| Wire / HTTP / file formats | Not touched. |
| UI | The destructive-confirmation widget appears inline, accepts a choice, closes, and gives way to the region-selection widget. It does not take over the whole terminal or become a numbered CLI prompt sweep. |
| Errors and refusals | Declining the destructive confirmation yields `Deploy cancelled`. Off a usable interactive terminal, the existing CLI fallback remains; a Textual constructor incompatibility must not be treated as a successful widget path. Exact fallback message wording remains provisional. |
| Generated or observable artifacts | Terminal output and CI evidence: a widget pilot plus a PTY transcript of the published command. No new file format is added. |

## 6. Diagrams

```text
Structure
job author -> rc.prompts public surface -> PromptCollector port
                                          -> functualize-inline adapter
                                          -> Textual inline app -> terminal widget
core job execution does not import the terminal adapter
```

```text
Behavior
operator -> func deploy.py run -> destructive-confirmation widget
operator -> confirm            -> region-selection widget
operator -> eu-west-1          -> job log -> successful exit
operator -> cancel             -> job log "Deploy cancelled" -> no region prompt
```

The short-lived widget lifecycle is create, render, accept or cancel, then close. The next prompt begins only after the previous widget closes.

## 7. Binding, provisional and illustrative

| Item shown | Status | Meaning |
| --- | --- | --- |
| `func deploy.py run`, `rc.prompts.confirm`, `rc.prompts.choice`, `functualize-inline`, `textual` | Binding | Existing user-facing names and published scenario remain usable. |
| Inline Textual widgets in sequence, no full-screen takeover or CLI prompt sweep on the interactive path | Binding | Approval fixes the visible interaction. |
| `Deploying to eu-west-1...`, `Deploy complete`, `Deploy cancelled`, `cancelled` | Binding | Existing example output and cancellation result remain recognizable. |
| `textual>=<verified-minimum>` in the package declaration, with a matching lock and evidence from pilot plus PTY | Binding | The floor is a tested compatibility claim, not a guessed number. |
| Exact minimum release, fallback diagnostic wording, borders, button labels, key bindings, and test command names | Provisional | The spec and verification select these without changing the interaction above. |
| `eu-west-1` as operator choice | Illustrative | Other listed regions remain valid choices. |
| `d58500f76ba65ba169451e3cb4af3820e271e266`, source paths and line numbers | Illustrative evidence | They identify the measured starting point, not a required implementation site. |

## 8. Boundaries and non-goals

| Surface | Owner | Boundary |
| --- | --- | --- |
| `rc.prompts` declarations and job execution | Functualize core | Core uses the collector port; it does not depend on Textual. |
| Widget rendering, terminal input, dependency floor | `functualize-inline` | The adapter owns Textual-specific behavior and packaging. |

**In scope:** restore a real inline widget for the published interactive example, prove one real widget in an app pilot and the full example on a PTY, and raise the `textual` minimum to a version those checks actually pass.

**Out of scope:** the remaining plugin test standard rows (K-T2, K-T3, K-T5, K-T6, S1/S3 and CI legs), changes to other plugins or core prompt APIs, and a new prompt design. Those rows remain in the post-release plugin-standard work on MCH-288/MCH-298.

## 9. Candidate models

**Selected: repair the existing inline adapter contract.** `func deploy.py run` draws a destructive-confirmation widget, then a region widget. This retains the published example and the adapter boundary. The spec determines the internal call placement.

**Rejected: keep CLI fallback as the interactive surface.** The same command prints a plain question and reads `input()`. This leaves the advertised widget path unfulfilled.

**Rejected: replace inline widgets with a full-screen TUI.** The same command changes the entire terminal screen for each answer. This changes the product surface and exceeds A2.

## 10. Hypotheses and risks

- The constructor argument is the observed immediate fault; correcting it may expose a later widget or terminal compatibility fault. The pilot and PTY run decide this.
- A minimum-version pilot alone could pass while the published PTY flow fails. Both are needed before naming the floor.
- Terminal screenshots vary by width and theme; verification must assert widget presence and response, not the illustrative border pixels in §1.

## 11. Next falsifiable experiment

On an interactive PTY with the proposed minimum Textual release installed, run:

```text
$ cd plugins/adapters/functualize-inline/examples/prompted_deploy
$ func deploy.py run
```

Confirm the destructive widget, select `eu-west-1` in the region widget, and record the PTY transcript plus process exit code. Expected: both widgets render, `Deploy complete` appears, and exit is zero. Falsifier: the constructor warning recurs, the terminal presents only plain `input()` prompts, or the region widget cannot accept a choice. Run the app pilot at that same Textual release before publishing the floor.

## 12. Open questions

The exact minimum Textual version is open until the experiment runs:

```text
Candidate A: textual>=<lowest release passing pilot and PTY>  (recommended)
Candidate B: textual>=8.2.7 without testing that floor        (reject)
```

Candidate A gives package users a minimum backed by the published interaction. Candidate B could ship another broken floor. The widget interaction and source diagnosis proceed regardless of the number; the later spec records the tested version.

## 13. Outcome

Proposed for the MCH-288 reporter's review at this document's commit SHA. No approval, spec, implementation, or verification result is recorded here.
