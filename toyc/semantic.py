"""Semantic analysis for Toy-C: symbol table, scope tree and type checking.

The analyser walks the AST produced by :mod:`toyc.parser` and raises the same
structured :class:`~toyc.errors.Diagnostic` objects used by the lexer and
parser.  Semantic diagnostics additionally carry:

* ``details``  -- machine-readable facts (expected/actual type, operator,
  argument counts, typo suggestion, ...) used by the typed LLM prompts;
* ``symbols``  -- a snapshot of every symbol visible at the error site, so the
  context extractor can tell the LLM what *is* in scope.

Language rules enforced
-----------------------
* Every identifier must be declared in the current or an enclosing scope
  before it is used (functions may be called before their definition).
* An identifier may be declared only once per scope; parameters share the
  scope of the function body (as in C).
* ``+ - * / %`` and unary ``-`` take ``int`` operands; ``< <= > >=`` take
  ``int`` and produce ``bool``; ``== !=`` need operands of the same type;
  ``&& || !`` take ``bool``.
* ``if`` / ``while`` conditions must be ``bool``.
* Initialisers, assignments, arguments and ``return`` values must match the
  declared type exactly (Toy-C has no implicit int/bool conversion).
* Variables and parameters cannot have type ``void``.
"""

from __future__ import annotations

import difflib
from contextlib import contextmanager
from dataclasses import dataclass, field

from . import ast_nodes as ast
from .errors import Diagnostic, ErrorCode, RelatedLocation

INT, BOOL, VOID = "int", "bool", "void"
ERROR_TYPE = "<error>"          # poison type: suppresses cascading diagnostics

_ARITHMETIC = frozenset({"+", "-", "*", "/", "%"})
_RELATIONAL = frozenset({"<", "<=", ">", ">="})
_EQUALITY = frozenset({"==", "!="})
_LOGICAL = frozenset({"&&", "||"})

MAX_ERRORS = 25


# ==========================================================================
# Symbols & scopes
# ==========================================================================

@dataclass
class Symbol:
    name: str
    kind: str                     # "variable" | "parameter" | "function"
    type: str                     # value type, or return type for functions
    line: int
    column: int
    params: list[tuple[str, str]] = field(default_factory=list)   # functions only
    scope: str = ""

    @property
    def signature(self) -> str:
        if self.kind == "function":
            ps = ", ".join(f"{t} {n}" for t, n in self.params)
            return f"{self.type} {self.name}({ps})"
        return f"{self.type} {self.name}"

    def to_dict(self) -> dict:
        d = {"name": self.name, "kind": self.kind, "type": self.type,
             "line": self.line, "column": self.column, "scope": self.scope,
             "signature": self.signature}
        if self.kind == "function":
            d["params"] = [{"type": t, "name": n} for t, n in self.params]
        return d


@dataclass
class Scope:
    name: str
    parent: "Scope | None" = None
    symbols: dict[str, Symbol] = field(default_factory=dict)
    children: list["Scope"] = field(default_factory=list)

    @property
    def depth(self) -> int:
        return 0 if self.parent is None else self.parent.depth + 1

    def lookup_local(self, name: str) -> Symbol | None:
        return self.symbols.get(name)

    def lookup(self, name: str) -> Symbol | None:
        scope: Scope | None = self
        while scope is not None:
            if name in scope.symbols:
                return scope.symbols[name]
            scope = scope.parent
        return None

    def visible(self) -> list[Symbol]:
        """All symbols visible from this scope (inner declarations shadow outer)."""
        seen: dict[str, Symbol] = {}
        scope: Scope | None = self
        while scope is not None:
            for name, sym in scope.symbols.items():
                seen.setdefault(name, sym)
            scope = scope.parent
        return list(seen.values())

    def to_dict(self) -> dict:
        return {"scope": self.name,
                "symbols": [s.to_dict() for s in self.symbols.values()],
                "children": [c.to_dict() for c in self.children]}


