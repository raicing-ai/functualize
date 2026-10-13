# skill-router — contracts

These are the declared surfaces of the instrument and of the `evals/` harness
option. **No public product surface changes.** `functualize.*`, every plugin,
`skills/**` and `tests/hermetic_eval/**` are consumed, not modified (spec B-29).
Python 3.11, `from __future__ import annotations`. The package
`tests/skill_router_eval/` imports public `functualize` modules only (AC-16).

| surface | kind | contract |
|---|---|---|
| `catalog.py`, the catalog declaration | function + JSON | C-1 |
| `corpus/v1/scenarios.jsonl` | data file | C-2 |
| `corpus/v1/corpus.lock.json` | data file | C-3 |
| `selection.py`, the selection workflow and result | workflow + function | C-4 |
| `comparators.py` | keyword table, native adapter, re-exports | C-5 |
| `python -m tests.skill_router_eval.replay` | command | C-6 |
| `python -m tests.skill_router_eval.select` | command, `selections.json` | C-7 |
| run directory, `cells.jsonl` | data files | C-8 |
| `python -m tests.skill_router_eval.report`, `verdict.json` | command + data | C-9 |
| `evals/` harness: `arm`, `skills=`, `append_system_prompt=`, `first_turn_input_tokens` | harness option | C-10 |
| `evals/suites/skill-router.yaml` | promptfoo suite | C-11 |

Consumed unchanged from Phase 3 (`tests/hermetic_eval/`): `comparators.identity_sha256`,
`comparators.hermetic`, `comparators.hermetic_identity`, `comparators.FrontierRouter`
(with `FrontierCall`), `corpus.corpus_sha256`, `corpus.ordered_cells`,
`metrics.accepts`, `metrics.agreement`, `metrics.variance`, `metrics.latency`,
`metrics.cost`.

## C-1 — the catalog declaration

```python
SKILLS: tuple[str, ...] = ("functualize", "functualize-app", "functualize-cli", "functualize-skill")
NONE = "none"
OPTIONS: tuple[str, ...] = (*SKILLS, NONE)
NONE_MEANING = "No functualize skill applies; answer without loading one."

class CatalogError(ValueError): ...

@dataclass(frozen=True)
class Entry:
    name: str
    description: str          # frontmatter `description`, whitespace collapsed to single spaces
    sha256: str               # over sorted (relative path, bytes) of every file in skills/<name>/
    skill_md_bytes: int       # len(SKILL.md bytes)
    total_bytes: int          # sum of every file's bytes in skills/<name>/

def derive_catalog(skills_root: Path) -> tuple[Entry, ...]: ...   # raises CatalogError unless dirs == SKILLS
def catalog_json(entries: Sequence[Entry]) -> dict[str, object]: ...
def catalog_sha256(entries: Sequence[Entry]) -> str: ...          # identity_sha256(catalog_json(entries))
def option_meanings(entries: Sequence[Entry]) -> dict[str, str]:  # OPTIONS order; none -> NONE_MEANING
```

Skill digest: `sha256` over, for each file in `sorted(p.relative_to(dir).as_posix())`,
`path.encode() + b"\0" + bytes + b"\0"`. `catalog_json` is:

```json
{"version": 1,
 "skills": [{"name": "functualize", "description": "...", "sha256": "<hex>", "skill_md_bytes": 0, "total_bytes": 0}, "..."],
 "none": "No functualize skill applies; answer without loading one."}
```

The frontmatter is read with `yaml.safe_load` on the block between the first
two `---` lines. No other field is read (ADR-006 §5 stays untouched).

## C-2 — a scenario line

One JSON object per line, UTF-8, keys in this order, no others:

```json
{"id": "k01", "state": "func: command not found after pip install, what now?", "expected": "functualize-cli", "stratum": "clear", "rationale": "Installing and locating the func tool (rubric §3).", "origin": "new"}
```

| key | rule |
|---|---|
| `id` | `k01`…`k40`, unique, in file order |
| `state` | 1–600 characters, no leading/trailing whitespace; never equal to a C-11 task prompt |
| `expected` | one of `OPTIONS` |
| `stratum` | `clear` or `borderline` |
| `rationale` | one sentence citing `LABELING.md` `§1`…`§7` |
| `origin` | `triggering:<n>` (1-based case index in `evals/suites/triggering.yaml`) or `new` |

## C-3 — the lock

```json
{
  "version": "v1",
  "scenarios_sha256": "<hex>",
  "count": 40,
  "per_option": {"functualize": 8, "functualize-app": 8, "functualize-cli": 8, "functualize-skill": 8, "none": 8},
  "per_stratum": {"clear": 25, "borderline": 15},
  "seed": 20261013,
  "repeats": 5,
  "time_box_hours": 72,
  "catalog": {"...": "catalog_json(...) as in C-1"},
  "catalog_sha256": "<hex>",
  "comparators": {"hermetic": "<hex>", "frontier": "<hex>", "deterministic": "<hex>", "native": "<hex>"},
  "declared": {"accept_at": 0.70, "min_margin": 0.10},
  "verdict": {"min_lead": 0.05, "max_unsafe_none": 0},
  "frozen_at": "2026-10-XXT00:00:00Z"
}
```

