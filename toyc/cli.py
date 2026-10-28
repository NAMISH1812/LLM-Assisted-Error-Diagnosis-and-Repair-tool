"""Command-line interface for the Toy-C Compiler and LLM Error Diagnosis & Repair Tool.

Supported commands:
  run <file>           Compile file (lex -> parse -> semantic) and show diagnostics
  diagnose <file>      Diagnose error using LLM and verify the proposed fix
  symbols <file>       Display the scoped symbol table
  eval                 Run the 20-program comparative evaluation & ablation study
  dfa-stats            Display lexer automaton statistics
"""

from __future__ import annotations

import argparse
import json
import os
import sys

from . import __version__
from .ast_nodes import format_ast
from .context import extract_context
from .errors import format_diagnostic
from .evaluation import format_evaluation_report, run_comparative_study, run_evaluation_suite
from .lexer import get_lexer_dfa
from .llm import DEFAULT_MODEL, diagnose_and_repair
from .pipeline import compile_source
from .semantic import format_symbol_table
from .verifier import VerificationStatus, verify_fix

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


def _read_source(filepath: str) -> str | None:
    try:
        with open(filepath, encoding="utf-8") as f:
            return f.read()
    except OSError as exc:
        print(f"toycompiler: cannot read '{filepath}': {exc.strerror}", file=sys.stderr)
        return None
    except UnicodeDecodeError:
        print(f"toycompiler: '{filepath}' is not valid UTF-8 text", file=sys.stderr)
        return None


def cmd_run(args: argparse.Namespace) -> int:
    source = _read_source(args.file)
    if source is None:
        return EXIT_USAGE

    result = compile_source(source, args.file)
    exit_code = EXIT_OK if result.ok else EXIT_COMPILE_ERROR

    if args.json:
        print(json.dumps(result.to_dict(args.tokens, args.ast, getattr(args, "symbols", False)), indent=2))
        return exit_code

    color = _use_color(args.no_color)
    if args.tokens:
        print(_format_tokens(result.tokens))
        print()
    if args.ast and result.program is not None:
        print(format_ast(result.program))
        print()
    if getattr(args, "symbols", False) and result.symbols is not None:
        print(format_symbol_table(result.symbols))
        print()

    if result.ok:
        green = "\033[1;32m" if color else ""
        reset = "\033[0m" if color else ""
        decls = len(result.program.declarations) if result.program else 0
        print(f"{green}OK{reset}  {args.file}: lexed {len(result.tokens) - 1} tokens, "
              f"parsed {decls} top-level declaration(s), passed semantic checks - no errors")
    else:
        for diag in result.diagnostics:
            print(format_diagnostic(diag, color))
            print()
        n = len(result.diagnostics)
        stage = result.failed_stage or "compilation"
        stage_names = {"lex": "lexing", "parse": "parsing", "semantic": "semantic analysis"}
        print(f"{n} error{'s' if n != 1 else ''} found during {stage_names.get(stage, stage)}.")
        if stage == "lex":
            print("(parsing and semantic checks skipped until lexical errors are fixed)")
        elif stage == "parse":
            print("(semantic checks skipped until syntax errors are fixed)")
    return exit_code


def cmd_symbols(args: argparse.Namespace) -> int:
    source = _read_source(args.file)
    if source is None:
        return EXIT_USAGE

    result = compile_source(source, args.file)
    if result.symbols is not None:
        print(format_symbol_table(result.symbols))
        return EXIT_OK
    else:
        print(f"toycompiler: cannot build complete symbol table due to syntax errors in '{args.file}'", file=sys.stderr)
        return EXIT_COMPILE_ERROR


