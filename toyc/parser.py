"""Recursive-descent parser for Toy-C producing an AST and structured syntax errors.

Each grammar rule in ``docs/grammar.ebnf`` maps to one ``_rule`` method.  The
parser keeps a *rule stack* so every syntax error records exactly which rule
failed and how it was reached (e.g. ``program > function_decl > block >
statement > var_decl``).  Errors use panic-mode recovery at statement and
declaration boundaries so several independent errors can be reported in one run.
"""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass, field

from . import ast_nodes as ast
from .errors import Diagnostic, ErrorCode, RelatedLocation
from .tokens import TYPE_KEYWORDS, Token, TokenType

T = TokenType

MAX_ERRORS = 25

_STATEMENT_STARTS = frozenset({T.IF, T.WHILE, T.RETURN, T.LBRACE, *TYPE_KEYWORDS})

_BINARY_OPERATORS = frozenset({
    T.OR, T.AND, T.EQ, T.NEQ, T.LT, T.LE, T.GT, T.GE,
    T.PLUS, T.MINUS, T.STAR, T.SLASH, T.PERCENT, T.ASSIGN, T.NOT,
})


class _ParseAbort(Exception):
    """Unwinds the parser to the nearest recovery point (diagnostic already recorded)."""


@dataclass
class ParseResult:
    program: ast.Program | None
    errors: list[Diagnostic] = field(default_factory=list)


