# hermetic-evaluation — Tasks

Authored 2026-10-04 against `e8e3b867` (`origin/master`). Twelve tasks in ten
waves. Every `now:` below was produced by running its command on this branch at
authoring time.

**Execute is authorised (maintainer, 2026-10-04).** `spec.md` is confirmed and
D-1…D-7, S-1 and S-4 are answered — recorded below. Two human gates remain
inside the graph: the maintainer approves the drafted corpus between T6 and
T7, and T8 runs only on the maintainer's Codex and Jev logins. A changed answer
sends `spec.md`/`plan.md` back for revision before the affected wave starts.

**The implementation lands on this branch, in this pull request.** The spec is
created, executed and completed within the same PR and removed before merging
(T12). Never open a second PR, and never merge.

**The Execute phase reads only this file from the feature directory.** Each
task restates the behaviour, the exact files, the commands and the observable
result that closes it. Ids `B-n`/`AC-n` are `spec.md`'s, `C-n` are
`contracts.md`'s, `S-n` are `schema.md`'s; you do not need to open them.

## How to read a gate

A fenced `bash` block holding one **count** (`rg -c …`, `… | wc -l`, `wc -l <
file`), followed on the next line by `now:` (measured at authoring) and
`after:` (what the task must produce). `tests/spec/test_task_gates_still_hold.py`
re-runs every gate of every `[x]` task against `HEAD` for the life of the
branch, so each gate counts something later tasks never remove. `invariant`
marks a count that must not change. **Comments and docstrings in a counted file
count too** — do not write a counted pattern in prose inside that file. Run
every command from the repository root.

## Standing rules for every task

- Worktree `/home/ubuntu/orca/workspaces/functualize/sdd-hermetic-evaluation`,
  branch `sdd/hermetic-evaluation`. If `.venv` is missing or stale:
  `uv sync --frozen --all-extras --all-packages`.
- Checks, from the repository root, output redirected:
  `uv run ruff check --fix src/ tests/ plugins/ examples/ > /tmp/functualize-ruff.log 2>&1`,
  `uv run ruff format src/ tests/ plugins/ examples/ > /tmp/functualize-format.log 2>&1`,
  `uv run mypy src/ > /tmp/functualize-mypy.log 2>&1`,
  `uv run lint-imports > /tmp/functualize-lint-imports.log 2>&1`, and the
  task's own pytest command (at most two pytest invocations per verification;
  never pipe pytest through `head`/`tail`). `mypy src/` does not cover
  `tests/`; still annotate every function fully — `ruff` enforces the style.
- One commit per task that changes files, conventional subject, single scope
  token `test` or `docs`, ≤72 chars, lowercase, imperative. **No tracker key,
  issue URL, agent, model or run identity in any commit message, and no
  `Co-authored-by:` naming an agent.**
- **No file under `src/` or `plugins/` changes in this feature** (B-27). If a
  task seems to need one, stop and report — the scope is wrong.
- `tests/hermetic_eval/` imports public `functualize` modules only
  (`functualize.app`, `functualize.app.utils`, `functualize.plugin`,
  `functualize.types`, `functualize.workflow`) — never `functualize._…`.
- No offline test makes a network request, spawns a process or sleeps.
  `subprocess` is imported by `comparators.py` only. The live replay (T8) is a
  command, never a pytest run.
- Reachability: every function a task adds is called by the command it serves
  (`replay` or `report`) by the end of T5/T4 respectively; the commit body of
  T5 and T9 names that call path.
- Wave ordering is binding: never start wave N+1 while wave N has an unchecked
  task.

## Decisions recorded (maintainer, 2026-10-04)

- spec confirmed: yes.
- D-1 (location): `tests/hermetic_eval/` — the paths below stand.
- D-2 (frontier binding): **Codex**, `gpt-6-astra`, effort `medium`, through
  `codex exec` on the maintainer's Codex login (T3). Cost is tokens, not
  dollars.
- D-3 (frontier distribution): verbalized probabilities, one structured call.
- D-4 (labels): the implementer drafts (T6); the maintainer approves before T7.
- D-5 (constants): as written in T1's `BOUNDARY`, `SEED`, `REPEATS`,
  `TIME_BOX_HOURS`.
- D-6 (publication): outside the repository and on the tracker, **plus** one
  Confluence page in space `SD` under page `5144577` (T9).
- D-7 (monetary cost): instrument only; no product change.
- S-1 (offline rule copy), S-4 (CLI output contract): accepted.

## Wave 0 — foundation

### [x] T1 — the corpus loader, the lock, the cell order and the labelling rubric

*Files (all new):* `tests/hermetic_eval/__init__.py`,
`tests/hermetic_eval/corpus.py`, `tests/hermetic_eval/corpus/v1/LABELING.md`,
`tests/hermetic_eval/test_corpus.py`

Behaviour (B-1…B-5, B-10; C-1, C-2):

1. `tests/hermetic_eval/__init__.py` — a module docstring only, stating the
   instrument's rules: it measures the hermetic router over a frozen corpus;
   nothing in the product imports it; it imports public `functualize` modules
   only; offline tests never touch the network or spawn a process; live runs
   are the `replay` command, writing outside the repository; measured numbers
   are not committed. (`tests/__init__.py` already exists, so
   `python -m tests.hermetic_eval.<module>` resolves.)
2. `tests/hermetic_eval/corpus.py`:
   - `ROUTES: tuple[str, ...] = ("deterministic", "cheap_model", "frontier_agent", "human_review")`
   - `SEED = 20261004`, `REPEATS = 5`, `TIME_BOX_HOURS = 72`,
     `BOUNDARY: Mapping[str, float]` =
     `{"min_support": 10, "min_distinct_scenarios": 4, "max_accuracy_gap": 0.05, "min_coverage": 0.25, "min_availability": 0.90, "declared_accept_at": 0.70, "declared_min_margin": 0.10}`
     (a `MappingProxyType`, so it is not mutable module state).
   - `class CorpusError(ValueError)`.
   - `@dataclass(frozen=True) class Scenario` — `id: str`, `state: str`,
     `expected: str`, `stratum: str`, `rationale: str`.
   - `@dataclass(frozen=True) class Lock` — the C-2 fields: `version`,
     `scenarios_sha256`, `count`, `per_route`, `per_stratum`, `seed`,
     `repeats`, `time_box_hours`, `comparators` (name → 64-hex), `boundary`,
     `frozen_at`.
   - `def load_corpus(path: Path) -> tuple[Scenario, ...]` — reads JSON Lines;
     each line must have exactly the keys `id, state, expected, stratum,
     rationale` (in that order); `state` 1–600 chars with no leading/trailing
     whitespace; `expected` in `ROUTES`; `stratum` in `{"clear", "borderline"}`;
     `rationale` non-empty; ids unique. Any violation raises `CorpusError`
     whose message starts `line <n>:`.
   - `def corpus_sha256(path: Path) -> str` — `hashlib.sha256(path.read_bytes()).hexdigest()`.
   - `def check_v1_shape(scenarios: Sequence[Scenario]) -> None` — 40
     scenarios, ids `s01`…`s40` in order, 10 per route, and per route 6
     `clear` + 4 `borderline`; else `CorpusError` naming the first violated
     count.
   - `def write_lock(version_dir: Path, identities: Mapping[str, str], *, frozen_at: str) -> Lock`
     — refuses with `CorpusError` if `version_dir / "corpus.lock.json"`
     exists; otherwise loads `version_dir / "scenarios.jsonl"`, builds the C-2
     object (counts derived from the file, `seed`/`repeats`/`time_box_hours`/
     `boundary` from the constants above, `comparators` = `identities`) and
     writes it with `json.dumps(..., indent=2, sort_keys=True) + "\n"`.
   - `def check_lock(version_dir: Path, identities: Mapping[str, str]) -> Lock`
     — `CorpusError` when the lock file is missing, `frozen_at` is empty,
     `scenarios_sha256` ≠ `corpus_sha256(scenarios.jsonl)`, `count` ≠ the
     loaded scenario count, or any `identities[name]` ≠ `lock.comparators[name]`
     (message names the comparator). Returns the `Lock`.
   - `def ordered_cells(ids: Sequence[str], *, seed: int, repeats: int) -> list[tuple[int, str]]`
     — `[(r, sid) for r in range(1, repeats + 1) for sid in random.Random(seed + r).sample(list(ids), k=len(ids))]`.
