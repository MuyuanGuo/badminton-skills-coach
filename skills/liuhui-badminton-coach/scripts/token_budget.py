#!/usr/bin/env python3
"""Deterministic conservative token estimates for Codex-facing text budgets."""

from __future__ import annotations

import json
import math
import re


ESTIMATOR_ID = "codex-conservative-unicode-v1"
_CJK = re.compile(
    r"[\u2e80-\u2fff\u3040-\u30ff\u3400-\u4dbf\u4e00-\u9fff\uac00-\ud7af]"
)
_ASCII_RUN = re.compile(r"[A-Za-z0-9_]+")


def estimate_text_tokens(text):
    """Return a reproducible upper-oriented estimate without external packages.

    Codex model tokenizers are versioned outside this repository. This estimator
    therefore reports its identity with every gate, counts CJK/Kana/Hangul per
    code point, ASCII word runs at no better than four characters per token, and
    remaining non-whitespace punctuation/symbols individually.
    """

    value = str(text)
    cjk = len(_CJK.findall(value))
    without_cjk = _CJK.sub(" ", value)
    ascii_runs = _ASCII_RUN.findall(without_cjk)
    ascii_tokens = sum(max(1, math.ceil(len(run) / 4)) for run in ascii_runs)
    remainder = _ASCII_RUN.sub("", without_cjk)
    symbol_tokens = sum(not character.isspace() for character in remainder)
    return int(cjk + ascii_tokens + symbol_tokens)


def estimate_json_tokens(payload):
    return estimate_text_tokens(
        json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
    )
