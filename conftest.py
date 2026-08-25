"""Ensures the repo root is importable without requiring `pip install -e .` first,
so `python -m pytest` works immediately after clone."""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