3. `tests/hermetic_eval/corpus/v1/LABELING.md` — the rubric, exactly six
   second-level headings `## §1 deterministic` … `## §6 …`:
   - `## §1 deterministic` — "a fixed rule or lookup answers it; no model needed"
   - `## §2 cheap_model` — "a short, low-risk text task a small model can do"
   - `## §3 frontier_agent` — "multi-step reasoning or tool use is required"
   - `## §4 human_review` — "risky, ambiguous, or needs a person's judgement"
   - `## §5 risk overrides` — any risk of harm, money movement (refunds,
     chargebacks, payments), a legal matter, or account security ⇒
     `human_review`, whatever else the request asks.
   - `## §6 lookups stay lookups` — a question a fixed rule or lookup answers
     is `deterministic` even when phrased loosely or politely.
   Then a short section *How labels are assigned*: each scenario's label is
   the clause that decides it (§5 and §6 override §1–§4); `borderline` means
   two clauses plausibly apply and the label is decided by §5/§6 or the nearer
   clause, which the `rationale` names; labels never consult any comparator's
   output; the maintainer approves the corpus before it is frozen; after the
   freeze, any change is a new version directory and a full re-run.
4. `tests/hermetic_eval/test_corpus.py` — offline, `tmp_path` fixtures only
   (the real `v1` corpus does not exist until T6): a valid 3-line file loads;
   each malformed variant (extra key, missing key, `expected="other"`,
   `stratum="hard"`, 601-char state, duplicate id) raises `CorpusError`
   starting `line `; `corpus_sha256` equals `hashlib.sha256` of the bytes;
   `check_v1_shape` rejects 39 scenarios and a 7/3 strata split; `write_lock`
   then `check_lock` round-trips; `check_lock` raises on a missing lock, on one
   changed byte of the scenario file, on an identity mismatch and on an empty
   `frozen_at`; `write_lock` refuses an existing lock; `ordered_cells` over 3
   ids, 2 repeats is 6 pairs, repeats outermost, each repeat a permutation, and
   identical across two calls.

Gates:

```bash
rg -c "^def (load_corpus|corpus_sha256|check_v1_shape|write_lock|check_lock|ordered_cells)\(" tests/hermetic_eval/corpus.py
```
now: `0` · after: `6`

```bash
rg -c "^class (CorpusError|Scenario|Lock)\b" tests/hermetic_eval/corpus.py
```
now: `0` · after: `3`

```bash
rg -c "^## §[1-6] " tests/hermetic_eval/corpus/v1/LABELING.md
```
now: `0` · after: `6`

Closes when: `uv run pytest tests/hermetic_eval/test_corpus.py -q > /tmp/functualize-t1.log 2>&1`
passes, the three gates read their `after:` values, and the standing checks are
clean. Commit: `test(hermetic): add the evaluation corpus loader and lock`.

### [x] T2 — the descriptive metrics

*Files (all new):* `tests/hermetic_eval/metrics.py`,
`tests/hermetic_eval/test_metrics.py`

A ledger row is a `dict[str, Any]` with the S-1 keys (listed in step 1). Every
function is pure — no I/O, no clock — and imports nothing from `functualize`.

Behaviour (B-15…B-19; S-3):

1. Module docstring lists the S-1 row keys it reads: `scenario`, `repeat`,
   `expected`, `stratum`, `status` (`routed`/`failed`/`invalid_model`/
   `not_attempted`), `route`, `decided_by`, `proposal`, `distribution`,
   `probability`, `margin`, `confidence`, `latency_seconds`, `frontier`
   (`{"cost_usd": float, …}` or `None`). `ROUTES` is imported from
   `tests.hermetic_eval.corpus`.
2. Functions (names exact):
   - `routed_confusion(rows) -> dict[str, dict[str, int]]` — expected → route →
     count, all four routes on both axes (zeros included); rows with
     `status == "not_attempted"` are excluded.
   - `proposed_confusion(rows)` — expected → proposal-or-`"failed"` → count
     (`failed` when `proposal is None`), same exclusion.
   - `accuracy_summary(rows) -> dict` — `cells` (all rows), `availability`
     (rows with `status == "routed"` ÷ `cells`), `routed_accuracy` (rows with
     `route == expected` ÷ `cells`; a not-attempted row counts as wrong),
     `per_route` (route → `{precision, recall, support}` over routed outcomes;
     precision is `0.0` when the route was never taken), `macro_f1` (mean of
     per-route F1, F1 `0.0` when precision + recall is 0).
   - `agreement(rows_a, rows_b) -> dict` — over `(scenario, repeat)` keys in
     both, excluding not-attempted: `rate` and Cohen's `kappa`
     (`(p_o − p_e) / (1 − p_e)`, `p_e` from the two marginals; `kappa = 1.0`
     when `p_e == 1`).
   - `calibration(rows, key="probability") -> dict` — over rows whose `key`
     value is not `None`: ten bins `[0.0,0.1) … [0.8,0.9) [0.9,1.0]` (1.0 in the
     last), each `{lo, hi, n, mean_p, accuracy}` (`accuracy` = share with
     `proposal == expected`; empty bins carry `n=0`, `mean_p=None`,
     `accuracy=None`); `ece` = Σ n·|accuracy − mean_p| ÷ Σ n; `brier` = mean
     over rows with a `distribution` of Σ over the four routes of
     `(p_route − [route == expected])²` (a missing route is `0.0`) — `None`
     when `key != "probability"`.
   - `escalation(rows) -> dict` — over non-not-attempted rows: `coverage`
     (rows with `decided_by == "decision"` and `route != "human_review"` ÷
     rows), `selective_accuracy` (accuracy of those rows; `None` if none),
     escalated = `route == "human_review"`, needed = `expected ==
     "human_review"` or `proposal != expected`; `precision`, `recall`
     (`None` on an empty denominator); `by_cause` = `{"fallback": n, "proposal": n}`
     over escalated rows by `decided_by == "fallback"` vs `"decision"`.
   - `latency(rows) -> dict` — `p50`, `p95` (nearest rank:
     `sorted[ceil(q·n) − 1]`), `max` over non-`None` `latency_seconds`.
   - `cost(rows) -> dict` — `input_tokens`/`output_tokens` = sums of the rows'
     `input_tokens`/`output_tokens` (`None` counts 0);
     `cached_input_tokens`/`reasoning_output_tokens` = sums over
     `frontier["usage"]` (0 when no row has a `frontier` block);
     `tokens_per_correct_route` = (input + output) ÷ rows with `route ==
     expected` (`None` when zero); `usd_total` = `0.0` when no row has a
     `frontier` block (the baseline costs nothing and the hermetic free tier
     bills nothing), else `None` — the Codex frontier is a subscription that
     reports no price, and none is invented (the report prints *subscription,
     unpriced*).
   - `variance(rows) -> dict` — per scenario over its non-not-attempted rows:
     modal agreement (count of the most common route ÷ rows), flipped (more
     than one distinct route), `statistics.pstdev` of non-`None`
     `probability` (0.0 with fewer than 2); returns `mean_modal_agreement`,
     `flips`, `mean_probability_sd`, `flipped` (sorted scenario ids).
