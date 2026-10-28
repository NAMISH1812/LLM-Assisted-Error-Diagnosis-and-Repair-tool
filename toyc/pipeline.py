"""Front-end pipeline: source -> tokens -> AST -> checked AST, collecting structured diagnostics."""

from __future__ import annotations

from dataclasses import dataclass, field

from .ast_nodes import Program, ast_to_dict
from .errors import Diagnostic
from .lexer import tokenize
from .parser import parse
from .semantic import SymbolTable, analyze
from .tokens import Token

STAGES = ("lex", "parse", "semantic")


@dataclass
class CompileResult:
    filename: str
    tokens: list[Token]
    program: Program | None
    diagnostics: list[Diagnostic] = field(default_factory=list)
    stages_run: list[str] = field(default_factory=list)
    symbols: SymbolTable | None = None
    source: str = ""

    @property
    def ok(self) -> bool:
        return not self.diagnostics

    @property
    def failed_stage(self) -> str | None:
        """Name of the stage that produced the diagnostics (None on success)."""
        return self.stages_run[-1] if self.diagnostics else None

    def to_dict(self, include_tokens: bool = False, include_ast: bool = False,
                include_symbols: bool = False) -> dict:
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
        if include_symbols and self.symbols is not None:
            d["symbols"] = self.symbols.to_dict()
        return d


def compile_source(source: str, filename: str = "<input>", stop_after: str = "semantic") -> CompileResult:
    """Run the front-end; ``stop_after`` may be ``"lex"``, ``"parse"`` or ``"semantic"``."""
    if stop_after not in STAGES:
        raise ValueError(f"stop_after must be one of {STAGES}")
    lex = tokenize(source, filename)
    result = CompileResult(filename, lex.tokens, None, list(lex.errors), ["lex"], source=source)
    if lex.errors or stop_after == "lex":
        # Phase gating: parsing a token stream with holes in it only produces
        # cascading, misleading syntax errors, so stop after lexing.
        return result
    parsed = parse(lex.tokens, source, filename)
    result.stages_run.append("parse")
    result.program = parsed.program
    result.diagnostics.extend(parsed.errors)
    if parsed.errors or stop_after == "parse":
        # Same gating for semantics: an AST with holes from panic-mode recovery
        # would produce spurious "undeclared variable" errors.
        return result
    sem = analyze(parsed.program, source, filename)
    result.stages_run.append("semantic")
    result.symbols = sem.symbols
    result.diagnostics.extend(sem.errors)
    return result
