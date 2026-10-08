"""Token definitions for the Toy-C language."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import Enum


class TokenType(Enum):
    # Keywords
    INT = "int"
    BOOL = "bool"
    VOID = "void"
    IF = "if"
    ELSE = "else"
    WHILE = "while"
    RETURN = "return"
    TRUE = "true"
    FALSE = "false"

    # Literals / names
    IDENT = "identifier"
    INT_LIT = "integer literal"

    # Multi-character operators
    EQ = "=="
    NEQ = "!="
    LE = "<="
    GE = ">="
    AND = "&&"
    OR = "||"

    # Single-character operators
    ASSIGN = "="
    LT = "<"
    GT = ">"
    PLUS = "+"
    MINUS = "-"
    STAR = "*"
    SLASH = "/"
    PERCENT = "%"
    NOT = "!"

    # Punctuation
    LPAREN = "("
    RPAREN = ")"
    LBRACE = "{"
    RBRACE = "}"
    COMMA = ","
    SEMICOLON = ";"

    EOF = "end of file"

    @property
    def display(self) -> str:
        """Human-readable form used in diagnostics, e.g. ``';'`` or ``identifier``."""
        if self in _DESCRIPTIVE:
            return self.value
        return f"'{self.value}'"


_DESCRIPTIVE = {TokenType.IDENT, TokenType.INT_LIT, TokenType.EOF}

KEYWORDS: tuple[TokenType, ...] = (
    TokenType.INT, TokenType.BOOL, TokenType.VOID, TokenType.IF, TokenType.ELSE,
    TokenType.WHILE, TokenType.RETURN, TokenType.TRUE, TokenType.FALSE,
)

TYPE_KEYWORDS: frozenset[TokenType] = frozenset({TokenType.INT, TokenType.BOOL, TokenType.VOID})

OPERATORS: tuple[TokenType, ...] = (
    TokenType.EQ, TokenType.NEQ, TokenType.LE, TokenType.GE, TokenType.AND, TokenType.OR,
    TokenType.ASSIGN, TokenType.LT, TokenType.GT, TokenType.PLUS, TokenType.MINUS,
    TokenType.STAR, TokenType.SLASH, TokenType.PERCENT, TokenType.NOT,
    TokenType.LPAREN, TokenType.RPAREN, TokenType.LBRACE, TokenType.RBRACE,
    TokenType.COMMA, TokenType.SEMICOLON,
)


@dataclass(frozen=True)
class Token:
    type: TokenType
    lexeme: str
    line: int          # 1-based
    column: int        # 1-based, first character
    end_line: int
    end_column: int    # 1-based, last character (inclusive)
    offset: int        # 0-based offset into the source

    def describe(self) -> str:
        """e.g. ``identifier 'x'``, ``keyword 'return'``, ``';'``, ``end of file``."""
        if self.type is TokenType.EOF:
            return "end of file"
        if self.type is TokenType.IDENT:
            return f"identifier '{self.lexeme}'"
        if self.type is TokenType.INT_LIT:
            return f"integer literal '{self.lexeme}'"
        if self.type in KEYWORDS:
            return f"keyword '{self.lexeme}'"
        return f"'{self.lexeme}'"

    def to_dict(self) -> dict:
        d = asdict(self)
        d["type"] = self.type.name
        d["description"] = self.describe()
        return d