3. `tests/hermetic_eval/test_metrics.py` — hand-computed fixtures, compared
   with `pytest.approx(abs=1e-4)`:
   - **Fixture A** (one repeat, six rows):
     s1 exp `deterministic`, routed, decided `decision`, proposal
     `deterministic`, distribution `{deterministic: .9, cheap_model: .1}`, p .9,
     margin .8, route `deterministic`, latency 1.0;
     s2 exp `cheap_model`, proposal `cheap_model`, `{cheap_model: .75, deterministic: .25}`,
     p .75, m .5, route `cheap_model`, latency 2.0;
     s3 exp `frontier_agent`, proposal `cheap_model`, `{cheap_model: .8, frontier_agent: .2}`,
     p .8, m .6, route `cheap_model`, latency 3.0;
     s4 exp `human_review`, proposal `deterministic`, `{deterministic: .72, human_review: .28}`,
     p .72, m .44, route `deterministic`, latency 4.0;
     s5 exp `deterministic`, proposal `deterministic`, `{deterministic: .6, cheap_model: .4}`,
     p .6, m .2, decided `fallback`, route `human_review`, latency 5.0;
     s6 exp `human_review`, status `failed`, decided `fallback`, route
     `human_review`, proposal/distribution/probability/margin `None`,
     latency 0.1.
     Expected: `routed_accuracy` 0.5; `availability` 0.8333; `macro_f1`
     0.4167; `per_route["cheap_model"]` precision 0.5 recall 1.0;
     `routed_confusion["human_review"]` = `{deterministic: 1, human_review: 1,
     cheap_model: 0, frontier_agent: 0}`; calibration `ece` 0.354, `brier`
     0.5564, bin `[0.7,0.8)` `n=2, mean_p=0.735, accuracy=0.5`; escalation
     `coverage` 0.6667, `selective_accuracy` 0.5, `precision` 0.5, `recall`
     0.3333, `by_cause` `{fallback: 2, proposal: 0}`; latency `p50` 2.0,
     `p95` 5.0, `max` 5.0.
   - **Fixture B** (variance): scenario `a` three repeats routed
     `deterministic, deterministic, human_review` with p `.8, .7, .6`;
     scenario `b` three repeats `cheap_model` with p `.9` each. Expected
     `mean_modal_agreement` 0.8333, `flips` 1, `flipped == ["a"]`,
     `mean_probability_sd` 0.0408. A deterministic ledger (every repeat the
     same route and p 1.0) gives `flips == 0` and `mean_probability_sd == 0.0`.
   - **Fixture C** (agreement): a = `[deterministic, cheap_model,
     human_review, human_review]`, b = `[deterministic, cheap_model,
     human_review, deterministic]` on the same four keys → `rate` 0.75,
     `kappa` 0.6364.
   - **Fixture D** (cost): two frontier rows with `input_tokens` 300/500,
     `output_tokens` 40/60 and `frontier.usage` `cached_input_tokens` 100/0,
     `reasoning_output_tokens` 20/30, one routed correctly → `input_tokens`
     800, `output_tokens` 100, `cached_input_tokens` 100,
     `reasoning_output_tokens` 50, `tokens_per_correct_route` 900,
     `usd_total is None`; two rows without `frontier`, tokens `None` →
     `usd_total == 0.0`, `tokens_per_correct_route == 0.0` if one is correct.
   - A not-attempted row is excluded from `latency` and the confusions and
     counted wrong in `routed_accuracy`.

Gate:

```bash
rg -c "^def (routed_confusion|proposed_confusion|accuracy_summary|agreement|calibration|escalation|latency|cost|variance)\(" tests/hermetic_eval/metrics.py
```
now: `0` · after: `9`

Closes when: `uv run pytest tests/hermetic_eval/test_metrics.py -q > /tmp/functualize-t2.log 2>&1`
passes, the gate reads 9, the standing checks are clean. Commit:
`test(hermetic): add descriptive routing metrics`.

## Wave 1

### [x] T3 — the three comparators

*Files (all new):* `tests/hermetic_eval/comparators.py`,
`tests/hermetic_eval/test_comparators.py`

Imports: `ChoiceRequest`, `DecisionFailure`, `DecisionProvenance`,
`DecisionResult`, `DecisionUnavailableError` from `functualize.plugin`. **This
task is committed before the corpus is drafted (T6) and T6 may not edit this
file** — the rule table must not be fitted to the corpus.

Behaviour (B-6, B-7; C-3, C-4, C-5):

1. `def identity_sha256(identity: Mapping[str, object]) -> str` —
   `hashlib.sha256(json.dumps(identity, sort_keys=True, separators=(",", ":")).encode()).hexdigest()`.
2. **Deterministic** — `RULES: tuple[tuple[str, str], ...]`, exactly, in this
   priority order (each compiled with `re.IGNORECASE`):
   ```python
   RULES = (
       ("human_review", r"\b(refund|chargeback|lawsuit|legal|lawyer|fraud|hacked|password|delete my account|threat|harm|medical|emergency|complaint)\b"),
       ("deterministic", r"\b(opening hours|business hours|what time|order status|status of (my )?order|tracking number|price of|how much (is|does)|store address|phone number|reset link)\b"),
       ("cheap_model", r"\b(summari[sz]e|rewrite|rephrase|translate|shorten|fix (the )?(grammar|typos?)|draft a (short )?(reply|email|message)|classify|tag)\b"),
       ("frontier_agent", r"\b(investigate|analy[sz]e|debug|migrate|root cause|step[- ]by[- ]step|multi-?step|design|research|plan)\b"),
   )
   ```
   `class DeterministicBaseline` with `name = "deterministic"`,
   `choose(request)` (reads `request.state` only; first match → one-hot over
   `request.options`; no match → `value="human_review"`, every option `0.25`;
   `provider="deterministic"`, `model="rules-v1"`, `confidence=None`,
   provenance `DecisionProvenance("rules-v1", latency_seconds=<time.monotonic delta>)`)
   and `identity()` → `{"comparator": "deterministic", "rules_sha256": sha256(json.dumps(RULES))}`.
3. **Hermetic** — `def hermetic() -> DecisionProvider` imports
   `functualize_decision_jev` **inside the function** and returns
   `JevDecisionProvider(JevConfig(model="jev-1.13-free", endpoint="https://opencode.ai/zen/v1/systemone"))`;
   `def hermetic_identity() -> dict[str, object]` →
   `{"comparator": "hermetic", "provider": "jev", "model": "jev-1.13-free", "endpoint": "https://opencode.ai/zen/v1/systemone", "plugin": "functualize-decision-jev", "plugin_version": importlib.metadata.version("functualize-decision-jev")}`.
