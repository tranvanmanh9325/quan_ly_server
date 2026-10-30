#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tools/acceptance_run.py — CLI Entrypoint for Acceptance Test Runner.
Milestone M0 / M6: Frozen Acceptance Judge Infrastructure.

Forwards all command-line calls directly to tools.acceptance.acceptance_run.main().
Usage:
  python tools/acceptance_run.py --suite public --out <dir>
  python tools/acceptance_run.py --suite sabotage --out <dir>
"""

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tools.acceptance.acceptance_run import main

if __name__ == "__main__":
    main()
