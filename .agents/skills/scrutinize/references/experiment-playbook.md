# Experiment Playbook

Mini-experiments prove claims that can't be verified by reading code alone. They are the nuclear option — use only when code reading and static analysis are insufficient, and the claim is load-bearing enough to warrant the effort.

---

## When to Experiment

Run an experiment ONLY when ALL of these are true:

1. The claim is **load-bearing** (the design fails if it's wrong)
2. The claim is **UNTESTABLE** via code reading alone
3. The experiment is **feasible** with available tools (no special hardware, no production access)
4. The experiment can run in **< 5 minutes** (wall clock)
5. The user hasn't explicitly restricted experiments (`quick` mode disables them)

Common experiment-worthy claims:
- "Importing module X takes <N>ms" — timing claims about import cost
- "These two interfaces are compatible" — duck-typing / protocol claims
- "This asyncio pattern doesn't deadlock" — concurrency claims
- "The TUI component handles this input sequence" — UI behavior claims
- "This signal handling works on macOS and Linux" — platform claims
- "This frame format can be parsed in <N> lines" — complexity claims

---

## Experiment Protocol

### 1. Design

Each experiment has:
- **Hypothesis**: The specific claim being tested (one per experiment)
- **Method**: The minimal code/commands that would confirm or deny it
- **Expected result if claim is TRUE**: What output proves the claim
- **Expected result if claim is FALSE**: What output disproves the claim
- **Cleanup**: How to remove all artifacts

### 2. Setup

```bash
# Create isolated temp directory
EXPERIMENT_DIR=$(mktemp -d /tmp/scrutinize-exp-XXXXXX)
cd "$EXPERIMENT_DIR"

# If the experiment needs project dependencies:
# Option A: import from the installed package (preferred — tests real behavior)
# Option B: create a minimal venv with just what's needed
# Option C: use the project's own interpreter (uv run)
```

### 3. Execute

Run the experiment. Record:
- The exact command(s) run
- The complete output (stdout + stderr)
- The exit code
- The wall-clock time

### 4. Interpret

Map the result to a verdict:
- Result matches "TRUE" expectation → claim is CONFIRMED with experiment evidence
- Result matches "FALSE" expectation → claim is FALSIFIED with experiment evidence
- Result is ambiguous or errors → claim remains UNTESTABLE; record what went wrong

### 5. Cleanup

```bash
rm -rf "$EXPERIMENT_DIR"
```

---

## Experiment Templates

### Template: Import Timing

**Use for:** "Module X imports in <N>ms" / "Boot time is ~Xms"

```python
# experiment_import_timing.py
import time
import sys

# Measure baseline (empty import)
start = time.perf_counter_ns()
import importlib
baseline = time.perf_counter_ns() - start

# Measure target import
start = time.perf_counter_ns()
import TARGET_MODULE  # replace with actual
elapsed = time.perf_counter_ns() - start

print(f"Baseline: {baseline / 1_000_000:.1f}ms")
print(f"Target: {elapsed / 1_000_000:.1f}ms")
print(f"Delta: {(elapsed - baseline) / 1_000_000:.1f}ms")
```

Run with: `uv run python experiment_import_timing.py` (use project's interpreter for accuracy)

---

### Template: Interface Compatibility

**Use for:** "Class X satisfies Protocol Y" / "Function F can be called with args A"

```python
# experiment_interface_check.py
from typing import runtime_checkable, Protocol
import sys
sys.path.insert(0, 'PATH_TO_PROJECT_SRC')

# Import the actual class/protocol
from MODULE import ActualClass, ClaimedProtocol

# Check structural compatibility
if isinstance(ActualClass(), ClaimedProtocol):
    print("COMPATIBLE: ActualClass satisfies ClaimedProtocol")
else:
    # Find what's missing
    required = set(dir(ClaimedProtocol)) - set(dir(object))
    actual = set(dir(ActualClass))
    missing = required - actual
    print(f"INCOMPATIBLE: missing {missing}")
```

---

### Template: Concurrency Safety

**Use for:** "This pattern doesn't deadlock" / "asyncio + threads works for this"

```python
# experiment_concurrency.py
import asyncio
import threading
import time

TIMEOUT = 5  # seconds — if we reach this, likely deadlocked

async def simulate_claimed_pattern():
    """Reproduce the exact pattern the proposal claims works."""
    # ... minimal reproduction ...
    pass

async def main():
    try:
        await asyncio.wait_for(simulate_claimed_pattern(), timeout=TIMEOUT)
        print("PASSED: Pattern completed without deadlock")
    except asyncio.TimeoutError:
        print("FAILED: Pattern appears to deadlock (timeout reached)")
    except Exception as e:
        print(f"ERROR: {type(e).__name__}: {e}")

asyncio.run(main())
```

---

### Template: Wire Protocol / Frame Format

**Use for:** "This protocol can be implemented in <N> lines" / "Framing is ~20 lines"

```python
# experiment_protocol.py
import struct

# Implement the claimed format
def encode_frame(frame_type: int, payload: bytes) -> bytes:
    """The proposal claims this is ~20 lines total for encode + decode."""
    return struct.pack(">BI", frame_type, len(payload)) + payload

def decode_frame(data: bytes) -> tuple[int, bytes]:
    frame_type = data[0]
    length = struct.unpack(">I", data[1:5])[0]
    payload = data[5:5+length]
    return frame_type, payload

# Test round-trip
test_payload = b'{"job": "deploy", "args": {}}'
encoded = encode_frame(0x10, test_payload)
decoded_type, decoded_payload = decode_frame(encoded)

assert decoded_type == 0x10
assert decoded_payload == test_payload
print(f"PASSED: Round-trip works. Encode: {len(encode_frame.__code__.co_code)} bytecode ops")
print(f"Total implementation: ~{sum(1 for _ in open(__file__) if _.strip())} lines (including tests)")
```

---

### Template: Platform Behavior

**Use for:** "Unix sockets work for this" / "Signal handling behaves like X"

```python
# experiment_platform.py
import sys
import os
import platform

print(f"Platform: {platform.system()} {platform.machine()}")
print(f"Python: {sys.version}")

# Test the specific platform claim
# e.g., Unix socket availability
try:
    import socket
    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    sock.close()
    print("PASSED: AF_UNIX available")
except (AttributeError, OSError) as e:
    print(f"FAILED: AF_UNIX not available: {e}")
```

---

### Template: TUI / UI Behavior

**Use for:** "The TUI handles this interaction" / "This widget renders correctly"

For Textual TUI claims, use the project's test infrastructure:

```python
# experiment_tui.py
"""
Minimal Textual pilot test to verify a UI claim.
Run with: uv run pytest experiment_tui.py -v
"""
import pytest
from textual.app import App, ComposeResult
from textual.widgets import Static

# Reproduce the minimal scenario from the claim
class MinimalApp(App):
    def compose(self) -> ComposeResult:
        yield Static("test")

@pytest.fixture
def app():
    return MinimalApp()

async def test_claimed_behavior(app):
    """The proposal claims: <specific behavior>"""
    async with app.run_test() as pilot:
        # Simulate the interaction the proposal assumes works
        # ... pilot.press(), pilot.click(), etc.
        # Assert the claimed outcome
        pass
```

---

## Recording Experiment Results

In the scrutiny report, each experiment gets a block:

```markdown
### Experiment: [CLAIM-ID] <claim statement>

- **Hypothesis**: <what we're testing>
- **Method**: <commands run, with exact invocation>
- **Result**:
  ```
  <complete output>
  ```
- **Interpretation**: CONFIRMED | FALSIFIED | INCONCLUSIVE
- **Notes**: <anything relevant — timing, platform, caveats>
```

---

## Safety Boundaries

**Never:**
- Install packages into the user's project environment
- Modify project files as part of an experiment
- Run experiments that require network access to external services
- Run experiments that write to project directories
- Run experiments that take longer than 60 seconds
- Run experiments that require elevated privileges

**Always:**
- Use a temporary directory
- Clean up after yourself
- Record the exact commands so the user can reproduce
- Note if an experiment is platform-specific
- Warn if an experiment's result might differ in CI vs local dev
