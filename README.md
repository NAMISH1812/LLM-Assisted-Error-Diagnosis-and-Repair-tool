# Toy-C Compiler & LLM Error Diagnosis and Repair Tool

**LLM-Assisted Compiler Error Diagnosis and Repair Tool**  
*Course:* BCSE307L — Compiler Design  
*Author:* Namish (3rd Year CSE)

---

## Overview

Toy-C is a complete C-subset compiler front-end and automated repair system built from scratch. Rather than treating compilers as black boxes that emit unformatted error strings, Toy-C generates typed, rich `Diagnostic` objects carrying grammar rule stacks, expected/found tokens, line/column spans, delimiter openers, and scoped symbol tables.

These internal compiler diagnostics are piped into an **error-type-specific LLM prompting engine** (powered by Google Gemini `gemini-3.8-flash` via the Interactions API or an offline deterministic heuristic client) and an **automated fix verification layer** that recompiles proposed repairs before presenting them as `[VERIFIED FIX]`.

---

## System Architecture Pipeline

```
                              +-----------------------------------------------+
                              |                 Source Code                   |
                              +-----------------------------------------------+
                                                      |
                                                      v
                              +-----------------------------------------------+
                              |         Stage 1: DFA-Driven Lexer             |
                              |  - Regex -> NFA -> DFA -> Minimal DFA         |
                              |  - Line/Col/Span tracking                     |
                              +-----------------------------------------------+
                                                      |
                                       [Token Stream with Spans]
                                                      |
                                                      v
                              +-----------------------------------------------+
                              |    Stage 2: Recursive-Descent Parser          |
                              |  - EBNF grammar implementation                |
                              |  - Live rule-stack tracker                    |
                              |  - Panic-mode boundary synchronization        |
                              +-----------------------------------------------+
                                       /                             \
                                      /                               \
                                     v                                 v
            +---------------------------------+      +---------------------------------+
            |      Abstract Syntax Tree       |      |   Structured Syntax Diagnostic  |
            |  (Program, Function, Stmt, Expr)|      |  - Error code & category        |
            +---------------------------------+      |  - Expected / Found tokens      |
                             |                       |  - Grammar rule stack trace     |
                             v                       +---------------------------------+
            +---------------------------------+                       |
            |   Stage 3: Semantic Analysis    |                       v
            |  - Symbol table & Scope tree    |      +---------------------------------+
            |  - Type checking & resolution   |----->|  Unified Compiler Diagnostic    |
            +---------------------------------+      |  - Symbol table slice & types   |
                                                     +---------------------------------+
                                                                      |
                                                                      v
                                                     +---------------------------------+
                                                     | Stage 4: Error-Type Prompting   |
                                                     |  - Missing Delimiter Template   |
                                                     |  - Undeclared Variable Template |
                                                     |  - Type Mismatch Template       |
                                                     |  - Undefined Function Template  |
                                                     |  - Generic Baseline (Ablation)  |
                                                     +---------------------------------+
                                                                      |
                                                                      v
                                                     +---------------------------------+
                                                     | Stage 5: In-Memory Verification |
                                                     |  - Recompilation through pipeline|
                                                     |  - [VERIFIED FIX] Tagging       |
                                                     |  - Unified Diff Generation      |
                                                     +---------------------------------+
```

---

## Features Implemented

### 1. Front-End Compiler Pipeline
- **Regex-to-DFA Lexer:** Formal regex AST, Thompson's $\epsilon$-NFA, Subset Construction, Moore's Partition Minimization (67 states, 62 accepting).
- **Recursive-Descent Parser:** Strict operator precedence hierarchy, panic-mode error recovery, live grammar rule stack tracking (`with self.rule(...)`), and delimiter opener references.
- **Semantic Analyzer:** Nested lexical scope tree (`SymbolTable`), type checking for arithmetic/logical/comparison expressions, `if`/`while` boolean condition enforcement, parameter and return type validation, and typo suggestions (`difflib`).

### 2. Error-Context Extraction & Typed LLM Prompting
- **Context Extractor (`toyc/context.py`):** Visual code slice (3 lines radius) with line carets, enclosing function signature, and visible symbol snapshot.
- **Error-Type-Specific Prompting (`toyc/prompts.py`):**
  - `PromptSyntaxMissingDelimiter`: Injects opener line/column and insertion points.
  - `PromptUndeclaredVariable`: Injects active symbols in scope and spelling suggestions.
  - `PromptTypeMismatch`: Injects required and inferred types with operator rules.
  - `PromptUndefinedFunction`: Injects candidate functions and parameter signatures.
  - `PromptGenericBaseline`: Ablation control mirroring raw compiler output.