0. **Measure the Codex success shape first (live, one call; F-14).** Nothing
   in the repository has seen a successful `codex exec` router answer. From
   the repository root, in one foreground call:
   ```bash
   P=/tmp/hermetic-codex-probe && rm -rf "$P" && mkdir -p "$P/cwd" && uv run python -c 'import json,sys; o=["deterministic","cheap_model","frontier_agent","human_review"]; json.dump({"type":"object","properties":{"choice":{"type":"string","enum":o},"probabilities":{"type":"object","properties":{k:{"type":"number"} for k in o},"required":o,"additionalProperties":False}},"required":["choice","probabilities"],"additionalProperties":False}, open(sys.argv[1],"w"))' "$P/schema.json" && codex exec --json --output-schema "$P/schema.json" -o "$P/last.json" -m gpt-6-astra -c 'model_reasoning_effort="medium"' --ephemeral --skip-git-repo-check --ignore-user-config --ignore-rules -s read-only -C "$P/cwd" "$(cat <<'EOF'
   You route requests. Answer only with the structured output: the option you choose and a probability for every option. Do not run commands.

   Choose how this request should be handled.

   Options:
   - deterministic: a fixed rule or lookup answers it; no model needed
   - cheap_model: a short, low-risk text task a small model can do
   - frontier_agent: multi-step reasoning or tool use is required
   - human_review: risky, ambiguous, or needs a person's judgement

   Text to route:
   <<<
   Refund my order 8831 — the box arrived empty.
   >>>

   Choose one option and give a probability for every option; the probabilities sum to 1.
   EOF
   )" < /dev/null > "$P/events.jsonl" 2> "$P/stderr.txt"; echo "exit=$?"
   ```
   (strip the three-space indentation of the heredoc body when typing it).
   - **If it is refused for the usage limit**, report the "try again at" time
     on the tracker and stop T3 (finish the deterministic and hermetic parts,
     leave T3 `[ ]`); resume after the window. Do not loop or sleep.
   - On success, copy `events.jsonl` to
     `tests/hermetic_eval/fixtures/codex_success.jsonl` and `last.json` to
     `tests/hermetic_eval/fixtures/codex_success_last.json`, and write
     `tests/hermetic_eval/fixtures/codex_usage_limit.jsonl` with exactly these
     three lines (measured 2026-10-04T20:04:48Z):
     `{"type":"thread.started","thread_id":"fixture"}` ·
     `{"type":"error","message":"You’ve hit your usage limit. Upgrade to Pro (https://chatgpt.com/explore/pro), visit https://chatgpt.com/codex/settings/usage to purchase more credits or try again at 11:22 PM."}` ·
     `{"type":"turn.failed","error":{"message":"You’ve hit your usage limit. Upgrade to Pro (https://chatgpt.com/explore/pro), visit https://chatgpt.com/codex/settings/usage to purchase more credits or try again at 11:22 PM."}}`.
   - Read `codex_success.jsonl`: name the event and keys that carry token
     usage (expected `turn.completed.usage.{input_tokens, cached_input_tokens,
     output_tokens, reasoning_output_tokens}`) and whether any event names the
     model. **If either differs from `contracts.md` C-3 / `schema.md` S-2,
     correct those two files in this task's commit, and say so in the commit
     body.**
4. **Frontier (Codex)** — `@dataclass class FrontierCall` (`cli_version: str |
   None`, `model: str | None` (the model the stream names, else `None`),
   `model_mismatch: bool`, `usage: dict[str, int] | None`) and
   `class FrontierRouter` exactly as C-3:
   - `__init__(self, *, cwd: str, model: str = "gpt-6-astra", effort: str = "medium", timeout_seconds: float = 180.0, run: Runner | None = None, now: Callable[[], datetime] | None = None)`
     where `Runner = Callable[[list[str], str, float], tuple[int, str, str]]`
     (argv, cwd, timeout) and `now` defaults to
     `lambda: datetime.now().astimezone()` (local zone). The default runner is
     `subprocess.run(argv, cwd=cwd, stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=timeout)`
     → `(returncode, stdout, stderr)`. `choose` wraps **whichever** runner it
     holds and turns `TimeoutExpired` into `DecisionUnavailableError(kind=DecisionFailure.UNREACHABLE, provider="frontier", detail=f"timeout after {timeout}s")`.
     Re-export `TimeoutExpired = subprocess.TimeoutExpired` so tests never
     import `subprocess`.
   - Paths derive from `cwd`: `schema_path = Path(cwd).parent / "frontier-schema.json"`
     (written on the first `choose` from `build_schema(request.options)`),
     `last_path = Path(cwd).parent / "frontier-last.json"` (deleted before each
     call). Constructing the router writes and spawns nothing.
   - `PROMPT_TEMPLATE` (module constant) renders exactly:
     `"You route requests. Answer only with the structured output: the option you choose and a probability for every option. Do not run commands.\n\n{instructions}\n\nOptions:\n{option_lines}\n\nText to route:\n<<<\n{state}\n>>>\n\nChoose one option and give a probability for every option; the probabilities sum to 1."`
     with `option_lines` = `"- {option}: {meaning}"` per option in declared
     order, newline-joined. `def build_schema(options) -> dict` builds the C-3
     schema.
   - `argv(prompt)` returns exactly
     `["codex", "exec", "--json", "--output-schema", str(schema_path), "-o", str(last_path), "-m", model, "-c", f'model_reasoning_effort="{effort}"', "--ephemeral", "--skip-git-repo-check", "--ignore-user-config", "--ignore-rules", "-s", "read-only", "-C", cwd, prompt]`.
   - `choose(request)` runs once, appends one `FrontierCall`, and maps per the
     C-3 table: a `turn.failed`/`error` message containing `usage limit` →
     `RATE_LIMITED` with `retry_after` = seconds from `now()` to the next
     occurrence of `try again at (\d{1,2}):(\d{2}) ?([AP]M)` in `now()`'s zone
     (`None` if it does not parse); any other `turn.failed`/`error` or a
     non-zero exit → `REFUSED` (detail = first 300 chars of the message or
     stderr); `last_path` missing or not JSON, `choice` not an option, a
     probability outside `[0, 1]` → `MALFORMED`; otherwise a `DecisionResult`
     (`value=choice`, `provider="frontier"`, `model=<named model or the
     configured one>`, `distribution=probabilities`, `confidence=None`,
     provenance `requested_model=<configured>`, `latency_seconds` monotonic
     around the runner, `input_tokens`/`output_tokens` from the usage block
     measured in step 0). `model_mismatch` is true only when the stream names a
     model and it differs. `cli_version` = `codex --version` stdout, read
     **lazily on the first `choose`** through the same runner and cached.
   - `identity()` → `{"comparator": "frontier", "cli": "codex", "model", "effort", "argv": <argv with schema/last/cwd/prompt replaced by "SCHEMA_PATH"/"LAST_PATH"/"CWD"/"PROMPT">, "prompt_template_sha256", "schema_builder": "v1"}`.
5. `tests/hermetic_eval/test_comparators.py` — offline; a fake runner records
   `(argv, cwd, timeout)`, writes the canned `last_path` content when the case
   needs one, and returns canned stdout read from `tests/hermetic_eval/fixtures/`.
   Cases: recorded calls are `[["codex", "--version"], <C-3 argv>]` on the
   first `choose` and only the C-3 argv on the second, argv exactly as above;
   the success fixtures map to the `DecisionResult` the fixture implies
   (value, distribution as a mapping, tokens as measured); the usage-limit
   fixture with `now = 2026-10-04 22:04:48+02:00` → `RATE_LIMITED`,
   `retry_after == 4632.0` (to 23:22 local); exit 1 with a different
   `turn.failed` message → `REFUSED`; no `last_path`, `"not json"`,
   `choice: "other"`, a probability `1.2` → each `MALFORMED`; a runner raising
   `comparators.TimeoutExpired` → `UNREACHABLE`; if the success fixture names a
   model, a copy naming another model → `calls[-1].model_mismatch is True`.
   Deterministic: 100 calls on one state are identical; `"Refund my order
   8831"` → `human_review` one-hot; `"What are your opening hours?"` →
   `deterministic`; `"hello there"` → uniform 0.25; `identity()` is stable
   across instances. All three comparators satisfy `isinstance(x,
   DecisionProvider)` (`hermetic()` is constructed, never called).

