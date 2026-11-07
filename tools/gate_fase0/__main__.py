"""`python -m gate_fase0`. Ver `cli.py`."""

from __future__ import annotations

import sys

from .cli import principal

if __name__ == "__main__":
    sys.exit(principal())