class SymbolTable:
    """A tree of lexical scopes with a cursor pointing at the current scope."""

    def __init__(self) -> None:
        self.global_scope = Scope("global")
        self.current = self.global_scope

    def push(self, name: str) -> Scope:
        scope = Scope(name, self.current)
        self.current.children.append(scope)
        self.current = scope
        return scope

    def pop(self) -> None:
        assert self.current.parent is not None, "cannot pop the global scope"
        self.current = self.current.parent

    def declare(self, sym: Symbol) -> Symbol | None:
        """Declare ``sym`` in the current scope; return the clashing symbol, if any."""
        existing = self.current.lookup_local(sym.name)
        if existing is not None:
            return existing
        sym.scope = self.current.name
        self.current.symbols[sym.name] = sym
        return None

    def lookup(self, name: str) -> Symbol | None:
        return self.current.lookup(name)

    def to_dict(self) -> dict:
        return self.global_scope.to_dict()


def format_symbol_table(table: SymbolTable) -> str:
    """Render the scope tree as an indented listing."""
    out: list[str] = []

    def walk(scope: Scope, indent: str) -> None:
        out.append(f"{indent}scope {scope.name}")
        for s in scope.symbols.values():
            out.append(f"{indent}  - {s.kind:<9} {s.signature}  @{s.line}:{s.column}")
        for c in scope.children:
            walk(c, indent + "    ")

    walk(table.global_scope, "")
    return "\n".join(out)


# ==========================================================================
# Analyzer
# ==========================================================================

@dataclass
class SemanticResult:
    symbols: SymbolTable
    errors: list[Diagnostic] = field(default_factory=list)


