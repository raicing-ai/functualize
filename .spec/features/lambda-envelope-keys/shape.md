| | |
|---|---|
| Document type | Shape Intent |
| Status | Exploring |
| Authority | Proposed |
| Owner | maintainer |
| Product | Functualize |
| Last reviewed | 2026-11-28 |
| Carried by | Phase A pre-tag row A4 (functualize-lambda) |
| Depends on | none |
| Related | `plugins/adapters/functualize-lambda/README.md` § *The event envelope*; `functualize.types.request_from_envelope` |

Written to the Shape Intent standard v3 (Confluence SD/3080295 v3, read 2026-11-28).

## 1. The shape at a glance

A Lambda event that carries a key the adapter does not read is **refused**. The adapter no
longer runs the job with its defaults and answers `200 Success`.

```text
>>> fat_handler({"job": "greet", "kwargs": {"name": "Old"}}, None)
{'statusCode': 400,
 'status': 'Invalid',
 'body': None,
 'error': "Unknown event key 'kwargs'. Job arguments go under 'arguments', "
          "for example {\"job\": \"greet\", \"arguments\": {...}}. "
          "Accepted keys: arguments, force, group_option_values, job, scope_id."}

>>> fat_handler({"job": "greet", "arguments": {"name": "New"}}, None)
{'statusCode': 200, 'status': 'Success', 'body': 'Hello, New!'}
```

The second call shows that the envelope documented today keeps working unchanged. §5 has
the exact shapes.

The refusal has the same response shape as the engine's refusal of an unknown
*argument*: `400`, `status: "Invalid"`, `body: null` and an `error` string. A caller that
already handles `Invalid` handles this case too.

## 2. Problem

Today, with the published example job `greet(name: str = "World")`, both handler shapes do this:

```text
>>> fat_handler({"job": "greet", "kwargs": {"name": "Old"}}, None)
{'statusCode': 200, 'status': 'Success', 'body': 'Hello, World!'}      # "Old" was dropped

>>> greet_handler({"kwargs": {"name": "Old"}}, None)                    # thin handler
{'statusCode': 200, 'status': 'Success', 'body': 'Hello, World!'}      # "Old" was dropped
```

`kwargs` was the event key for job parameters before the `arguments` envelope
replaced it. Three published pages still show it (§3). A caller who copies them gets a
**successful run of the wrong call**. Nothing in the response tells them their
arguments were ignored. A refusal would be better than that answer.

A typo does the same thing (`"argumnets"` → `200`, defaults). So does a field that
another surface accepts but Lambda does not read (`"run_tags"` → `200`, ignored).

## 3. Current reality

Measured on `origin/master` @ `d58500f76ba65ba169451e3cb4af3820e271e266`:

```text
{'job': 'greet', 'arguments': {'name': 'New'}}  -> {'statusCode': 200, 'status': 'Success', 'body': 'Hello, New!'}
{'job': 'greet', 'kwargs': {'name': 'Old'}}     -> {'statusCode': 200, 'status': 'Success', 'body': 'Hello, World!'}
{'job': 'greet', 'argumnets': {'name': 'Typo'}} -> {'statusCode': 200, 'status': 'Success', 'body': 'Hello, World!'}
{'job': 'greet', 'run_tags': {'door': 'wire'}}  -> {'statusCode': 200, 'status': 'Success', 'body': 'Hello, World!'}
{'job': 'greet', 'arguments': {'nme': 'x'}}     -> {'statusCode': 400, 'status': 'Invalid', 'body': None, 'error': "Unknown argument 'nme'. This job accepts: name"}
{'job': 'greet', 'arguments': 'not-an-object'}  -> {'statusCode': 500, 'body': "'arguments' must be a JSON object"}
thin {'kwargs': {'name': 'Old'}}                -> {'statusCode': 200, 'status': 'Success', 'body': 'Hello, World!'}
```

- The parser reads only four keys: `arguments`, `group_option_values`, `scope_id` and
  `force`. Every other key is never looked at
  (`src/functualize/_types/run_request.py:343-358`).
