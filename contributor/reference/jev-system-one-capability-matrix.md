# Jev / System One decision-provider capability matrix

What the decision provider at `opencode.ai/zen/v1/systemone` **actually does**, measured by
sending it real requests. The instrument is `tests/jev_probe/`; the rows below were produced
by running it on `spike/jev-decision-provider-probe`, against the free model `jev-1.13-free`
— see *Provenance* for the commit, the commands and what the account's own budget cost this
document.

This exists because the roadmap's next stage wants a decision to be *evidence*, and the
evidence has to come from somewhere outside this repository. Before an adapter can be
designed against the provider, four things need to be true of it at the wire: a request
shape an adapter can build, a response shape it can deserialize, a stability figure that
tells a caller how much a decision is worth, and a cost shape that bounds what a decision
run costs. This document measures those four and the two rows around them — what happens
when a call is wrong, and what the provider does *not* decide.

**Nothing here is a vendor claim.** No cell quotes documentation, a sample from a blog post,
or a number this account did not itself observe. Where this document has no measurement it
says so in the cell and gives the reason.

**Nothing here is a decision rule.** The provider returns probabilities and labels; it does
not accept or reject anything (row G). The matrix describes what an adapter may rely on. It
does not say the adapter should exist, where a threshold would come from, or what a
`noul` of 0.02 should mean — those are decisions for the feature that needs them, with the
guard this document's row G supports.

## How to read a cell

Every cell carries an evidence level:

| stamp | means |
|---|---|
| `measured (real service)` | the request went to `opencode.ai` while the run was running |
| `NOT MEASURED` | nobody measured it; the reason is in the cell |

**There is no fixture level, and no third level is admitted.** The probe has no cassettes,
no recorded responses and no emulator standing in for the service — for this provider there
is nothing to emulate, because reaching it costs one HTTP request to a URL that is already
public. A recorded body would be evidence about the recording, and it would rot silently the
first time the provider changed a field. Every number here is a request made while the run
was running, or it is a stated gap.

**A rate-limited cell is a gap, not a level.** The free tier's budget is finite and it is the
*account's*, not the contract's (row F4). When a run meets `429`, the affected cell says
`NOT MEASURED (rate limited)` and names the wait the service asked for. It never fails —
the probe is not a monitor — and it never reports the refusal as a measurement.

### The refusal rule: there is no third kind of measurement

Two levels, and a run that fits neither is refused rather than filed under the closer one.
Concretely: row E17 asked for a count of the refusal layers a run exercised. The first
version of that cell carried a hard-coded set of layers, and the run of record printed a
count that did not match its own table — an assertion about the instrument dressed as an
observation about the service. It now derives the number from the statuses it actually met,
and this document quotes the derived value (five), with the discrepancy named in row E's
note rather than quietly corrected in the table.

## The matrix

