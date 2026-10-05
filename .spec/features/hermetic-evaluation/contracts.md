# hermetic-evaluation — contracts

Declared surfaces of the instrument only. **No public product surface changes**:
`functualize.*` and every plugin are consumed, not modified (spec B-27). Python
3.11, `from __future__ import annotations`. The package is
`tests/hermetic_eval/` (D-1); it imports public `functualize` modules only
(AC-15).

| surface | kind | contract |
|---|---|---|
| `corpus/v1/scenarios.jsonl` | data file | C-1 |
| `corpus/v1/corpus.lock.json` | data file | C-2 |
| `comparators.py` | three `DecisionProvider`s + identities | C-3, C-4, C-5 |
| `python -m tests.hermetic_eval.replay` | command | C-6 |
| run directory, `cells.jsonl` | data files | C-7 (row shape in `schema.md`) |
| `python -m tests.hermetic_eval.report` | command | C-8 |
| `boundary.json` | data file | C-9 |

## C-1 — a scenario line

One JSON object per line, UTF-8, `\n`-terminated, keys in this order, no other
keys:

```json
{"id": "s01", "state": "What are your opening hours on Sunday?", "expected": "deterministic", "stratum": "clear", "rationale": "A fixed lookup answers it (rubric §1)."}
```

| key | type | rule |
|---|---|---|
| `id` | str | `s01`…`s40`, unique, in file order |
| `state` | str | 1–600 characters, no leading/trailing whitespace |
| `expected` | str | one of `deterministic`, `cheap_model`, `frontier_agent`, `human_review` |
| `stratum` | str | `clear` or `borderline` |
| `rationale` | str | one sentence citing a `LABELING.md` clause (`§1`…`§6`) |

The corpus digest is `sha256` of the file's **bytes**, lower-case hex.

## C-2 — the lock

```json
{
  "version": "v1",
  "scenarios_sha256": "<64 hex>",
  "count": 40,
  "per_route": {"deterministic": 10, "cheap_model": 10, "frontier_agent": 10, "human_review": 10},
  "per_stratum": {"clear": 24, "borderline": 16},
  "seed": 20261004,
  "repeats": 5,
  "time_box_hours": 72,
  "comparators": {
    "hermetic": "<64 hex: sha256 of the canonical identity JSON>",
    "frontier": "<64 hex>",
    "deterministic": "<64 hex>"
  },
  "boundary": {"min_support": 10, "min_distinct_scenarios": 4, "max_accuracy_gap": 0.05, "min_coverage": 0.25, "min_availability": 0.90, "declared_accept_at": 0.70, "declared_min_margin": 0.10},
  "frozen_at": "2026-10-0XT00:00:00Z"
}
```

Canonical identity JSON = `json.dumps(identity, sort_keys=True,
separators=(",", ":"))`. The lock carries no tracker key, no person's name and
no machine identity.

## C-3 — the frontier comparator (Codex, D-2)

```python
class FrontierRouter:  # satisfies functualize.plugin.DecisionProvider
    name: str = "frontier"
    def __init__(self, *, cwd: str, model: str = "gpt-6-astra", effort: str = "medium",
                 timeout_seconds: float = 180.0,
                 run: Callable[[list[str], str, float], Completed] | None = None,
                 now: Callable[[], datetime] | None = None) -> None: ...  # now: local-zone clock for retry_after
    def choose(self, request: ChoiceRequest) -> DecisionResult[str]: ...
    def identity(self) -> dict[str, object]: ...
    calls: list[FrontierCall]  # one per choose(), for the ledger's frontier block (schema.md S-2)
```

`Completed` is `(returncode: int, stdout: str, stderr: str)`; the default
runner is `subprocess.run(argv, cwd=cwd, stdin=subprocess.DEVNULL,
capture_output=True, text=True, timeout=timeout)` — the **only** `subprocess`
use in the package. Constructing a `FrontierRouter` spawns nothing.

Paths, all inside the run directory: `cwd` = `<run-dir>/frontier-cwd` (empty),
`SCHEMA_PATH` = `<run-dir>/frontier-schema.json` (written once, on the first
`choose`), `LAST_PATH` = `<run-dir>/frontier-last.json` (overwritten by each
call).

**argv**, exactly, in this order:

```
codex exec --json --output-schema SCHEMA_PATH -o LAST_PATH
  -m gpt-6-astra -c model_reasoning_effort="medium"
  --ephemeral --skip-git-repo-check --ignore-user-config --ignore-rules
  -s read-only -C CWD PROMPT
```

(`-c` takes the TOML string `model_reasoning_effort="medium"` as one argv
element.) Codex has no system-prompt flag, so the routing instruction is the
first paragraph of **PROMPT**, rendered from the `ChoiceRequest` only, options
in declared order:

