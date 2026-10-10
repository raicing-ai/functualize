# spec.md — an optional `Stdin` parameter on a pipe that carries nothing

## Behaviour

A job with an optional `Stdin` parameter must never wait forever on stdin that
carries nothing. "Nothing was piped" and "an empty stream was piped" are
different facts about the same command line; the job must be able to tell them
apart, promptly, without a hang.

What the job receives, for one unresolved `Stdin` parameter:

| stdin | the parameter receives |
|---|---|
| a plain TTY — nothing was piped | its own default (Rule 4, unchanged) |
| a pipe that is never written (`sleep 30 \| func s`) | its own default, promptly — never waiting for the pipe |
| an empty stream that is present (`< /dev/null`, a closed pipe) | the empty string `""` |
| real piped data | that data, intact — multi-line and encodings included |
| nothing piped, and the parameter has no default | the ordinary required-argument failure — never a hang |

An iterator/iterable-typed `Stdin` parameter keeps receiving the lazy NDJSON
stream on any non-TTY stdin. Waiting for that producer is the type's documented
contract — the one opt-in to waiting this feature recognises — so
`func extract | func transform` keeps flowing row-wise even when the upstream
starts slowly.

The prompt door of an agent run / MCP session reads the same stdin
classification but projects it differently: its TTY verdict is unchanged
(prompts happen at a TTY), and on anything else it stays unavailable — the
`default` / `InputNotAvailable` behaviour — never blocking. Both doors are
pinned together by one test so they agree rather than contradict.

Nothing user-visible is added: no flag, no timeout, no knob.

## The decision this pins

"Nothing was piped" and "an empty stream was piped" resolve differently: the
parameter's own default survives the first, the empty string wins the second.
An empty document is still a document — `""` is what the user actually piped —
so it is deposited like any other piped content instead of the job's default
silently standing in for it. Today the two states are indistinguishable in the
worst way: a never-written pipe hangs the process outright, and where an empty
stream does arrive, `""` overwrites the default without being documented
anywhere.

## Acceptance criteria

1. `sleep 30 | func s` — an optional `Stdin` parameter, stdin a pipe that is
   never written — returns promptly. Bounded in a test with a wall-clock
   assertion, not by inspection. A blocking read happens only for the lazy
   stream of an iterator-typed parameter: the explicit, documented opt-in.
2. An empty-but-present stream (`< /dev/null`, a closed pipe) is not the same
   as "data was piped": the parameter is set to `""`, the default is what
   survives when nothing was piped, and both sides are pinned in tests.
3. Real piped data still arrives intact, including the multi-line and encoding
   cases.
4. The same rule holds on the agent-run and MCP paths (`stdin_collector.py`):
   the two tests agree rather than contradicting each other.
5. `func s` on a plain TTY keeps today's Rule 4 behaviour: the parameter's own
   default wins.

## Platform note

The non-blocking probe is the POSIX one (`select.poll` — the idiom
`_engine/capabilities/shell.py` already documents and uses, chosen over
`select.select` for its FD_SETSIZE ceiling). Windows has no `select.poll` and
its `select()` is sockets-only; there, stdin keeps today's eager rule exactly —
no regression by construction, and no claim that the new promptness reaches it.
The acceptance criteria are pinned by tests on the POSIX CI matrix.

## Out of scope

Interactive prompting, gate input and the `Stdin` type's schema. If the fix
needed a documented knob (a timeout, or an explicit "wait for stdin" flag),
that would be a user-visible surface decision and would go back to the shape
gate. This design adds none, so it does not.