class Parser:
    def __init__(self, tokens: list[Token], source: str = "", filename: str = "<input>"):
        if not tokens or tokens[-1].type is not T.EOF:
            raise ValueError("token stream must end with EOF")
        self.tokens = tokens
        self.filename = filename
        self.lines = source.split("\n")
        self.pos = 0
        self.errors: list[Diagnostic] = []
        self.rule_stack: list[str] = []

    # ======================================================================
    # Token helpers
    # ======================================================================
    @property
    def cur(self) -> Token:
        return self.tokens[self.pos]

    @property
    def prev(self) -> Token | None:
        return self.tokens[self.pos - 1] if self.pos > 0 else None

    def peek(self, k: int = 1) -> Token:
        return self.tokens[min(self.pos + k, len(self.tokens) - 1)]

    def check(self, *types: TokenType) -> bool:
        return self.cur.type in types

    def advance(self) -> Token:
        tok = self.cur
        if tok.type is not T.EOF:
            self.pos += 1
        return tok

    def match(self, *types: TokenType) -> Token | None:
        return self.advance() if self.cur.type in types else None

    @contextmanager
    def rule(self, name: str):
        self.rule_stack.append(name)
        try:
            yield
        finally:
            self.rule_stack.pop()

    # ======================================================================
    # Error reporting
    # ======================================================================
    def _source_line(self, line: int) -> str:
        return self.lines[line - 1] if 0 < line <= len(self.lines) else ""

    def error(self, code: ErrorCode, message: str, *, token: Token | None = None,
              expected: list[str] | None = None, at: tuple[int, int] | None = None,
              hint: str | None = None, related: list[RelatedLocation] | None = None):
        """Record a structured syntax error and unwind to the nearest recovery point."""
        token = token or self.cur
        if at is not None:
            line, column, end_column = at[0], at[1], None
        else:
            line, column = token.line, token.column
            end_column = token.end_column if token.end_line == token.line and token.lexeme else None

        duplicate = self.errors and self.errors[-1].found and \
            self.errors[-1].found["offset"] == token.offset
        if not duplicate and len(self.errors) < MAX_ERRORS:
            self.errors.append(Diagnostic(
                code=code, message=message, filename=self.filename,
                line=line, column=column, end_column=end_column,
                expected=expected or [], found=token.to_dict(),
                rule=self.rule_stack[-1] if self.rule_stack else None,
                rule_stack=list(self.rule_stack),
                source_line=self._source_line(line),
                hint=hint, related=related or [],
            ))
        raise _ParseAbort()

    def expect(self, ttype: TokenType, context: str = "") -> Token:
        """Consume a token of ``ttype`` or raise a structured syntax error."""
        if self.cur.type is ttype:
            return self.advance()
        found, prev = self.cur, self.prev
        ctx = f" {context}" if context else ""
        message = f"expected {ttype.display}{ctx}, found {found.describe()}"

        if ttype is T.SEMICOLON:
            code = ErrorCode.SYN_MISSING_SEMICOLON
            at = None
            # Like GCC/Clang, point just past the previous token when the
            # offending token is on a later line -- that is where ';' belongs.
            if prev is not None and (found.type is T.EOF or found.line != prev.end_line):
                at = (prev.end_line, prev.end_column + 1)
            self.error(code, message, expected=[ttype.display], at=at,
                       hint=f"insert ';'{ctx}")
        if found.type is T.EOF:
            self.error(ErrorCode.SYN_UNEXPECTED_EOF, message, expected=[ttype.display])
        if ttype is T.IDENT:
            hint = None
            nxt = self.peek()
            if found.type.value == found.lexeme and found.lexeme.isalpha():
                hint = f"'{found.lexeme}' is a reserved keyword and cannot be used as a name"
            elif (found.type is T.INT_LIT and nxt.type is T.IDENT
                  and nxt.offset == found.offset + len(found.lexeme)):
                hint = (f"identifiers cannot start with a digit; "
                        f"'{found.lexeme}{nxt.lexeme}' is not a valid name")
            self.error(ErrorCode.SYN_EXPECTED_IDENTIFIER, message,
                       expected=[ttype.display], hint=hint)
        self.error(ErrorCode.SYN_UNEXPECTED_TOKEN, message, expected=[ttype.display])

    def expect_closing(self, ttype: TokenType, opener: Token) -> Token:
        """Consume a closing delimiter, reporting where its opener was if missing."""
        if self.cur.type is ttype:
            return self.advance()
        found = self.cur
        self.error(
            ErrorCode.SYN_UNBALANCED_DELIMITER,
            f"expected {ttype.display} to close {opener.type.display}, found {found.describe()}",
            expected=[ttype.display],
            related=[RelatedLocation(f"{opener.type.display} opened here", opener.line, opener.column)],
            hint=f"add the missing {ttype.display} or remove the extra {opener.type.display}",
        )

    # ======================================================================
    # Recovery
    # ======================================================================
    def _synchronize_statement(self) -> None:
        """Skip tokens until a likely statement boundary."""
        while not self.check(T.EOF):
            if self.match(T.SEMICOLON):
                return
            if self.check(T.RBRACE) or self.cur.type in _STATEMENT_STARTS:
                return
            self.advance()

    def _synchronize_declaration(self) -> None:
        """Skip tokens until a likely top-level declaration boundary."""
        depth = 0
        while not self.check(T.EOF):
            t = self.cur.type
            if t is T.LBRACE:
                depth += 1
            elif t is T.RBRACE:
                depth -= 1
                if depth <= 0:
                    self.advance()
                    return
            elif depth == 0 and t is T.SEMICOLON:
                self.advance()
                return
            elif depth == 0 and t in TYPE_KEYWORDS:
                return
            self.advance()

    # ======================================================================
    # Grammar rules
    # ======================================================================
    def parse(self) -> ParseResult:
        program = self._program()
        return ParseResult(program, self.errors)

    # program = { declaration } EOF ;
    def _program(self) -> ast.Program:
        decls: list[ast.Node] = []
        with self.rule("program"):
            while not self.check(T.EOF):
                start = self.pos
                try:
                    decls.append(self._declaration())
                except _ParseAbort:
                    self._synchronize_declaration()
                    if self.pos == start:
                        self.advance()
        return ast.Program(decls, line=1, column=1)

    # declaration = type IDENT ( function_rest | var_decl_rest ) ;
    def _declaration(self) -> ast.Node:
        with self.rule("declaration"):
            type_tok = self._type_spec("at start of a declaration")
            name = self.expect(T.IDENT, "after type specifier")
            if self.check(T.LPAREN):
                return self._function_rest(type_tok, name)
            return self._var_decl_rest(type_tok, name)

    # type = "int" | "bool" | "void" ;
    def _type_spec(self, context: str) -> Token:
        with self.rule("type"):
            tok = self.match(*TYPE_KEYWORDS)
            if tok is not None:
                return tok
            found = self.cur
            code = ErrorCode.SYN_UNEXPECTED_EOF if found.type is T.EOF else ErrorCode.SYN_EXPECTED_TYPE
            hint = None
            if found.type is T.IDENT and self.peek().type in (T.IDENT, T.LPAREN):
                hint = f"'{found.lexeme}' is not a type; Toy-C types are 'int', 'bool' and 'void'"
            self.error(code, f"expected a type specifier {context}, found {found.describe()}",
                       expected=["'int'", "'bool'", "'void'"], hint=hint)

    # function_rest = "(" [ param { "," param } ] ")" block ;
    def _function_rest(self, type_tok: Token, name: Token) -> ast.FunctionDecl:
        with self.rule("function_decl"):
            lparen = self.advance()
            params: list[ast.Param] = []
            if not self.check(T.RPAREN):
                with self.rule("param_list"):
                    params.append(self._param())
                    while self.match(T.COMMA):
                        params.append(self._param())
            self.expect_closing(T.RPAREN, lparen)
            body = self._block()
            return ast.FunctionDecl(type_tok.lexeme, name.lexeme, params, body,
                                    line=type_tok.line, column=type_tok.column)

    # param = type IDENT ;
    def _param(self) -> ast.Param:
        with self.rule("param"):
            type_tok = self._type_spec("for parameter")
            name = self.expect(T.IDENT, "for parameter name")
            return ast.Param(type_tok.lexeme, name.lexeme, line=type_tok.line, column=type_tok.column)

    # var_decl_rest = [ "=" expression ] ";" ;
    def _var_decl_rest(self, type_tok: Token, name: Token) -> ast.VarDecl:
        with self.rule("var_decl"):
            init = None
            if self.match(T.ASSIGN):
                init = self._expression()
            self.expect(T.SEMICOLON, "after variable declaration")
            return ast.VarDecl(type_tok.lexeme, name.lexeme, init,
                               line=type_tok.line, column=type_tok.column)

    # block = "{" { statement } "}" ;
    def _block(self) -> ast.Block:
        with self.rule("block"):
            if not self.check(T.LBRACE):
                self.expect(T.LBRACE, "to begin a block")
            lbrace = self.advance()
            statements: list[ast.Node] = []
            while not self.check(T.RBRACE, T.EOF):
                start = self.pos
                try:
                    statements.append(self._statement())
                except _ParseAbort:
                    self._synchronize_statement()
                    if self.pos == start:
                        self.advance()
            self.expect_closing(T.RBRACE, lbrace)
            return ast.Block(statements, line=lbrace.line, column=lbrace.column)

    # statement = var_decl | if_stmt | while_stmt | return_stmt | block | expr_stmt ;
    def _statement(self) -> ast.Node:
        with self.rule("statement"):
            t = self.cur.type
            if t in TYPE_KEYWORDS:
                type_tok = self.advance()
                name = self.expect(T.IDENT, "after type specifier")
                return self._var_decl_rest(type_tok, name)
            if t is T.IF:
                return self._if_stmt()
            if t is T.WHILE:
                return self._while_stmt()
            if t is T.RETURN:
                return self._return_stmt()
            if t is T.LBRACE:
                return self._block()
            return self._expr_stmt()

    # if_stmt = "if" "(" expression ")" statement [ "else" statement ] ;
    def _if_stmt(self) -> ast.If:
        with self.rule("if_stmt"):
            kw = self.advance()
            lparen = self.expect(T.LPAREN, "after 'if'")
            cond = self._expression()
            self.expect_closing(T.RPAREN, lparen)
            then_branch = self._statement()
            else_branch = self._statement() if self.match(T.ELSE) else None
            return ast.If(cond, then_branch, else_branch, line=kw.line, column=kw.column)

    # while_stmt = "while" "(" expression ")" statement ;
    def _while_stmt(self) -> ast.While:
        with self.rule("while_stmt"):
            kw = self.advance()
            lparen = self.expect(T.LPAREN, "after 'while'")
            cond = self._expression()
            self.expect_closing(T.RPAREN, lparen)
            body = self._statement()
            return ast.While(cond, body, line=kw.line, column=kw.column)

    # return_stmt = "return" [ expression ] ";" ;
    def _return_stmt(self) -> ast.Return:
        with self.rule("return_stmt"):
            kw = self.advance()
            value = None if self.check(T.SEMICOLON) else self._expression()
            self.expect(T.SEMICOLON, "after return statement")
            return ast.Return(value, line=kw.line, column=kw.column)

    # expr_stmt = expression ";" ;
    def _expr_stmt(self) -> ast.ExprStmt:
        with self.rule("expr_stmt"):
            expr = self._expression()
            self.expect(T.SEMICOLON, "after expression")
            return ast.ExprStmt(expr, line=expr.line, column=expr.column)

    # ---------------------------------------------------------------- expressions
    # expression = assignment ;
    def _expression(self) -> ast.Node:
        with self.rule("expression"):
            return self._assignment()

    # assignment = IDENT "=" assignment | logic_or ;
    def _assignment(self) -> ast.Node:
        with self.rule("assignment"):
            if self.check(T.IDENT) and self.peek().type is T.ASSIGN:
                name = self.advance()
                self.advance()  # '='
                value = self._assignment()
                return ast.Assign(name.lexeme, value, line=name.line, column=name.column)
            expr = self._logic_or()
            if self.check(T.ASSIGN):
                self.error(
                    ErrorCode.SYN_INVALID_ASSIGNMENT_TARGET,
                    "invalid assignment target: the left-hand side of '=' must be a variable name",
                    at=(expr.line, expr.column),
                    hint="only a variable can be assigned to; if you meant to compare values, use '=='",
                )
            return expr

    def _binary(self, name: str, operand, ops: tuple[TokenType, ...]) -> ast.Node:
        with self.rule(name):
            left = operand()
            while self.check(*ops):
                op = self.advance()
                right = operand()
                left = ast.Binary(op.lexeme, left, right, line=left.line, column=left.column)
            return left

    # logic_or = logic_and { "||" logic_and } ;
    def _logic_or(self):
        return self._binary("logic_or", self._logic_and, (T.OR,))

    # logic_and = equality { "&&" equality } ;
    def _logic_and(self):
        return self._binary("logic_and", self._equality, (T.AND,))

    # equality = comparison { ( "==" | "!=" ) comparison } ;
    def _equality(self):
        return self._binary("equality", self._comparison, (T.EQ, T.NEQ))

    # comparison = term { ( "<" | "<=" | ">" | ">=" ) term } ;
    def _comparison(self):
        return self._binary("comparison", self._term, (T.LT, T.LE, T.GT, T.GE))

    # term = factor { ( "+" | "-" ) factor } ;
    def _term(self):
        return self._binary("term", self._factor, (T.PLUS, T.MINUS))

    # factor = unary { ( "*" | "/" | "%" ) unary } ;
    def _factor(self):
        return self._binary("factor", self._unary, (T.STAR, T.SLASH, T.PERCENT))

    # unary = ( "!" | "-" ) unary | call ;
    def _unary(self) -> ast.Node:
        with self.rule("unary"):
            op = self.match(T.NOT, T.MINUS)
            if op is not None:
                operand = self._unary()
                return ast.Unary(op.lexeme, operand, line=op.line, column=op.column)
            return self._call()

    # call = IDENT "(" [ expression { "," expression } ] ")" | primary ;
    def _call(self) -> ast.Node:
        with self.rule("call"):
            if self.check(T.IDENT) and self.peek().type is T.LPAREN:
                name = self.advance()
                lparen = self.advance()
                args: list[ast.Node] = []
                if not self.check(T.RPAREN):
                    args.append(self._expression())
                    while self.match(T.COMMA):
                        args.append(self._expression())
                self.expect_closing(T.RPAREN, lparen)
                return ast.Call(name.lexeme, args, line=name.line, column=name.column)
            return self._primary()

    # primary = INT_LIT | "true" | "false" | IDENT | "(" expression ")" ;
    def _primary(self) -> ast.Node:
        with self.rule("primary"):
            tok = self.cur
            if self.match(T.INT_LIT):
                return ast.IntLiteral(int(tok.lexeme), line=tok.line, column=tok.column)
            if self.match(T.TRUE, T.FALSE):
                return ast.BoolLiteral(tok.type is T.TRUE, line=tok.line, column=tok.column)
            if self.match(T.IDENT):
                return ast.Identifier(tok.lexeme, line=tok.line, column=tok.column)
            if self.match(T.LPAREN):
                expr = self._expression()
                self.expect_closing(T.RPAREN, tok)
                return expr

            prev = self.prev
            after = ""
            hint = None
            if prev is not None and (prev.type in _BINARY_OPERATORS or prev.type in (T.LPAREN, T.COMMA)):
                after = f" after {prev.type.display}"
                if prev.type in _BINARY_OPERATORS:
                    hint = f"the operator {prev.type.display} is missing its right-hand operand"
            code = ErrorCode.SYN_UNEXPECTED_EOF if tok.type is T.EOF else ErrorCode.SYN_EXPECTED_EXPRESSION
            if tok.type is T.ELSE:
                hint = "'else' must directly follow the statement of an 'if'"
            self.error(code, f"expected an expression{after}, found {tok.describe()}",
                       expected=["expression"], hint=hint)


def parse(tokens: list[Token], source: str = "", filename: str = "<input>") -> ParseResult:
    return Parser(tokens, source, filename).parse()
