#!/usr/bin/env python3
import runpy
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
INSTALLER = ROOT / "skills" / "liuhui-badminton-coach" / "scripts" / "install.py"


if __name__ == "__main__":
    runpy.run_path(str(INSTALLER), run_name="__main__")