- The Lambda adapter hands the whole event to that parser
  (`plugins/adapters/functualize-lambda/src/functualize_lambda/__init__.py:65-75`). The fat
  handler reads `job` first (`:216-239`). The thin handler ignores `job` (`:196-202`).
- A wrong-typed field is reported as **500**, a server fault (`:202`, `:239`), although
  the fault is the caller's.
- `kwargs` is still published as the event key at:
  - `plugins/adapters/functualize-lambda/examples/lambda_handler/README.md:26,48`
  - `plugins/adapters/functualize-lambda/examples/lambda_handler/src/lambda_service/app.py:34` (docstring)
  - `docs/examples/project/lambda-handler.md:29,56`
- Two plugin tests send `kwargs` and assert `200`, which pins the defect
  (`plugins/adapters/functualize-lambda/tests/test_plugin.py:19,62`). One test sends
  `run_tags` and asserts `200` (`tests/test_request_envelope.py:42`).

## 4. Use cases

**UC-1: a caller sends the documented envelope (main path, unchanged).**
Actor: a service invoking the fat Lambda. Goal: run `process_order` with its order.

```text
>>> fat_handler({"job": "process_order", "arguments": {"order_id": "ORD-001", "amount": 99.99}}, None)
{'statusCode': 200, 'status': 'Success', 'body': {...}}
```

Outcome: the job runs with the caller's values. This works today and is not changed.

**UC-2: a caller copied the legacy example (refusal).**
Actor: a developer who followed an old README. Goal: run `greet` for "Old".

```text
>>> fat_handler({"job": "greet", "kwargs": {"name": "Old"}}, None)
{'statusCode': 400, 'status': 'Invalid', 'body': None,
 'error': "Unknown event key 'kwargs'. Job arguments go under 'arguments', for example {\"job\": \"greet\", \"arguments\": {...}}. Accepted keys: arguments, force, group_option_values, job, scope_id."}
```

Outcome: the job **does not run**. No run record is written. The message names the
rejected key and the key to use instead.

**UC-3: the thin handler gets a legacy or unrelated event (refusal, non-human actor).**
Actor: an AWS trigger or another service calling `greet_handler`.

```text
>>> greet_handler({"kwargs": {"name": "Old"}}, None)
{'statusCode': 400, 'status': 'Invalid', 'body': None,
 'error': "Unknown event key 'kwargs'. Job arguments go under 'arguments', for example {\"job\": \"greet\", \"arguments\": {...}}. Accepted keys: arguments, force, group_option_values, job, scope_id."}

>>> greet_handler({"job": "greet", "arguments": {"name": "New"}}, None)   # `job` accepted, still ignored
{'statusCode': 200, 'status': 'Success', 'body': 'Hello, New!'}
```

**UC-4: several unknown keys and a typo (refusal).**

```text
>>> fat_handler({"job": "greet", "argumnets": {"name": "x"}, "run_tags": {}}, None)
{'statusCode': 400, 'status': 'Invalid', 'body': None,
 'error': "Unknown event keys 'argumnets', 'run_tags'. Job arguments go under 'arguments', ... Accepted keys: arguments, force, group_option_values, job, scope_id."}
```

**UC-5: a wrong-typed field is the caller's fault, so it is a 400 (changed from 500).**

```text
>>> fat_handler({"job": "greet", "arguments": "not-an-object"}, None)
{'statusCode': 400, 'status': 'Invalid', 'body': None, 'error': "'arguments' must be a JSON object"}
```

An exception raised by the run itself is still `500` with `body: <message>`, unchanged.

## 5. The shape, surface by surface

| Surface | Change |
|---|---|
| Authoring / library API | *not touched*. `LambdaAdapter`, `run`, `make_handler` keep their signatures |
| Command line | *not touched* |
| Configuration | *not touched* |
| Wire (Lambda event / response) | below |
| UI | *not touched* |
| Errors and refusals | below |
| Generated or observable artifacts | a refused event writes **no** run record (the job never starts) |

