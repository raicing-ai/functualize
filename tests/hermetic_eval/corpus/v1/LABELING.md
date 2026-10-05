# Routing corpus v1 — labelling rubric

Every scenario in `scenarios.jsonl` carries one label from the four routes, and
one clause below decides it. The clauses are applied in the order they are
written: a clause that matches overrides every clause after it.

## §1 deterministic — a fixed rule or lookup answers it; no model needed

The answer exists as data: opening hours, an order's status, a tracking number,
a price, an address, a phone number, a reset link.

## §2 cheap_model — a short, low-risk text task a small model can do

Summarise, rewrite, rephrase, translate, shorten, fix grammar or typos, draft a
short reply, classify or tag. The work is textual and low-stakes.

## §3 frontier_agent — multi-step reasoning or tool use is required

Investigate, analyse, debug, migrate, find a root cause, design, research,
plan, or work through a problem step by step — anything needing several
operations or a tool.

## §4 human_review — risky, ambiguous, or needs a person's judgement

The request cannot be settled by a rule, a small model or a bounded agent run:
it is a judgement call, a relationship, or a decision a person owns.

## §5 risk overrides

Any risk of harm, money movement (refunds, chargebacks, payments), a legal
matter, or account security is `human_review`, whatever else the request asks.

## §6 lookups stay lookups

A question that a fixed rule or lookup answers is `deterministic` even when it
is phrased loosely, at length, or politely.

## How labels are assigned

Each scenario's label is the clause that decides it. §5 and §6 override §1–§4:
a refund request is `human_review` even when it reads like a lookup, and a
politely padded question about opening hours stays `deterministic`.

`borderline` means two clauses plausibly apply and the label is decided by §5,
by §6, or by the nearer clause; the scenario's `rationale` names the deciding
clause. `clear` means exactly one clause applies.

Labels never consult any comparator's output. The maintainer approves the
corpus before it is frozen; after the freeze, any change is a new version
directory and a full re-run.
