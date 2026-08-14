import importlib.util
import sys
import unittest
from pathlib import Path


MODULE_PATH = Path(__file__).resolve().parents[1] / "run_pipeline.py"
SPEC = importlib.util.spec_from_file_location("run_pipeline", MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


class PipelineHelperTests(unittest.TestCase):
    def test_printed_page_candidate_from_first_lines(self):
        self.assertEqual(MODULE.printed_page_candidate("\n20\nchapter"), 20)

    def test_printed_page_candidate_ignores_embedded_number(self):
        self.assertIsNone(MODULE.printed_page_candidate("chapter 20\ntext"))

    def test_low_native_text_requires_review(self):
        reasons = MODULE.review_reasons(
            native_chars=103,
            markdown="x" * 500,
            low_native_threshold=200,
        )
        self.assertIn("low_native_text", reasons)

    def test_normal_page_does_not_require_review(self):
        reasons = MODULE.review_reasons(
            native_chars=800,
            markdown="normal content " * 30,
            low_native_threshold=200,
        )
        self.assertEqual(reasons, [])


if __name__ == "__main__":
    unittest.main()
