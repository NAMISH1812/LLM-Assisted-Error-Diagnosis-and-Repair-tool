# Toy-C Compiler (Phase 1)

**LLM-Assisted Compiler Error Diagnosis and Repair Tool**  
*Course:* BCSE307L — Compiler Design (Phase 1 — 25% Implementation)

---

## Overview

Toy-C is a lightweight C-subset compiler front-end built from scratch to demonstrate structured diagnostic generation for compiler errors. Unlike standard compilers that emit flattened text error strings, Toy-C generates typed, rich `Diagnostic` objects carrying grammar rule stacks, expected/found tokens, source spans, and opener references to empower downstream LLM analysis.

## Features Implemented (Phase 1)

1. **Regex-to-DFA Lexer Engine:**
   - Formal regex parser: concatenation, alternation `|`, Kleene `*`, `+`, `?`, character classes `[...]` and negated classes `[^...]`.
   - Thompson's Construction ($\epsilon$-NFA) $\to$ Subset Construction (DFA) $\to$ Moore's Partition Refinement (Minimal DFA).
   - Maximal-munch tokenization with line and column span tracking.
   - Lexical error detection with intelligent recovery and hints.

2. **Recursive-Descent Parser:**
   - EBNF grammar implementation supporting variable declarations, functions, blocks, `if`/`else`, `while`, `return`, arithmetic, logical and comparison expressions.
   - Live grammar rule stack tracking attached to every diagnostic.
   - Delimiter matching tracking initial opener spans (e.g. unclosed parentheses or braces).
   - Panic-mode recovery at statement and declaration boundaries for multi-error diagnostics.

3. **Structured Diagnostics Architecture:**
   - Typed error codes (`SYN_MISSING_SEMICOLON`, `SYN_UNBALANCED_DELIMITER`, etc.).
   - Machine-readable JSON output format designed for LLM prompts in Phase 2.
   - Rustc-style visual diagnostics with ASCII carets and context hints.

4. **CLI & Test Suite:**
   - CLI utility `toycompiler.bat` supporting `run`, `--tokens`, `--ast`, `--json`, and `dfa-stats`.
   - 43 unit tests covering regex engine, DFA minimization, lexer edge cases, operator precedence, associativity, and error recovery.

---

## Directory Structure

```
├── toyc/
│   ├── regex_dfa.py    # Regex parsing, Thompson NFA, Subset DFA & minimization
│   ├── tokens.py       # Token definitions and Token spans
│   ├── lexer.py        # DFA-driven lexer with line/col tracking
│   ├── ast_nodes.py    # AST node definitions, JSON & ASCII tree formatters
│   ├── errors.py       # Structured Diagnostic schema and pretty formatter
│   ├── parser.py       # Recursive-descent parser with live rule-stack context
│   ├── pipeline.py     # Compiler driver & phase gating
│   └── cli.py          # Command line interface
├── docs/
│   ├── grammar.ebnf         # Formal EBNF specification
│   └── literature_survey.md # Literature survey, problem statement & gap analysis
├── examples/
│   ├── valid_factorial.toy     # Valid test program (loops, recursion, logic)
│   ├── err_missing_semicolon.toy
│   ├── err_unbalanced_paren.toy
│   ├── err_multiple.toy
│   └── err_lexical.toy
├── tests/
│   ├── test_regex_dfa.py # DFA engine & minimization tests
│   ├── test_lexer.py     # Tokenizer & error recovery tests
│   └── test_parser.py    # Syntax, precedence & diagnostic tests
└── toycompiler.bat       # Windows CLI runner
```

---

## Quickstart & Usage

### 1. View Lexer Automaton Statistics
```bash
.\toycompiler.bat dfa-stats
```

### 2. Compile a Valid Program
```bash
.\toycompiler.bat run examples\valid_factorial.toy
```

### 3. Inspect Tokens and AST
```bash
.\toycompiler.bat run examples\valid_factorial.toy --tokens --ast
```

### 4. Emit Machine-Readable Diagnostic JSON
```bash
.\toycompiler.bat run examples\err_missing_semicolon.toy --json
```

### 5. Run Full Test Suite
```bash
python -m unittest discover -s tests -v
```
