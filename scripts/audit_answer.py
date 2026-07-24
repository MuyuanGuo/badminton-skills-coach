#!/usr/bin/env python3
"""Repository entry point for the portable final-answer auditor."""

import importlib.util
from pathlib import Path


RUNTIME_PATH = (
    Path(__file__).resolve().parents[1]
    / "skills"
    / "liuhui-badminton-coach"
    / "scripts"
    / "audit_answer.py"
)
SPEC = importlib.util.spec_from_file_location("liuhui_answer_auditor", RUNTIME_PATH)
RUNTIME = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(RUNTIME)

audit_answer = RUNTIME.audit_answer
canonical_json_digest = RUNTIME.canonical_json_digest
load_json = RUNTIME.load_json
load_rules = RUNTIME.load_rules
validate_packet_binding = RUNTIME.validate_packet_binding


if __name__ == "__main__":
    RUNTIME.main()
