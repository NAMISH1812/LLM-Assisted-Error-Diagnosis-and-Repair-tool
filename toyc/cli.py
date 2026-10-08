"""Command-line interface:  toycompiler run <file> [--tokens] [--ast] [--json]"""

from __future__ import annotations

import argparse
import json
import os
import sys

from . import __version__
from .ast_nodes import format_ast
from .errors import format_diagnostic
from .lexer import get_lexer_dfa
from .pipeline import compile_source

EXIT_OK, EXIT_COMPILE_ERROR, EXIT_USAGE = 0, 1, 2


def _use_color(disabled: bool) -> bool:
    if disabled or os.environ.get("NO_COLOR") or not sys.stdout.isatty():
        return False
    if os.name == "nt":
        os.system("")  # enables ANSI escape processing in the Windows console
    return True


def _format_tokens(tokens) -> str:
    rows = [f"{'LINE:COL':<10}{'TYPE':<12}LEXEME", "-" * 34]
    for t in tokens:
        rows.append(f"{f'{t.line}:{t.column}':<10}{t.type.name:<12}{t.lexeme!r}")
    return "\n".join(rows)


def cmd_run(args: argparse.Namespace) -> int:
    try:
        with open(args.file, encoding="utf-8") as f:
            source = f.read()
    except OSError as exc:
        print(f"toycompiler: cannot read '{args.file}': {exc.strerror}", file=sys.stderr)
        return EXIT_USAGE
    except UnicodeDecodeError:
        print(f"toycompiler: '{args.file}' is not valid UTF-8 text", file=sys.stderr)
        return EXIT_USAGE

    result = compile_source(source, args.file)
    exit_code = EXIT_OK if result.ok else EXIT_COMPILE_ERROR

    if args.json:
        print(json.dumps(result.to_dict(args.tokens, args.ast), indent=2))
        return exit_code

    color = _use_color(args.no_color)
    if args.tokens:
        print(_format_tokens(result.tokens))
        print()
    if args.ast and result.program is not None:
        print(format_ast(result.program))
        print()

    if result.ok:
        green = "\033[1;32m" if color else ""
        reset = "\033[0m" if color else ""
        decls = len(result.program.declarations) if result.program else 0
        print(f"{green}OK{reset}  {args.file}: lexed {len(result.tokens) - 1} tokens, "
              f"parsed {decls} top-level declaration(s) - no errors")
    else:
        for diag in result.diagnostics:
            print(format_diagnostic(diag, color))
            print()
        n = len(result.diagnostics)
        stage = "lexing" if "parse" not in result.stages_run else "parsing"
        print(f"{n} error{'s' if n != 1 else ''} found during {stage}.")
        if stage == "lexing":
            print("(parsing skipped until lexical errors are fixed)")
    return exit_code


def cmd_dfa(args: argparse.Namespace) -> int:
    dfa = get_lexer_dfa()
    transitions = sum(len(row) for row in dfa.transitions)
    print(f"Lexer DFA: {dfa.num_states} states, {len(dfa.accepting)} accepting, "
          f"{transitions} transitions")
    return EXIT_OK


def build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="toycompiler",
        description="Toy-C compiler front-end with structured, LLM-ready diagnostics.")
    p.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    sub = p.add_subparsers(dest="command", required=True)

    run = sub.add_parser("run", help="tokenize and parse a Toy-C source file")
    run.add_argument("file", help="path to a .toy source file")
    run.add_argument("--tokens", action="store_true", help="print the token stream")
    run.add_argument("--ast", action="store_true", help="print the abstract syntax tree")
    run.add_argument("--json", action="store_true", help="emit machine-readable JSON")
    run.add_argument("--no-color", action="store_true", help="disable ANSI colours")
    run.set_defaults(func=cmd_run)

    dfa = sub.add_parser("dfa-stats", help="show statistics of the generated lexer DFA")
    dfa.set_defaults(func=cmd_dfa)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_arg_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