```
You route requests. Answer only with the structured output: the option you choose and a probability for every option. Do not run commands.

{instructions}

Options:
- {option}: {meaning}
  (one line per option)

Text to route:
<<<
{state}
>>>

Choose one option and give a probability for every option; the probabilities sum to 1.
```

**SCHEMA** — built from `request.options`, written to `SCHEMA_PATH`:

```json
{"type": "object",
 "properties": {
   "choice": {"type": "string", "enum": ["<option>", "..."]},
   "probabilities": {"type": "object",
     "properties": {"<option>": {"type": "number"}, "...": {}},
     "required": ["<option>", "..."], "additionalProperties": false}},
 "required": ["choice", "probabilities"], "additionalProperties": false}
```

**What is measured (F-14).** The refusal path is measured: on a spent usage
window, stdout is JSONL carrying
`{"type":"error","message":"You've hit your usage limit. … try again at 11:22 PM."}`
and `{"type":"turn.failed","error":{"message": <same>}}`, exit 1. The success
path was measured on 2026-10-04 with `codex-cli 0.156.1`: the stream ends in
`{"type":"turn.completed","usage":{…}}` whose keys are `input_tokens`,
`cached_input_tokens`, `cache_write_input_tokens`, `output_tokens` and
`reasoning_output_tokens`; the schema-shaped answer is written to `LAST_PATH`
and also appears in the stream as `item.completed.item.text`; **no event names
the answering model**, so `FrontierCall.model` is `null` for this CLI. That
call's stdout and `LAST_PATH` are the fixtures
`tests/hermetic_eval/fixtures/codex_success.jsonl` and
`codex_success_last.json`.

**Mapping a call:**

| condition | outcome |
|---|---|
| timeout | `DecisionUnavailableError(kind=UNREACHABLE, provider="frontier", detail="timeout after {t}s")` |
| a `turn.failed`/`error` message containing `usage limit` | `kind=RATE_LIMITED`, `status=None`, `retry_after` = seconds from now until the next occurrence of the `try again at <h:mm AM/PM>` time in the host's local zone (`None` if absent or unparseable), `detail` = the message |
| any other `turn.failed`/`error`, or `returncode != 0` | `kind=REFUSED`, `status=None`, `detail` = first 300 chars of the message or stderr |
| `LAST_PATH` missing or not JSON, `choice` not an option, a probability outside `[0, 1]` | `kind=MALFORMED`, `status=None` |
| the stream names an answering model ≠ the configured one | returns normally; `FrontierCall.model_mismatch` is true — the replay records `invalid_model` and stops (spec B-7) |
| otherwise | `DecisionResult(value=choice, provider="frontier", model=<the named model, else the configured one>, distribution=probabilities, confidence=None, provenance=DecisionProvenance(requested_model=<configured>, latency_seconds=<monotonic around the call>, input_tokens=usage.input_tokens, output_tokens=usage.output_tokens))` |

`identity()` returns `{"comparator": "frontier", "cli": "codex", "model",
"effort", "argv": <argv with SCHEMA_PATH/LAST_PATH/CWD/PROMPT as
placeholders>, "prompt_template_sha256", "schema_builder": "v1"}` — no CLI
version (recorded per cell instead, spec B-7).

## C-4 — the hermetic comparator

```python
def hermetic() -> DecisionProvider: ...   # JevDecisionProvider(JevConfig(model="jev-1.13-free",
                                          #   endpoint="https://opencode.ai/zen/v1/systemone"))
def hermetic_identity() -> dict[str, object]:
    # {"comparator": "hermetic", "provider": "jev", "model": "jev-1.13-free",
    #  "endpoint": "https://opencode.ai/zen/v1/systemone",
    #  "plugin": "functualize-decision-jev", "plugin_version": importlib.metadata.version(...)}
```

`functualize_decision_jev` is imported inside `hermetic()` only, so importing
`comparators` never requires the plugin. The credential is the plugin's own:
`OPENCODE_API_KEY`, read at call time. A missing key is the plugin's
`not_configured` failure — recorded as data like any other (spec B-8).

## C-5 — the deterministic comparator

```python
RULES: tuple[tuple[str, str], ...]  # (route, regex) in priority order, re.IGNORECASE
class DeterministicBaseline:  # satisfies DecisionProvider
    name: str = "deterministic"
    def choose(self, request: ChoiceRequest) -> DecisionResult[str]: ...
    def identity(self) -> dict[str, object]:  # {"comparator": "deterministic", "rules_sha256": ...}
```