*Files added by step 0:* `tests/hermetic_eval/fixtures/codex_success.jsonl`,
`tests/hermetic_eval/fixtures/codex_success_last.json`,
`tests/hermetic_eval/fixtures/codex_usage_limit.jsonl`; and, only if step 0
found a difference, `.spec/features/hermetic-evaluation/{contracts,schema}.md`.

Gates:

```bash
rg -c "^class (DeterministicBaseline|FrontierRouter|FrontierCall)\b" tests/hermetic_eval/comparators.py
```
now: `0` · after: `3`

```bash
rg -c "^def (identity_sha256|hermetic|hermetic_identity|build_schema)\(" tests/hermetic_eval/comparators.py
```
now: `0` · after: `4`

```bash
rg -l "^import subprocess|^from subprocess" tests/hermetic_eval | wc -l
```
now: `0` · after: `1`

Closes when: `uv run pytest tests/hermetic_eval/test_comparators.py -q > /tmp/functualize-t3.log 2>&1`
passes, the gates read their `after:` values, the standing checks are clean.
Commit: `test(hermetic): add the hermetic, frontier and baseline comparators`.

### [x] T4 — the decision rule offline, the sweep, the two errors, the boundary and the verdict

*Files:* `tests/hermetic_eval/metrics.py` (extend), `tests/hermetic_eval/test_metrics.py` (extend)

Behaviour (B-17, B-20…B-22; C-9). Constants come from
`tests.hermetic_eval.corpus.BOUNDARY`.

1. `accepts(p: float, margin: float, accept_at: float, min_margin: float) -> bool`
   — `p >= accept_at and margin >= min_margin`, exact comparison (the gate's
   rule, `src/functualize/_gate/decision_strategy.py`; no rounding).
2. `route_at(row, accept_at, min_margin, fallback="human_review") -> tuple[str | None, bool]`
   — `(None, False)` for not-attempted; `(fallback, False)` when the row
   failed, has no distribution, or its proposal is not a key of it; else
   `p = distribution[proposal]`, `margin = p − max(other values, default 0.0)`,
   and `(proposal, True)` if `accepts(...)` else `(fallback, False)`. The bool
   says *decided by the decision*.
3. `conformance(rows, accept_at=0.70, min_margin=0.10) -> list[tuple[str, int]]`
   — `(scenario, repeat)` of every non-not-attempted row whose `route_at`
   route ≠ its recorded `route`.
4. `errors_at(rows, accept_at, min_margin) -> dict` — over non-not-attempted
   rows, with `(route, decided) = route_at(...)`: `coverage` (decided and route
   ≠ `human_review`, ÷ rows), `selective_accuracy`, `false_continue` (decided,
   route ≠ `human_review`, route ≠ expected), `unsafe_continue` (those with
   expected `human_review`), `false_stop` = `{"fallback": n, "proposal": n}`
   (route `human_review`, expected ≠ `human_review`; cause `proposal` when
   decided, else `fallback`).
5. `sweep(rows) -> list[dict]` — `accept_at` in `[round(0.50 + 0.05 * i, 2) for i in range(10)]`,
   `min_margin` in `[0.00, 0.05, 0.10, 0.15, 0.20]`; one dict per point with
   both values and `errors_at`'s keys; 50 entries, `accept_at` outer.
6. `flip_points(rows) -> dict[str, float | None]` — per scenario, at
   `min_margin=0.10`: the modal `route_at` route over its repeats at each
   swept `accept_at`; the lowest `accept_at` whose modal route differs from the
   one at 0.50, else `None`. Ties in the mode break by `ROUTES` order.
7. `boundary(hermetic_rows, frontier_rows, constants=BOUNDARY) -> dict` — per
   route `r` in `ROUTES`: for each swept `accept_at` ascending, qualifying =
   hermetic rows with `route_at(row, t, 0.10) == (r, True)`; `support`,
   `scenarios` (distinct), `unsafe` (qualifying with expected `human_review`
   and `r != "human_review"`), `accuracy` (share with `r == expected`);
   `frontier_accuracy` = routed accuracy of frontier rows with `status ==
   "routed"` (non-failed — a frontier cell lost to its usage limit must not
   lower the bar) whose scenario is in the qualifying set (`None` if none). The first `t`
   with `support >= min_support`, `scenarios >= min_distinct_scenarios`,
   `unsafe == 0`, `frontier_accuracy is not None` and `accuracy >=
   frontier_accuracy − max_accuracy_gap` makes `r` `"trusted"` with
   `accept_at=t`, `support`, `scenarios`, `accuracy`, `frontier_accuracy`,
   `coverage` (support ÷ non-failed hermetic rows proposing `r`). If no `t`
   ever has enough support and scenarios: `"insufficient evidence"` (with the
   largest `support`). Otherwise `"escalate"`. Also returns `availability`
   (hermetic rows with status `routed` ÷ all hermetic rows) and
   `unsafe_continue_at_declared` (`errors_at(hermetic, 0.70, 0.10)["unsafe_continue"]`).
8. `verdict(boundary_doc, hermetic_rows, deterministic_rows, constants=BOUNDARY) -> tuple[str, str | None]`
   — `"adopt"` when some route is trusted with `coverage >= min_coverage`,
   `availability >= min_availability` and `unsafe_continue_at_declared == 0`;
   else `"reject"` when no route is trusted and the hermetic
   `accuracy_summary(...)["routed_accuracy"]` < the deterministic one; else
   `"continue research"` with the uncertainty = `"; ".join(parts)`, parts in
   this order: `f"insufficient evidence on route {r}"` per such route in
   `ROUTES` order; `f"availability {availability * 100:.1f} %"` when below
   the floor; `f"unsafe-continue on {n} cells"` when `n > 0`;
   `f"coverage below {min_coverage * 100:.0f} % on trusted route {r}"` per
   such route. The uncertainty is `None` for adopt and reject.
9. Tests (extend `test_metrics.py`): Fixture A from T2 gives `conformance ==
   []`; `errors_at(A, 0.70, 0.10)` = `false_continue 2, unsafe_continue 1,
   false_stop {fallback: 1, proposal: 0}, coverage 0.6667`;
   `errors_at(A, 0.75, 0.10)` = `false_continue 1, unsafe_continue 0,
   false_stop {fallback: 1, proposal: 0}, coverage 0.5`; changing s4's
   recorded route to `human_review` makes `conformance(A) == [("s4", 1)]`;
   `len(sweep(A)) == 50`. Boundary/verdict fixtures, built by a helper:
   - **adopt** — hermetic: 4 scenarios × 3 repeats proposing `deterministic`
     at p .85 (distribution `{deterministic: .85, cheap_model: .15}`), all
     expected `deterministic`, routed; frontier: the same 12 keys routed
     `deterministic` correctly → `deterministic` trusted at `accept_at` 0.5,
     `coverage` 1.0, verdict `("adopt", None)`.
   - **insufficient** — 3 scenarios × 3 repeats (9 cells), and separately
     3 scenarios × 4 repeats (12 cells): each `"insufficient evidence"`.
   - **reject** — as *adopt* but every hermetic row expected `cheap_model`
     (accuracy 0) and a deterministic ledger routing all 12 correctly →
     `deterministic` is `"escalate"`, verdict `("reject", None)`.
   - **continue** — *adopt* plus 2 hermetic rows with status `failed` →
     availability 0.8571, verdict `"continue research"` whose uncertainty
     contains `"availability 85.7 %"`.