| row | what was measured | value | evidence |
|---|---|---|---|
| A1 | request envelope | keys `{"model", "state", "questions"}`; a question carries `{type, instructions}` plus `criteria` | measured (real service) |
| A2 | response envelope | keys `["answers", "model", "usage"]`; one `usage` for the whole request | measured (real service) |
| A3 | `noul` answer | `{"noul": 0.02, "type": "noul"}` | measured (real service) |
| A4 | `choice` answer | `{"choice", "confidence", "probabilities", "type"}` — no `deterministic` field | measured (real service) |
| A5 | `score` answer | `{"confidence", "legend", "probabilities", "score", "type"}` | measured (real service) |
| A6 | the three answer types | share exactly one field, `type`; the union is 7 fields | measured (real service) |
| B1 | `score` vs Σ index × probability | max absolute residual **0.01** over 72 answers, inside the **0.02** the wire's reported precision allows | measured (real service) |
| B2 | `confidence` vs `max(probabilities)` | 0.01 – 0.26 apart; they coincide in 5/24 answers, only where one option is unanimous | measured (real service) |
| B3 | `probabilities` key order | 6 distinct orders over 12 answers; the request's order appeared once | measured (real service) |
| C1 | stable decision, 20 identical requests | argmax flips **0/20**; per-option range 0.04 – 0.66 | measured (real service) |
| C2 | near-tied decision, 20 identical requests | argmax flips **9/20**; top-two gap falls to 0.00 – 0.12 | measured (real service) |
| C3 | one clause is the whole difference | the two sweeps differ by `"I am furious."` and nothing else | measured (real service) |
| D1 | cost per request | 283/20 tokens for one `noul` on a 26-character state | measured (real service) |
| D2 | a second question in the same request | +17 input, +18 output; the same again for a third | measured (real service) |
| D3 | a longer state | 288 more characters → +52 input tokens, output unchanged | measured (real service) |
| D4 | three more `choice` criteria | +44 input, +21 output | measured (real service) |
| D5 | cost by question type | `noul` 283/20 · `score` 307/17 · `choice` 332/38 | measured (real service) |
| E | 16 request cases around a valid control | 14 refusals, five status layers, three JSON envelopes, one plain-text gate | measured (real service) |
| F1 | catalog `GET /zen/v1/models` | HTTP 200, 81 models, `0.35 – 0.48 s` | measured (real service) |
| F2 | the model is listed | both `jev-1.13-free` and the paid `jev-1.13` are listed | measured (real service) |
| F3 | decision endpoint reachability | HTTP 200, `0.995 s`, without a retry | measured (real service) |
| F4 | what the run met for load | `3 × HTTP 429 over 4 round trips`, asking for ~18834 s | measured (real service) |
| G1 | `noul` value range | `0.02 – 0.02` over 4 samples; fields `["noul", "type"]` | measured (real service) |
| G2 | boolean fields in any answer | **0** across every answer type measured | measured (real service) |

Row E is one row in the summary because its 18 facts are a table of their own; it is under
*Row E* below, verbatim.

## What was measured, and how

### Row A — the wire contract

The request is `{"model", "state", "questions"}`, and `state` is a plain string — the ticket
text as the caller wrote it, with no envelope around it. A question is a discriminated union
tagged by `type`:

```json
{"type": "choice", "instructions": "Which team should handle this?",
 "criteria": {"billing": "…", "returns": "…", "shipping": "…"}}
```

`criteria` means two different things by type: an **object** of option → meaning for `choice`
(row A4, and refusals E6/E7 show the validator enforcing exactly that), and an **ordered
list** for `score`, whose order becomes the `legend` in the answer (A5). The same field name
with two shapes is the first thing an adapter built from one example will get wrong.

The response is `{"model", "answers", "usage"}`. `answers` is keyed by the caller's own
question ids, `model` echoes the requested name, and `usage` is **one block for the whole
request** — not per question (D1). The three answer types share exactly one field:

| type | fields | the answer itself |
|---|---|---|
| `noul` | `type`, `noul` | a single probability |
| `choice` | `type`, `choice`, `confidence`, `probabilities` | the winning option, keyed by the request's options |
| `score` | `type`, `score`, `confidence`, `legend`, `probabilities` | the expected value over the `legend` indices, not the winning index itself |

A single response model requiring any field from another type cannot deserialize every
answer (A6). In TypeScript terms this is a discriminated union, not a struct with optional
members — which is why row A6 exists.

### Row B — the identities an adapter should not re-derive

Three measurements that together say *trust the service's own numbers, do not recompute
them*:

- **B1 — `score` is the expected value of `probabilities` over `legend` indices.** Max
  absolute residual **0.01** over 72 answers, against the **0.02** the wire's own precision
  allows. Both sides are reported to two decimals, so the identity carries one rounding term
  per value it sums: half of `score`'s last reported place, plus half of each probability's
  last reported place weighted by that probability's index — `0.005 + 0.005 × (0 + 1 + 2) =
  0.02` for a three-point legend, the same sum the committed row prints beside its residual.
  The comparison is on the **unrounded** residual and the rounding is presentation only:
  rounding before comparing would read an answer one place outside its budget as `0.00`, and
  a budget that follows the reported precision is worth nothing if the thing it measures has
  been flattened first.
  The one non-zero residual measured was `score` **1.99** against printed probabilities
  `{"0": 0, "1": 0, "2": 1}`, whose indices sum to `2.00` — a whole unit of the wire's last
  place, and twice the flat half-place tolerance this row used to assert. The adapter should
  read `score` rather than accumulate a float: a break in the identity itself, such as
  ranking the legend instead of averaging it, moves the sum by a whole index unit, an order
  of magnitude above the budget.
- **B2 — `confidence` is not `max(probabilities)`.** The gaps run 0.01 – 0.26, they coincide
  only when an option is unanimous (5/24), and `confidence` never once exceeded
  `max(probabilities)`. It is a provider-supplied scalar. An adapter that treats it as the
  winning probability will be wrong by up to a quarter.
- **B3 — `probabilities` is not in request order.** Six distinct key orders in 12 answers;
  the request's order appeared once. Positional reading of `probabilities` reads an order
  the service never promised.

`B1`'s cell previously read **max absolute residual 0 across 12 answers**, with the sentence
*"with two-decimal probabilities and integer indices the sum is exact"* beside it, and the
committed row allowed a flat `0.005`. The measurement above is what did not hold: the sum
lands exactly on most answers and a whole unit of the last place out on others, because two
rounded quantities are compared and only the indices are integers. One answer of the 72
measured for the cell went out by `0.01` — twice the old tolerance — while the row's own
twelve-answer run went out by none, which is how a tolerance no wire promised survives a
run. The row now derives its tolerance from the precision the wire reports, and this note
records the earlier reading rather than leaving it silently replaced.

The first version of that derived bound **rounded each residual to six places before
comparing it**, which hid exactly the case the bound exists for: `score` `1.0000003` against
probabilities `0.3333333` at each legend index `0`, `1`, `2` leaves `4.0000000001150227e-7`
— two places outside the `2e-7` its own values allow — and rounds to `0.0`, so the row
passed. The comparison now runs on the unrounded residual and only the printed one is
rounded, so a budget derived from the reported precision is not defeated by a rounding step
downstream of it. The case above is the offline witness, not a wire measurement: no wire
observed here reports past two decimals, which is why the rounding had to be tested at the
arithmetic rather than waited for.

### Row C — how much a decision is worth

Twenty identical requests at one state, twice, with the two states differing only by the
clause `"I am furious."`:

| | stable state | near-tied state |
|---|---|---|
| argmax flips | **0/20** | **9/20** |
| per-option range | shipping 0.30–0.40 · billing 0.04–0.05 · returns 0.56–0.66 | shipping 0.42–0.52 · billing 0.03–0.04 · returns 0.44–0.54 |
| top-two gap | 0.16 – 0.36 | 0.00 – 0.12 |
| `confidence` | 0.34 – 0.49 | 0.22 – 0.30 |
| latency min/mean/max | 0.619 / 0.709 / 1.264 s | 0.617 / 0.733 / 0.979 s |

This is the row a decision adapter has to answer for. A clear decision is stable to twenty
identical requests; a near-tied one flips nine times in twenty with the same input. The
latencies are measured at one request at a time, from a developer's machine to a hosted
service, and include neither batching nor concurrency (Q4).

### Row D — the cost shape

Seven measured points, one `usage` block each:

| request | input/output |
|---|---|
| `noul` ×1 | 283 / 20 |
| `noul` ×2 (same request) | 300 / 38 |
| `noul` ×3 (same request) | 317 / 55 |
| `noul` ×1, long state (+288 chars) | 335 / 20 |
| `choice`, 3 criteria | 332 / 38 |
| `choice`, 6 criteria | 376 / 59 |
| `score`, 3 criteria | 307 / 17 |

Three things follow, and they are the ones a cost model needs. **A question is not a unit of
cost**: the second and third question in one request add +17/+18 tokens each (D2) — the unit
is the *request*. **The state is paid for, the answer is not**: 288 more characters cost +52
input tokens and changed the output not at all (D3). **Criteria cost twice**: they are part
of the question and of the answer's `probabilities` (D4). Batching questions into one
`DecisionRequest` is cheaper than batching requests, by roughly half a question's worth per
marginal question.

### Row E — the refusal taxonomy, and the five layers that produce it

Sixteen request cases — the control, plus fifteen each one change away from it, so a status is
attributable to that change — plus two facts derived from them (E16, E17). Two of the sixteen
answer `200`: the control (E0) and the empty-`User-Agent` case (E14). The other fourteen
refused, which is the count E17 and the summary row carry.

| case | status | layer | body |
|---|---|---|---|
| E1 | 422 | request shape | `{"detail":[{"type":"missing","loc":["body","questions"],"msg":"Field required", …}]}` |
| E2 | 422 | request shape | `{"detail":[{"type":"too_short","loc":["body","questions"],"msg":"Dictionary should have at least 1 item after validation, not 0", …}]}` |
| E3 | 422 | request shape | `{"detail":[{"type":"union_tag_not_found","loc":["body","questions","q"],"msg":"Unable to extract tag using discriminator 'type'", …}]}` |
| E4 | 400 | tagged union | `{"detail":{"error_type":"api_usage_error","message":"Invalid request."}}` |
| E5 | 422 | request shape | `{"detail":[{"type":"missing","loc":["body","questions","q","choice","criteria"],"msg":"Field required", …}]}` |
| E6 | 422 | request shape | `{"detail":[{"type":"dict_type","loc":["body","questions","q","choice","criteria"],"msg":"Input should be a valid dictionary","input":"shipping"}]}` |
| E7 | 422 | request shape | `{"detail":[{"type":"list_type","loc":["body","questions","q","score","criteria"],"msg":"Input should be a valid list", …}]}` |
| E8 | 401 | model resolver | `{"type":"error","error":{"type":"ModelError","message":"Model  is not supported"}}` |
| E9 | 400 | upstream | `{"error":{"type":"server_error","message":"Upstream request failed: Model is unavailable."}}` |
| E10 | 402 | funds | `{"error":{"type":"server_error","message":"Upstream request failed: Insufficient account funds"}}` |
| E11 | 401 | credential | `{"type":"error","error":{"type":"AuthError","message":"Invalid API key."}}` |
| E12 | 403 | edge gate | `error code: 1010` (plain text) |
| E13 | 403 | edge gate | `error code: 1010` — byte-identical to E12 |
| E14 | 200 | — | a valid answer, with `User-Agent: ""` |
| E15 | 403 | edge gate | `error code: 1010`, on the catalog `GET` |
| E16 | — | — | the envelopes are not uniform: `detail` · `type`+`error` · `error` alone |
| E17 | — | — | 14 of 16 cases refused, by **five** statuses: 400 · 401 · 402 · 403 · 422 |

**Two facts in this row matter more than the rest.** The 422s and 400s are *pydantic* — the
`loc` field names the exact body path, so a caller debugging a 4xx is being told where the
bug is, and an adapter can map them to its own validation without guessing. And the five
layers are genuinely different: request shape (422, `detail` as a list of paths), the tagged
union (400, `detail` as an object), the credential and the model resolver (401,
`type`+`error`), funds and upstream (402/400, `error` alone), and the edge's `User-Agent`
gate (403, not JSON at all). **An adapter that deserializes every failure into one shape
misreads at least half of them** (E16).

`E17` is quoted as **five**, from the statuses in the table above. The run of record printed
`by 4 layers` because that text was a hard-coded set rather than a count of what the run met;
the committed instrument derives it from the observed statuses, and the discrepancy is
recorded here rather than corrected in place.

The summary row above and the sentence introducing the case table both once read **fifteen
refusals**, where the table computes fourteen: the control `E0` and the empty-`User-Agent`
case `E14` both answer `200`, and the other fourteen cases refuse. A hand-written count beside
a derived one is what produced it, and both now read what the table says.

`E10` is the reason the paid model is unusable as a probe target: `402 Insufficient account
funds` is a refusal for *funds*, not for permission, so a probe pointed at it would spend
money rather than measure anything.

### Row F — reachability, and the budget that is not the contract

The catalog is a plain `GET /zen/v1/models`, unauthenticated (the probe sends no token to
it), answering in `0.35 – 0.48 s` with **81 models**; both `jev-1.13-free` and the paid
`jev-1.13` are listed. Two consequences: an adapter can discover the model name instead of
hard-coding one, and **the catalog says a model exists, not that the account may call it** —
`jev-1.13` is listed and answers `402`.

`F4` is the operational fact this document exists to record as much as any other. A full
credentialed run is about a hundred requests. The first run of record completed all 40
facts in 84 s. **The very next run met `429 FreeUsageLimitError` partway through its
row B, and every model-backed row after that refused until the budget returned:**

```
HTTP 429 · {"type":"error","error":{"type":"FreeUsageLimitError",
            "message":"Rate limit exceeded. Please try again later."}}
