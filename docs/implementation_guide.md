# Project Implementation Guide & Architecture Documentation

**Course:** BCSE307L — Compiler Design  
**Project:** LLM-Assisted Compiler Error Diagnosis and Repair Tool  
**Student:** Namish (3rd Year CSE)

---

## 1. Executive Summary & Architecture

The objective of this project is to bridge compiler front-end internals with Large Language Models (LLMs) to provide clear, actionable explanations and verified fixes for compilation errors.

Unlike conventional tools that scrape compiler error text from `stderr` as a black box, this project implements a custom compiler front-end where every error is modeled as an enriched, typed `Diagnostic` object directly at the moment it is raised.

### System Architecture Pipeline

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
                                  |  - Early Lexical Diagnostic emission          |
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
                                                         |  - Grammar rule stack trace     |
                                                         |  - Related opener locations     |
                                                         +---------------------------------+
                                                                          |
                                                                          v
[Phase 2 Ready]                                          +---------------------------------+
                                                         |  Stage 3: Semantic Analysis     |
                                                         |  - Symbol table & Scope tree    |
                                                         |  - Type checking & resolution   |
                                                         +---------------------------------+
                                                                          |
                                                                          v
[Phase 2 Ready]                                          +---------------------------------+
                                                         | Stage 4: Typed LLM Prompting    |
                                                         |  - Error-type prompt dispatch   |
                                                         |  - Automated fix verification   |
                                                         +---------------------------------+
