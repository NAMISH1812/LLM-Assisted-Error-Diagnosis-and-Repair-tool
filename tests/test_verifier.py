"""Unit tests for the fix verification layer."""

import unittest

from toyc.pipeline import compile_source
from toyc.verifier import VerificationStatus, compute_unified_diff, verify_fix


class VerifierTests(unittest.TestCase):
    def test_verified_when_fix_compiles_clean(self):
        orig = "int main() {\n    int a = 10\n    return a;\n}"
        fixed = "int main() {\n    int a = 10;\n    return a;\n}"
        res = compile_source(orig)
        diag = res.diagnostics[0]

        verif = verify_fix(orig, fixed, diag, "test.toy")
        self.assertEqual(verif.status, VerificationStatus.VERIFIED)
        self.assertTrue(verif.is_verified)
        self.assertIn("+    int a = 10;", verif.diff)

    def test_unverified_when_same_error_persists(self):
        orig = "int main() {\n    int a = 10\n    return a;\n}"
        broken_fix = "int main() {\n    int a = 10\n    return a + 1;\n}"
        res = compile_source(orig)
        diag = res.diagnostics[0]

        verif = verify_fix(orig, broken_fix, diag, "test.toy")
        self.assertEqual(verif.status, VerificationStatus.UNVERIFIED_SAME_ERROR)
        self.assertFalse(verif.is_verified)

    def test_unverified_when_fix_introduces_new_error(self):
        orig = "int main() {\n    int a = 10\n    return a;\n}"
        new_err_fix = "int main() {\n    int a = 10;\n    return a + missing;\n}"
        res = compile_source(orig)
        diag = res.diagnostics[0]

        verif = verify_fix(orig, new_err_fix, diag, "test.toy")
        self.assertEqual(verif.status, VerificationStatus.UNVERIFIED_NEW_ERROR)
        self.assertFalse(verif.is_verified)

    def test_empty_fix_rejected(self):
        orig = "int main() { return 0; }"
        res = compile_source("int main() { 10 = x; }")
        diag = res.diagnostics[0]

        verif = verify_fix(orig, "   \n  ", diag, "test.toy")
        self.assertEqual(verif.status, VerificationStatus.INVALID_EMPTY)
        self.assertFalse(verif.is_verified)

    def test_diff_generation(self):
        diff = compute_unified_diff("line1\nline2\n", "line1\nline_changed\n", "foo.toy")
        self.assertIn("-line2", diff)
        self.assertIn("+line_changed", diff)


if __name__ == "__main__":
    unittest.main()
