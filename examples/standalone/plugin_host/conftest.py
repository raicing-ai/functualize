"""Put this example's root on `sys.path`, so its tests can import it.

`examples/conftest.py` adds each directory that *contains* a `test_*.py`, which
is `tests/` here. The module under test sits one level up, where a reader looks
for it rather than among the tests — so this file adds that.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
