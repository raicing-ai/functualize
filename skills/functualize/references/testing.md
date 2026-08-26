# Testing jobs

A job is a plain function, so it is directly callable in a test. What makes it
testable is that every side channel arrives as an injected capability, and each
has a test double in `functualize.testing`.

## The doubles

```python
from functualize.testing import (
    TestRunContext,   # stands in for RunContext
    CapturingLog,     # records log calls for assertion
    MockInvoke,       # stubs job-to-job invocation
    FakeShell,        # records shell commands, never executes
    FakeShellCall,    # one recorded FakeShell invocation
    FakeStdout,       # captures emit()/write()
    AutoPrompt,       # answers prompts without a terminal
    NoopPerf,         # discards timing marks
)
```

Confirm against the installed version:

```python
import functualize.testing as t; print(t.__all__)
```

## Shape of a test

Call the function directly, passing doubles for exactly the capabilities its
signature declares:

```python
def test_deploy_emits_status():
    log = CapturingLog()
    out = FakeStdout()
    sh = FakeShell()

    deploy(DeployConfig(region="us-west-2"), TestRunContext(), log, sh, out)

    assert any("deploying" in str(m) for m in log.messages)
    assert sh.calls[0].command.startswith("kubectl")
    assert out.emitted == [{"status": "ok"}]
```

Check the exact attribute names on each double before asserting — they are the
API surface of the test, and guessing them is the usual source of a failing test
that looks correct.

## What to assert

Prefer asserting on the **capability record** rather than on captured stdout.
`FakeStdout` sees the structured value passed to `emit()`, so a test asserts on
`{"status": "ok"}` rather than on serialized text that changes with `--output`.

`FakeShell` records rather than executes, which is what makes a job with side
effects safe to unit test. Assert on the recorded `FakeShellCall`s.

## Wiring, not just behavior

Passing a test does not prove the job is reachable. A job can be correct, fully
unit-tested, and undiscovered — see [discovery.md](discovery.md). Verify the
production path separately:

```bash
func builtin info          # the job appears
func builtin why <job>     # if it does not
```

The project's own guidance on this is `contributor/guides/wiring-discipline.md`:
name every path that reaches your code and break each once to prove a test
notices. That discipline exists because capabilities shipped built, unit-tested,
and unreachable.

## Where tests live

Mirror the domain structure rather than inventing `unit/` or `properties/`
directories. In a functualize project the convention is a test module beside the
job package; in this framework's own repo the rules are in
`contributor/reference/testing-strategy.md`.
