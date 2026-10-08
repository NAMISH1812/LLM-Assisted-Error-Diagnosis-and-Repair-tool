import unittest

from toyc.errors import ErrorCode
from toyc.lexer import tokenize
from toyc.tokens import TokenType as T


def types(src: str):
    return [t.type for t in tokenize(src).tokens]


class LexerTests(unittest.TestCase):
    def test_empty_input_yields_only_eof(self):
        res = tokenize("")
        self.assertEqual([t.type for t in res.tokens], [T.EOF])
        self.assertEqual((res.tokens[0].line, res.tokens[0].column), (1, 1))

    def test_keywords_vs_identifiers(self):
        self.assertEqual(types("if iffy int int_x while1 return"),
                         [T.IF, T.IDENT, T.INT, T.IDENT, T.IDENT, T.RETURN, T.EOF])

    def test_maximal_munch_operators(self):
        self.assertEqual(types("a<=b==c!=d>=e&&f||g"),
                         [T.IDENT, T.LE, T.IDENT, T.EQ, T.IDENT, T.NEQ, T.IDENT,
                          T.GE, T.IDENT, T.AND, T.IDENT, T.OR, T.IDENT, T.EOF])
        self.assertEqual(types("= ="), [T.ASSIGN, T.ASSIGN, T.EOF])
        self.assertEqual(types("!x"), [T.NOT, T.IDENT, T.EOF])

    def test_number_followed_by_identifier(self):
        toks = tokenize("123abc").tokens
        self.assertEqual([t.type for t in toks], [T.INT_LIT, T.IDENT, T.EOF])
        self.assertEqual([t.lexeme for t in toks[:2]], ["123", "abc"])

    def test_comments_and_whitespace_are_skipped(self):
        src = "int /* block\n comment */ x; // trailing\n\ty = 1;"
        self.assertEqual(types(src),
                         [T.INT, T.IDENT, T.SEMICOLON, T.IDENT, T.ASSIGN,
                          T.INT_LIT, T.SEMICOLON, T.EOF])

    def test_division_is_not_a_comment(self):
        self.assertEqual(types("a / b"), [T.IDENT, T.SLASH, T.IDENT, T.EOF])

    def test_line_and_column_tracking(self):
        src = "int main() {\n    return 42;\n}\n"
        toks = tokenize(src).tokens
        ret = next(t for t in toks if t.type is T.RETURN)
        self.assertEqual((ret.line, ret.column, ret.end_column), (2, 5, 10))
        lit = next(t for t in toks if t.type is T.INT_LIT)
        self.assertEqual((lit.line, lit.column, lit.end_column), (2, 12, 13))
        self.assertEqual((toks[-1].line, toks[-1].column), (4, 1))  # EOF after trailing newline

    def test_positions_after_multiline_comment(self):
        toks = tokenize("/* a\nb\nc */ x").tokens
        self.assertEqual((toks[0].line, toks[0].column), (3, 6))

    def test_unexpected_character_with_recovery_and_hint(self):
        res = tokenize("a & b @ c")
        self.assertEqual([e.code for e in res.errors],
                         [ErrorCode.LEX_UNEXPECTED_CHAR, ErrorCode.LEX_UNEXPECTED_CHAR])
        amp = res.errors[0]
        self.assertEqual((amp.line, amp.column), (1, 3))
        self.assertIn("&&", amp.hint)
        self.assertEqual([t.type for t in res.tokens], [T.IDENT, T.IDENT, T.IDENT, T.EOF])

    def test_unterminated_block_comment(self):
        res = tokenize("int x;\n/* never closed\nint y;")
        self.assertEqual(len(res.errors), 1)
        err = res.errors[0]
        self.assertEqual(err.code, ErrorCode.LEX_UNTERMINATED_COMMENT)
        self.assertEqual((err.line, err.column), (2, 1))
        self.assertEqual([t.type for t in res.tokens], [T.INT, T.IDENT, T.SEMICOLON, T.EOF])

    def test_non_ascii_character_is_an_error(self):
        res = tokenize("int x = 5\u00a7;")
        self.assertEqual(res.errors[0].code, ErrorCode.LEX_UNEXPECTED_CHAR)
        self.assertEqual(res.errors[0].column, 10)


if __name__ == "__main__":
    unittest.main()
