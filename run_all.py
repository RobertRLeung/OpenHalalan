#!/usr/bin/env python3
"""
OpenHalalan: one-click replication.

    python run_all.py              # rebuild both datasets from the committed raw scrapes, then audit
    python run_all.py --scrape     # also re-scrape COMELEC first (slow)
    python run_all.py --audit-only # just re-run the audit

Thin wrapper around data/make.py, which is where the pipeline actually lives.
"""

import subprocess
import sys
from pathlib import Path

MAKE = Path(__file__).resolve().parent / "data" / "make.py"

if __name__ == "__main__":
    sys.exit(subprocess.run([sys.executable, str(MAKE), *sys.argv[1:]]).returncode)
