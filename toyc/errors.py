"""Structured compiler diagnostics.

Every error raised by the front-end is a :class:`Diagnostic` -- a typed,
structured object rather than a flat string.  Phase 2 will reuse the same
schema for semantic errors and will dispatch error-type-specific LLM prompts
on ``Diagnostic.code``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class ErrorCategory(str, Enum):
    LEXICAL = "lexical"
    SYNTAX = "syntax"
    SEMANTIC = "semantic"


class ErrorCode(str, Enum):
    # Lexical
    LEX_UNEXPECTED_CHAR = "LEX_UNEXPECTED_CHAR"
    LEX_UNTERMINATED_COMMENT = "LEX_UNTERMINATED_COMMENT"
    # Syntax
    SYN_MISSING_SEMICOLON = "SYN_MISSING_SEMICOLON"
    SYN_UNBALANCED_DELIMITER = "SYN_UNBALANCED_DELIMITER"
    SYN_EXPECTED_EXPRESSION = "SYN_EXPECTED_EXPRESSION"
    SYN_EXPECTED_IDENTIFIER = "SYN_EXPECTED_IDENTIFIER"
    SYN_EXPECTED_TYPE = "SYN_EXPECTED_TYPE"
    SYN_INVALID_ASSIGNMENT_TARGET = "SYN_INVALID_ASSIGNMENT_TARGET"
    SYN_UNEXPECTED_EOF = "SYN_UNEXPECTED_EOF"
    SYN_UNEXPECTED_TOKEN = "SYN_UNEXPECTED_TOKEN"
    # Semantic
    SEM_UNDECLARED_VARIABLE = "SEM_UNDECLARED_VARIABLE"
    SEM_DUPLICATE_DECLARATION = "SEM_DUPLICATE_DECLARATION"
    SEM_TYPE_MISMATCH = "SEM_TYPE_MISMATCH"
    SEM_UNDEFINED_FUNCTION = "SEM_UNDEFINED_FUNCTION"
    SEM_ARGUMENT_MISMATCH = "SEM_ARGUMENT_MISMATCH"
    SEM_NOT_CALLABLE = "SEM_NOT_CALLABLE"
    SEM_RETURN_MISMATCH = "SEM_RETURN_MISMATCH"
    SEM_INVALID_VOID = "SEM_INVALID_VOID"

    @property
    def category(self) -> ErrorCategory:
        if self.value.startswith("LEX_"):
            return ErrorCategory.LEXICAL
        if self.value.startswith("SEM_"):
            return ErrorCategory.SEMANTIC
        return ErrorCategory.SYNTAX


@dataclass
class RelatedLocation:
    """A secondary location, e.g. where an unclosed '(' was opened."""
    message: str
    line: int
    column: int

    def to_dict(self) -> dict:
        return {"message": self.message, "line": self.line, "column": self.column}


@dataclass
class Diagnostic:
    code: ErrorCode
    message: str
    filename: str
    line: int
    column: int
    end_column: int | None = None          # inclusive; None -> single caret
    expected: list[str] = field(default_factory=list)
    found: dict | None = None               # Token.to_dict() of the offending token
    rule: str | None = None                 # grammar rule that failed
    rule_stack: list[str] = field(default_factory=list)
    source_line: str = ""
    hint: str | None = None
    related: list[RelatedLocation] = field(default_factory=list)
    # Semantic extras: inferred/expected types, operator, typo suggestion, ...
    details: dict = field(default_factory=dict)
    # Snapshot of the symbols visible at the error site (name, kind, type, line)
    symbols: list[dict] = field(default_factory=list)

    @property
    def category(self) -> ErrorCategory:
        return self.code.category

    def to_dict(self) -> dict:
        return {
            "category": self.category.value,
            "code": self.code.value,
            "message": self.message,
            "location": {
                "file": self.filename,
                "line": self.line,
                "column": self.column,
                "end_column": self.end_column,
            },
            "expected": self.expected,
            "found": self.found,
            "rule": self.rule,
            "rule_stack": self.rule_stack,
            "source_line": self.source_line,
            "hint": self.hint,
            "related": [r.to_dict() for r in self.related],
            "details": self.details,
            "symbols": self.symbols,
        }


# --------------------------------------------------------------------------
# Human-readable rendering
# --------------------------------------------------------------------------

class _Style:
    def __init__(self, color: bool):
        self.color = color

    def _wrap(self, code: str, text: str) -> str:
        return f"\033[{code}m{text}\033[0m" if self.color else text

    def red(self, t): return self._wrap("1;31", t)
    def blue(self, t): return self._wrap("1;34", t)
    def cyan(self, t): return self._wrap("36", t)
    def bold(self, t): return self._wrap("1", t)
    def dim(self, t): return self._wrap("2", t)


def _compact_stack(stack: list[str], keep: int = 5) -> str:
    if len(stack) <= keep:
        return " > ".join(stack)
    return "... > " + " > ".join(stack[-keep:])


def format_diagnostic(d: Diagnostic, color: bool = False) -> str:
    s = _Style(color)
    gutter = " " * len(str(d.line))
    out = [
        f"{s.red('error')}{s.bold(f'[{d.code.value}]')}: {s.bold(d.message)}",
        f"{gutter}{s.blue('-->')} {d.filename}:{d.line}:{d.column}",
        f"{gutter} {s.blue('|')}",
    ]
    line_text = d.source_line.expandtabs(4)
    prefix = d.source_line[: max(d.column - 1, 0)].expandtabs(4)
    width = 1
    if d.end_column is not None and d.end_column >= d.column:
        width = d.end_column - d.column + 1
    label = f"expected {' or '.join(d.expected)}" if d.expected else ""
    out.append(f"{s.blue(str(d.line))} {s.blue('|')} {line_text}")
    out.append(f"{gutter} {s.blue('|')} {' ' * len(prefix)}{s.red('^' * width)} {s.red(label)}".rstrip())
    out.append(f"{gutter} {s.blue('|')}")

    def note(key: str, value: str) -> None:
        out.append(f"{gutter} {s.blue('=')} {s.bold(key)}: {value}")

    note("category", d.category.value)
    if d.rule and len(d.rule_stack) > 1:
        note("rule", f"{d.rule}  {s.dim('(' + _compact_stack(d.rule_stack) + ')')}")
    elif d.rule:
        note("rule", d.rule)
    if d.found is not None:
        note("found", f"{d.found['description']} at {d.found['line']}:{d.found['column']}")
    if "expected_type" in d.details and "actual_type" in d.details:
        note("types", f"expected '{d.details['expected_type']}', found '{d.details['actual_type']}'")
    for r in d.related:
        note("note", f"{r.message} at {r.line}:{r.column}")
    if d.hint:
        note("hint", s.cyan(d.hint))
    return "\n".join(out)
