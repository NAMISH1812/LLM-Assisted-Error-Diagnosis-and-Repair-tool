import unittest

from toyc.regex_dfa import (
    RegexSyntaxError, build_nfa, compile_dfa, minimize, nfa_to_dfa,
)


def accepts(pattern: str, text: str) -> bool:
    return compile_dfa([("T", pattern)]).accepts(text) == "T"


class RegexToDfaTests(unittest.TestCase):
    def test_literal_and_concatenation(self):
        self.assertTrue(accepts("abc", "abc"))
        self.assertFalse(accepts("abc", "ab"))
        self.assertFalse(accepts("abc", "abcd"))

    def test_alternation_and_grouping(self):
        for s in ("ab", "cd"):
            self.assertTrue(accepts("(ab|cd)", s))
        self.assertFalse(accepts("(ab|cd)", "ad"))

    def test_kleene_operators(self):
        self.assertTrue(accepts("a*", ""))
        self.assertTrue(accepts("a*", "aaaa"))
        self.assertFalse(accepts("a+", ""))
        self.assertTrue(accepts("a+", "aaa"))
        self.assertTrue(accepts("ab?c", "ac"))
        self.assertTrue(accepts("ab?c", "abc"))
        self.assertFalse(accepts("ab?c", "abbc"))

    def test_character_classes(self):
        ident = "[a-zA-Z_][a-zA-Z0-9_]*"
        for s in ("x", "_tmp", "abc123", "A_b"):
            self.assertTrue(accepts(ident, s), s)
        for s in ("1abc", "", "a-b"):
            self.assertFalse(accepts(ident, s), s)

    def test_negated_class_and_escapes(self):
        self.assertTrue(accepts(r"//[^\n]*", "// hello */ world"))
        self.assertFalse(accepts(r"//[^\n]*", "// a\nb"))
        self.assertTrue(accepts(r"\(\*\)", "(*)"))

    def test_block_comment_pattern(self):
        pat = r"/\*([^*]|\*+[^*/])*\*+/"
        for s in ("/**/", "/* x */", "/***/", "/* a ** b */", "/* multi\nline */"):
            self.assertTrue(accepts(pat, s), s)
        for s in ("/* open", "/*/", "/* a */ b */"):
            self.assertFalse(accepts(pat, s), s)

    def test_priority_resolves_ties(self):
        dfa = compile_dfa([("IF", "if"), ("IDENT", "[a-z]+")])
        self.assertEqual(dfa.accepts("if"), "IF")
        self.assertEqual(dfa.accepts("iff"), "IDENT")
        dfa2 = compile_dfa([("IDENT", "[a-z]+"), ("IF", "if")])
        self.assertEqual(dfa2.accepts("if"), "IDENT")

    def test_minimization_preserves_language_and_shrinks(self):
        specs = [("T", "(a|b)*abb")]
        raw = nfa_to_dfa(build_nfa(specs))
        small = minimize(raw)
        self.assertLessEqual(small.num_states, raw.num_states)
        self.assertEqual(small.num_states, 4)  # textbook result (Dragon Book, Ex. 3.36)
        for s in ("abb", "aabb", "babb", "ababb"):
            self.assertEqual(small.accepts(s), "T")
        for s in ("", "ab", "abba", "bbb"):
            self.assertIsNone(small.accepts(s))

    def test_invalid_regexes(self):
        for bad in ("(ab", "a)", "*a", "[abc", "a\\"):
            with self.assertRaises(RegexSyntaxError, msg=bad):
                compile_dfa([("T", bad)])


if __name__ == "__main__":
    unittest.main()