Retry-After: 19014
```

Two requests minutes apart in the same session, an earlier raw one and one from the run
above, were asked to wait `19014` s and `18834` s: the wait counts down toward a fixed reset
about five hours out, so this is a **window**, not a per-second rate. That is
the account's burst budget, and it is why the instrument has a third skip reason — a run
that meets it reports `NOT MEASURED (rate limited)` for the affected cells and names the
wait, rather than sleeping for five hours or failing. It also bounds the roadmap: **an
adapter that calls this provider per decision has to treat "the provider refused for load"
as a normal outcome with a bound, not as an exception** — exactly what F4 records, and the
equivalent of the substrate probe's finding that a client, not the vendor, owns retry and
timeout policy.

`F3`'s reachability is established by a TCP connect *before* the module's first request, so a
skip means the service was absent and a failure means it is unhappy about the request — the
two are never the same thing.

### Row G — the authority boundary

The provider returns probabilities and labels, and nothing else:

- **G1 — `noul` is a probability in [0, 1]**, field set `["noul", "type"]`: no threshold, no
  boolean, no field naming an outcome. Measured `0.02` four times over four identical
  requests at one state, so this is the spread of *the answer*, not of the evidence (Q1).
- **G2 — no answer field is a boolean.** Across every answer type measured in this row the
  union of fields is `["choice", "confidence", "legend", "noul", "probabilities", "score",
  "type"]` and zero of them carries `true`/`false`.

That is the wire-level basis for the roadmap guard: **the provider cannot by itself accept or
reject anything.** A decision becomes an acceptance only where this repository writes the
rule that turns a probability into one, and that rule is not in this document.

## Two corrections to the numbers in the brief

The task that asked for this probe carried three sample values from an earlier throwaway
session. Two of them were not reproducible, and both are worth stating because they are
easy to believe:

1. **A `deterministic` field does not exist.** The brief's `choice` sample carried
   `"deterministic": 0.81`. No `choice` body in the run of record — twelve of them — carried
   that field, nor did the union of every answer field in any row. The `choice` answer is
   exactly `{type, choice, confidence, probabilities}` (A4). A `deterministic` scalar may
   exist in some other response shape of the service; it was not observed here, and the
   adapter must not be designed around it. (The brief's probabilities also differed —
   0.83/0.11/0.06 against 0.49/0.47/0.04 here. That is a *decision* differing run to run,
   which row C2 shows is ordinary, and not a contradiction: the numbers in this document are
   one run's, and a re-run will differ in the third decimal and sometimes in the argmax.)
2. **The `User-Agent` gate covers `POST`, and omitting the header is not neutral.** The
   brief recorded the gate on the catalog and treated the decision endpoint as reachable
   without a header. Measured: the stdlib default (`Python-urllib/3.x`) draws `403 error
   code: 1010` on **both** endpoints (E12, E15), and *omitting* the header draws a
   byte-identical 403 (E13) because the transport substitutes its own default before the
   request leaves. An empty string is accepted, with a 200 (E14) — the gate blocks one
   specific string, not the absence of one. The probe therefore always sends its own name,
   and so must any adapter: "clearing" the header is not clearing it, because the transport
   puts `Python-urllib/3.x` back when the request leaves (E13).

## Open questions

### Q1 — Does `noul` track the evidence?

G1 measured `0.02 – 0.02` over four identical requests at one state. That is the spread of
the answer at *one* input, and a probability that never moves is not the same finding as a
probability that is insensitive to its evidence. The instrument samples four *states* for the
next run; the free tier's window closed before that design could be measured, and it is not
in the committed row G — an unmeasured sampling design in an instrument is how a number ends
up behind a stamp it did not earn. **Not measured. Needs the next window.**

### Q2 — What is the free tier's actual ceiling and reset window?

Measured: `429` with `Retry-After` counting down to a reset about five hours out, after
roughly a hundred requests in a burst. Not measured: the requests-per-window ceiling, whether
it is a token budget or a call count, and whether the paid tier removes it (unmeasurable
here — see E10). A decision run today must budget for a burst of about a hundred requests and
a five-hour recovery.

### Q3 — Does the paid model change the contract or the stability?

`jev-1.13` is listed in the catalog (F2) and refuses this account for funds (E10). Every
number in this document is `jev-1.13-free`. Whether the paid model answers faster, more
stably, or with a different field set is **not measured**, and the roadmap should not assume
the free model's stability figures carry over.

### Q4 — Latency under batching and load?

Row C's latencies are one request at a time. Batching several questions into one request
(documented in D2 as cheaper) changes the wall clock per question, and concurrent callers
are not measured at all.

## Reproducing this

```console
$ export OPENCODE_API_KEY=…          # the account's free-model key; never committed
$ uv run pytest -q -m jev_probe -p no:randomly
$ env -u OPENCODE_API_KEY uv run pytest -q -m jev_probe -p no:randomly
```

The second command is the one that matters for a contributor with no credential: every row
reports `NOT MEASURED (no credentials)` with the reason, the run is **green**, and nothing
is skipped silently. The fact tables print from `pytest_terminal_summary`, so `-q` still
shows them. The `jev_probe` marker is how a *credentialed* run selects exactly these rows
(`-m jev_probe`); in the default suite they are collected and skip themselves at module level,
because they are measurements and not assertions a CI runner can hold.

A full credentialed run sweeps 20 identical requests per stability state, 20 more per cost
point and the whole refusal table, and took 84 s wall clock. Budget the window (Q2) before
starting one: a second run inside the same window will refuse most of its model-backed rows.

### Provenance

The 40 facts in the tables above were measured on branch `spike/jev-decision-provider-probe`
by `uv run pytest -q -m jev_probe -p no:randomly` on 2026-09-25, from the instrument committed
at `a5b2d10` — repository commit `a5b2d10c08968448e033d206d2907053b6181a63`, whose base is
`498a8a5`. The values are that run's output; the code in that commit differs from the code that
produced the run in exactly the three renderings named where they apply — the evidence stamp,
the whitespace the printer clipped, and row E17's count. That run reported:

```
40 facts recorded.
1 failed, 34 passed, 2 skipped, 12745 deselected in 83.93s
```

The single failure was an assertion in the probe's *own* gating tests — a fact recorded
without credentials was rendered under a measured stamp — and no measurement module failed.
It is fixed in the same commit, and it is the failure that produced row E's note above: a
stamp belongs to the fact, not to the printer.

Row F1, F2 and F4 were **re-measured** by the same instrument later the same day, after the
free tier's window closed, from a run in which every model-backed row reported
`NOT MEASURED (rate limited)`:

```
F. Reachability
  F1  catalog reachability: HTTP 200 in 0.400 s · 81 models — measured (real service)
  F2  the measured model is listed: jev-1.13-free listed (paid sibling jev-1.13 listed) — measured (real service)
  F4  load refusals met by the run: 3 × HTTP 429 over 4 round trips — measured (real service)
        first body: {"type":"error","error":{"type":"FreeUsageLimitError","message":"Rate limit exceeded. Please try again later."}} · the service asked to wait [18834.0, 18834.0, 18833.0] s …
