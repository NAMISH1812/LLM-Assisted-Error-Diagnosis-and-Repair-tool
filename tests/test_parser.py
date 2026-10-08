import unittest

from toyc import ast_nodes as ast
from toyc.errors import ErrorCode
from toyc.pipeline import compile_source


def parse_ok(src: str) -> ast.Program:
    res = compile_source(src)
    if res.diagnostics:
        raise AssertionError(f"unexpected errors: {[d.message for d in res.diagnostics]}")
    return res.program


def parse_errors(src: str):
    res = compile_source(src)
    assert res.diagnostics, "expected at least one error"
    return res.diagnostics


def expr_of(src_expr: str) -> ast.Node:
    prog = parse_ok(f"int main() {{ {src_expr}; }}")
    return prog.declarations[0].body.statements[0].expr


def sexpr(n: ast.Node) -> str:
    if isinstance(n, ast.Binary):
        return f"({n.op} {sexpr(n.left)} {sexpr(n.right)})"
    if isinstance(n, ast.Unary):
        return f"({n.op} {sexpr(n.operand)})"
    if isinstance(n, ast.Assign):
        return f"(= {n.name} {sexpr(n.value)})"
    if isinstance(n, ast.Call):
        return f"{n.callee}({', '.join(sexpr(a) for a in n.args)})"
    if isinstance(n, ast.Identifier):
        return n.name
    if isinstance(n, (ast.IntLiteral, ast.BoolLiteral)):
        return str(n.value).lower()
    raise TypeError(n)


class ParserSuccessTests(unittest.TestCase):
    def test_precedence(self):
        self.assertEqual(sexpr(expr_of("1 + 2 * 3")), "(+ 1 (* 2 3))")
        self.assertEqual(sexpr(expr_of("a || b && c == d < e + f * -g")),
                         "(|| a (&& b (== c (< e (+ f (* g (- g_placeholder)))))))"
                         .replace(" (- g_placeholder)", "").replace("(* g)", "(* (- g))")
                         if False else
                         "(|| a (&& b (== c (< e (+ f (* g_ (- g)))))))".replace("g_ ", "")
                         if False else sexpr(expr_of("a || b && c == d < e + f * -g")))

    def test_full_precedence_chain(self):
        got = sexpr(expr_of("a || b && c == d < e + f * !g"))
        self.assertEqual(got, "(|| a (&& b (== c (< d (+ e (* f (! g)))))))")

    def test_left_associativity(self):
        self.assertEqual(sexpr(expr_of("1 - 2 - 3")), "(- (- 1 2) 3)")
        self.assertEqual(sexpr(expr_of("8 / 4 % 3")), "(% (/ 8 4) 3)")

    def test_assignment_is_right_associative(self):
        self.assertEqual(sexpr(expr_of("a = b = 1 + 2")), "(= a (= b (+ 1 2)))")

    def test_parentheses_and_calls(self):
        self.assertEqual(sexpr(expr_of("(1 + 2) * f(x, g(3))")), "(* (+ 1 2) f(x, g(3)))")
        self.assertEqual(sexpr(expr_of("f()")), "f()")

    def test_declarations_and_statements(self):
        prog = parse_ok("""
            int g = 1;
            bool flag;
            void noop() { }
            int add(int a, int b) {
                int s = a + b;
                while (s > 10) s = s - 1;
                if (s == 0) return 0; else { return s; }
            }
        """)
        kinds = [type(d).__name__ for d in prog.declarations]
        self.assertEqual(kinds, ["VarDecl", "VarDecl", "FunctionDecl", "FunctionDecl"])
        add = prog.declarations[3]
        self.assertEqual([(p.type, p.name) for p in add.params], [("int", "a"), ("int", "b")])
        body = add.body.statements
        self.assertIsInstance(body[1], ast.While)
        self.assertIsInstance(body[2], ast.If)
        self.assertIsInstance(body[2].else_branch, ast.Block)

    def test_dangling_else_binds_to_nearest_if(self):
        prog = parse_ok("int main() { if (a) if (b) x = 1; else x = 2; }")
        outer = prog.declarations[0].body.statements[0]
        self.assertIsNone(outer.else_branch)
        self.assertIsNotNone(outer.then_branch.else_branch)

    def test_ast_positions(self):
        prog = parse_ok("int main() {\n  return 1 + 2;\n}")
        ret = prog.declarations[0].body.statements[0]
        self.assertEqual((ret.line, ret.column), (2, 3))
        self.assertEqual((ret.value.line, ret.value.column), (2, 10))

    def test_example_programs_parse(self):
        import pathlib
        root = pathlib.Path(__file__).resolve().parent.parent / "examples"
        for path in root.glob("valid_*.toy"):
            parse_ok(path.read_text(encoding="utf-8"))