There is no tracker key, person or machine identity in it. Native identity:
`{"comparator": "native", "provider": "evals/providers/claude_router.py",
"model": "claude-sonnet-5", "max_turns": 3, "tools": ["Skill","Read","Glob","Grep"],
"provider_sha256": <sha256 of that file's bytes>}`.

## C-4 — the selection workflow and its result

```python
SELECT_INSTRUCTIONS = (
    "Choose the one functualize skill whose instructions this request needs "
    "before work starts, or none if no functualize skill applies."
)
ESCALATED = "escalated"

def select_decision(entries: Sequence[Entry]) -> ChoiceDecision:
    # ChoiceDecision(field="skill", instructions=SELECT_INSTRUCTIONS,
    #   options=option_meanings(entries), state=FromStep("intake"),
    #   accept_at=0.70, min_margin=0.10, fallback=None)

def build_selection(app: FunctualizeApp, text: str, entries: Sequence[Entry]) -> None:
    # registers workflow "select": intake -> Gate("select", awaits=SkillChoice, decide=...)
    # -> ConditionalEdge on answer["skill"] to one stub step per option -> END

@dataclass(frozen=True)
class Selection:
    outcome: str                   # an OPTIONS value, or ESCALATED
    decided_by: str | None         # "decision" or None (no fallback is declared)
    record: Mapping[str, Any]      # decision_record(...) verbatim

def select(text: str, provider: DecisionProvider, *, entries, project: Path, scope: str) -> Selection: ...
```

`outcome` is `record["route"]` when `decided_by == "decision"`, and `ESCALATED`
otherwise. `SkillChoice` is a pydantic model with one required field `skill:
Literal[...]` over `OPTIONS`, with no default (the gate refuses a default on a
decided field).

## C-5 — comparators

```python
KEYWORDS: tuple[tuple[str, str], ...]   # (option, regex), priority order, re.IGNORECASE; written from meanings only
class KeywordTable:                      # satisfies DecisionProvider
    name = "deterministic"
    def choose(self, request: ChoiceRequest) -> DecisionResult[str]: ...
    def identity(self) -> dict[str, object]:   # {"comparator": "deterministic", "keywords_sha256": ...}

class NativeRouter:                      # NOT a DecisionProvider
    name = "native"
    def __init__(self, *, call_api: Callable[[str, dict, dict], dict] | None = None,
                 model: str = "claude-sonnet-5") -> None: ...   # default: loaded by path from evals/providers/claude_router.py
    def select(self, state: str) -> NativeCell: ...   # NativeCell(selected: str | None, failed: str | None, cost_usd, latency_seconds)
    def identity(self) -> dict[str, object]: ...      # C-3 native identity
```

On a match, `KeywordTable` returns `DecisionResult(value=opt, provider="deterministic",
model="keywords-v1", distribution=one-hot, confidence=None, provenance=…)`. On no
match it returns `value="none"` with every option at `0.20`. `NativeRouter` maps
`selected` ∈ `SKILLS` to itself, `None` to `none`, any other `functualize*` name
to `failed="unknown_skill"`, and an `error` key to `failed=<message>`.
Constructing it spawns nothing.

## C-6 — the replay command

```
uv run python -m tests.skill_router_eval.replay
    --corpus v1 --comparator {hermetic,frontier,deterministic,native}
    [--run-dir PATH] [--budget-seconds 360] [--corpus-root PATH] [--skills-root PATH]

uv run python -m tests.skill_router_eval.replay --freeze --corpus v1 [--corpus-root PATH] [--skills-root PATH]
```

| exit | meaning |
|---|---|
| 0 | budget reached, run complete, or rate-limit pause (`resume after <UTC>`) |
| 2 | refused before any write: `--freeze` over an existing lock; lock missing; scenario, catalog or identity digest ≠ lock; `CatalogError`; a header mismatch in an existing run directory |
| 3 | frontier `invalid_model` |

`<run-id>` is `<comparator>-<UTC yyyymmddThhmmssZ>`. Repeats and seed come from
the lock only.

## C-7 — the `select` command and `selections.json`

```
uv run python -m tests.skill_router_eval.select --tasks evals/suites/skill-router.yaml --out PATH
    [--comparator hermetic] [--skills-root PATH]
```

It checks the catalog against the v1 lock (exit 2 on mismatch), runs each case's
`task` once through C-4, and writes:

```json
{"catalog_sha256": "<hex>", "comparator": "hermetic", "identity_sha256": "<hex>", "repo_commit": "<sha>",
 "cases": {"d1": {"outcome": "functualize", "expected": "functualize", "decided_by": "decision",
                  "latency_seconds": 0.0, "evidence": {"...": "decision-evidence/1"}}, "...": {}}}
```

`PATH` must lie outside the repository (exit 2 otherwise).

## C-8 — the run directory and a ledger row

```
<run-dir>/run.json  cells.jsonl  project/.functualize/  frontier-cwd/
```

A row has these keys, in this order: `cell repeat scenario expected stratum
comparator status route decided_by proposal distribution probability margin
confidence verdict failure latency_seconds input_tokens output_tokens frontier
native started_at`.

- `status` ∈ `routed | failed | invalid_model | not_attempted`.
- `route` ∈ `OPTIONS ∪ {"escalated"}`. The name is kept so that Phase 3's
  `agreement`/`variance` read it unchanged.
- `native` is `{"selected", "cost_usd"}` or `null`.

## C-9 — the report command and `verdict.json`

```
uv run python -m tests.skill_router_eval.report
    --run-dir H --run-dir F --run-dir D --run-dir N
    --selections selections.json --downstream results.json --out DIR [--check DIR]
```

| exit | meaning |
|---|---|
| 0 | written, or `--check` identical |
| 1 | `--check` difference |
| 2 | inputs disagree on corpus or catalog digest; a comparator missing or duplicated |
| 4 | conformance failure (spec B-17) |

```json
{"corpus": {"version": "v1", "sha256": "<hex>"}, "catalog_sha256": "<hex>",
 "declared": {"accept_at": 0.70, "min_margin": 0.10}, "constants": {"min_lead": 0.05, "max_unsafe_none": 0},
 "e2": {"hermetic_accuracy": 0.0, "deterministic_accuracy": 0.0, "lead": 0.0, "holds": false, "unsafe_none": 0},
 "e3": {"router_over_native_bytes": 0.0, "load_everything_over_native_bytes": 0.0,
        "first_turn_tokens": {"load-everything": 0.0, "native": 0.0, "router": 0.0}, "holds": false},
 "e4": {"success": {"load-everything": [0, 15], "native": [0, 15], "router": [0, 15]},
        "wilson95": {"native": [0.0, 0.0], "router": [0.0, 0.0]}, "holds": false},
 "verdict": "negative result", "failed_conditions": ["..."]}
```

`verdict` is one of `promote to Phase 5`, `negative result` or `continue
research`. The values above only illustrate the shape. Output is deterministic:
`sort_keys`, 4-decimal rounding at print time, and no wall-clock time.

## C-10 — the `evals/` harness option

```python
# _harness.py
def build_workspace(fixture: str | None, with_skills: bool, mode: str = "host",
                    *, skills: Sequence[str] | None = None) -> tuple[Path, Sandbox]: ...
    # skills=None keeps today's behaviour (all or none per with_skills);
    # skills=[...] copies exactly those skills/<name>/ dirs; [] copies none. Unknown name -> FileNotFoundError.
def run_claude(sandbox, prompt, *, model=None, max_turns=..., allowed_tools=None,
               timeout_s=..., append_system_prompt: str | None = None) -> AgentRun: ...
    # appends ["--append-system-prompt", text] when given
class AgentRun:
    first_turn_input_tokens: int | None = None   # first assistant event's usage: input + cache_creation_input + cache_read_input
    duration_s: float = 0.0
def skill_bodies(names: Sequence[str]) -> str: ...  # SKILL.md files joined, each under "## Skill: <name>"

# claude_agent.py — provider config `arm` (absent = today's behaviour, unchanged):
#   "load-everything" | "native" | "router"
# router reads JSON at env FZ_SKILL_ROUTER_SELECTIONS, key = test var `case`.
# output: the existing "arm" key (today "with-skills" | "baseline", claude_agent.py:119) carries the
# config arm when one is set, else today's value; output gains "first_turn_input_tokens",
# "duration_s" and "router_outcome" (router arm only).
```

Existing suites set no `arm`, so their behaviour and argv are unchanged
(AC-11).

## C-11 — `evals/suites/skill-router.yaml`

- Prompt: `'{{task}}'`. There are three providers, all `file://../providers/claude_agent.py`,
  labelled `load-everything`, `native` and `router`, each with `model:
  claude-sonnet-5`, `sandbox: docker`, `max_turns: 40` and the same worker
  timeout as `functualize.yaml`.
- Five tests, `vars.case` ∈ `d1`…`d5`. Each test's `vars` and `assert` equal its
  source case (spec B-19) field for field, plus `case` and `expect`.
- Run: `npx promptfoo eval -c suites/skill-router.yaml --no-cache --repeat 3
  -o <outside-repo>/results.json`, with `FZ_SKILL_ROUTER_SELECTIONS` set.
