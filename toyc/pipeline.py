"""Front-end pipeline: source -> tokens -> AST, collecting structured diagnostics."""

from __future__ import annotations

from dataclasses import dataclass, field

from .ast_nodes import Program, ast_to_dict
from .errors import Diagnostic
from .lexer import tokenize
from .parser import parse
from .tokens import Token


@dataclass
class CompileResult:
    filename: str
    tokens: list[Token]
    program: Program | None
    diagnostics: list[Diagnostic] = field(default_factory=list)
    stages_run: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.diagnostics

    def to_dict(self, include_tokens: bool = False, include_ast: bool = False) -> dict:
        d: dict = {
            "file": self.filename,
            "success": self.ok,
            "stages_run": self.stages_run,
            "error_count": len(self.diagnostics),
            "errors": [e.to_dict() for e in self.diagnostics],
        }
        if include_tokens:
            d["tokens"] = [t.to_dict() for t in self.tokens]
        if include_ast and self.program is not None:
            d["ast"] = ast_to_dict(self.program)
        return d


def compile_source(source: str, filename: str = "<input>") -> CompileResult:
    lex = tokenize(source, filename)
    result = CompileResult(filename, lex.tokens, None, list(lex.errors), ["lex"])
    if lex.errors:
        # Phase gating: parsing a token stream with holes in it only produces
        # cascading, misleading syntax errors, so stop after lexing.
        return result
    parsed = parse(lex.tokens, source, filename)
    result.stages_run.append("parse")
    result.program = parsed.program
    result.diagnostics.extend(parsed.errors)
    return result
