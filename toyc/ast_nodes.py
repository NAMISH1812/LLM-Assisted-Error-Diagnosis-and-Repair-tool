"""AST node definitions and printers for Toy-C."""

from __future__ import annotations

from dataclasses import dataclass, field, fields


@dataclass
class Node:
    line: int = field(default=0, kw_only=True)
    column: int = field(default=0, kw_only=True)


# -- Declarations ------------------------------------------------------------

@dataclass
class Program(Node):
    declarations: list[Node]


@dataclass
class Param(Node):
    type: str
    name: str


@dataclass
class FunctionDecl(Node):
    return_type: str
    name: str
    params: list[Param]
    body: "Block"


@dataclass
class VarDecl(Node):
    type: str
    name: str
    init: Node | None = None


# -- Statements --------------------------------------------------------------

@dataclass
class Block(Node):
    statements: list[Node]


@dataclass
class If(Node):
    condition: Node
    then_branch: Node
    else_branch: Node | None = None


@dataclass
class While(Node):
    condition: Node
    body: Node


@dataclass
class Return(Node):
    value: Node | None = None


@dataclass
class ExprStmt(Node):
    expr: Node


# -- Expressions -------------------------------------------------------------

@dataclass
class Assign(Node):
    name: str
    value: Node


@dataclass
class Binary(Node):
    op: str
    left: Node
    right: Node


@dataclass
class Unary(Node):
    op: str
    operand: Node


@dataclass
class Call(Node):
    callee: str
    args: list[Node]


@dataclass
class IntLiteral(Node):
    value: int


@dataclass
class BoolLiteral(Node):
    value: bool


@dataclass
class Identifier(Node):
    name: str


# -- Printers ----------------------------------------------------------------

def _is_child(value) -> bool:
    return isinstance(value, Node) or isinstance(value, list)


def ast_to_dict(node):
    if isinstance(node, list):
        return [ast_to_dict(n) for n in node]
    if not isinstance(node, Node):
        return node
    d = {"node": type(node).__name__}
    for f in fields(node):
        d[f.name] = ast_to_dict(getattr(node, f.name))
    return d


def format_ast(root: Node) -> str:
    """Render an AST as an ASCII tree."""
    lines: list[str] = []

    def label(n: Node) -> str:
        attrs = [
            f"{f.name}={getattr(n, f.name)!r}"
            for f in fields(n)
            if f.name not in ("line", "column")
            and getattr(n, f.name) is not None
            and not _is_child(getattr(n, f.name))
        ]
        return f"{type(n).__name__}({', '.join(attrs)})  @{n.line}:{n.column}"

    def children(n: Node) -> list[tuple[str, Node]]:
        out = []
        for f in fields(n):
            v = getattr(n, f.name)
            if isinstance(v, Node):
                out.append((f.name, v))
            elif isinstance(v, list):
                out.extend((f"{f.name}[{i}]", c) for i, c in enumerate(v))
        return out

    def walk(n: Node, prefix: str, edge: str, name: str | None) -> None:
        tag = f"{name}: " if name else ""
        lines.append(f"{prefix}{edge}{tag}{label(n)}")
        kids = children(n)
        if edge == "":
            child_prefix = prefix
        else:
            child_prefix = prefix + ("    " if edge == "`-- " else "|   ")
        for i, (child_name, child) in enumerate(kids):
            walk(child, child_prefix, "`-- " if i == len(kids) - 1 else "|-- ", child_name)

    walk(root, "", "", None)
    return "\n".join(lines)
