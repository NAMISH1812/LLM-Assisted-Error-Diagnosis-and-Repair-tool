"""DFA-driven lexer for Toy-C with line/column tracking and error recovery."""

from __future__ import annotations

from bisect import bisect_right
from dataclasses import dataclass, field

from .errors import Diagnostic, ErrorCode
from .regex_dfa import DFA, compile_dfa, escape
from .tokens import KEYWORDS, OPERATORS, Token, TokenType

# Order matters only for ties on the *same* lexeme length: earlier wins.
# (Keywords must come before IDENT so that "if" is a keyword, not an identifier.)
TOKEN_SPECS: list[tuple[str, str]] = [
    ("WHITESPACE", r"[ \t\r\n]+"),
    ("LINE_COMMENT", r"//[^\n]*"),
    ("BLOCK_COMMENT", r"/\*([^*]|\*+[^*/])*\*+/"),
    *[(kw.name, escape(kw.value)) for kw in KEYWORDS],
    ("IDENT", r"[a-zA-Z_][a-zA-Z0-9_]*"),
    ("INT_LIT", r"[0-9]+"),
    *[(op.name, escape(op.value)) for op in OPERATORS],
]

SKIPPED = frozenset({"WHITESPACE", "LINE_COMMENT", "BLOCK_COMMENT"})

_HINTS = {
    "&": "Toy-C has no bitwise '&'; did you mean the logical operator '&&'?",
    "|": "Toy-C has no bitwise '|'; did you mean the logical operator '||'?",
    '"': "string literals are not supported in Toy-C",
    "'": "character literals are not supported in Toy-C",
    "[": "arrays are not supported in Toy-C",
    "]": "arrays are not supported in Toy-C",
}

_DFA_CACHE: DFA | None = None


def get_lexer_dfa() -> DFA:
    """Build (once) the minimal DFA recognising every Toy-C token."""
    global _DFA_CACHE
    if _DFA_CACHE is None:
        _DFA_CACHE = compile_dfa(TOKEN_SPECS)
    return _DFA_CACHE


@dataclass
class LexResult:
    tokens: list[Token]
    errors: list[Diagnostic] = field(default_factory=list)


class Lexer:
    def __init__(self, source: str, filename: str = "<input>"):
        self.source = source
        self.filename = filename
        self.dfa = get_lexer_dfa()
        self._line_starts = [0] + [i + 1 for i, ch in enumerate(source) if ch == "\n"]
        self._lines = source.split("\n")

    # -- position helpers -------------------------------------------------
    def location(self, offset: int) -> tuple[int, int]:
        """0-based offset -> (1-based line, 1-based column)."""
        idx = bisect_right(self._line_starts, offset) - 1
        return idx + 1, offset - self._line_starts[idx] + 1

    def source_line(self, line: int) -> str:
        return self._lines[line - 1] if 0 < line <= len(self._lines) else ""

    def _make_token(self, ttype: TokenType, start: int, end: int) -> Token:
        line, col = self.location(start)
        end_line, end_col = self.location(max(end - 1, start))
        return Token(ttype, self.source[start:end], line, col, end_line, end_col, start)

    def _error(self, code: ErrorCode, message: str, start: int, end: int,
               hint: str | None = None) -> Diagnostic:
        line, col = self.location(start)
        end_line, end_col = self.location(max(end - 1, start))
        return Diagnostic(
            code=code, message=message, filename=self.filename,
            line=line, column=col,
            end_column=end_col if end_line == line else None,
            rule="token", rule_stack=["token"],
            source_line=self.source_line(line), hint=hint,
        )

    # -- main loop ----------------------------------------------------------
    def tokenize(self) -> LexResult:
        src, n, dfa = self.source, len(self.source), self.dfa
        tokens: list[Token] = []
        errors: list[Diagnostic] = []
        pos = 0

        while pos < n:
            # Maximal munch: run the DFA as far as possible, remembering the
            # last accepting position.
            state: int | None = dfa.start
            i = pos
            last_accept: tuple[int, str] | None = None
            while i < n:
                state = dfa.step(state, src[i])
                if state is None:
                    break
                i += 1
                kind = dfa.accepting.get(state)
                if kind is not None:
                    last_accept = (i, kind)

            if src.startswith("/*", pos) and (last_accept is None or last_accept[1] != "BLOCK_COMMENT"):
                errors.append(self._error(
                    ErrorCode.LEX_UNTERMINATED_COMMENT,
                    "unterminated block comment", pos, pos + 2,
                    hint="close the comment with '*/'"))
                pos = n
                break

            if last_accept is None:
                ch = src[pos]
                shown = ch if ch.isprintable() else repr(ch)
                errors.append(self._error(
                    ErrorCode.LEX_UNEXPECTED_CHAR,
                    f"unexpected character '{shown}'", pos, pos + 1,
                    hint=_HINTS.get(ch)))
                pos += 1          # error recovery: skip the bad character
                continue

            end, kind = last_accept
            if kind not in SKIPPED:
                tokens.append(self._make_token(TokenType[kind], pos, end))
            pos = end

        eof_line, eof_col = self.location(n)
        tokens.append(Token(TokenType.EOF, "", eof_line, eof_col, eof_line, eof_col, n))
        return LexResult(tokens, errors)


def tokenize(source: str, filename: str = "<input>") -> LexResult:
    return Lexer(source, filename).tokenize()