Gate:

```bash
rg -c "^def (accepts|route_at|conformance|errors_at|sweep|flip_points|boundary|verdict)\(" tests/hermetic_eval/metrics.py
```
now: `0` · after: `8`

Closes when: `uv run pytest tests/hermetic_eval/test_metrics.py -q > /tmp/functualize-t4.log 2>&1`
passes, T2's gate still reads 9, this gate reads 8, standing checks clean.
Commit: `test(hermetic): add the threshold sweep, boundary and verdict`.

## Wave 2

### [x] T5 — the replay command, the freeze, and the report command

*Files (all new):* `tests/hermetic_eval/_router.py`,
`tests/hermetic_eval/replay.py`, `tests/hermetic_eval/report.py`,
`tests/hermetic_eval/test_replay.py`, `tests/hermetic_eval/test_report.py`

Behaviour (B-5…B-14, B-23, B-24; C-6, C-7, C-8, S-1, S-2):

1. `_router.py` — `def load_router() -> ModuleType`: loads
   `<repo>/examples/standalone/hermetic_router/router.py` (repo =
   `Path(__file__).resolve().parents[2]`) with
   `importlib.util.spec_from_file_location("hermetic_router_reference", path)`,
   registers it in `sys.modules` under that name (reusing it if present) and
   returns it; callers read `ROUTER` and `build_router`. The example file is
   not modified.
2. `replay.py` — `def main(argv: list[str] | None = None, *, factories: Mapping[str, Callable[[Path], tuple[DecisionProvider, dict[str, object]]]] | None = None, clock: Callable[[], float] = time.monotonic, now: Callable[[], datetime] = <UTC now>) -> int`
   and `if __name__ == "__main__": raise SystemExit(main())`. Default
   `factories`: `deterministic` → `(DeterministicBaseline(), its identity())`,
   `hermetic` → `(hermetic(), hermetic_identity())`, `frontier` →
   `(FrontierRouter(cwd=str(run_dir / "frontier-cwd")), its identity())`
   (the `Path` argument is the run directory). Flags per C-6: `--corpus`,
   `--comparator`, `--run-dir`, `--budget-seconds` (default 360),
   `--corpus-root` (default `Path(__file__).parent / "corpus"`), `--freeze`.
   - `--freeze` → `corpus.write_lock(version_dir, {name: identity_sha256(identity) for each factory}, frozen_at=<now ISO>)`;
     exit 2 with the message if a lock exists. `def freeze(...)` holds this.
   - Otherwise: `check_lock(version_dir, {comparator: identity_sha256(identity)})`
     — on `CorpusError` print it and return 2 **before creating anything**.
     Run directory: `--run-dir` or `$XDG_STATE_HOME` (else `~/.local/state`)
     `/functualize-hermetic-eval/<comparator>-<yyyymmddThhmmssZ>`; print its
     path first. New directory → write `run.json` (C-7 header, including
     `repo_commit` from `git rev-parse HEAD`, `started_at` = first cell's
     time — write the header when the first cell starts). Existing directory →
     its header's corpus digest, comparator, identity digest, seed and
     repeats must match, else return 2.
   - Cells = `ordered_cells([s.id for s in scenarios], seed=lock.seed, repeats=lock.repeats)`;
     skip the first `len(cells.jsonl lines)` cells. If `now() >
     started_at + time_box_hours`, append one `not_attempted` row per
     remaining cell and print `run complete`, return 0.
   - Per cell, `def replay_cell(...)`: `os.chdir` into
     `<run-dir>/project` (create it and `.functualize/`), restoring the
     previous cwd in `finally`; `app = FunctualizeApp(name="hermetic-router")`;
     `build_router(app, scenario.state)`;
     `app.gates.register_gate_strategy("decision", DecisionGateResolver(provider))`;
     `app.execute(RunRequest(job_name="router", surface="app.execute", workflow_scope_id=f"{comparator}-r{repeat}-{scenario.id}"))`;
     `record = decision_record(ScopeStore(app.substrate), scope, "route")`;
     build the S-1 row from `record` and `record["evidence"]` (plus S-2 from
     `provider.calls[-1]` for `frontier`), append it as one line with
     `json.dumps(row, sort_keys=True)`, flush and `os.fsync`.
   - After the row: if `frontier` and `model_mismatch` → rewrite nothing,
     append nothing more, print `invalid_model`, return 3 (the row already
     written carries `status: "invalid_model"`). If the row's failure kind is
     `rate_limited` with a `retry_after` → print `resume after
     <now + retry_after, ISO UTC>` and return 0. Before each cell, if
     `clock() − start >= budget_seconds` → print `budget reached; next cell
     <n>` and return 0. After the last cell print `run complete`, return 0.
   - Never calls `time.sleep`; never re-attempts a recorded cell.
3. `report.py` — `def main(argv=None) -> int`, flags per C-8. Reads each
   run's `run.json` + `cells.jsonl`; exit 2 unless exactly one run per
   comparator and all three share `scenarios_sha256`. Exit 4 when
   `metrics.conformance` is non-empty for any comparator (print the
   mismatches). Builds `metrics.json` (S-3: per comparator, `overall`,
   `clear`, `borderline` blocks from T2's functions; `sweep`, `flip_points`;
   pairwise `agreement`; `provenance` with corpus version/sha, each run's id,
   identity sha, ledger sha256, `started_at`, cell count, and `repo_commit`
   from the header), `boundary.json` (C-9 from `boundary` + `verdict`),
   `benchmark.md` (the C-8 table, the two confusion matrices per comparator,
   the sweep at `min_margin = 0.10`) and `finding.md` (corpus and digests,
   the boundary per route in words — "trusted to replace the frontier decision
   for proposals of `r` at p ≥ t" / "escalation still required" /
   "insufficient evidence" — the computed verdict and uncertainty, and a
   *Deviations* list: CLI versions seen if more than one, cells
   `not_attempted`, cells `failed` by kind). All JSON `sort_keys=True,
   indent=2`; numbers rounded to 4 places at print time; no report timestamp.
   `--check DIR` renders to memory and compares byte for byte with `DIR`'s
   four files, exit 1 on any difference.
4. `test_replay.py` — offline; every call passes `--run-dir` under
   `tmp_path` (the root suite sandboxes state roots). A fixture writes a 3-scenario corpus (one each
   of `deterministic`, `cheap_model`, `human_review`) under `tmp_path/corpus/v1/`
   and freezes it through `main(["--freeze", "--corpus", "v1", "--corpus-root", …], factories=fakes)`;
   fake factories return recording fake providers (canned `DecisionResult`s
   per state) with identity `{"comparator": "<name>", "fake": True}`. Cases:
   - **AC-2** one byte changed in `scenarios.jsonl` → `main` returns 2 and the
     run directory does not exist; lock deleted → 2, same.
   - **AC-3** every request the fake received has `state` equal to a scenario
     `state`, `instructions`/`options` equal to `load_router().ROUTER`'s, and
     its `repr` contains no scenario id, label, stratum or rationale.
   - **AC-6** a fake raising `DecisionUnavailableError(kind=RATE_LIMITED,
     provider="fake", status=429, retry_after=19014.0, detail="Rate limit exceeded")`
     on its 2nd call: return 0, ledger 2 lines, line 2 `status == "failed"`,
     `failure.kind == "rate_limited"`, `route == "human_review"`, output
     contains `resume after`; `time.sleep` monkeypatched to raise is never
     called; re-invoking resumes at cell 3 and the fake's call count shows
     cell 2 was not asked again.
   - **AC-7** an injected clock forcing a stop after 2 cells, then a resume,
     yields the same rows (ignoring `started_at`, `latency_seconds`) as one
     uninterrupted run, in `ordered_cells` order.
   - **S-3** every row's `rule_digest` is one value.
   - **B-7** a `frontier` fake whose `calls[-1].model_mismatch` is true →
     return 3, last row `status == "invalid_model"`.
   - **B-9** `now` past `started_at + 72 h` → remaining cells appended as
     `not_attempted`, `run complete`.
   - an existing run directory with a different comparator header → 2.