First matching rule → `DecisionResult(value=route, provider="deterministic",
model="rules-v1", distribution={route: 1.0, other: 0.0 ...}, confidence=None,
provenance=DecisionProvenance("rules-v1", latency_seconds=<monotonic>,
input_tokens=None, output_tokens=None))`. No match → `value="human_review"`,
every option `0.25`. Reads `request.state` only. `rules_sha256` = sha256 of
`json.dumps(RULES)`.

## C-6 — the replay command

```
uv run python -m tests.hermetic_eval.replay
    --corpus v1
    --comparator {hermetic,frontier,deterministic}
    [--run-dir PATH]            # default $XDG_STATE_HOME|~/.local/state /functualize-hermetic-eval/<run-id>
    [--budget-seconds 360]
    [--corpus-root PATH]        # default tests/hermetic_eval/corpus; a test seam

uv run python -m tests.hermetic_eval.replay --freeze --corpus v1 [--corpus-root PATH]
    # writes corpus/v1/corpus.lock.json (C-2) from the scenario file and the three
    # comparators' current identities; refuses (exit 2) if a lock already exists
```

`<run-id>` = `<comparator>-<UTC yyyymmddThhmmssZ>`; the path is printed on the
first line of output. Repeats and seed come from the lock, never from flags.

| exit | meaning |
|---|---|
| 0 | budget reached, run complete, or a rate-limit pause — the last line says which, and for a pause prints `resume after <UTC>` |
| 2 | refused before any write: `--freeze` over an existing lock; lock missing, scenario digest ≠ lock, comparator identity digest ≠ lock, or an existing run directory whose header differs (corpus, comparator, seed) |
| 3 | stopped: a frontier cell recorded `invalid_model` (spec B-7) |

After the 72-hour box closes, the next invocation appends one
`not_attempted` line per remaining cell and exits 0 with `run complete`.

## C-7 — the run directory

```
<run-dir>/
  run.json          # header, written once: run_id, comparator, identity, identity_sha256,
                    #   corpus version, scenarios_sha256, seed, repeats, repo_commit, started_at
  cells.jsonl       # append-only, one line per attempted cell (schema.md S-1)
  project/.functualize/   # scratch project the cells boot in
  frontier-cwd/     # empty cwd for the frontier comparator
```

## C-8 — the report command

```
uv run python -m tests.hermetic_eval.report
    --run-dir HERMETIC --run-dir FRONTIER --run-dir DETERMINISTIC
    --out DIR            # writes benchmark.md, finding.md, metrics.json, boundary.json
    [--check DIR]        # recompute and compare with DIR; exit 1 on any byte difference
```

| exit | meaning |
|---|---|
| 0 | written (or `--check` identical) |
| 1 | `--check` found a difference |
| 2 | the three runs disagree on corpus digest, or a comparator is missing or duplicated |
| 4 | conformance failure: the offline rule at the declared point disagrees with a recorded route (spec B-20) |

Output is deterministic: JSON with `sort_keys=True, indent=2`, floats rounded
to 4 decimals at print time only, rows sorted by comparator name then route in
`ROUTER` order, no wall-clock timestamp — the provenance block carries the
ledgers' SHA-256 and the runs' `started_at`, not the report's time.

`benchmark.md` holds, per comparator: availability, routed accuracy, macro-F1,
coverage, selective accuracy, ECE, Brier, escalation precision/recall,
false-continue, unsafe-continue, false-stop, latency p50/p95, cost per run
(dollars where priced, else *subscription, unpriced*), tokens per correct
route, flip count; then the two confusion matrices
and the threshold table at `min_margin = 0.10`.

## C-9 — `boundary.json`

```json
{
  "corpus": {"version": "v1", "sha256": "<hex>"},
  "declared": {"accept_at": 0.70, "min_margin": 0.10},
  "constants": {"min_support": 10, "min_distinct_scenarios": 4, "max_accuracy_gap": 0.05, "min_coverage": 0.25, "min_availability": 0.90},
  "routes": {
    "deterministic": {"status": "trusted", "accept_at": 0.80, "support": 23, "scenarios": 6, "accuracy": 0.9565, "frontier_accuracy": 0.96, "coverage": 0.46},
    "cheap_model":   {"status": "insufficient evidence", "support": 7},
    "frontier_agent":{"status": "escalate"},
    "human_review":  {"status": "escalate"}
  },
  "availability": 0.955,
  "unsafe_continue_at_declared": 0,
  "verdict": "adopt",
  "uncertainty": null
}
```

`status` ∈ `trusted` | `escalate` | `insufficient evidence`; `verdict` ∈
`adopt` | `continue research` | `reject`; `uncertainty` is a sentence when the
verdict is `continue research`, else `null`. (Values above are illustrative of
the shape only.)
