"""Run from a plugin checkout without installing into global Python."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from framecheck.cli import main

if __name__ == "__main__":
    raise SystemExit(main())