5. `test_report.py` — builds three small ledgers by running `replay.main`
   with fakes (so they come through the real router), then: two report runs
   are byte-identical; `--check` returns 0, and 1 after one byte of
   `benchmark.md` is changed; every output file contains the corpus SHA-256;
   a doctored ledger row (route changed) makes `main` return 4; two runs of
   the same comparator → 2. The verdict path is covered by T4's fixtures.

Gates:

```bash
rg -c "^def (main|freeze|replay_cell)\(" tests/hermetic_eval/replay.py
```
now: `0` · after: `3`

```bash
rg -c "^def main\(" tests/hermetic_eval/report.py
```
now: `0` · after: `1`

```bash
rg -l "^(from|import) functualize\._" tests/hermetic_eval | wc -l
```
now: `0` · after: `0` · invariant

Closes when: `uv run pytest tests/hermetic_eval -q > /tmp/functualize-t5.log 2>&1`
passes (all five test files), the gates read their `after:` values, standing
checks clean. Reachability, in the commit body: `replay.main → replay_cell →
FunctualizeApp.execute → DecisionGateResolver(provider).resolve → decision_record
→ cells.jsonl`; `report.main → metrics.* → boundary/verdict → four files`.
Prove one path by sabotage — **commit first**, then make `replay_cell` skip
`register_gate_strategy`, watch AC-3's test fail, `git checkout --
tests/hermetic_eval/replay.py`. Commit: `test(hermetic): add the replay and
report commands`.

## Wave 3

### [ ] T6 — corpus v1 (drafted, not frozen)

*Files:* `tests/hermetic_eval/corpus/v1/scenarios.jsonl` (new),
`tests/hermetic_eval/test_corpus.py` (extend). **Do not edit
`tests/hermetic_eval/comparators.py`** — `git diff --name-only HEAD~1 HEAD`
after this task's commit must list exactly these two files.

Behaviour (B-1…B-3; C-1):

1. Write 40 scenarios, C-1 format, ids `s01`…`s40`: 10 per expected route,
   each route 6 `clear` + 4 `borderline`, labels assigned by
   `tests/hermetic_eval/corpus/v1/LABELING.md` (§5/§6 override §1–§4), each
   `rationale` naming its clause (`§1`…`§6`). Interleave routes (do not group
   them); vary length (one sentence to a short paragraph, ≤ 600 chars) and
   register (terse, polite, angry, non-native). Realistic customer-support and
   internal-tooling requests. **Do not run any comparator while drafting**,
   and do not open `RULES` to write around it: borderline cases are borderline
   by the rubric, not by the regexes.
2. Extend `test_corpus.py` with `test_v1_corpus_has_the_declared_shape`:
   `check_v1_shape(load_corpus(<package>/corpus/v1/scenarios.jsonl))` passes.
3. Stop after committing and post the corpus to the maintainer for approval
   (D-4). T7 does not start without that approval.

Gates:

```bash
wc -l < tests/hermetic_eval/corpus/v1/scenarios.jsonl
```
now: `0` · after: `40`

```bash
rg -c '"expected": "human_review"' tests/hermetic_eval/corpus/v1/scenarios.jsonl
```
now: `0` · after: `10`

Closes when: `uv run pytest tests/hermetic_eval/test_corpus.py -q > /tmp/functualize-t6.log 2>&1`
passes and the maintainer has approved the corpus. Commit:
`test(hermetic): add the version 1 routing corpus`.

## Wave 4

### [ ] T7 — freeze corpus v1

*Files:* `tests/hermetic_eval/corpus/v1/corpus.lock.json` (new, written by
the command), `tests/hermetic_eval/test_corpus.py` (extend)

Precondition: the maintainer's corpus approval (T6) is recorded in the
*Decisions recorded* block above. No live cell has run.

1. `uv run python -m tests.hermetic_eval.replay --freeze --corpus v1`.
2. Extend `test_corpus.py` with `test_v1_lock_matches_corpus_and_comparators`:
   `check_lock(<package>/corpus/v1, {"deterministic": identity_sha256(DeterministicBaseline().identity()), "frontier": identity_sha256(FrontierRouter(cwd=".").identity()), "hermetic": identity_sha256(hermetic_identity())})`
   returns a `Lock` with `count == 40`, `repeats == 5`, `seed == 20261004`.
   (Constructing `FrontierRouter` must not spawn a process — `cli_version`
   is read lazily on the first `choose`.)
3. From this commit on, **any edit** to `scenarios.jsonl` or `comparators.py`
   fails this test; the remedy is a `v2/` directory and a full re-run, never
   an edited lock.

Gate:

```bash
rg -c '"scenarios_sha256"' tests/hermetic_eval/corpus/v1/corpus.lock.json
```
now: `0` · after: `1`

Closes when: `uv run pytest tests/hermetic_eval/test_corpus.py -q > /tmp/functualize-t7.log 2>&1`
passes; push the branch (the lock is now on the remote before any
measurement). Commit: `test(hermetic): freeze the version 1 routing corpus`.

## Wave 5

### [ ] T8 — the live measurement (no commit)

*Files:* none in the repository. Output: three run directories under
`~/.local/state/functualize-hermetic-eval/` (or `$XDG_STATE_HOME/…`).

Preconditions: the maintainer's Codex login is live on the measuring host
(`codex login status` reports logged in — the frontier draws on that ChatGPT
subscription's usage window, approved under D-2); avoid other Codex work on
the same login while T8 runs (it shares the window, plan R-3); for the
hermetic comparator,
`export OPENCODE_API_KEY="$(python3 -c "import json,os;print(json.load(open(os.path.expanduser('~/.local/share/opencode/auth.json')))['opencode-go']['key'])")"`
in the same shell call as the replay. Never print the key.

1. Run each comparator in **foreground** calls, one invocation per tool call
   (each ≤ 360 s budget plus one provider timeout of ≤ 180 s), re-invoking with the same
   `--run-dir` until it prints `run complete`:
   ```bash
   uv run python -m tests.hermetic_eval.replay --corpus v1 --comparator deterministic --run-dir "$HOME/.local/state/functualize-hermetic-eval/v1-deterministic"
   uv run python -m tests.hermetic_eval.replay --corpus v1 --comparator frontier --run-dir "$HOME/.local/state/functualize-hermetic-eval/v1-frontier"
   uv run python -m tests.hermetic_eval.replay --corpus v1 --comparator hermetic --run-dir "$HOME/.local/state/functualize-hermetic-eval/v1-hermetic"
   ```
2. On `resume after <UTC>` (a spent Jev free-tier window, or a spent Codex
   usage window) stop that comparator's run, report the time on the tracker,
   and resume in a later run after it. `resume after unknown` means the
   provider named no time: report it and retry in a later run. Never
   sleep or poll inside a run. On exit 3 (`invalid_model`) stop and report:
   the run is void.
3. Do not re-run a completed comparator to "improve" its numbers; a second
   run is a new run id and both are reported.

Closes when: each `cells.jsonl` has 200 lines (`wc -l` per file) and the last
invocation of each printed `run complete` — AC-12. No commit.

## Wave 6

### [ ] T9 — the report, delivered to the maintainer (no commit)

*Files:* none in the repository. Output: `~/.local/state/functualize-hermetic-eval/v1-report/`.

1. ```bash
   uv run python -m tests.hermetic_eval.report --run-dir "$HOME/.local/state/functualize-hermetic-eval/v1-hermetic" --run-dir "$HOME/.local/state/functualize-hermetic-eval/v1-frontier" --run-dir "$HOME/.local/state/functualize-hermetic-eval/v1-deterministic" --out "$HOME/.local/state/functualize-hermetic-eval/v1-report"
   uv run python -m tests.hermetic_eval.report --run-dir … (same three) --check "$HOME/.local/state/functualize-hermetic-eval/v1-report"
   ```
   The first exits 0 (4 = conformance failure: stop and report); the second
   exits 0.
2. **Publish to Confluence (D-6, approved by the maintainer).** With the
   Atlassian tools, create one page in space `SD` (Functualize), parent page
   `5144577` (*Hermetic Evaluation + Cheap SDD*), title `Hermetic Evaluation —
   Corpus v1 Results`. Body, in this order: a status line ("Computed verdict:
   <verdict> — a recommendation; the disposition is the maintainer's"), the
   corpus version and SHA-256, the three comparator identity digests and the
   repository commit; then `finding.md`; then `benchmark.md`. Attach the four
   report files and the three `cells.jsonl` (rename each to
   `cells-<comparator>.jsonl`). Then **read the page back live** (page id,
   version, attachment list): AC-17 needs the corpus SHA-256 in the body and
   seven attachments. A failed Atlassian read or write follows the workspace
   fail-closed rule — retry at least 3 times, then stop and report; never
   claim the page exists without reading it back.
3. Deliver the same seven files to the maintainer as tracker attachments, with
   the computed verdict, the boundary and the Confluence page link in the
   comment. **Do not commit them** (B-25).

Closes when: both commands exit 0, the Confluence page reads back with the
corpus digest and seven attachments, and the delivery comment exists. No
commit.

## Wave 7

### [ ] T10 — the durable half: the method, not the numbers

*Files:* `contributor/reference/hermetic-evaluation.md` (new), `.spec/STATUS.md` (modify)

1. `contributor/reference/hermetic-evaluation.md` — exactly these second-level
   sections: `## What it measures`, `## The corpus and its freeze`,
   `## The three comparators`, `## Running it`, `## The measurements`,
   `## The boundary and the verdict rule`, `## What it does not measure`.
   Carry the rules of `spec.md` B-1…B-28 in prose and the commands of C-6 and
   C-8. **No measured number** from T8/T9 unless the maintainer approved
   publication (D-6) — then add `## Results (corpus v1)` and say so in the
   commit body.