```

---

## 2. Phase 1 Implementation Walkthrough

Phase 1 provides the foundational 25% implementation: the lexical analyzer, recursive-descent parser, and structured error reporting engine.

### 2.1 Lexical Analysis (`toyc/regex_dfa.py` & `toyc/lexer.py`)

Rather than relying on high-level Python libraries, the tokenizer is implemented using foundational automata theory from the ground up:

1. **Regular Expression Parsing:**  
   `_RegexParser` converts regex strings into an explicit AST (`CharSet`, `Concat`, `Alt`, `Star`, `Plus`, `Opt`, `Epsilon`).
2. **Thompson's Construction:**  
   `_thompson()` builds an $\epsilon$-NFA graph. Each token rule's accept state is labeled with a priority rank `(priority, token_name)`.
3. **Subset Construction:**  
   `nfa_to_dfa()` calculates the $\epsilon$-closure to convert the non-deterministic automaton to deterministic states. When multiple tokens could match, the lowest priority index (order in specification) breaks ties—allowing keywords (e.g. `if`, `while`) to take precedence over identifiers.
4. **Moore's Partition Refinement:**  
   `minimize()` partitions states based on output signatures, generating the minimal DFA (reducing our token matcher to an optimal 67 states).
5. **Maximal-Munch Tokenizer:**  
   `Lexer.tokenize()` greedily consumes input using the DFA until no transition is possible, recording the furthest accepting position.
6. **Span & Source Tracking:**  
   Calculates 1-based `line`, `column`, `end_line`, and `end_column` using newline index bisecting (`bisect_right`).

### 2.2 Grammar & Parsing (`toyc/ast_nodes.py` & `toyc/parser.py`)

The recursive-descent parser directly mirrors the formal EBNF grammar defined in `docs/grammar.ebnf`:

1. **Explicit Operator Precedence:**  
   Expressions are broken into distinct grammar layers to enforce precedence without ambiguity:
   $$\text{assignment} \to \text{logic\_or} \to \text{logic\_and} \to \text{equality} \to \text{comparison} \to \text{term} \to \text{factor} \to \text{unary} \to \text{call} \to \text{primary}$$
2. **Grammar Rule Stack Tracking:**  
   Using a Python context manager (`with self.rule("function_decl"):`), the parser maintains an active `rule_stack`. If an error occurs, the exact nested grammatical path is preserved (e.g., `program > declaration > function_decl > block > statement > var_decl`).
3. **Delimiter Opener Tracking:**  
   When matching delimiters (`( ... )`, `{ ... }`), the opening token is tracked. If the closing delimiter is missing, the diagnostic references both the missing token and the line/column where the delimiter was opened.
4. **Panic-Mode Error Recovery:**  
   When a syntax error occurs, a `_ParseAbort` exception unwinds parsing to either `_synchronize_statement()` or `_synchronize_declaration()`. The parser skips corrupt tokens until reaching a boundary token (`;`, `}`, or a keyword), allowing multiple independent errors to be diagnosed in a single pass.

### 2.3 Structured Diagnostics (`toyc/errors.py`)

Instead of raising uncaught exceptions or printing bare strings, diagnostics are modeled as structured objects:

```json
{
  "category": "syntax",
  "code": "SYN_MISSING_SEMICOLON",
  "message": "expected ';' after variable declaration, found keyword 'int'",
  "location": {
    "file": "examples/err_missing_semicolon.toy",
    "line": 3,
    "column": 18,
    "end_column": null
  },
  "expected": [ "';'" ],
  "found": {
    "type": "INT",
    "lexeme": "int",
    "line": 4,
    "column": 5,
    "description": "keyword 'int'"
  },
  "rule": "var_decl",
  "rule_stack": [
    "program",
    "declaration",
    "function_decl",
    "block",
    "statement",
    "var_decl"
  ],
  "source_line": "    int count = 5",
  "hint": "insert ';' after variable declaration",
  "related": []
}
```

---

## 3. Step-by-Step Guide to Implement the Project

This section details how to develop the complete system from scratch across both phases.

### Step 1: Lexical Specification & Automata Engine
- [x] **Define Token Types:** Enumerate keywords, identifiers, numeric literals, multi-char operators (`==`, `!=`, `<=`, `>=`, `&&`, `||`), single-char symbols, and `EOF`.
- [x] **Implement Automata Builders:**
  - Build a regex AST parser.
  - Implement Thompson's NFA construction.
  - Implement subset construction for DFA conversion.
  - Implement Moore's partition refinement for state minimization.
- [x] **Build Tokenizer:** Implement maximal-munch matching, skip whitespace/comments, and track line/column offsets.

### Step 2: AST Nodes and EBNF Grammar
- [x] **Formalize EBNF:** Specify program structure, statements (`var_decl`, `if`, `while`, `return`, `expr_stmt`), and expression precedence hierarchy.
- [x] **Define AST Data Classes:** Create structured dataclasses for nodes (`Program`, `FunctionDecl`, `VarDecl`, `Block`, `If`, `While`, `Return`, `Assign`, `Binary`, `Unary`, `Call`, `IntLiteral`, `BoolLiteral`, `Identifier`).
- [x] **Build AST Visualizer:** Implement ASCII tree indentation and JSON export.

### Step 3: Recursive-Descent Parser & Error Recovery
- [x] **Implement Grammar Rules:** Write a parsing function corresponding to each non-terminal in the EBNF grammar.
- [x] **Implement Contextual Stack:** Track the current active rule hierarchy during descent.
- [x] **Implement Intelligent Error Detection:**
  - Delimiter matching with opener reference.
  - Semicolon detection with lookahead to place the caret after the prior token.
  - Invalid assignment target detection (e.g., `5 = x` vs `5 == x`).
  - Reserved keyword and malformed identifier detection.
- [x] **Implement Panic-Mode Synchronization:** Recover at statement boundaries (`;`, `}`) and declaration boundaries.

### Step 4: CLI and Phase 1 Validation
- [x] **Build CLI:** Support commands:
  - `run <file>`: Standard compilation with colorized diagnostics.
  - `run <file> --tokens`: Inspect token sequence.
  - `run <file> --ast`: Inspect abstract syntax tree.
  - `run <file> --json`: Output full structured JSON diagnostics.
  - `dfa-stats`: Display automaton metrics.
- [x] **Write Unit Test Suite:** Verify DFA minimization, lexer edge cases, operator precedence, and diagnostic reporting.

---

### Step 5: Semantic Analysis (Phase 2 — Complete)
- [x] **Symbol Table & Scopes:**
  - `SymbolTable` class supporting nested lexical scopes (`Scope` stack).
  - Records variable names, types (`int`, `bool`, `void`), declaration locations, and function signatures.
- [x] **Semantic Checks:**
  - **Undeclared Variables:** Flag variable usage without prior declaration (`SEM_UNDECLARED_VARIABLE`) with spelling typo suggestions (`difflib`).
  - **Duplicate Declarations:** Flag redeclaring an identifier in the same scope (`SEM_DUPLICATE_DECLARATION`).
  - **Type Checking:** Ensure operands to arithmetic operators are `int`, condition in `if`/`while` is `bool`, assignment types match (`SEM_TYPE_MISMATCH`).
  - **Function Validation:** Verify argument count and parameter types on calls (`SEM_ARGUMENT_MISMATCH`, `SEM_UNDEFINED_FUNCTION`, `SEM_NOT_CALLABLE`).
- [x] **Unified Semantic Diagnostics:**
  - Emit semantic errors into the identical `Diagnostic` schema used by syntax errors with detailed type and symbol snapshots.

### Step 6: Error-Context Extraction & LLM Integration
- [x] **Context Extraction Engine (`toyc/context.py`):**
  - Slices surrounding source code lines with visual indicators.
  - Slices relevant in-scope symbol table entries.
- [x] **Error-Type-Specific Prompt Templates (`toyc/prompts.py`):**
  - `PromptSyntaxMissingDelimiter`: Injects opener line/col and expected delimiter.
  - `PromptUndeclaredVariable`: Injects active symbols in scope to suggest typos or missing declarations.
  - `PromptTypeMismatch`: Injects expected operand types and inferred sub-expression types.
  - `PromptUndefinedFunction`: Injects callee signature expectations and available declarations.
  - `PromptGenericBaseline`: Generic prompt used as the control for ablation study.
- [x] **LLM Client Integration (`toyc/llm.py`):**
  - Gemini Interactions API integration with model `gemini-3.8-flash`.
  - Built-in heuristic offline mock client for deterministic evaluation and testing without API keys.

### Step 7: Automated Fix Verification Layer (`toyc/verifier.py`)
- [x] **In-Memory Recompilation:**
  - Parses and recompiles proposed fixes through the complete compiler pipeline.
- [x] **Verification Status Tagging:**
  - Marks diagnostics as `[VERIFIED FIX]` (clean recompilation) or `[UNVERIFIED - FIX FAILED]`.
  - Calculates unified diffs between original and repaired code.

### Step 8: Evaluation Suite & Comparative Study (`toyc/evaluation.py`)
- [x] **Curate Benchmark Dataset:**
  - 20 benchmark buggy programs in `examples/benchmarks/` covering all error categories.
- [x] **Run Comparative Evaluations:**
  - **Evaluation 1:** Toy-C Structured Output vs. Raw GCC/Clang `stderr` diagnostics.
  - **Evaluation 2 (Ablation Study):** Error-type-specific prompting vs. Generic single-prompt baseline.
- [x] **Evaluation Metrics:**
  - Educational rubric scoring for novice accessibility and compiler fact grounding.
  - Fix verification success rate (% of code suggestions compiling clean).

---

## 4. Verification and Quick Commands

Run these commands in the terminal to verify the complete Phase 1 and Phase 2 implementation:

```bash
# 1. View DFA generation statistics (67 states, 62 accepting, 2730 transitions)
.\toycompiler.bat dfa-stats

# 2. Run valid program and inspect AST & symbol table
.\toycompiler.bat run examples\valid_factorial.toy --ast --symbols

# 3. Test LLM diagnosis and automated fix verification on a syntax error
.\toycompiler.bat diagnose examples\err_missing_semicolon.toy

# 4. Test LLM diagnosis on a semantic error
.\toycompiler.bat diagnose examples\benchmarks\12_sem_var_typo.toy

# 5. Run the 20-benchmark comparative study & ablation report
.\toycompiler.bat eval --output evaluation_report.md --json

# 6. Run full unit test suite (75 tests passing)
python -m unittest discover -s tests -v
```

