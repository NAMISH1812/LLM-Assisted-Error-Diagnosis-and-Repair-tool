"""Unit tests for the evaluation suite and comparative study."""

import unittest

from toyc.evaluation import (
    BENCHMARK_DIR,
    format_evaluation_report,
    run_benchmark_item,
    run_comparative_study,
    run_evaluation_suite,
)


class EvaluationSuiteTests(unittest.TestCase):
    def test_all_20_benchmarks_exist(self):
        files = list(BENCHMARK_DIR.glob("*.toy"))
        self.assertGreaterEqual(len(files), 20)

    def test_single_benchmark_run(self):
        sample = BENCHMARK_DIR / "01_syntax_missing_semicolon.toy"
        res = run_benchmark_item(sample, mode="typed", offline=True)
        self.assertEqual(res.error_code, "SYN_MISSING_SEMICOLON")
        self.assertTrue(res.is_verified)
        self.assertGreaterEqual(res.explanation_score, 5.0)

    def test_full_evaluation_suite(self):
        summary = run_evaluation_suite(mode="typed", offline=True)
        self.assertEqual(summary.total_benchmarks, 20)
        self.assertGreaterEqual(summary.verification_rate, 90.0)
        self.assertGreaterEqual(summary.average_explanation_score, 6.5)

    def test_comparative_study_and_markdown_report(self):
        study = run_comparative_study(offline=True)
        self.assertIn("typed", study)
        self.assertIn("generic", study)
        report = format_evaluation_report(study)
        self.assertIn("Comparative Evaluation Report", report)
        self.assertIn("Verified Fix Rate", report)
        self.assertIn("Ablation Study", report)


if __name__ == "__main__":
    unittest.main()