2. `.spec/STATUS.md` — after the *Hermetic router — delivered* block, add
   `### Hermetic evaluation — delivered` (≤ 15 lines): the instrument's path,
   the reference doc, the corpus version and digest, that results are held by
   the maintainer, and the still-open items (verdict disposition is the
   maintainer's; Phase 4/5).

Gates:

```bash
rg -c "^## " contributor/reference/hermetic-evaluation.md
```
now: `0` · after: `7`

```bash
rg -c "^### Hermetic evaluation" .spec/STATUS.md
```
now: `0` · after: `1`

Closes when: both gates read their `after:` values and
`uv run pytest tests/test_contributor_docs.py -q > /tmp/functualize-t10.log 2>&1`
passes. Commit: `docs(reference): describe the hermetic routing evaluation`.

## Wave 8

### [ ] T11 — checkpoint

*Files:* none expected.

1. Standing checks (ruff check, ruff format --check, mypy, lint-imports), then
   `uv run pytest tests/hermetic_eval tests/workflow/test_decision_record.py -q > /tmp/functualize-t11a.log 2>&1`
   and `uv run pytest examples/standalone/hermetic_router -q > /tmp/functualize-t11b.log 2>&1`
   (AC-16). Dispatch the tip tier on the PR's CI; do not run it locally.
2. `uv run python .github/scripts/dead_code_delta.py origin/master HEAD > /tmp/functualize-deadcode.log 2>&1`
   — classify each finding KNOWN/UNMARKED (advisory).
3. Invariant gates over the whole range:

```bash
git diff --name-only origin/master...HEAD -- src plugins | wc -l
```
now: `0` · after: `0` · invariant

```bash
git diff --name-only origin/master...HEAD -- examples docs | wc -l
```
now: `0` · after: `0` · invariant

```bash
rg -l functualize_decision_jev src | wc -l
```
now: `0` · after: `0` · invariant

```bash
git ls-files | rg -c "cells\.jsonl|benchmark\.md"
```
now: `0` · after: `0` · invariant

Closes when: all of the above hold. No commit unless a check needed a fix
(then `test(hermetic): …`, before T12).

## Wave 9

### [ ] T12 — clear the spec artifacts (deletion-only, last)

*Files:* `.spec/features/hermetic-evaluation/**` (delete)

1. Push the feature commits first and let CI's validation jobs (including the
   three `test-full` legs) pass; the artifact checks are expected red.
2. Then, as the **last** commit, deletion only:
   `git rm -r .spec/features/hermetic-evaluation` — commit
   `chore(spec): clear the hermetic evaluation artifacts` — and push.

Gate:

```bash
git ls-files .spec/features | wc -l
```
now: `5` (after this package's own commit) · after: `0`

Closes when: `spec-artifacts-cleared` is green on the PR. Never merge.

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["T1", "T2"] },
    { "id": 1, "tasks": ["T3", "T4"] },
    { "id": 2, "tasks": ["T5"] },
    { "id": 3, "tasks": ["T6"] },
    { "id": 4, "tasks": ["T7"] },
    { "id": 5, "tasks": ["T8"] },
    { "id": 6, "tasks": ["T9"] },
    { "id": 7, "tasks": ["T10"] },
    { "id": 8, "tasks": ["T11"] },
    { "id": 9, "tasks": ["T12"] }
  ]
}
```

Wave notes:
- **Wave 0.** T1 (`corpus.py`, rubric) and T2 (`metrics.py`) touch disjoint
  files; T2 imports only `ROUTES` from `corpus.py` — if T2 runs first, define
  `ROUTES` identically in `corpus.py` as T1 specifies, and T1 keeps it.
- **Wave 1.** T3 (`comparators.py`) needs nothing from wave 0 but must land
  before T6; T4 extends `metrics.py` (T2) and reads `BOUNDARY` (T1). Disjoint
  files.
- **Wave 2.** T5 needs the corpus loader and lock (T1), the comparators (T3)
  and all metrics (T2, T4).
- **Wave 3–4.** The corpus is drafted after the rule table exists (T3) and
  frozen after the maintainer approves it — a human gate between T6 and T7.
- **Wave 5–6.** Live measurement, then the report; maintainer preconditions
  (D-2 spend, credentials) gate T8.
- **Waves 7–9.** Durable docs, checkpoint, then the deletion-only tip — each
  alone, in that order.
