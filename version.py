"""
Version string — get_version() returns "<git-describe> <YYMMDD>" for display in the window title.
"""
from __future__ import annotations

import subprocess
import os
from datetime import date

def get_version() -> str:
    try:
        git = subprocess.check_output(
            ["git", "describe", "--tags", "--always", "--dirty"],
            cwd=os.path.dirname(os.path.abspath(__file__)),
            text=True,
            stderr=subprocess.DEVNULL,
        ).strip()
    except Exception:
        git = "dev"
    return f"{git} {date.today().strftime('%y%m%d')}"
