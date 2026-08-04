"""Ensure this directory's weather.py is importable as 'weather'."""

import sys
from pathlib import Path

# Remove any conflicting 'weather' from other step directories
this_dir = str(Path(__file__).parent)
sys.path = [p for p in sys.path if "step" not in p or p == this_dir]
sys.path.insert(0, this_dir)

# Force reimport
sys.modules.pop("weather", None)
