#!/usr/bin/env python3
import importlib.util
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DOCTOR_PATH = ROOT / "skills" / "liuhui-badminton-coach" / "scripts" / "doctor.py"


def load_doctor():
    spec = importlib.util.spec_from_file_location("liuhui_skill_doctor", DOCTOR_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


if __name__ == "__main__":
    if "--repo-root" not in sys.argv:
        sys.argv.extend(["--repo-root", str(ROOT)])
    raise SystemExit(load_doctor().main(default_profile="maintainer"))