- **LLM Client (`toyc/llm.py`):** Google Gemini Interactions API (`gemini-3.8-flash`) + offline heuristic mock engine.

### 3. Automated Fix Verification Layer (`toyc/verifier.py`)
- Re-compiles proposed fixes in memory through the full compiler pipeline.
- Tags repairs as `[VERIFIED FIX]` (clean recompilation) or `[UNVERIFIED - FIX FAILED]`.
- Computes standard unified diffs for transparent inspection before patching.

### 4. Comparative Evaluation Suite (`toyc/evaluation.py`)
- 20 benchmark buggy programs in `examples/benchmarks/`.
- Automated comparative evaluation: Toy-C vs. Raw GCC/Clang `stderr` output.
- Ablation study: Error-type-specific prompting vs. Generic single-prompt baseline.
- Rubric-scored explanation quality and fix verification rate metrics.

---

## Directory Structure

```
├── toyc/
│   ├── regex_dfa.py    # Automata theory: Regex -> NFA -> DFA -> Minimal DFA
│   ├── tokens.py       # Token definitions and source spans
│   ├── lexer.py        # DFA-driven tokenizer with line/col tracking
│   ├── ast_nodes.py    # AST node definitions, JSON & ASCII tree formatters
│   ├── errors.py       # Unified structured Diagnostic schema
│   ├── parser.py       # Recursive-descent parser with live rule-stack context
│   ├── semantic.py     # Scoped symbol table, type checker & semantic diagnostics
│   ├── context.py      # Error-context extractor (code windows & symbol slices)
│   ├── prompts.py      # Error-type-specific prompt templates & ablation baseline
│   ├── llm.py          # Gemini 3.8 Flash Interactions API & offline mock engine
│   ├── verifier.py     # In-memory recompilation & unified diff generator
│   ├── evaluation.py   # 20-benchmark evaluation & comparative study engine
│   ├── pipeline.py     # Multi-stage compiler driver & phase gating
│   └── cli.py          # Command line interface
├── docs/
│   ├── grammar.ebnf            # Formal EBNF specification
│   ├── implementation_guide.md # Comprehensive implementation walkthrough
│   └── literature_survey.md    # Survey, problem statement & novelty write-up
├── examples/
│   ├── valid_factorial.toy     # Valid test program (loops, recursion, logic)
│   ├── err_missing_semicolon.toy
│   ├── err_unbalanced_paren.toy
│   ├── err_multiple.toy
│   ├── err_lexical.toy
│   └── benchmarks/             # 20 curated benchmark buggy programs
├── tests/
│   ├── test_regex_dfa.py  # DFA engine & minimization tests
│   ├── test_lexer.py      # Tokenizer & error recovery tests
│   ├── test_parser.py     # Syntax, precedence & diagnostic tests
│   ├── test_semantic.py   # Scoped symbol table & type checking tests
│   ├── test_prompts.py    # Context extraction & prompt dispatch tests
│   ├── test_verifier.py   # Automated fix verification tests
│   └── test_evaluation.py # Benchmark suite & comparative study tests
├── evaluation_report.md   # Generated comparative evaluation & ablation report
├── evaluation_report.json # Machine-readable evaluation dataset
└── toycompiler.bat        # Windows CLI runner
```

---

## Quickstart & Usage

### 1. View Lexer Automaton Statistics
```bash
.\toycompiler.bat dfa-stats
```

### 2. Compile a Program (Tokens, AST, and Scoped Symbol Table)
```bash
.\toycompiler.bat run examples\valid_factorial.toy --tokens --ast --symbols
```

### 3. Diagnose an Error with LLM & Verify Fix Automatically
```bash
.\toycompiler.bat diagnose examples\err_missing_semicolon.toy
```

### 4. Diagnose a Semantic Error (Variable Typo or Type Mismatch)
```bash
.\toycompiler.bat diagnose examples\benchmarks\12_sem_var_typo.toy
```

### 5. Run the 20-Benchmark Evaluation & Ablation Study
```bash
.\toycompiler.bat eval --output evaluation_report.md --json
```

### 6. Run the Full Test Suite (75 Tests Passing)
```bash
python -m unittest discover -s tests -v
```
