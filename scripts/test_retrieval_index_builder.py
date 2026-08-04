#!/usr/bin/env python3

import importlib.util
import random
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PATH = ROOT / "scripts" / "build_retrieval_index.py"


def load_builder():
    spec = importlib.util.spec_from_file_location("retrieval_builder", PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class RetrievalIndexBuilderTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.builder = load_builder()
        cls.lexicon = {
            "反手", "反手高远", "高远球", "击球点", "拍面", "挡网", "双打",
            "接杀", "力量", "发力", "转体", "放松",
        }
        cls.prefix, cls.normalized = cls.builder.build_lexicon_prefix_index(
            cls.lexicon
        )

    def assert_matches_naive(self, text):
        normalized_text = self.builder.normalize(text)
        expected = {
            term: normalized_text.count(self.builder.normalize(term))
            for term in sorted(self.lexicon)
            if self.builder.normalize(term) in normalized_text
        }
        actual = self.builder.lexicon_term_frequencies(
            normalized_text, self.prefix, self.normalized
        )
        self.assertEqual(actual, expected)

    def test_prefix_matcher_preserves_exact_counts(self):
        self.assert_matches_naive("双打接杀挡网，拍面和击球点都会影响反手高远球发力。")

    def test_prefix_matcher_matches_naive_for_deterministic_fuzz(self):
        randomizer = random.Random(20260802)
        terms = sorted(self.lexicon)
        for _ in range(100):
            text = "。".join(randomizer.choices(terms, k=randomizer.randint(0, 20)))
            self.assert_matches_naive(text)


if __name__ == "__main__":
    unittest.main()
