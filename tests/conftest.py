"""Put the repository root on the import path.

The modules live flat at the root (CLAUDE.md §3), so the tests need the root importable
without installing anything. Nothing else belongs in here.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
