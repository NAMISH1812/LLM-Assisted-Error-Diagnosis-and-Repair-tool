"""Error-context extraction: everything the LLM needs to know about one diagnostic.

For every :class:`~toyc.errors.Diagnostic` we capture, *from inside the
compiler* rather than from printed text:

* a numbered source window (``radius`` lines either side of the error, plus
  any related locations such as the line where an unclosed ``(`` was opened);
* the enclosing function and its signature;
* a snapshot of the symbols in scope at the error site.  Semantic diagnostics
  carry an exact snapshot taken by the analyser.  Lexical/syntax errors are
  raised before a symbol table exists, so we approximate it from the token
  stream (declarations appearing before the error offset, scoped by braces);
* the list of other errors in the same file (so a fix for one error does not
  fight another).
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .errors import Diagnostic
from .tokens import TYPE_KEYWORDS, Token, TokenType

T = TokenType


@dataclass
class ErrorContext:
    diagnostic: Diagnostic
    source: str
    filename: str
    snippet: str                       # numbered lines, error line marked with '>'
    snippet_start: int
    snippet_end: int
    enclosing_function: str | None     # e.g. "int area(int w, int h)"
    symbols: list[dict] = field(default_factory=list)
    symbols_exact: bool = False        # True if taken from the semantic analyser
    other_errors: list[str] = field(default_factory=list)

    @property
    def symbol_lines(self) -> list[str]:
        return [f"{s['signature']}  ({s['kind']}, declared at line {s['line']})"
                for s in self.symbols]

    def to_dict(self) -> dict:
        return {
            "diagnostic": self.diagnostic.to_dict(),
            "snippet": self.snippet,
            "snippet_range": [self.snippet_start, self.snippet_end],
            "enclosing_function": self.enclosing_function,
            "symbols": self.symbols,
            "symbols_exact": self.symbols_exact,
            "other_errors": self.other_errors,
        }


def numbered_source(source: str) -> str:
    lines = source.split("\n")
    width = len(str(len(lines)))
    return "\n".join(f"{i:>{width}} | {text}" for i, text in enumerate(lines, 1))


def _snippet(lines: list[str], center: int, radius: int, extra: list[int]) -> tuple[str, int, int]:
    lo = max(1, center - radius)
    hi = min(len(lines), center + radius)
    for ln in extra:                          # widen to include related locations
        if 0 < ln <= len(lines):
            lo, hi = min(lo, ln), max(hi, ln)
    width = len(str(hi))
    out = []
    for i in range(lo, hi + 1):
        mark = ">" if i == center else " "
        out.append(f"{mark} {i:>{width}} | {lines[i - 1]}")
    return "\n".join(out), lo, hi


def _signature_from_tokens(toks: list[Token], i: int) -> str:
    """Build 'int f(int a, bool b)' from tokens starting at type keyword index i."""
    parts, depth, j = [], 0, i
    while j < len(toks):
        t = toks[j]
        parts.append(t.lexeme)
        if t.type is T.LPAREN:
            depth += 1
        elif t.type is T.RPAREN:
            depth -= 1
            if depth <= 0:
                break
        elif t.type in (T.LBRACE, T.SEMICOLON, T.EOF):
            parts.pop()
            break
        j += 1
    text = " ".join(parts)
    return text.replace(" (", "(").replace("( ", "(").replace(" )", ")").replace(" ,", ",")


def _approximate_scope(tokens: list[Token], offset: int) -> tuple[list[dict], str | None]:
    """Scan tokens before ``offset`` to recover declarations still in scope.

    Returns (symbols, enclosing_function_signature).
    """
    toks = [t for t in tokens if t.type is not T.EOF]
    scopes: list[list[dict]] = [[]]
    function: str | None = None
    pending_params: list[dict] = []
    function_depth: int | None = None
    i = 0
    while i < len(toks) and toks[i].offset < offset:
        t = toks[i]
        if t.type is T.LBRACE:
            scopes.append(pending_params)
            pending_params = []
            if function is not None and function_depth is None:
                function_depth = len(scopes) - 1
        elif t.type is T.RBRACE:
            if len(scopes) > 1:
                scopes.pop()
            if function_depth is not None and len(scopes) - 1 < function_depth:
                function, function_depth = None, None
        elif (t.type in TYPE_KEYWORDS and i + 1 < len(toks) and toks[i + 1].type is T.IDENT):
            name_tok = toks[i + 1]
            nxt = toks[i + 2] if i + 2 < len(toks) else None
            if nxt is not None and nxt.type is T.LPAREN and len(scopes) == 1:
                sig = _signature_from_tokens(toks, i)
                scopes[0].append({"name": name_tok.lexeme, "kind": "function", "type": t.lexeme,
                                  "line": t.line, "column": t.column, "signature": sig})
                function = sig
                function_depth = None
                # collect parameters until ')'
                j = i + 3
                while j + 1 < len(toks) and toks[j].type is not T.RPAREN:
                    if toks[j].type in TYPE_KEYWORDS and toks[j + 1].type is T.IDENT:
                        pending_params.append({
                            "name": toks[j + 1].lexeme, "kind": "parameter", "type": toks[j].lexeme,
                            "line": toks[j].line, "column": toks[j].column,
                            "signature": f"{toks[j].lexeme} {toks[j + 1].lexeme}"})
                    j += 1
                i = j          # resume after the parameter list
            elif name_tok.offset < offset:
                kind = "variable"
                scopes[-1].append({"name": name_tok.lexeme, "kind": kind, "type": t.lexeme,
                                   "line": t.line, "column": t.column,
                                   "signature": f"{t.lexeme} {name_tok.lexeme}"})
        i += 1
    seen: dict[str, dict] = {}
    for scope in reversed(scopes):
        for sym in scope:
            seen.setdefault(sym["name"], sym)
    return list(seen.values()), function


def _enclosing_from_symbols(diag: Diagnostic) -> str | None:
    for frame in reversed(diag.rule_stack):
        if frame.startswith("function_decl "):
            name = frame.split(" ", 1)[1]
            for s in diag.symbols:
                if s["name"] == name and s["kind"] == "function":
                    return s["signature"]
            return name
    return None


def extract_context(diag: Diagnostic, source: str, tokens: list[Token] | None = None,
                    all_diagnostics: list[Diagnostic] | None = None,
                    radius: int = 3) -> ErrorContext:
    lines = source.split("\n")
    extra = [r.line for r in diag.related]
    snippet, lo, hi = _snippet(lines, diag.line, radius, extra)

    if diag.symbols:
        symbols, exact = list(diag.symbols), True
        enclosing = _enclosing_from_symbols(diag)
    else:
        exact = False
        offset = _offset_of(lines, diag.line, diag.column)
        if diag.found is not None:
            offset = min(offset, diag.found.get("offset", offset))
        symbols, enclosing = _approximate_scope(tokens or [], offset) if tokens else ([], None)

    others = [f"line {d.line}: [{d.code.value}] {d.message}"
              for d in (all_diagnostics or []) if d is not diag]
    return ErrorContext(diag, source, diag.filename, snippet, lo, hi, enclosing,
                        symbols, exact, others)


def _offset_of(lines: list[str], line: int, column: int) -> int:
    line = max(1, min(line, len(lines)))
    return sum(len(l) + 1 for l in lines[: line - 1]) + max(column - 1, 0)
