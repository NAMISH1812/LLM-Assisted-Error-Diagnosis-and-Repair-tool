"""Unit tests for semantic analysis (symbol table, scopes, type checking)."""

import unittest

from toyc.errors import ErrorCode
from toyc.pipeline import compile_source


def compile_errors(src: str):
    res = compile_source(src)
    assert res.diagnostics, f"expected semantic errors, but compilation succeeded on:\n{src}"
    return res.diagnostics


def compile_ok(src: str):
    res = compile_source(src)
    assert res.ok, f"unexpected errors: {[d.message for d in res.diagnostics]}"
    return res


class SemanticAnalysisTests(unittest.TestCase):
    def test_valid_program_passes(self):
        src = """
        int global_var = 10;
        bool is_positive(int n) {
            return n > 0;
        }
        int main() {
            int a = 5;
            if (is_positive(a)) {
                int b = a + global_var;
                return b;
            }
            return 0;
        }
        """
        res = compile_ok(src)
        self.assertIsNotNone(res.symbols)
        self.assertIn("global_var", res.symbols.global_scope.symbols)
        self.assertIn("is_positive", res.symbols.global_scope.symbols)

    def test_undeclared_variable(self):
        errs = compile_errors("int main() { return x + 1; }")
        self.assertEqual(errs[0].code, ErrorCode.SEM_UNDECLARED_VARIABLE)
        self.assertEqual(errs[0].details["name"], "x")
        self.assertEqual(errs[0].line, 1)

    def test_undeclared_variable_spelling_suggestion(self):
        src = """
        int main() {
            int counter = 10;
            return conter + 1;
        }
        """
        errs = compile_errors(src)
        self.assertEqual(errs[0].code, ErrorCode.SEM_UNDECLARED_VARIABLE)
        self.assertEqual(errs[0].details["suggestion"], "counter")
        self.assertIn("counter", errs[0].hint)

    def test_duplicate_declaration_in_same_scope(self):
        src = """
        int main() {
            int x = 1;
            int x = 2;
            return x;
        }
        """
        errs = compile_errors(src)
        self.assertEqual(errs[0].code, ErrorCode.SEM_DUPLICATE_DECLARATION)
        self.assertEqual(errs[0].line, 4)
        self.assertEqual(len(errs[0].related), 1)
        self.assertEqual(errs[0].related[0].line, 3)

    def test_inner_scope_shadowing_is_allowed(self):
        src = """
        int main() {
            int x = 1;
            if (true) {
                int x = 2;
                return x;
            }
            return x;
        }
        """
        res = compile_ok(src)
        self.assertTrue(res.ok)

    def test_arithmetic_requires_int_operands(self):
        errs = compile_errors("int main() { int a = 5 + true; return a; }")
        self.assertEqual(errs[0].code, ErrorCode.SEM_TYPE_MISMATCH)
        self.assertEqual(errs[0].details["expected_type"], "int")
        self.assertEqual(errs[0].details["actual_type"], "bool")

    def test_logical_requires_bool_operands(self):
        errs = compile_errors("int main() { bool b = true && 10; return 0; }")
        self.assertEqual(errs[0].code, ErrorCode.SEM_TYPE_MISMATCH)
        self.assertEqual(errs[0].details["expected_type"], "bool")
        self.assertEqual(errs[0].details["actual_type"], "int")

    def test_if_condition_must_be_bool(self):
        errs = compile_errors("int main() { int x = 1; if (x) return 0; return 1; }")
        self.assertEqual(errs[0].code, ErrorCode.SEM_TYPE_MISMATCH)
        self.assertEqual(errs[0].details["expected_type"], "bool")
        self.assertEqual(errs[0].details["actual_type"], "int")
        self.assertIn("explicit", errs[0].hint)

    def test_while_condition_must_be_bool(self):
        errs = compile_errors("int main() { while (1) { return 0; } return 1; }")
        self.assertEqual(errs[0].code, ErrorCode.SEM_TYPE_MISMATCH)
        self.assertEqual(errs[0].details["expected_type"], "bool")

    def test_equality_requires_same_type(self):
        errs = compile_errors("int main() { bool b = (5 == true); return 0; }")
        self.assertEqual(errs[0].code, ErrorCode.SEM_TYPE_MISMATCH)
        self.assertIn("cannot compare 'int' with 'bool'", errs[0].message)

    def test_assignment_type_mismatch(self):
        errs = compile_errors("int main() { int x = 0; x = true; return x; }")
        self.assertEqual(errs[0].code, ErrorCode.SEM_TYPE_MISMATCH)
        self.assertEqual(errs[0].details["expected_type"], "int")
        self.assertEqual(errs[0].details["actual_type"], "bool")

    def test_variable_cannot_have_void_type(self):
        errs = compile_errors("int main() { void v; return 0; }")
        self.assertEqual(errs[0].code, ErrorCode.SEM_INVALID_VOID)

    def test_return_mismatch_typed_function(self):
        errs = compile_errors("int main() { return true; }")
        self.assertEqual(errs[0].code, ErrorCode.SEM_RETURN_MISMATCH)
        self.assertEqual(errs[0].details["expected_type"], "int")
        self.assertEqual(errs[0].details["actual_type"], "bool")

    def test_return_mismatch_void_function(self):
        errs = compile_errors("void run() { return 5; }")
        self.assertEqual(errs[0].code, ErrorCode.SEM_RETURN_MISMATCH)
        self.assertEqual(errs[0].details["expected_type"], "void")

    def test_undefined_function(self):
        errs = compile_errors("int main() { return helper(); }")
        self.assertEqual(errs[0].code, ErrorCode.SEM_UNDEFINED_FUNCTION)
        self.assertEqual(errs[0].details["name"], "helper")

    def test_calling_variable_as_function(self):
        errs = compile_errors("int main() { int f = 10; return f(); }")
        self.assertEqual(errs[0].code, ErrorCode.SEM_NOT_CALLABLE)

    def test_argument_count_mismatch(self):
        src = """
        int add(int a, int b) { return a + b; }
        int main() { return add(1); }
        """
        errs = compile_errors(src)
        self.assertEqual(errs[0].code, ErrorCode.SEM_ARGUMENT_MISMATCH)
        self.assertEqual(errs[0].details["expected_count"], 2)
        self.assertEqual(errs[0].details["actual_count"], 1)

    def test_argument_type_mismatch(self):
        src = """
        int add(int a, int b) { return a + b; }
        int main() { return add(1, true); }
        """
        errs = compile_errors(src)
        self.assertEqual(errs[0].code, ErrorCode.SEM_ARGUMENT_MISMATCH)
        self.assertEqual(errs[0].details["expected_type"], "int")
        self.assertEqual(errs[0].details["actual_type"], "bool")

    def test_functions_callable_before_definition(self):
        src = """
        int main() { return helper(); }
        int helper() { return 42; }
        """
        res = compile_ok(src)
        self.assertTrue(res.ok)


if __name__ == "__main__":
    unittest.main()