class Analyzer:
    def __init__(self, source: str = "", filename: str = "<input>"):
        self.filename = filename
        self.lines = source.split("\n")
        self.table = SymbolTable()
        self.errors: list[Diagnostic] = []
        self.path: list[str] = []
        self.current_function: Symbol | None = None

    # -- helpers -----------------------------------------------------------
    @contextmanager
    def _ctx(self, name: str):
        self.path.append(name)
        try:
            yield
        finally:
            self.path.pop()

    def _source_line(self, line: int) -> str:
        return self.lines[line - 1] if 0 < line <= len(self.lines) else ""

    def _error(self, code: ErrorCode, message: str, node: ast.Node, *,
               length: int | None = None, hint: str | None = None,
               details: dict | None = None,
               related: list[RelatedLocation] | None = None,
               expected: list[str] | None = None) -> None:
        if len(self.errors) >= MAX_ERRORS:
            return
        end_column = node.column + length - 1 if length else None
        self.errors.append(Diagnostic(
            code=code, message=message, filename=self.filename,
            line=node.line, column=node.column, end_column=end_column,
            expected=expected or [],
            rule=self.path[-1] if self.path else None,
            rule_stack=list(self.path),
            source_line=self._source_line(node.line),
            hint=hint, related=related or [],
            details=details or {},
            symbols=[s.to_dict() for s in self.table.current.visible()],
        ))

    def _suggest(self, name: str, kinds: set[str]) -> str | None:
        candidates = [s.name for s in self.table.current.visible() if s.kind in kinds]
        match = difflib.get_close_matches(name, candidates, n=1, cutoff=0.6)
        return match[0] if match else None

    def _check_type(self, expected: str, actual: str, node: ast.Node,
                    what: str, code: ErrorCode = ErrorCode.SEM_TYPE_MISMATCH,
                    hint: str | None = None, extra: dict | None = None) -> None:
        if ERROR_TYPE in (expected, actual) or expected == actual:
            return
        details = {"expected_type": expected, "actual_type": actual, "context": what}
        details.update(extra or {})
        if hint is None:
            hint = _conversion_hint(expected, actual)
        self._error(code, f"type mismatch in {what}: expected '{expected}', found '{actual}'",
                    node, hint=hint, details=details, expected=[f"'{expected}'"])

    # -- entry -------------------------------------------------------------
    def analyze(self, program: ast.Program) -> SemanticResult:
        with self._ctx("program"):
            # Pass 1: collect function signatures so calls may precede definitions.
            for decl in program.declarations:
                if isinstance(decl, ast.FunctionDecl):
                    self._declare_function(decl)
            # Pass 2: globals in order, function bodies.
            for decl in program.declarations:
                if isinstance(decl, ast.FunctionDecl):
                    self._function(decl)
                elif isinstance(decl, ast.VarDecl):
                    self._var_decl(decl, kind="variable")
        return SemanticResult(self.table, self.errors)

    # -- declarations ------------------------------------------------------
    def _declare_function(self, fn: ast.FunctionDecl) -> None:
        sym = Symbol(fn.name, "function", fn.return_type, fn.line, fn.column,
                     params=[(p.type, p.name) for p in fn.params])
        clash = self.table.declare(sym)
        if clash is not None:
            with self._ctx(f"function_decl {fn.name}"):
                self._duplicate(fn.name, fn, clash)

    def _duplicate(self, name: str, node: ast.Node, clash: Symbol) -> None:
        self._error(
            ErrorCode.SEM_DUPLICATE_DECLARATION,
            f"'{name}' is already declared in this scope",
            node,
            related=[RelatedLocation(f"previous declaration of '{name}' ({clash.kind})",
                                     clash.line, clash.column)],
            hint=f"rename one of the declarations, or remove the type to assign to the existing '{name}'",
            details={"name": name, "previous_kind": clash.kind, "previous_type": clash.type,
                     "previous_line": clash.line},
        )

    def _function(self, fn: ast.FunctionDecl) -> None:
        sym = self.table.lookup(fn.name)
        with self._ctx(f"function_decl {fn.name}"):
            outer = self.current_function
            self.current_function = sym if sym and sym.line == fn.line else Symbol(
                fn.name, "function", fn.return_type, fn.line, fn.column)
            self.table.push(f"function {fn.name}")
            for p in fn.params:
                with self._ctx("param"):
                    if p.type == VOID:
                        self._error(ErrorCode.SEM_INVALID_VOID,
                                    f"parameter '{p.name}' cannot have type 'void'", p,
                                    hint="use 'int' or 'bool' for parameters",
                                    details={"name": p.name})
                    clash = self.table.declare(Symbol(p.name, "parameter", p.type, p.line, p.column))
                    if clash is not None:
                        self._duplicate(p.name, p, clash)
            # The outermost block shares the parameters' scope (C semantics).
            self._block(fn.body, new_scope=False)
            self.table.pop()
            self.current_function = outer

    def _var_decl(self, decl: ast.VarDecl, kind: str = "variable") -> None:
        with self._ctx("var_decl"):
            if decl.type == VOID:
                self._error(ErrorCode.SEM_INVALID_VOID,
                            f"variable '{decl.name}' cannot have type 'void'", decl,
                            length=len(VOID),
                            hint="'void' is only valid as a function return type; use 'int' or 'bool'",
                            details={"name": decl.name})
            # The initialiser is checked *before* the name is declared, so
            # `int x = x;` reports x as undeclared, matching C's intent.
            if decl.init is not None:
                actual = self._expr(decl.init)
                if decl.type != VOID:
                    self._check_type(decl.type, actual, decl.init,
                                     f"initialisation of '{decl.name}'",
                                     extra={"name": decl.name})
            clash = self.table.declare(Symbol(decl.name, kind, decl.type, decl.line, decl.column))
            if clash is not None:
                self._duplicate(decl.name, decl, clash)

    # -- statements --------------------------------------------------------
    def _block(self, block: ast.Block, new_scope: bool = True) -> None:
        with self._ctx("block"):
            if new_scope:
                self.table.push(f"block@{block.line}:{block.column}")
            for stmt in block.statements:
                self._statement(stmt)
            if new_scope:
                self.table.pop()

    def _statement(self, stmt: ast.Node) -> None:
        if isinstance(stmt, ast.VarDecl):
            self._var_decl(stmt)
        elif isinstance(stmt, ast.Block):
            self._block(stmt)
        elif isinstance(stmt, ast.If):
            with self._ctx("if_stmt"):
                self._condition(stmt.condition, "'if'")
                self._statement(stmt.then_branch)
                if stmt.else_branch is not None:
                    self._statement(stmt.else_branch)
        elif isinstance(stmt, ast.While):
            with self._ctx("while_stmt"):
                self._condition(stmt.condition, "'while'")
                self._statement(stmt.body)
        elif isinstance(stmt, ast.Return):
            with self._ctx("return_stmt"):
                self._return(stmt)
        elif isinstance(stmt, ast.ExprStmt):
            with self._ctx("expr_stmt"):
                self._expr(stmt.expr)

    def _condition(self, cond: ast.Node, keyword: str) -> None:
        actual = self._expr(cond)
        hint = None
        if actual == INT:
            hint = "Toy-C has no implicit int-to-bool conversion; compare explicitly, e.g. '(x != 0)'"
        self._check_type(BOOL, actual, cond, f"{keyword} condition", hint=hint,
                         extra={"statement": keyword.strip("'")})

    def _return(self, ret: ast.Return) -> None:
        fn = self.current_function
        if fn is None:
            return
        if ret.value is None:
            if fn.type != VOID:
                self._error(ErrorCode.SEM_RETURN_MISMATCH,
                            f"function '{fn.name}' must return a value of type '{fn.type}'", ret,
                            length=len("return"),
                            hint=f"return an expression of type '{fn.type}'",
                            details={"function": fn.name, "expected_type": fn.type, "actual_type": VOID},
                            expected=[f"'{fn.type}'"])
            return
        actual = self._expr(ret.value)
        if fn.type == VOID:
            self._error(ErrorCode.SEM_RETURN_MISMATCH,
                        f"void function '{fn.name}' cannot return a value", ret.value,
                        hint="remove the value (write 'return;') or change the return type",
                        details={"function": fn.name, "expected_type": VOID, "actual_type": actual})
            return
        self._check_type(fn.type, actual, ret.value, f"return value of '{fn.name}'",
                         code=ErrorCode.SEM_RETURN_MISMATCH, extra={"function": fn.name})

    # -- expressions -------------------------------------------------------
    def _expr(self, e: ast.Node) -> str:
        if isinstance(e, ast.IntLiteral):
            return INT
        if isinstance(e, ast.BoolLiteral):
            return BOOL
        if isinstance(e, ast.Identifier):
            return self._identifier(e)
        if isinstance(e, ast.Assign):
            return self._assign(e)
        if isinstance(e, ast.Unary):
            return self._unary(e)
        if isinstance(e, ast.Binary):
            return self._binary(e)
        if isinstance(e, ast.Call):
            return self._call(e)
        return ERROR_TYPE

    def _resolve_variable(self, name: str, node: ast.Node) -> Symbol | None:
        sym = self.table.lookup(name)
        if sym is None:
            suggestion = self._suggest(name, {"variable", "parameter"})
            hint = (f"did you mean '{suggestion}'?" if suggestion
                    else f"declare '{name}' before using it, e.g. 'int {name} = 0;'")
            self._error(ErrorCode.SEM_UNDECLARED_VARIABLE,
                        f"use of undeclared variable '{name}'", node, length=len(name),
                        hint=hint, details={"name": name, "suggestion": suggestion})
            return None
        if sym.kind == "function":
            self._error(ErrorCode.SEM_TYPE_MISMATCH,
                        f"'{name}' is a function, not a variable", node, length=len(name),
                        hint=f"call it with arguments, e.g. '{name}(...)'",
                        details={"name": name, "expected_type": "variable",
                                 "actual_type": sym.signature},
                        related=[RelatedLocation(f"'{name}' declared here", sym.line, sym.column)])
            return None
        return sym

    def _identifier(self, e: ast.Identifier) -> str:
        sym = self._resolve_variable(e.name, e)
        return sym.type if sym else ERROR_TYPE

    def _assign(self, e: ast.Assign) -> str:
        value_type = self._expr(e.value)
        sym = self._resolve_variable(e.name, e)
        if sym is None:
            return ERROR_TYPE
        self._check_type(sym.type, value_type, e.value, f"assignment to '{e.name}'",
                         extra={"name": e.name})
        return sym.type

    def _unary(self, e: ast.Unary) -> str:
        t = self._expr(e.operand)
        want, result = (BOOL, BOOL) if e.op == "!" else (INT, INT)
        self._check_type(want, t, e.operand, f"operand of unary '{e.op}'",
                         extra={"operator": e.op})
        return result

    def _binary(self, e: ast.Binary) -> str:
        lt, rt = self._expr(e.left), self._expr(e.right)
        op = e.op
        extra = {"operator": op, "left_type": lt, "right_type": rt}
        if op in _ARITHMETIC or op in _RELATIONAL:
            for side, t in ((e.left, lt), (e.right, rt)):
                self._check_type(INT, t, side, f"operand of '{op}'", extra=extra)
            return INT if op in _ARITHMETIC else BOOL
        if op in _LOGICAL:
            for side, t in ((e.left, lt), (e.right, rt)):
                self._check_type(BOOL, t, side, f"operand of '{op}'", extra=extra,
                                 hint=_conversion_hint(BOOL, t))
            return BOOL
        if op in _EQUALITY:
            if ERROR_TYPE not in (lt, rt) and lt != rt:
                self._error(ErrorCode.SEM_TYPE_MISMATCH,
                            f"cannot compare '{lt}' with '{rt}' using '{op}'", e,
                            hint="both sides of an equality comparison must have the same type",
                            details={**extra, "expected_type": lt, "actual_type": rt})
            return BOOL
        return ERROR_TYPE

    def _call(self, e: ast.Call) -> str:
        arg_types = [self._expr(a) for a in e.args]
        sym = self.table.lookup(e.callee)
        if sym is None:
            suggestion = self._suggest(e.callee, {"function"})
            known = sorted(s.name for s in self.table.current.visible() if s.kind == "function")
            hint = (f"did you mean '{suggestion}'?" if suggestion
                    else f"define a function named '{e.callee}' before calling it")
            self._error(ErrorCode.SEM_UNDEFINED_FUNCTION,
                        f"call to undefined function '{e.callee}'", e, length=len(e.callee),
                        hint=hint, details={"name": e.callee, "suggestion": suggestion,
                                            "known_functions": known,
                                            "arg_types": arg_types})
            return ERROR_TYPE
        if sym.kind != "function":
            self._error(ErrorCode.SEM_NOT_CALLABLE,
                        f"'{e.callee}' is a {sym.kind} of type '{sym.type}', not a function", e,
                        length=len(e.callee),
                        hint="only functions can be called",
                        details={"name": e.callee, "actual_type": sym.type},
                        related=[RelatedLocation(f"'{e.callee}' declared here", sym.line, sym.column)])
            return ERROR_TYPE

        related = [RelatedLocation(f"'{sym.name}' declared here as '{sym.signature}'",
                                   sym.line, sym.column)]
        if len(arg_types) != len(sym.params):
            n = len(sym.params)
            self._error(ErrorCode.SEM_ARGUMENT_MISMATCH,
                        f"function '{sym.name}' expects {n} argument{'s' if n != 1 else ''}, "
                        f"but {len(arg_types)} {'were' if len(arg_types) != 1 else 'was'} given",
                        e, length=len(e.callee),
                        hint=f"call it as '{sym.signature}'",
                        details={"function": sym.name, "signature": sym.signature,
                                 "expected_count": n, "actual_count": len(arg_types),
                                 "expected_types": [t for t, _ in sym.params],
                                 "arg_types": arg_types},
                        related=related)
        else:
            for i, ((ptype, pname), atype, arg) in enumerate(zip(sym.params, arg_types, e.args), 1):
                if ERROR_TYPE in (ptype, atype) or ptype == atype:
                    continue
                self._error(ErrorCode.SEM_ARGUMENT_MISMATCH,
                            f"argument {i} of '{sym.name}' has type '{atype}', "
                            f"but parameter '{pname}' expects '{ptype}'",
                            arg, hint=_conversion_hint(ptype, atype),
                            details={"function": sym.name, "signature": sym.signature,
                                     "position": i, "parameter": pname,
                                     "expected_type": ptype, "actual_type": atype},
                            related=related, expected=[f"'{ptype}'"])
        return sym.type


def _conversion_hint(expected: str, actual: str) -> str | None:
    if expected == BOOL and actual == INT:
        return "Toy-C has no implicit int-to-bool conversion; use a comparison such as 'x != 0'"
    if expected == INT and actual == BOOL:
        return "Toy-C has no implicit bool-to-int conversion; use an if/else to choose 1 or 0"
    if actual == VOID:
        return "a 'void' function does not produce a value that can be used here"
    return None


def analyze(program: ast.Program, source: str = "", filename: str = "<input>") -> SemanticResult:
    return Analyzer(source, filename).analyze(program)