def cmd_diagnose(args: argparse.Namespace) -> int:
    source = _read_source(args.file)
    if source is None:
        return EXIT_USAGE

    color = _use_color(args.no_color)
    result = compile_source(source, args.file)

    if result.ok:
        green = "\033[1;32m" if color else ""
        reset = "\033[0m" if color else ""
        print(f"{green}SUCCESS{reset}: '{args.file}' compiled with 0 errors. No repair needed.")
        return EXIT_OK

    primary_diag = result.diagnostics[0]
    ctx = extract_context(primary_diag, source, result.tokens, result.diagnostics)

    # Invoke LLM diagnosis with chosen mode (typed vs generic)
    offline = args.offline or not os.environ.get("GEMINI_API_KEY")
    try:
        llm_resp = diagnose_and_repair(
            ctx=ctx,
            mode=args.mode,
            offline=offline,
            model=args.model,
        )
    except Exception as exc:
        print(f"toycompiler: LLM diagnosis failed: {exc}", file=sys.stderr)
        return EXIT_COMPILE_ERROR

    # Run Automated Fix Verification Layer
    verif = verify_fix(
        original_source=source,
        fixed_source=llm_resp.fixed_source,
        target_diagnostic=primary_diag,
        filename=args.file,
        explanation=llm_resp.explanation,
        fix_description=llm_resp.fix_description,
    )

    if args.json:
        payload = {
            "file": args.file,
            "mode": args.mode,
            "diagnostic": primary_diag.to_dict(),
            "llm": llm_resp.to_dict(),
            "verification": verif.to_dict(),
        }
        print(json.dumps(payload, indent=2))
        return EXIT_OK

    # Pretty print formatted diagnosis and fix
    bold = "\033[1m" if color else ""
    cyan = "\033[36m" if color else ""
    green = "\033[1;32m" if color else ""
    red = "\033[1;31m" if color else ""
    yellow = "\033[1;33m" if color else ""
    reset = "\033[0m" if color else ""

    print(format_diagnostic(primary_diag, color))
    print()
    print(f"{cyan}{bold}--- LLM Diagnosis [{llm_resp.prompt_used.template}] ---{reset}")
    if offline:
        print(f"{yellow}[Mode: Local Heuristic Mock / Offline]{reset}")
    else:
        print(f"{green}[Model: {llm_resp.model} via Gemini Interactions API]{reset}")
    print()
    print(f"{bold}Explanation:{reset}\n{llm_resp.explanation}")
    print()
    print(f"{bold}Suggested Fix:{reset} {llm_resp.fix_description}")
    print()

    # Verification status badge
    if verif.status == VerificationStatus.VERIFIED:
        badge = f"{green}{bold}[VERIFIED FIX - Recompilation Succeeded with 0 Errors]{reset}"
    elif verif.status == VerificationStatus.PARTIAL:
        badge = f"{yellow}{bold}[PARTIALLY VERIFIED - Target Error Resolved; Other Pre-existing Errors Remain]{reset}"
    else:
        badge = f"{red}{bold}[UNVERIFIED - FIX FAILED: {verif.status.value}]{reset}"

    print(f"{bold}Verification Status:{reset} {badge}")
    print()

    if verif.diff:
        print(f"{bold}Proposed Code Diff:{reset}")
        print(verif.diff)

    if args.apply and verif.is_verified:
        with open(args.file, "w", encoding="utf-8") as f:
            f.write(llm_resp.fixed_source)
        print(f"{green}Applied verified fix to '{args.file}'.{reset}")

    return EXIT_OK


def cmd_eval(args: argparse.Namespace) -> int:
    color = _use_color(args.no_color)
    bold = "\033[1m" if color else ""
    cyan = "\033[36m" if color else ""
    reset = "\033[0m" if color else ""

    print(f"{cyan}{bold}Running LLM-Assisted Compiler Evaluation Suite...{reset}\n")
    study = run_comparative_study(offline=args.offline)

    report = format_evaluation_report(study)
    print(report)

    if args.output:
        with open(args.output, "w", encoding="utf-8") as f:
            f.write(report)
        print(f"\nSaved full evaluation report to: {args.output}")

    if args.json:
        json_path = os.path.splitext(args.output or "evaluation_results")[0] + ".json"
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(study, f, indent=2)
        print(f"Saved machine-readable JSON evaluation data to: {json_path}")

    return EXIT_OK


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

    # run
    run = sub.add_parser("run", help="tokenize, parse, and type-check a Toy-C source file")
    run.add_argument("file", help="path to a .toy source file")
    run.add_argument("--tokens", action="store_true", help="print the token stream")
    run.add_argument("--ast", action="store_true", help="print the abstract syntax tree")
    run.add_argument("--symbols", action="store_true", help="print the symbol table")
    run.add_argument("--json", action="store_true", help="emit machine-readable JSON")
    run.add_argument("--no-color", action="store_true", help="disable ANSI colours")
    run.set_defaults(func=cmd_run)

    # diagnose
    diag = sub.add_parser("diagnose", help="diagnose compiler error using LLM and verify proposed repair")
    diag.add_argument("file", help="path to a buggy .toy source file")
    diag.add_argument("--mode", choices=["typed", "generic"], default="typed",
                      help="prompting strategy: 'typed' (error-type-specific) or 'generic' (baseline)")
    diag.add_argument("--offline", action="store_true", help="use local heuristic offline engine")
    diag.add_argument("--model", default=DEFAULT_MODEL, help=f"Gemini model name (default: {DEFAULT_MODEL})")
    diag.add_argument("--apply", action="store_true", help="write verified fix back to file if recompilation succeeds")
    diag.add_argument("--json", action="store_true", help="emit machine-readable JSON")
    diag.add_argument("--no-color", action="store_true", help="disable ANSI colours")
    diag.set_defaults(func=cmd_diagnose)

    # symbols
    sym = sub.add_parser("symbols", help="inspect the scoped symbol table for a program")
    sym.add_argument("file", help="path to a .toy source file")
    sym.set_defaults(func=cmd_symbols)

    # eval
    ev = sub.add_parser("eval", help="run comparative study & ablation benchmark suite")
    ev.add_argument("--offline", action="store_true", default=True, help="run evaluation using deterministic offline model")
    ev.add_argument("--online", dest="offline", action="store_false", help="run evaluation using live Gemini API")
    ev.add_argument("--output", "-o", default="evaluation_report.md", help="output path for markdown evaluation report")
    ev.add_argument("--json", action="store_true", help="also emit machine-readable JSON results")
    ev.add_argument("--no-color", action="store_true", help="disable ANSI colours")
    ev.set_defaults(func=cmd_eval)

    # dfa-stats
    dfa = sub.add_parser("dfa-stats", help="show statistics of the generated lexer DFA")
    dfa.set_defaults(func=cmd_dfa)

    return p


def main(argv: list[str] | None = None) -> int:
    args = build_arg_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