**Accepted top-level event keys**, for both handler shapes: `job`, `arguments`,
`group_option_values`, `scope_id`, `force`. Any other key causes a refusal.

**Refusal response**, for an unknown key or a wrong-typed field:

```json
{"statusCode": 400, "status": "Invalid", "body": null, "error": "<message>"}
```

**Message for unknown keys**, in this order: the rejected key or keys, quoted and sorted;
the pointer to `arguments`; the accepted set, sorted.

```text
Unknown event key 'kwargs'. Job arguments go under 'arguments', for example {"job": "greet", "arguments": {...}}. Accepted keys: arguments, force, group_option_values, job, scope_id.
```

The example uses the job's own name. The thin handler uses its bound job's name.

**Unchanged:** a missing `job` on the fat handler (`400`, `body: "Missing required field 'job' in event: ..."`);
an exception from the run (`500`, `body: <message>`); and every successful or engine-decided
outcome (`_response`, the WIRE status table).

## 6. Diagrams

Structure (unchanged layering; the check is added inside the plugin):

```text
plugins/adapters/functualize-lambda          src/functualize/_types (stdlib-only)
  functualize_lambda.__init__                  run_request.py
  ├─ LambdaAdapter.run / make_handler ───┐     request_from_envelope()  ◄── also used by
  │                                      ▼                                   functualize-http
  └─ _envelope(event, job) ── [NEW] refuse keys ∉ {job} ∪ ENVELOPE ──► request_from_envelope()
                                  │ ValueError
                                  ▼
                       400 {"status": "Invalid", "error": …}
```

Behaviour (main refusal path):

```text
caller ──event──► LambdaAdapter.run
                    ├─ "job" missing?        → 400 Missing required field   (unchanged)
                    ├─ _envelope(event, job)
                    │    ├─ unknown key?     → ValueError → 400 Invalid     (NEW)
                    │    └─ wrong type?      → ValueError → 400 Invalid     (was 500)
                    └─ app.execute(request)
                         ├─ result           → _response → WIRE status      (unchanged)
                         └─ raises           → 500 body=str(exc)            (unchanged)
```

No new states.

## 7. Binding, provisional and illustrative

| Item | Mark |
|---|---|
| Unknown top-level keys are refused on fat **and** thin handlers | Binding |
| Accepted set `job, arguments, group_option_values, scope_id, force` | Binding |
| Refusal is `statusCode 400`, `status "Invalid"`, `body null`, `error <string>` | Binding |
| Wrong-typed field moves from `500` to `400 Invalid` | Binding |
| The message names every rejected key, names `arguments`, and lists the accepted set | Binding |
| Exact wording `Unknown event key(s) … Job arguments go under 'arguments', for example … Accepted keys: …` | Provisional |
| The job never starts on a refusal (no run record) | Binding |
| Missing-`job` response, run-exception `500`, success shapes | Binding (unchanged) |
| `greet`, `process_order`, `"Old"`, `"New"`, `ORD-001` | Illustrative |
| Docs and examples show `arguments`; no published Lambda event carries `kwargs` | Binding |

## 8. Boundaries and non-goals

- **HTTP is not touched.** It shares `request_from_envelope`, so a flat or legacy HTTP
  body is silently ignored in the same way. That is the HTTP plugin's own envelope-grammar
  work (K-A2 in its plugin-test-standard issue), which comes after the release. This row is
  scoped to Lambda.
- **Not in scope:** real AWS event shapes (direct invoke versus API Gateway proxy), an RIE
  container test, and the cold-start budget (K-A1, K-A6 and K-A7 come after the release).
- No alias: `kwargs` is **not** accepted as a synonym for `arguments`.
- The missing-`job` message and response shape are not changed.

| Surface | Owner | Rule |
|---|---|---|
| Which keys a Lambda event may carry | `functualize-lambda` | the allow-list lives next to `_envelope` |
| What each envelope field means and its type | core `request_from_envelope` | one parser for every wire door |
| Status code of a finished run | core WIRE table | unchanged |