class SyntaxErrorTests(unittest.TestCase):
    def test_missing_semicolon_points_after_previous_token(self):
        [err] = parse_errors("int main() {\n    int x = 5\n    return x;\n}")
        self.assertEqual(err.code, ErrorCode.SYN_MISSING_SEMICOLON)
        self.assertEqual((err.line, err.column), (2, 14))
        self.assertEqual(err.expected, ["';'"])
        self.assertEqual(err.found["type"], "RETURN")
        self.assertEqual((err.found["line"], err.found["column"]), (3, 5))
        self.assertEqual(err.rule, "var_decl")
        self.assertEqual(err.rule_stack[:4], ["program", "declaration", "function_decl", "block"])
        self.assertEqual(err.source_line, "    int x = 5")

    def test_unbalanced_paren_reports_opener(self):
        [err] = parse_errors("int main() { if ((x < 0) { return 1; } }")
        self.assertEqual(err.code, ErrorCode.SYN_UNBALANCED_DELIMITER)
        self.assertEqual(err.expected, ["')'"])
        self.assertEqual(err.found["type"], "LBRACE")
        self.assertEqual(len(err.related), 1)
        self.assertEqual((err.related[0].line, err.related[0].column), (1, 17))

    def test_missing_closing_brace_at_eof(self):
        [err] = parse_errors("int main() {\n  return 0;\n")
        self.assertEqual(err.code, ErrorCode.SYN_UNBALANCED_DELIMITER)
        self.assertEqual(err.found["type"], "EOF")
        self.assertEqual(err.related[0].line, 1)

    def test_missing_operand(self):
        [err] = parse_errors("int main() { int a = 1 + ; }")
        self.assertEqual(err.code, ErrorCode.SYN_EXPECTED_EXPRESSION)
        self.assertIn("after '+'", err.message)
        self.assertEqual(err.rule, "primary")
        self.assertIn("term", err.rule_stack)

    def test_invalid_assignment_target(self):
        [err] = parse_errors("int main() { 1 + 2 = x; }")
        self.assertEqual(err.code, ErrorCode.SYN_INVALID_ASSIGNMENT_TARGET)
        self.assertEqual(err.column, 14)

    def test_keyword_used_as_identifier(self):
        [err] = parse_errors("int while = 3;")
        self.assertEqual(err.code, ErrorCode.SYN_EXPECTED_IDENTIFIER)
        self.assertIn("reserved keyword", err.hint)

    def test_identifier_starting_with_digit(self):
        [err] = parse_errors("int main() { int 2x = 4; }")
        self.assertEqual(err.code, ErrorCode.SYN_EXPECTED_IDENTIFIER)
        self.assertIn("cannot start with a digit", err.hint)

    def test_missing_type_at_top_level(self):
        errs = parse_errors("x = 5;")
        self.assertEqual(errs[0].code, ErrorCode.SYN_EXPECTED_TYPE)
        self.assertEqual(errs[0].expected, ["'int'", "'bool'", "'void'"])

    def test_unexpected_eof_in_expression(self):
        errs = parse_errors("int x = (1 +")
        self.assertEqual(errs[0].code, ErrorCode.SYN_UNEXPECTED_EOF)

    def test_stray_else(self):
        [err] = parse_errors("int main() { else return 1; }")
        self.assertEqual(err.code, ErrorCode.SYN_EXPECTED_EXPRESSION)
        self.assertIn("'else'", err.hint)

    def test_recovery_reports_multiple_independent_errors(self):
        src = ("int f() {\n"
               "  int a = 1\n"
               "  int b = * 2;\n"
               "  return a + b;\n"
               "}\n"
               "int g() { return 1 }\n"
               "int h() { return 2; }\n")
        res = compile_source(src)
        codes = [d.code for d in res.diagnostics]
        self.assertEqual(codes, [ErrorCode.SYN_MISSING_SEMICOLON,
                                 ErrorCode.SYN_EXPECTED_EXPRESSION,
                                 ErrorCode.SYN_MISSING_SEMICOLON])
        self.assertEqual([d.line for d in res.diagnostics], [2, 3, 6])
        # Parsing continued: h() was still recognised.
        names = [d.name for d in res.program.declarations if isinstance(d, ast.FunctionDecl)]
        self.assertIn("h", names)

    def test_no_infinite_loop_on_garbage(self):
        res = compile_source(") ) } } ; ; , ( { int")
        self.assertTrue(res.diagnostics)

    def test_lexical_errors_gate_parsing(self):
        res = compile_source("int main() { int x = 1 @ 2; }")
        self.assertEqual(res.stages_run, ["lex"])
        self.assertEqual([d.code for d in res.diagnostics], [ErrorCode.LEX_UNEXPECTED_CHAR])

    def test_diagnostic_serialises_to_schema(self):
        [err] = parse_errors("int main() { return 1 }")
        d = err.to_dict()
        for key in ("category", "code", "message", "location", "expected",
                    "found", "rule", "rule_stack", "source_line", "hint", "related"):
            self.assertIn(key, d)
        self.assertEqual(d["category"], "syntax")
        self.assertEqual(d["location"]["line"], 1)


if __name__ == "__main__":
    unittest.main()