25 passed, 14 skipped, 12745 deselected in 56.27s
```

E8's body is quoted **raw**, from a single request made while that window was closed, because
the run of record's printer collapsed the doubled space in `"Model  is not supported"` into
one. The measure was a real 401 from the real service; the whitespace is the one thing in
the tables above that the run of record did not itself render.

**B1 was re-measured on 2026-09-26**, because the row as first committed asserted an exact
sum the wire does not hold: both its cell and the row allowed `0.005` of rounding, and one of
the 72 answers measured for the cell came back with `score` **1.99** against printed
probabilities `{"0": 0, "1": 0, "2": 1}` — a whole unit of its last reported place, and twice
that tolerance. The committed instrument now derives the tolerance from the precision the wire
reports: half of the last reported place of `score`, plus half of each probability's last
reported place weighted by that probability's index, compared against the **unrounded**
residual so the rounding the budget accounts for is not applied twice. It was measured on
branch `fix/jev-probe-b1-identity`, cut from `8036cfc3f80d5e88c8f0212db921b39760f2bb0a`:

```
$ uv run pytest -q -m jev_probe -p no:randomly        # OPENCODE_API_KEY exported
36 facts recorded.
31 passed, 8 skipped, 12775 deselected in 72.28s (0:01:12)
```

That run measured rows A, B1, D, E, F and G. Row C's three tests and rows B2 and B3 skipped,
the run meeting the free tier's `429` before them (Q2), so row C and B2/B3 still stand on the
`a5b2d10` run above. Its B1 cell printed `max |residual| 0 over 12 answers, against a 0.02
rounding budget`. Six further twelve-sample sets of the same request were measured in the
same window — 72 answers in all — and one residual was non-zero: `score` 1.99 against
`{"0": 0, "1": 0, "2": 1}`, `-0.01`, inside the `0.02` budget and twice the `0.005` the row
allowed before. That six-set measurement is the one B1's cell above carries.

The comparison that reads that budget was corrected after the run above, from a version of
the bound that rounded each residual to six places before comparing it: the budget is now
compared against the unrounded residual and only the printed one is rounded. No wire run
reached row B1 afterwards — the later run of the same day met the closed window and recorded
row F alone, `3 facts recorded`, `25 passed, 14 skipped, 12775 deselected in 51.65s` — so
that correction is evidenced at the arithmetic, on the `1.0000003` case recorded under
*Row B* above, and not by a measurement. The identity and the budget arithmetic are the ones
this run measured.

A run of the same probe with no credential exported is green, every measurement row skipping
by name — five module-level `NOT MEASURED (no credentials)` skips plus the `.spec` and floci
gates that are no part of this probe:

```
$ env -u OPENCODE_API_KEY uv run pytest -q -m jev_probe -p no:randomly
24 passed, 7 skipped, 12775 deselected in 21.69s
```

The counts are what that run is evidence of; the wall time is machine-local and moves
between hosts and loads — the same green keyless run has been observed at `14.61 s` and at
`21.69 s` on this one — which is why the line above is quoted with the command that produced
it rather than as a bare figure.

### Two things to know before re-running this

**It costs the account's budget, and the budget is per window.** Two full runs inside one
window is one run too many (row F4). The instrument will not hang on a refusal — it records
it and moves on — but the rows it skipped in an earlier window are exactly the rows a
re-run is for.

**The probe is not a monitor and not a contract test.** It asserts that each module made a
measurement at all; it does not assert that the service still returns `0.02`, and a green
`-m jev_probe` run does not mean the provider is unchanged. Read the numbers it prints.

## What this does not say

- **It does not say an adapter should exist.** It measures what an adapter would have to
  survive: three answer shapes, two meanings for `criteria`, a `confidence` that is not the
  top probability, unordered `probabilities`, a five-layer refusal taxonomy with three
  envelopes, and a provider that answers your hundredth request with `429`.
- **It does not say what a probability means to a decision.** No threshold, no calibration,
  and no claim that 0.02 or 0.56 should decide anything. Row G is the boundary, not a rule.
- **It does not measure the paid model, batch latency, or concurrency** (Q3, Q4).
- **It does not claim the numbers hold tomorrow.** A decision provider is not a versioned
  wire: the free model's answers change run to run (C2), and the instrument is the only thing
  here that is pinned.
- **It says nothing about prompt quality.** The `state` and `instructions` strings in the
  probe are the probe's own; the provider's answers depend on them, and row C3 shows that a
  single clause can be the difference between a decision that holds and one that flips.
  Anything built on top of this needs its own measurement of its own prompts.