## 9. Candidate models

**A — the Lambda adapter checks keys before the shared parser (selected).**

```python
_EVENT_KEYS = frozenset({"job", "arguments", "group_option_values", "scope_id", "force"})
def _envelope(payload, job_name):
    unknown = sorted(set(payload) - _EVENT_KEYS)
    if unknown: raise ValueError(_unknown_keys_message(unknown, job_name))
    return request_from_envelope(payload, job_name=job_name, surface="lambda")
```
UC-2 gives `400 Invalid`. HTTP is unchanged. The cost is that the accepted set is
written down twice: here, and implicitly in the parser. A parity test pins them
together (every parser field round-trips through the Lambda handler).

**B — core `request_from_envelope` refuses unknown keys for every wire door.**
UC-2 behaves the same on Lambda, and HTTP's flat `{"name": "Old"}` body also becomes a
400. Rejected **for this row**: it changes HTTP behaviour inside a Lambda-scoped pre-tag
fix, and the allowed sets differ per door anyway (`job` is in the Lambda event but in
the HTTP URL path). It stays the natural follow-up when the HTTP envelope-grammar work
lands.

**C — log a warning and keep `200`.**
UC-2 still answers `200 Success` with `Hello, World!`. Rejected: the caller never sees a
log, so the answer is still silently wrong.

**D — accept `kwargs` as an alias for `arguments`.**
UC-2 answers `200`, `Hello, Old!`. Rejected: it reopens a deliberate breaking change, and
the wire would have two spellings for good. It also fixes only this one key, not typos.

## 10. Hypotheses and risks

- **H1:** No supported caller sends extra top-level keys. Risk: a **thin** handler wired
  directly to an AWS trigger (an EventBridge schedule, SQS, or an API Gateway proxy) gets
  the trigger's own event (`version`, `source`, `detail`, `headers` and so on). It ran the
  job with defaults before and is refused after this change. See open question Q1.
- **H2:** A future envelope field added to the core parser without being added to the
  Lambda allow-list would be refused loudly. The parity test catches that in CI. It is
  never silent.
- **H3:** No caller depends on the `500` for a wrong-typed field.

## 11. Next falsifiable experiment

```bash
uv run python - <<'EOF'
from functualize.app.core import FunctualizeApp
from functualize_lambda import LambdaAdapter
app = FunctualizeApp("demo")
def greet(name: str = "World") -> str: return f"Hello, {name}!"
app.register_dynamic_job("greet", greet)
a = LambdaAdapter(); a(app)
print(a.run({"job": "greet", "kwargs": {"name": "Old"}}, None))
print(a.run({"job": "greet", "arguments": {"name": "New"}}, None))
print(a.make_handler("greet")({"kwargs": {"name": "Old"}}, None))
EOF
```

Expected after the change: `400 Invalid` naming `'kwargs'` and `'arguments'`, then
`200 Hello, New!`, then `400 Invalid`. **Falsified** if any `kwargs` line answers `200`,
or if the documented envelope stops answering `200`.

## 12. Open questions

**Q1 — Is the thin handler strict too?**

```text
# (a) strict on both, recommended
greet_handler({"version": "0", "source": "aws.events", "detail": {}}, None)  → 400 Invalid
# workaround: configure the EventBridge target with constant input {} or {"arguments": {...}}

# (b) strict on fat only
greet_handler({"kwargs": {"name": "Old"}}, None)  → 200 'Hello, World!'   (the defect survives on thin)
```

Recommendation: **(a)**. The `kwargs` defect reproduces on the thin handler too, and real
trigger shapes are the explicit post-release K-A1 work. Either way, the fat handler,
the docs and the examples go ahead.

**Q2 — Is the 500→400 move for wrong-typed fields in this row?** Recommendation: yes.
Two different status codes for one class of caller fault would be incoherent. If the
answer is no, the unknown-key refusal still ships as `400`, and the wrong-type case stays
`500`.

## 13. Outcome

Pending maintainer approval.
